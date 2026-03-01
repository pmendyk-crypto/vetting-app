from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Multi-tenant imports
try:
    from app.routers import multitenant
    MULTITENANT_ENABLED = True
except ImportError:
    MULTITENANT_ENABLED = False
    print("[WARNING] Multi-tenant router not found - running in single-tenant mode")

from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone, timedelta
import sqlite3
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import os
import hashlib
import secrets
import mimetypes
import csv
import io
import random
import string
import shutil
import re

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import urllib.request
import urllib.parse
import json as _json

# Azure Blob Storage
try:
    from azure.storage.blob import BlobServiceClient, BlobSasPermissions, generate_blob_sas
except ImportError:
    BlobServiceClient = None
    print("[WARNING] azure-storage-blob not installed, blob storage disabled")


# -------------------------
# Paths / App
# -------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("DB_PATH", str(BASE_DIR / "hub.db")))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)

# Storage TTL constants (in days)
REFERRAL_FILE_TTL_DAYS = int(os.environ.get("REFERRAL_FILE_TTL_DAYS", "7"))   # delete uploaded file after 7 days
CASE_RECORD_TTL_DAYS   = int(os.environ.get("CASE_RECORD_TTL_DAYS",   "28"))  # keep case record/PDF for 28 days

# Azure Blob Storage config
AZURE_STORAGE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
REFERRAL_BLOB_CONTAINER = os.environ.get("REFERRAL_BLOB_CONTAINER", "referrals")
BLOB_STORAGE_ENABLED = bool(AZURE_STORAGE_CONNECTION_STRING and BlobServiceClient)

if BLOB_STORAGE_ENABLED:
    print(f"[startup] Azure Blob Storage ENABLED (container={REFERRAL_BLOB_CONTAINER})")
else:
    print("[startup] Azure Blob Storage DISABLED - using local filesystem")

# SMTP notification settings
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

# iRefer API settings
IREFER_API_KEY = os.environ.get("IREFER_API_KEY", "")
_irefer_guidelines_cache: list = []  # in-memory cache, populated on first request
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)

# Log paths at startup for debugging persistence issues
print(f"[startup] BASE_DIR={BASE_DIR}, DB_PATH={DB_PATH}, UPLOAD_DIR={UPLOAD_DIR}")

# -------------------------
# Helper Functions
# -------------------------
def generate_case_id() -> str:
    """Generate a unique readable case ID in format: YYYYMMDD-0001."""
    return generate_case_ids(1)[0]


def generate_case_ids(count: int) -> list[str]:
    """Generate consecutive unique case IDs for a batch submission."""
    total = max(1, int(count or 1))
    date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
    like_pattern = f"{date_prefix}-%"

    conn = get_db()
    try:
        rows = conn.execute("SELECT id FROM cases WHERE id LIKE ?", (like_pattern,)).fetchall()
    finally:
        conn.close()

    max_seq = 0
    for row in rows or []:
        case_id = row.get("id") if isinstance(row, dict) else row[0]
        if not case_id or "-" not in case_id:
            continue
        suffix = str(case_id).rsplit("-", 1)[-1]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))

    return [f"{date_prefix}-{max_seq + idx + 1:04d}" for idx in range(total)]


def format_csv_timestamp(value: str | None) -> str:
    return format_display_datetime(value)


def clear_case_stored_filepath(case_id: str) -> None:
    if not case_id:
        return
    conn = get_db()
    conn.execute("UPDATE cases SET stored_filepath = NULL WHERE id = ?", (case_id,))
    conn.commit()
    conn.close()


def normalize_case_attachment(case_dict: dict) -> dict:
    path = case_dict.get("stored_filepath")
    if path and not Path(path).exists():
        clear_case_stored_filepath(case_dict.get("id"))
        case_dict["stored_filepath"] = None
    return case_dict


# -------------------------
# Azure Blob Storage Helpers
# -------------------------
def get_blob_service_client():
    """Get BlobServiceClient from connection string."""
    if not BLOB_STORAGE_ENABLED:
        return None
    try:
        return BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    except Exception as e:
        print(f"[BLOB] Failed to create blob service client: {e}")
        return None


def upload_to_blob(case_id: str, file_bytes: bytes, original_filename: str) -> str | None:
    """
    Upload file to Azure Blob Storage.
    Returns the blob name (stored in DB as stored_filepath), or None if upload fails.
    """
    if not BLOB_STORAGE_ENABLED:
        return None
    
    try:
        # Use short blob name: case_id.ext (blob names have length limits)
        ext = Path(original_filename).suffix or ".bin"
        blob_name = f"{case_id}{ext}"
        client = get_blob_service_client()
        if not client:
            return None
        
        container_client = client.get_container_client(REFERRAL_BLOB_CONTAINER)
        container_client.upload_blob(blob_name, file_bytes, overwrite=True)
        print(f"[BLOB] Uploaded {blob_name} to {REFERRAL_BLOB_CONTAINER}")
        return blob_name  # Store blob name in DB
    except Exception as e:
        print(f"[BLOB] Upload failed for {case_id}: {e}")
        return None


def download_from_blob(blob_name: str) -> bytes | None:
    """
    Download file from Azure Blob Storage.
    Returns file bytes, or None if download fails.
    """
    if not BLOB_STORAGE_ENABLED or not blob_name:
        return None
    
    try:
        client = get_blob_service_client()
        if not client:
            return None
        
        container_client = client.get_container_client(REFERRAL_BLOB_CONTAINER)
        blob_client = container_client.get_blob_client(blob_name)
        
        download_stream = blob_client.download_blob()
        return download_stream.readall()
    except Exception as e:
        print(f"[BLOB] Download failed for {blob_name}: {e}")
        return None


def blob_exists(blob_name: str) -> bool:
    """Check if a blob exists in storage."""
    if not BLOB_STORAGE_ENABLED or not blob_name:
        return False
    
    try:
        client = get_blob_service_client()
        if not client:
            return False
        
        container_client = client.get_container_client(REFERRAL_BLOB_CONTAINER)
        blob_client = container_client.get_blob_client(blob_name)
        return blob_client.exists()
    except Exception as e:
        print(f"[BLOB] exists() check failed for {blob_name}: {e}")
        return False

app = FastAPI(title="Vetting App")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

APP_SECRET = os.environ.get("APP_SECRET", "dev-secret-change-me")
SESSION_TIMEOUT_MINUTES = 20  # Session expires after 20 minutes of inactivity

APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM = os.environ.get("SMTP_FROM") or SMTP_USER
AUTO_PROVISION_SUPERADMIN = os.environ.get("AUTO_PROVISION_SUPERADMIN", "false").strip().lower() in ("1", "true", "yes", "on")
SUPERADMIN_USERNAME = os.environ.get("SUPERADMIN_USERNAME", "superadmin").strip() or "superadmin"
SUPERADMIN_EMAIL = os.environ.get("SUPERADMIN_EMAIL", "superadmin@lumoslab.com").strip() or "superadmin@lumoslab.com"
SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD", "").strip()
LOGO_DARK_URL = os.environ.get("LOGO_DARK_URL", "/static/images/logo-light.png")

# Warn if using default secret in production
if APP_SECRET == "dev-secret-change-me":
    print("[WARNING] Using default APP_SECRET! Set APP_SECRET environment variable in production!")

app.add_middleware(SessionMiddleware, secret_key=APP_SECRET, same_site="lax", max_age=SESSION_TIMEOUT_MINUTES * 60)

# Middleware to add no-cache headers to authenticated pages
class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Add no-cache headers to all responses to prevent browser caching of authenticated pages
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
        return response

app.add_middleware(NoCacheMiddleware)


# Global 401/403 handler — redirect to login instead of showing a raw error
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code in (401, 403):
        # For AJAX / JSON requests keep the status code
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return RedirectResponse(url=f"/login?expired=1&next={request.url.path}", status_code=303)
    # For other HTTP errors return a simple styled error page
    return HTMLResponse(
        content=f"""<!DOCTYPE html><html><head><title>Error {exc.status_code}</title>
        <style>body{{font-family:sans-serif;background:#0f1724;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
        .box{{text-align:center;}}.btn{{margin-top:20px;padding:10px 20px;background:#1f6feb;color:#fff;border:none;border-radius:6px;text-decoration:none;cursor:pointer;font-size:14px;}}
        </style></head><body><div class="box"><h2>{exc.status_code}</h2><p>{exc.detail}</p>
        <a class="btn" href="/">Go Home</a>&nbsp;<a class="btn" href="/login">Login</a></div></body></html>""",
        status_code=exc.status_code,
    )


# -------------------------
# Health Check Endpoint
# -------------------------
@app.get("/health")
@app.get("/healthz")
async def health_check():
    """
    Health check endpoint for Azure App Service health monitoring.
    Returns 200 OK if the application and database are healthy.
    Returns 503 Service Unavailable if there are issues.
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {}
    }
    
    # Check database connectivity
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = f"error: {str(e)}"
        return JSONResponse(content=health_status, status_code=503)
    
    # Check blob storage if enabled
    if BLOB_STORAGE_ENABLED:
        try:
            blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
            container_client = blob_service_client.get_container_client(REFERRAL_BLOB_CONTAINER)
            container_client.exists()
            health_status["checks"]["blob_storage"] = "ok"
        except Exception as e:
            health_status["status"] = "degraded"
            health_status["checks"]["blob_storage"] = f"warning: {str(e)}"
            # Don't fail health check for blob storage issues, just mark as degraded
    else:
        health_status["checks"]["blob_storage"] = "disabled"
    
    # Return appropriate status code
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)


# Multi-tenant routes disabled for now - using existing login system
# if MULTITENANT_ENABLED:
#     app.include_router(multitenant.router)
#     print("[INFO] Multi-tenant features enabled")

DECISIONS = ["Approve", "Reject", "Approve with comment"]

STATUS_PENDING = "pending"
STATUS_VETTED = "vetted"


# -------------------------
# Helpers
# -------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def format_display_datetime(value: str | None, fallback: str = "") -> str:
    if value is None:
        return fallback
    value_str = str(value).strip()
    if not value_str:
        return fallback
    dt = parse_iso_dt(value_str)
    if not dt:
        return value_str
    return dt.strftime("%d/%m/%Y %H:%M")


templates.env.filters["display_datetime"] = format_display_datetime


def tat_seconds(created_at: str | None, vetted_at: str | None) -> int:
    created_dt = parse_iso_dt(created_at)
    if not created_dt:
        return 0
    end_dt = parse_iso_dt(vetted_at) or datetime.now(timezone.utc)
    return max(0, int((end_dt - created_dt).total_seconds()))


def format_tat(seconds: int) -> str:
    minutes_total = seconds // 60
    hours_total = minutes_total // 60
    days = hours_total // 24
    minutes = minutes_total % 60
    hours = hours_total % 24

    if days > 0:
        return f"{days}d {hours:02}h {minutes:02}m"
    if hours_total > 0:
        return f"{hours_total:02}h {minutes:02}m"
    if minutes_total > 0:
        return f"{minutes_total}m"
    return "<1m"


# -------------------------
# DB
# -------------------------
def get_db() -> sqlite3.Connection:
    # If DATABASE_URL is set, return a SQLAlchemy-backed connection wrapper
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # lazy create engine
        global SA_ENGINE
        if 'SA_ENGINE' not in globals():
            SA_ENGINE = create_engine(database_url)

        class SAResult:
            def __init__(self, result):
                self._result = result

            def fetchall(self):
                try:
                    return [dict(r) for r in self._result.mappings().all()]
                except Exception:
                    return []

            def fetchone(self):
                try:
                    row = self._result.mappings().first()
                    return dict(row) if row else None
                except Exception:
                    return None

        class SAConn:
            def __init__(self, engine):
                self._conn = engine.connect()
                self._trans = self._conn.begin()

            def execute(self, sql, params=None):
                # convert positional ? params to named parameters for SQLAlchemy
                if params is None:
                    params = []
                if isinstance(params, (list, tuple)) and "?" in sql:
                    # replace ? with :p0, :p1 ...
                    parts = sql.split("?")
                    named = []
                    param_map = {}
                    for i in range(len(parts) - 1):
                        name = f":p{i}"
                        named.append(parts[i] + name)
                        param_map[f"p{i}"] = params[i]
                    named.append(parts[-1])
                    sql_named = "".join(named)
                    res = self._conn.execute(text(sql_named), param_map)
                    return SAResult(res)
                else:
                    # assume dict or none
                    if isinstance(params, (list, tuple)):
                        # convert to positional mapping p0..pn
                        param_map = {f"p{i}": v for i, v in enumerate(params)}
                        return SAResult(self._conn.execute(text(sql), param_map))
                    else:
                        return SAResult(self._conn.execute(text(sql), params or {}))

            def commit(self):
                try:
                    self._trans.commit()
                except Exception:
                    pass

            def rollback(self):
                try:
                    self._trans.rollback()
                except Exception:
                    pass

            def close(self):
                try:
                    self._conn.close()
                except Exception:
                    pass

        return SAConn(SA_ENGINE)

    # default: sqlite3
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def using_postgres() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def init_db() -> None:
    if using_postgres():
        conn = get_db()

        # Core multi-tenant tables
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS organisations (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                modified_at TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                salt_hex TEXT NOT NULL,
                is_superuser INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                modified_at TEXT,
                first_name TEXT,
                surname TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memberships (
                id SERIAL PRIMARY KEY,
                org_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                org_role TEXT NOT NULL DEFAULT 'org_user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                modified_at TEXT,
                UNIQUE(org_id, user_id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS radiologist_profiles (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE,
                gmc TEXT,
                specialty TEXT,
                display_name TEXT,
                created_at TEXT NOT NULL,
                modified_at TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                org_id INTEGER,
                user_id INTEGER,
                action TEXT NOT NULL,
                target_user_id INTEGER,
                target_org_id INTEGER,
                details TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL,
                requested_ip TEXT,
                requested_ua TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS case_events (
                id SERIAL PRIMARY KEY,
                case_id TEXT NOT NULL,
                org_id INTEGER,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                user_id INTEGER,
                username TEXT,
                org_role TEXT,
                decision TEXT,
                protocol TEXT,
                comment TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notify_events (
                id SERIAL PRIMARY KEY,
                org_id INTEGER,
                radiologist_name TEXT NOT NULL,
                channel TEXT NOT NULL,
                recipient TEXT,
                message TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT,
                created_by_id INTEGER
            )
            """
        )

        # Legacy operational tables (used by main app)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS institutions (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                sla_hours INTEGER NOT NULL DEFAULT 48,
                created_at TEXT NOT NULL,
                modified_at TEXT,
                org_id INTEGER
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                patient_first_name TEXT NOT NULL,
                patient_surname TEXT NOT NULL,
                patient_referral_id TEXT,
                patient_dob TEXT,
                institution_id INTEGER,
                study_description TEXT NOT NULL,
                modality TEXT,
                admin_notes TEXT,
                radiologist TEXT NOT NULL,
                uploaded_filename TEXT,
                stored_filepath TEXT,
                status TEXT NOT NULL,
                protocol TEXT,
                decision TEXT,
                decision_comment TEXT,
                vetted_at TEXT,
                org_id INTEGER,
                contrast_required TEXT,
                contrast_details TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS protocols (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                institution_id INTEGER NOT NULL,
                instructions TEXT,
                last_modified TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                org_id INTEGER,
                UNIQUE(name, institution_id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS radiologists (
                name TEXT PRIMARY KEY,
                first_name TEXT,
                email TEXT,
                surname TEXT,
                gmc TEXT,
                speciality TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS study_description_presets (
                id SERIAL PRIMARY KEY,
                organization_id INTEGER NOT NULL,
                modality TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                UNIQUE(organization_id, modality, description)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_presets_org_modality
            ON study_description_presets(organization_id, modality)
            """
        )

        conn.commit()
        conn.close()
        return

    conn = get_db()

    # Institutions table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS institutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sla_hours INTEGER NOT NULL DEFAULT 48,
            created_at TEXT NOT NULL
        )
        """
    )

    # Cases table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            patient_first_name TEXT NOT NULL,
            patient_surname TEXT NOT NULL,
            patient_referral_id TEXT,
            patient_dob TEXT,
            institution_id INTEGER,
            study_description TEXT NOT NULL,
            admin_notes TEXT,
            radiologist TEXT NOT NULL,
            uploaded_filename TEXT,
            stored_filepath TEXT,
            status TEXT NOT NULL,
            protocol TEXT,
            decision TEXT,
            decision_comment TEXT,
            vetted_at TEXT,
            FOREIGN KEY (institution_id) REFERENCES institutions(id)
        )
        """
    )

    # Config table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    # Radiologists table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS radiologists (
            name TEXT PRIMARY KEY,
            first_name TEXT,
            email TEXT,
            surname TEXT,
            gmc TEXT,
            speciality TEXT
        )
        """
    )

    # Users table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            first_name TEXT,
            surname TEXT,
            email TEXT,
            role TEXT NOT NULL,
            radiologist_name TEXT,
            salt_hex TEXT NOT NULL,
            pw_hash_hex TEXT NOT NULL
        )
        """
    )

    # Protocols table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS protocols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            institution_id INTEGER NOT NULL,
            instructions TEXT,
            last_modified TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (institution_id) REFERENCES institutions(id),
            UNIQUE(name, institution_id)
        )
        """
    )

    # Password reset tokens
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL,
            requested_ip TEXT,
            requested_ua TEXT
        )
        """
    )

    # Case event history
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS case_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            org_id INTEGER,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER,
            username TEXT,
            org_role TEXT,
            decision TEXT,
            protocol TEXT,
            comment TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notify_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            radiologist_name TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT,
            message TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT,
            created_by_id INTEGER
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS study_description_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            modality TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            UNIQUE(organization_id, modality, description)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_presets_org_modality
        ON study_description_presets(organization_id, modality)
        """
    )

    conn.commit()
    conn.close()


def ensure_cases_schema() -> None:
    """
    Safe schema upgrades for older hub.db files.
    """
    if using_postgres():
        return
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cases'")
    if not cur.fetchone():
        conn.close()
        return

    cur.execute("PRAGMA table_info(cases)")
    cols = {row[1] for row in cur.fetchall()}

    if "status" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
    if "vetted_at" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN vetted_at TEXT")
    if "protocol" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN protocol TEXT")
    if "decision" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN decision TEXT")
    if "decision_comment" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN decision_comment TEXT")
    if "patient_first_name" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN patient_first_name TEXT")
    if "patient_surname" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN patient_surname TEXT")
    if "patient_referral_id" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN patient_referral_id TEXT")
    if "patient_dob" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN patient_dob TEXT")
    if "institution_id" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN institution_id INTEGER")
    if "modality" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN modality TEXT")
    if "contrast_required" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN contrast_required TEXT")
    if "contrast_details" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN contrast_details TEXT")

    conn.commit()
    conn.close()


def ensure_institutions_schema() -> None:
    """
    Safe schema upgrades for the institutions table (Bug 2: Add modified_at column).
    """
    if using_postgres():
        return
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='institutions'")
    if not cur.fetchone():
        conn.close()
        return

    cur.execute("PRAGMA table_info(institutions)")
    cols = {row[1] for row in cur.fetchall()}

    if "modified_at" not in cols:
        cur.execute("ALTER TABLE institutions ADD COLUMN modified_at TEXT")

    conn.commit()
    conn.close()


def ensure_radiologists_schema() -> None:
    """
    Safe schema upgrades for the radiologists table.
    """
    if using_postgres():
        return
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='radiologists'")
    if not cur.fetchone():
        conn.close()
        return

    cur.execute("PRAGMA table_info(radiologists)")
    cols = {row[1] for row in cur.fetchall()}

    if "first_name" not in cols:
        cur.execute("ALTER TABLE radiologists ADD COLUMN first_name TEXT")
    if "surname" not in cols:
        cur.execute("ALTER TABLE radiologists ADD COLUMN surname TEXT")
    if "gmc" not in cols:
        cur.execute("ALTER TABLE radiologists ADD COLUMN gmc TEXT")
    if "speciality" not in cols:
        cur.execute("ALTER TABLE radiologists ADD COLUMN speciality TEXT")

    conn.commit()
    conn.close()


def ensure_users_schema() -> None:
    """
    Safe schema upgrades for the users table.
    """
    if using_postgres():
        conn = get_db()
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS surname TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
        conn.commit()
        conn.close()
        return
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cur.fetchone():
        conn.close()
        return

    cur.execute("PRAGMA table_info(users)")
    cols = {row[1] for row in cur.fetchall()}

    if "first_name" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
    if "surname" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN surname TEXT")
    if "email" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN email TEXT")

    conn.commit()
    conn.close()


def ensure_protocols_schema() -> None:
    """
    Safe schema upgrades for the protocols table.
    """
    if using_postgres():
        return
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='protocols'")
    if not cur.fetchone():
        conn.close()
        return

    cur.execute("PRAGMA table_info(protocols)")
    cols = {row[1] for row in cur.fetchall()}

    if "institution_id" not in cols:
        cur.execute("ALTER TABLE protocols ADD COLUMN institution_id INTEGER")
    if "org_id" not in cols:
        cur.execute("ALTER TABLE protocols ADD COLUMN org_id INTEGER")

    conn.commit()
    conn.close()


def ensure_notify_events_schema() -> None:
    if using_postgres():
        return
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notify_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            radiologist_name TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT,
            message TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT,
            created_by_id INTEGER
        )
        """
    )
    conn.commit()
    conn.close()


def cleanup_old_files() -> None:
    """
    Storage TTL enforcement:
    - Referral attachment files (stored_filepath) are deleted from disk after REFERRAL_FILE_TTL_DAYS days.
      The case record and DB row are kept; stored_filepath is set to NULL so the viewing link shows
      a "file no longer available" message instead of an error.
    - The case DB record itself is retained for CASE_RECORD_TTL_DAYS days before being archived/deleted.
      (Phase 1: only file deletion is implemented; DB record retention can be added later.)
    """
    if using_postgres():
        return  # Postgres / cloud deployments handle file lifecycle separately

    try:
        conn = get_db()
        cutoff_referral = (datetime.now() - timedelta(days=REFERRAL_FILE_TTL_DAYS)).isoformat()
        # Find cases whose upload file should be deleted (created more than TTL days ago and still have a stored path)
        rows = conn.execute(
            "SELECT id, stored_filepath FROM cases WHERE created_at < ? AND stored_filepath IS NOT NULL AND stored_filepath != ''",
            (cutoff_referral,)
        ).fetchall()

        deleted_count = 0
        for row in rows:
            filepath = row["stored_filepath"]
            try:
                p = Path(filepath)
                if p.exists():
                    p.unlink()
                    deleted_count += 1
            except Exception as e:
                print(f"[TTL] Could not delete file {filepath}: {e}")
            # Null out the stored path so UI shows 'unavailable' gracefully
            conn.execute(
                "UPDATE cases SET stored_filepath = NULL WHERE id = ?",
                (row["id"],)
            )

        if rows:
            conn.commit()
            print(f"[TTL] Referral file cleanup: deleted {deleted_count}/{len(rows)} files older than {REFERRAL_FILE_TTL_DAYS} days.")
        conn.close()
    except Exception as e:
        print(f"[TTL] cleanup_old_files error: {e}")


def get_setting(key: str, default: str) -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO config(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


# -------------------------
# Radiologists
# -------------------------
def list_radiologists(org_id: int | None = None) -> list[dict]:
    if org_id and table_exists("memberships") and table_exists("users"):
        conn = get_db()
        rows = conn.execute(
            """
            SELECT u.username as name, u.email, u.surname, rp.gmc, rp.specialty as speciality, rp.display_name
            FROM memberships m
            JOIN users u ON m.user_id = u.id
            LEFT JOIN radiologist_profiles rp ON rp.user_id = u.id
            WHERE m.org_id = ? AND m.is_active = 1 AND m.org_role = 'radiologist'
            ORDER BY COALESCE(rp.display_name, u.username)
            """,
            (org_id,),
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("display_name"):
                d["name"] = d["display_name"]
            result.append(d)
        return result

    conn = get_db()
    rows = conn.execute("SELECT name, email, surname, gmc, speciality FROM radiologists ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_radiologist(name: str, email: str, surname: str = "", gmc: str = "") -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO radiologists(name, email, surname, gmc) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET email=excluded.email, surname=excluded.surname, gmc=excluded.gmc",
        (name.strip(), email.strip(), surname.strip(), gmc.strip()),
    )
    conn.commit()
    conn.close()


def delete_radiologist(name: str) -> None:
    conn = get_db()
    conn.execute("DELETE FROM radiologists WHERE name = ?", (name.strip(),))
    conn.commit()
    conn.close()


def get_radiologist(name: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT name, email, surname, gmc, speciality FROM radiologists WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


# -------------------------
# Protocols
# -------------------------
DEFAULT_PROTOCOLS = [
    "CT Head (standard)",
    "CT Head (stroke)",
    "CT C-Spine",
    "CT Chest",
    "CT Abdomen/Pelvis",
    "CT KUB",
    "MRI Brain",
    "MRI Spine",
    "XR Chest",
]


def ensure_default_protocols() -> None:
    if using_postgres():
        return
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM protocols").fetchone()
    if row and row["c"] == 0:
        for p in DEFAULT_PROTOCOLS:
            conn.execute("INSERT OR IGNORE INTO protocols(name, is_active) VALUES(?, 1)", (p,))
        conn.commit()
    conn.close()


def _load_study_presets_from_migration() -> list[tuple[str, str]]:
    full_csv_path = BASE_DIR / "database" / "migrations" / "004_study_description_presets_full.csv"
    if full_csv_path.exists():
        presets: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        try:
            with full_csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    modality_clean = (row.get("modality") or "").strip().upper()
                    description_clean = (row.get("description") or "").strip()
                    if not modality_clean or not description_clean:
                        continue
                    key = (modality_clean, description_clean)
                    if key in seen:
                        continue
                    seen.add(key)
                    presets.append(key)
            if presets:
                return presets
        except Exception:
            pass

    migration_path = BASE_DIR / "database" / "migrations" / "003_study_description_presets.sql"
    if not migration_path.exists():
        return []

    try:
        sql_text = migration_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    pattern = re.compile(r"\(\s*1\s*,\s*'([^']+)'\s*,\s*'((?:''|[^'])+)'\s*,")
    presets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for modality, description in pattern.findall(sql_text):
        modality_clean = modality.strip().upper()
        description_clean = description.replace("''", "'").strip()
        if not modality_clean or not description_clean:
            continue
        key = (modality_clean, description_clean)
        if key in seen:
            continue
        seen.add(key)
        presets.append(key)

    return presets


def ensure_default_study_description_presets() -> None:
    if not table_exists("study_description_presets"):
        return

    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM study_description_presets").fetchone()
    if row and row["c"]:
        conn.close()
        return

    presets = _load_study_presets_from_migration()
    if not presets:
        presets = [
            ("CT", "CT Head"),
            ("CT", "CT Thorax"),
            ("MRI", "MRI Brain"),
            ("MRI", "MRI Spine lumbar"),
            ("XR", "XR Chest"),
            ("PET", "PET FDG Whole body"),
            ("DEXA", "DXA Whole body"),
        ]

    now = utc_now_iso()
    for modality, description in presets:
        if using_postgres():
            conn.execute(
                """
                INSERT INTO study_description_presets (organization_id, modality, description, created_at, updated_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (organization_id, modality, description) DO NOTHING
                """,
                (1, modality, description, now, now, 1),
            )
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO study_description_presets (organization_id, modality, description, created_at, updated_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (1, modality, description, now, now, 1),
            )

    conn.commit()
    conn.close()


def list_protocols(active_only: bool = True, org_id: int | None = None) -> list[str]:
    conn = get_db()
    base_sql = "SELECT name FROM protocols"
    clauses = []
    params: list = []

    if active_only:
        clauses.append("is_active = 1")
    if org_id and table_has_column("protocols", "org_id"):
        clauses.append("org_id = ?")
        params.append(org_id)

    if clauses:
        base_sql += " WHERE " + " AND ".join(clauses)
    base_sql += " ORDER BY name"

    rows = conn.execute(base_sql, params).fetchall()
    conn.close()
    return [r["name"] for r in rows]


def list_protocol_rows(org_id: int | None = None) -> list[dict]:
    conn = get_db()
    if org_id and table_has_column("protocols", "org_id"):
        rows = conn.execute(
            "SELECT p.id, p.name, p.institution_id, p.instructions, p.last_modified, p.is_active, i.name as institution_name "
            "FROM protocols p LEFT JOIN institutions i ON p.institution_id = i.id "
            "WHERE p.org_id = ? ORDER BY p.name",
            (org_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT p.id, p.name, p.institution_id, p.instructions, p.last_modified, p.is_active, i.name as institution_name FROM protocols p LEFT JOIN institutions i ON p.institution_id = i.id ORDER BY p.name"
        ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["last_modified"] = format_display_datetime(d.get("last_modified"), d.get("last_modified") or "")
        result.append(d)
    return result


def upsert_protocol(name: str) -> None:
    name = name.strip()
    if not name:
        return
    conn = get_db()
    if using_postgres():
        conn.execute("INSERT INTO protocols(name, is_active) VALUES(?, 1)", (name,))
    else:
        conn.execute("INSERT OR IGNORE INTO protocols(name, is_active) VALUES(?, 1)", (name,))
    conn.execute("UPDATE protocols SET is_active = 1 WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def deactivate_protocol(name: str, org_id: int | None = None) -> None:
    conn = get_db()
    if org_id and table_has_column("protocols", "org_id"):
        conn.execute("UPDATE protocols SET is_active = 0 WHERE name = ? AND org_id = ?", (name.strip(), org_id))
    else:
        conn.execute("UPDATE protocols SET is_active = 0 WHERE name = ?", (name.strip(),))
    conn.commit()
    conn.close()


# -------------------------
# Users (PBKDF2)
# -------------------------
def hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)


def create_user(username: str, password: str, role: str, radiologist_name: str | None = None, first_name: str = "", surname: str = "", email: str = "") -> None:
    username = username.strip()
    role = role.strip()
    if role not in ("admin", "radiologist", "user"):
        raise ValueError("Invalid role")
    if role == "radiologist" and not radiologist_name:
        raise ValueError("Radiologist name is required")

    salt = secrets.token_bytes(16)
    pw_hash = hash_password(password, salt)

    conn = get_db()
    conn.execute(
        """
        INSERT INTO users(username, first_name, surname, email, role, radiologist_name, salt_hex, pw_hash_hex)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
          first_name=excluded.first_name,
          surname=excluded.surname,
          email=excluded.email,
          role=excluded.role,
          radiologist_name=excluded.radiologist_name,
          salt_hex=excluded.salt_hex,
          pw_hash_hex=excluded.pw_hash_hex
        """,
        (username, first_name.strip(), surname.strip(), email.strip(), role, radiologist_name, salt.hex(), pw_hash.hex()),
    )
    conn.commit()
    conn.close()


def verify_user(username: str, password: str) -> dict | None:
    normalized_username = username.strip()

    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (normalized_username,)).fetchone()
    conn.close()
    if not row:
        return None

    salt = bytes.fromhex(row["salt_hex"])
    
    # Support both old (pw_hash_hex) and new (password_hash) column names
    # Check which column exists in the row
    try:
        pw_hash_hex = row["password_hash"]
    except (KeyError, IndexError):
        try:
            pw_hash_hex = row["pw_hash_hex"]
        except (KeyError, IndexError):
            return None
    
    if not pw_hash_hex:
        return None
        
    expected = bytes.fromhex(pw_hash_hex)
    provided = hash_password(password, salt)
    
    if secrets.compare_digest(provided, expected):
        user_dict = dict(row)
        # Map new structure to old for backward compatibility
        row_keys = row.keys()
        if "is_superuser" in row_keys:
            is_platform_superadmin = normalized_username.lower() == "superadmin"
            user_dict["is_superuser"] = True if (row["is_superuser"] and is_platform_superadmin) else False

            if user_dict["is_superuser"]:
                user_dict["role"] = "admin"
            else:
                # Map role from active membership (only if user has id column)
                if "id" in row_keys:
                    conn = get_db()
                    membership = conn.execute(
                        "SELECT org_role FROM memberships WHERE user_id = ? AND is_active = 1 ORDER BY id LIMIT 1",
                        (row["id"],),
                    ).fetchone()
                    conn.close()

                    if membership and membership["org_role"] == "org_admin":
                        user_dict["role"] = "admin"
                    elif membership and membership["org_role"] == "radiologist":
                        user_dict["role"] = "radiologist"
                    else:
                        user_dict["role"] = "user"
                else:
                    # Fall back to role column for old schema
                    user_dict["role"] = row.get("role", "user")

            user_dict["radiologist_name"] = None  # Will be looked up separately if needed
        return user_dict
    return None


def list_users(org_id: int | None = None) -> list[dict]:
    conn = get_db()
    # Check which table structure we have (old vs new)
    if table_has_column("users", "is_superuser"):
        # New multi-tenant structure
        if org_id:
            rows = conn.execute(
                """
                SELECT 
                    u.id as user_id, u.username, u.email, u.is_superuser,
                    u.is_active, u.first_name, u.surname,
                    m.org_role as org_role,
                    NULL as radiologist_name
                FROM users u
                INNER JOIN memberships m ON m.user_id = u.id AND m.org_id = ? AND m.is_active = 1
                WHERE u.is_superuser = 0
                ORDER BY u.username
                """,
                (org_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT 
                    u.id as user_id, u.username, u.email, u.is_superuser,
                    u.is_active, u.first_name, u.surname,
                    NULL as org_role,
                    NULL as radiologist_name
                FROM users u
                ORDER BY u.username
                """
            ).fetchall()
    else:
        # Old structure
        rows = conn.execute("""
            SELECT username, first_name, surname, email, role, radiologist_name 
            FROM users 
            ORDER BY username
        """).fetchall()
    
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if "org_role" in d and d.get("org_role"):
            if d["org_role"] == "org_admin":
                d["role"] = "admin"
            elif d["org_role"] == "radiologist":
                d["role"] = "radiologist"
            else:
                d["role"] = "user"
        result.append(d)
    return result


def delete_user(username: str) -> None:
    conn = get_db()
    conn.execute("DELETE FROM users WHERE username = ?", (username.strip(),))
    conn.commit()
    conn.close()


# -------------------------
# Seed data
# -------------------------
RADIOLOGISTS_SEED = ["Dr Smith", "Dr Patel", "Dr Jones"]
DEFAULT_INSTITUTIONS = [
    ("UHCL", 48),
    ("Nuffield Hospital", 24),
    ("Local Medical Centre", 72),
]


def ensure_seed_data() -> None:
    if using_postgres():
        return
    if not get_setting("system_initialized", ""):
        set_setting("system_initialized", "true")

    # Add default institutions
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM institutions").fetchone()
    if row and row["c"] == 0:
        for inst_name, sla in DEFAULT_INSTITUTIONS:
            conn.execute(
                "INSERT INTO institutions(name, sla_hours, created_at) VALUES(?, ?, ?)",
                (inst_name, sla, utc_now_iso()),
            )
        conn.commit()
    conn.close()

    # Add radiologists
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM radiologists").fetchone()
    if row and row["c"] == 0:
        for n in RADIOLOGISTS_SEED:
            conn.execute(
                "INSERT OR IGNORE INTO radiologists(name, first_name, email, surname, gmc, speciality) VALUES(?, ?, ?, ?, ?, ?)",
                (n, "", "", "", "", ""),
            )
        conn.commit()
    conn.close()

    # Add admin user
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    conn.close()
    if row and row["c"] == 0:
        create_user("admin", "admin123", "admin", None, "Admin", "User", "admin@lumoslab.com")


def ensure_superadmin_user() -> None:
    """
    Ensure a dedicated superadmin user exists for multi-tenant dashboard access.
    Controlled by environment variables to avoid hardcoded credentials.
    """
    if not AUTO_PROVISION_SUPERADMIN:
        return

    if not SUPERADMIN_PASSWORD:
        print("[WARNING] AUTO_PROVISION_SUPERADMIN is enabled but SUPERADMIN_PASSWORD is empty. Skipping superadmin bootstrap.")
        return

    username = SUPERADMIN_USERNAME
    password = SUPERADMIN_PASSWORD
    email = SUPERADMIN_EMAIL
    now = utc_now_iso()

    if table_has_column("users", "password_hash") and table_has_column("users", "is_superuser"):
        conn = get_db()
        
        # Check if superadmin user already exists
        existing = conn.execute("SELECT id, email FROM users WHERE username = ?", (username,)).fetchone()
        
        salt = secrets.token_bytes(16)
        pw_hash = hash_password(password, salt)
        
        if existing:
            # User exists - just update password and ensure superuser status
            conn.execute(
                """
                UPDATE users 
                SET password_hash = ?, salt_hex = ?, is_superuser = 1, is_active = 1, modified_at = ?
                WHERE username = ?
                """,
                (pw_hash.hex(), salt.hex(), now, username),
            )
            print(f"[startup] Updated superadmin user: {username}")
        else:
            # Create new superadmin user
            # Check if email is already taken by another user
            email_exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if email_exists:
                # Use a unique email if the configured one is taken
                unique_email = f"superadmin-{secrets.token_hex(4)}@lumoslab.com"
                print(f"[WARNING] Email {email} already in use. Using {unique_email} for superadmin.")
                email = unique_email
            
            conn.execute(
                """
                INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at)
                VALUES(?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (username, email, pw_hash.hex(), salt.hex(), now, now),
            )
            print(f"[startup] Created superadmin user: {username} ({email})")
        
        conn.commit()
        conn.close()
        return

    # Legacy schema fallback
    try:
        create_user(username, password, "admin", None, "Super", "Admin", email)
    except Exception:
        pass


# -------------------------
# Institutions
# -------------------------
def list_institutions(org_id: int | None = None) -> list[dict]:
    conn = get_db()
    if table_has_column("institutions", "org_id"):
        if org_id:
            rows = conn.execute(
                "SELECT id, name, sla_hours, created_at, modified_at, org_id FROM institutions WHERE org_id = ? ORDER BY name",
                (org_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, sla_hours, created_at, modified_at, org_id FROM institutions ORDER BY name"
            ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, sla_hours, created_at, modified_at FROM institutions ORDER BY name"
        ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["created_at"] = format_display_datetime(d.get("created_at"), d.get("created_at") or "")
        d["modified_at"] = format_display_datetime(d.get("modified_at"), d.get("modified_at") or "")
        if not d.get("modified_at"):
            d["modified_at"] = d.get("created_at")  # Use created_at if modified_at not set
        result.append(d)
    return result


def get_institution(inst_id: int, org_id: int | None = None) -> dict | None:
    conn = get_db()
    if org_id and table_has_column("institutions", "org_id"):
        row = conn.execute(
            "SELECT id, name, sla_hours FROM institutions WHERE id = ? AND org_id = ?",
            (inst_id, org_id),
        ).fetchone()
    else:
        row = conn.execute("SELECT id, name, sla_hours FROM institutions WHERE id = ?", (inst_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_institution(name: str, sla_hours: int, org_id: int | None = None) -> int:
    conn = get_db()
    if org_id and table_has_column("institutions", "org_id"):
        conn.execute(
            "INSERT INTO institutions(name, sla_hours, created_at, modified_at, org_id) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET sla_hours=excluded.sla_hours, modified_at=excluded.modified_at",
            (name.strip(), sla_hours, utc_now_iso(), utc_now_iso(), org_id),
        )
    else:
        conn.execute(
            "INSERT INTO institutions(name, sla_hours, created_at, modified_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET sla_hours=excluded.sla_hours, modified_at=excluded.modified_at",
            (name.strip(), sla_hours, utc_now_iso(), utc_now_iso()),
        )
    conn.commit()
    if org_id and table_has_column("institutions", "org_id"):
        row = conn.execute("SELECT id FROM institutions WHERE name = ? AND org_id = ?", (name.strip(), org_id)).fetchone()
    else:
        row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name.strip(),)).fetchone()
    inst_id = row["id"] if row else None
    conn.close()
    return inst_id


def delete_institution(inst_id: int, org_id: int | None = None) -> None:
    conn = get_db()
    if org_id and table_has_column("institutions", "org_id"):
        conn.execute("DELETE FROM institutions WHERE id = ? AND org_id = ?", (inst_id, org_id))
    else:
        conn.execute("DELETE FROM institutions WHERE id = ?", (inst_id,))
    conn.commit()
    conn.close()


# -------------------------
# Auth helpers
# -------------------------
def get_session_user(request: Request) -> dict | None:
    """Get current user from session with expiration check and multi-window detection"""
    user = request.session.get("user")
    if not user:
        return None
    
    # Check if session has login timestamp and if it's expired
    login_time = request.session.get("login_time")
    session_id = request.session.get("session_id")
    
    if login_time:
        try:
            import time
            current_time = time.time()
            # Session timeout = 20 minutes of inactivity
            if current_time - login_time > SESSION_TIMEOUT_MINUTES * 60:
                request.session.clear()
                return None
            
            # Validate session_id for multi-window logout (detect new login from another window)
            if session_id and user.get("id"):
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute("SELECT session_id FROM user_sessions WHERE user_id = ? LIMIT 1", (user.get("id"),))
                    row = cur.fetchone()
                    conn.close()
                    if row:
                        stored_session_id = row[0] if isinstance(row, tuple) else row.get("session_id")
                        if stored_session_id and stored_session_id != session_id:
                            # User logged in from another window/browser - invalidate this session
                            request.session.clear()
                            return None
                except Exception:
                    pass  # Table might not exist for old schema, continue
            
            # Update login_time on each request (sliding window)
            request.session["login_time"] = current_time
        except Exception:
            return None
    
    return user


def require_login(request: Request) -> dict:
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def get_current_org_context(request: Request) -> tuple[int | None, bool, int | None, str | None]:
    user = get_session_user(request) or {}
    user_id = user.get("id")
    is_superuser = bool(user.get("is_superuser"))
    org_id = user.get("org_id")
    org_role = user.get("org_role") or user.get("role")

    if user_id and table_exists("memberships"):
        membership = get_user_primary_membership(user_id)
        if membership:
            org_id = membership.get("org_id") or org_id
            org_role = membership.get("org_role") or org_role
            if not user.get("org_id"):
                user["org_id"] = org_id
            if not user.get("org_role") and org_role:
                user["org_role"] = org_role
            request.session["user"] = user

    return user_id, is_superuser, org_id, org_role


def require_admin(request: Request) -> dict:
    user = require_login(request)
    _user_id, is_superuser, _org_id, org_role = get_current_org_context(request)
    if is_superuser:
        return user
    if table_exists("memberships"):
        if org_role in ("org_admin", "radiology_admin"):
            return user
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_superuser(request: Request) -> dict:
    user = require_admin(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser only")
    return user


def require_radiologist(request: Request) -> dict:
    user = require_login(request)
    _user_id, is_superuser, _org_id, org_role = get_current_org_context(request)
    if is_superuser:
        raise HTTPException(status_code=403, detail="Radiologist only")
    if table_exists("memberships"):
        if org_role != "radiologist":
            raise HTTPException(status_code=403, detail="Radiologist only")
    elif user.get("role") != "radiologist":
        raise HTTPException(status_code=403, detail="Radiologist only")
    
    # Populate radiologist_name from radiologist profile if not already set
    if not user.get("radiologist_name") and user.get("id"):
        try:
            conn = get_db()
            rad_profile = conn.execute(
                "SELECT display_name FROM radiologist_profiles WHERE user_id = ? LIMIT 1",
                (user.get("id"),)
            ).fetchone()
            if rad_profile:
                radiologist_name = rad_profile.get("display_name") if isinstance(rad_profile, dict) else rad_profile[0]
                user["radiologist_name"] = radiologist_name
                # Also update the session
                request.session["user"] = user
            conn.close()
        except Exception:
            pass
    
    # Also try to get from radiologists table using first/last name
    if not user.get("radiologist_name") and user.get("first_name"):
        try:
            conn = get_db()
            first_name = user.get("first_name", "")
            surname = user.get("surname", "")
            full_name = f"{first_name} {surname}".strip() if surname else first_name
            
            rad_row = conn.execute(
                "SELECT name FROM radiologists WHERE name = ? OR first_name = ? LIMIT 1",
                (full_name, first_name)
            ).fetchone()
            if rad_row:
                radiologist_name = rad_row.get("name") if isinstance(rad_row, dict) else rad_row[0]
                user["radiologist_name"] = radiologist_name
                # Also update the session
                request.session["user"] = user
            conn.close()
        except Exception:
            pass
    
    return user


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    import hmac
    digest = hmac.new(APP_SECRET.encode("utf-8"), token.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def send_email(to_address: str, subject: str, body: str) -> bool:
    if not SMTP_HOST or not SMTP_FROM:
        print("[email] SMTP not configured. Email content below:")
        print(f"To: {to_address}\nSubject: {subject}\n\n{body}")
        return False

    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)

    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
    try:
        server.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        return True
    finally:
        try:
            server.quit()
        except Exception:
            pass


def get_user_by_email(email: str) -> dict | None:
    if not email:
        return None
    conn = get_db()
    if table_has_column("users", "is_active"):
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? AND is_active = 1",
            (email.strip().lower(),),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def table_exists(table_name: str) -> bool:
    conn = get_db()
    if using_postgres():
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ?",
            (table_name,),
        ).fetchone()
        conn.close()
        return bool(row)

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    conn.close()
    return bool(row)


def table_has_column(table_name: str, column_name: str) -> bool:
    conn = get_db()
    if using_postgres():
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ? AND column_name = ?",
            (table_name, column_name),
        ).fetchone()
        conn.close()
        return bool(row)

    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = {row[1] for row in cur.fetchall()}
    conn.close()
    return column_name in cols


def get_user_primary_membership(user_id: int) -> dict | None:
    if not table_exists("memberships"):
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT org_id, org_role FROM memberships WHERE user_id = ? AND is_active = 1 ORDER BY id LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_request_org_id(request: Request) -> int | None:
    user = get_session_user(request) or {}
    return user.get("org_id")


def redirect_to_login(role: str, next_path: str):
    return RedirectResponse(url=f"/login?role={role}&next={next_path}", status_code=303)


def insert_case_event(
    case_id: str,
    org_id: int | None,
    event_type: str,
    user: dict | None = None,
    decision: str | None = None,
    protocol: str | None = None,
    comment: str | None = None,
) -> None:
    if not table_exists("case_events"):
        return

    now = utc_now_iso()
    user_id = None
    username = None
    org_role = None

    if user:
        user_id = user.get("id")
        username = user.get("username")
        org_role = user.get("org_role") or user.get("role")

    conn = get_db()
    conn.execute(
        """
        INSERT INTO case_events (case_id, org_id, event_type, created_at, user_id, username, org_role, decision, protocol, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (case_id, org_id, event_type, now, user_id, username, org_role, decision, protocol, comment),
    )
    conn.commit()
    conn.close()


# -------------------------
# Init DB on startup
# -------------------------
try:
    print("[startup] Initializing database...")
    init_db()
    ensure_cases_schema()
    ensure_institutions_schema()
    ensure_radiologists_schema()
    ensure_users_schema()
    ensure_protocols_schema()
    ensure_notify_events_schema()
    ensure_seed_data()
    ensure_superadmin_user()
    ensure_default_protocols()
    ensure_default_study_description_presets()
    cleanup_old_files()
    print("[startup] Database initialization complete")
except Exception as e:
    print(f"[ERROR] Database initialization failed: {e}")
    import traceback
    traceback.print_exc()
    print("[ERROR] Application may not function correctly. Check DATABASE_URL environment variable.")


# -------------------------
# Landing + login/logout
# -------------------------
@app.get("/", response_class=HTMLResponse)
def landing(request: Request, expired: str = ""):
    user = get_session_user(request)
    if user:
        if user.get("is_superuser"):
            return RedirectResponse(url="/mt", status_code=303)
        if user.get("role") == "admin":
            return RedirectResponse(url="/admin", status_code=303)
        return RedirectResponse(url="/radiologist", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request, "expired": expired})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, expired: str = ""):
    # Redirect to home if already logged in
    user = get_session_user(request)
    if user:
        if user.get("is_superuser"):
            return RedirectResponse(url="/mt", status_code=303)
        if user.get("role") == "admin":
            return RedirectResponse(url="/admin", status_code=303)
        return RedirectResponse(url="/radiologist", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request, "expired": expired})


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    try:
        user = verify_user(username, password)
        if not user:
            return templates.TemplateResponse(
                "index.html",
                {"request": request, "error": "Invalid username or password"},
                status_code=401,
            )
    except Exception as e:
        print(f"[ERROR] Login failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "System error during login. Please check server logs."},
            status_code=500,
        )

    import time
    import uuid
    
    # Generate unique session ID for multi-window logout
    session_id = str(uuid.uuid4())
    
    request.session["user"] = {
        "id": user.get("id"),  # May be None for old schema
        "username": user["username"],
        "first_name": user.get("first_name"),
        "surname": user.get("surname"),
        "role": user["role"],
        "radiologist_name": user["radiologist_name"],
        "is_superuser": user.get("is_superuser", False),
    }
    request.session["login_time"] = time.time()  # Store login timestamp
    request.session["session_id"] = session_id  # Track session for multi-window detection
    
    # Store session_id in database for multi-window logout detection
    if user.get("id"):
        try:
            conn = get_db()
            # Try to store in user_sessions table (new schema)
            try:
                conn.execute(
                    "INSERT INTO user_sessions(user_id, session_id, created_at) VALUES(?, ?, datetime('now')) ON CONFLICT(user_id) DO UPDATE SET session_id=excluded.session_id, created_at=excluded.created_at",
                    (user.get("id"), session_id)
                )
                conn.commit()
            except Exception:
                # Table might not exist, silently fail
                pass
            conn.close()
        except Exception:
            pass

    # Attach org context for non-superadmin users
    if not user.get("is_superuser") and user.get("id"):
        membership = get_user_primary_membership(user["id"])
        if membership:
            request.session["user"]["org_id"] = membership.get("org_id")
            request.session["user"]["org_role"] = membership.get("org_role")

    # Auto-route based on user role
    if user.get("is_superuser"):
        return RedirectResponse(url="/mt", status_code=303)
    if user["role"] == "admin":
        return RedirectResponse(url="/admin", status_code=303)
    else:
        return RedirectResponse(url="/radiologist", status_code=303)


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, role: str = "admin"):
    user = get_session_user(request)
    if user:
        if user.get("role") == "admin":
            return RedirectResponse(url="/admin", status_code=303)
        return RedirectResponse(url="/radiologist", status_code=303)

    role = (role or "admin").strip().lower()
    if role not in ("admin", "radiologist"):
        role = "admin"

    return templates.TemplateResponse(
        "forgot_password.html",
        {"request": request, "role": role, "submitted": False},
    )


@app.post("/forgot-password", response_class=HTMLResponse)
def forgot_password_submit(request: Request, role: str = Form("admin"), email: str = Form(...)):
    role = (role or "admin").strip().lower()
    if role not in ("admin", "radiologist"):
        role = "admin"

    email = (email or "").strip().lower()
    user = get_user_by_email(email)

    if user and user.get("id"):
        token = generate_token()
        token_hash = hash_token(token)
        now = utc_now_iso()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat()

        requested_ip = request.client.host if request.client else None
        requested_ua = request.headers.get("user-agent")

        conn = get_db()
        conn.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, used_at, created_at, requested_ip, requested_ua)
            VALUES (?, ?, ?, NULL, ?, ?, ?)
            """,
            (user.get("id"), token_hash, expires_at, now, requested_ip, requested_ua),
        )
        conn.commit()
        conn.close()

        reset_link = f"{APP_BASE_URL}/reset-password?token={token}"
        send_email(
            to_address=email,
            subject="Password reset request",
            body=f"Use this link to reset your password (valid for 60 minutes):\n{reset_link}",
        )

    return templates.TemplateResponse(
        "forgot_password.html",
        {"request": request, "role": role, "submitted": True},
    )


@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str = ""):
    token = (token or "").strip()
    if not token:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": "", "error": "Invalid or expired reset link."},
            status_code=400,
        )

    token_hash = hash_token(token)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = ?",
        (token_hash,),
    ).fetchone()
    conn.close()

    if not row:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": "", "error": "Invalid or expired reset link."},
            status_code=400,
        )

    if row.get("used_at"):
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": "", "error": "Reset link already used."},
            status_code=400,
        )

    expires_at = parse_iso_dt(row.get("expires_at"))
    if not expires_at or expires_at < datetime.now(timezone.utc):
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": "", "error": "Reset link expired."},
            status_code=400,
        )

    return templates.TemplateResponse(
        "reset_password.html",
        {"request": request, "token": token},
    )


@app.post("/reset-password", response_class=HTMLResponse)
def reset_password_submit(request: Request, token: str = Form(""), password: str = Form("")):
    token = (token or "").strip()
    if not token or not password:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token, "error": "Token and password are required."},
            status_code=400,
        )

    token_hash = hash_token(token)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = ?",
        (token_hash,),
    ).fetchone()

    if not row or row.get("used_at"):
        conn.close()
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": "", "error": "Invalid or expired reset link."},
            status_code=400,
        )

    expires_at = parse_iso_dt(row.get("expires_at"))
    if not expires_at or expires_at < datetime.now(timezone.utc):
        conn.close()
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": "", "error": "Reset link expired."},
            status_code=400,
        )

    user_id = row.get("user_id")
    if not user_id:
        conn.close()
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": "", "error": "Invalid or expired reset link."},
            status_code=400,
        )

    salt = secrets.token_bytes(16)
    pw_hash = hash_password(password, salt)
    now = utc_now_iso()

    if table_has_column("users", "password_hash"):
        conn.execute(
            "UPDATE users SET password_hash = ?, salt_hex = ?, modified_at = ? WHERE id = ?",
            (pw_hash.hex(), salt.hex(), now, user_id),
        )
    else:
        conn.close()
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": "", "error": "Password reset not supported for this user schema."},
            status_code=400,
        )

    conn.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
        (now, row.get("id")),
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url="/login", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    response = RedirectResponse(url="/", status_code=303)
    # Add headers to prevent caching of authenticated pages
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# -------------------------
# Admin dashboard (tabs + filters + TAT)
# -------------------------
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    tab: str = "all",
    institution: str | None = None,
    radiologist: str | None = None,
    q: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
):
    try:
        user = require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/admin")

    org_id = user.get("org_id")
    org_name = "Admin Dashboard"
    
    # Get org name if user has org_id
    if org_id:
        conn = get_db()
        org_row = conn.execute("SELECT name FROM organisations WHERE id = ?", (org_id,)).fetchone()
        if org_row:
            org_name = f"Admin Dashboard - {org_row['name']}"
        conn.close()
    
    if not user.get("is_superuser") and not org_id:
        return templates.TemplateResponse(
            "home.html",
            {
                "request": request,
                "tab": tab,
                "cases": [],
                "institutions": [],
                "selected_institution": institution or "",
                "radiologists": [],
                "selected_radiologist": radiologist or "",
                "q": q or "",
                "sort_by": sort_by,
                "sort_dir": sort_dir,
                "pending_count": 0,
                "vetted_count": 0,
                "rejected_count": 0,
                "total_count": 0,
                "org_name": org_name,
                "current_user": get_session_user(request),
            },
        )

    tab = (tab or "all").strip().lower()
    if tab not in ("all", "pending", "vetted", "rejected"):
        tab = "all"

    # Validate sort parameters
    valid_sorts = ["created_at", "patient_first_name", "patient_surname", "patient_referral_id", "institution_id", "tat", "status", "study_description", "radiologist"]
    if sort_by not in valid_sorts:
        sort_by = "created_at"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    sql = "SELECT c.*, i.name as institution_name FROM cases c LEFT JOIN institutions i ON c.institution_id = i.id WHERE 1=1"
    params: list = []

    if org_id and not user.get("is_superuser"):
        sql += " AND c.org_id = ?"
        params.append(org_id)

    if tab == "pending":
        sql += " AND c.status = ?"
        params.append("pending")
    elif tab == "vetted":
        sql += " AND c.status = ?"
        params.append("vetted")
    elif tab == "rejected":
        sql += " AND c.status = ?"
        params.append("rejected")

    if institution and institution.strip():
        sql += " AND c.institution_id = ?"
        params.append(int(institution))

    if radiologist and radiologist.strip():
        sql += " AND c.radiologist = ?"
        params.append(radiologist.strip())

    if q and q.strip():
        sql += " AND (c.patient_first_name LIKE ? OR c.patient_surname LIKE ? OR c.patient_referral_id LIKE ?)"
        like = f"%{q.strip()}%"
        params.extend([like, like, like])

    # Add sorting
    if sort_by == "tat":
        sql += " ORDER BY (JULIANDAY(c.vetted_at) - JULIANDAY(c.created_at)) " + sort_dir
    else:
        sort_col = f"c.{sort_by}" if sort_by != "institution_name" else "i.name"
        sql += f" ORDER BY {sort_col} {sort_dir.upper()}"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    case_ids = [r["id"] for r in rows]
    events_map: dict[str, list[dict]] = {}
    if case_ids and table_exists("case_events"):
        placeholders = ",".join(["?"] * len(case_ids))
        conn = get_db()
        ev_rows = conn.execute(
            f"SELECT * FROM case_events WHERE case_id IN ({placeholders}) ORDER BY created_at",
            case_ids,
        ).fetchall()
        conn.close()
        for e in ev_rows:
            d = dict(e)
            events_map.setdefault(d["case_id"], []).append(d)

    org_names: dict[int, str] = {}
    if table_exists("organisations"):
        conn = get_db()
        org_rows = conn.execute("SELECT id, name FROM organisations").fetchall()
        conn.close()
        org_names = {r["id"]: r["name"] for r in org_rows}

    # Dashboard counts
    conn = get_db()
    if org_id and not user.get("is_superuser"):
        counts_rows = conn.execute(
            "SELECT LOWER(status) AS status, COUNT(*) AS c FROM cases WHERE org_id = ? GROUP BY LOWER(status)",
            (org_id,),
        ).fetchall()
    else:
        counts_rows = conn.execute(
            "SELECT LOWER(status) AS status, COUNT(*) AS c FROM cases GROUP BY LOWER(status)"
        ).fetchall()
    conn.close()

    counts = {r["status"]: r["c"] for r in counts_rows}
    pending_count = counts.get("pending", 0)
    vetted_count = counts.get("vetted", 0)
    rejected_count = counts.get("rejected", 0)
    total_count = pending_count + vetted_count + rejected_count

    institutions = list_institutions(org_id)
    radiologists = [r["name"] for r in list_radiologists(org_id)]

    cases: list[dict] = []
    for r in rows:
        d = dict(r)

        # Format created date
        created_dt = parse_iso_dt(d.get("created_at"))
        d["created_display"] = format_display_datetime(d.get("created_at"), "")

        # Calculate TAT
        secs = tat_seconds(d.get("created_at"), d.get("vetted_at"))
        d["tat_display"] = format_tat(secs)
        d["tat_seconds"] = secs

        # Get SLA from institution
        inst = get_institution(d.get("institution_id")) if d.get("institution_id") else None
        sla_hours = inst["sla_hours"] if inst else 48
        sla_seconds = sla_hours * 3600
        d["sla_breached"] = (d.get("status") == "pending") and (secs > sla_seconds)

        cases.append(d)

    # Get org name if user has org_id
    org_name = "Admin Dashboard"
    if org_id:
        conn = get_db()
        org_row = conn.execute("SELECT name FROM organisations WHERE id = ?", (org_id,)).fetchone()
        if org_row:
            org_name = f"Admin Dashboard - {org_row['name']}"
        conn.close()

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "tab": tab,
            "cases": cases,
            "institutions": institutions,
            "selected_institution": institution or "",
            "radiologists": radiologists,
            "selected_radiologist": radiologist or "",
            "q": q or "",
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "pending_count": pending_count,
            "vetted_count": vetted_count,
            "rejected_count": rejected_count,
            "total_count": total_count,
            "org_name": org_name,
            "current_user": get_session_user(request),
        },
    )


@app.get("/admin.csv")
def admin_dashboard_csv(
    request: Request,
    tab: str = "all",
    institution: str | None = None,
    radiologist: str | None = None,
    q: str | None = None,
):
    user = require_admin(request)

    tab = (tab or "all").strip().lower()
    if tab not in ("all", "pending", "vetted", "rejected"):
        tab = "all"

    sql = "SELECT c.*, i.name as institution_name FROM cases c LEFT JOIN institutions i ON c.institution_id = i.id WHERE 1=1"
    params: list = []

    org_id = user.get("org_id")
    if org_id and not user.get("is_superuser"):
        sql += " AND c.org_id = ?"
        params.append(org_id)

    if tab == "pending":
        sql += " AND c.status = ?"
        params.append("pending")
    elif tab == "vetted":
        sql += " AND c.status = ?"
        params.append("vetted")
    elif tab == "rejected":
        sql += " AND c.status = ?"
        params.append("rejected")

    if institution and institution.strip():
        sql += " AND c.institution_id = ?"
        params.append(int(institution))

    if radiologist and radiologist.strip():
        sql += " AND c.radiologist = ?"
        params.append(radiologist.strip())

    if q and q.strip():
        sql += " AND (c.patient_first_name LIKE ? OR c.patient_surname LIKE ? OR c.patient_referral_id LIKE ?)"
        like = f"%{q.strip()}%"
        params.extend([like, like, like])

    sql += " ORDER BY c.created_at DESC"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    case_ids = [r["id"] for r in rows]
    events_map: dict[str, list[dict]] = {}
    if case_ids and table_exists("case_events"):
        placeholders = ",".join(["?"] * len(case_ids))
        conn = get_db()
        ev_rows = conn.execute(
            f"SELECT * FROM case_events WHERE case_id IN ({placeholders}) ORDER BY created_at",
            case_ids,
        ).fetchall()
        conn.close()
        for e in ev_rows:
            d = dict(e)
            events_map.setdefault(d["case_id"], []).append(d)

    org_names: dict[int, str] = {}
    if table_exists("organisations"):
        conn = get_db()
        org_rows = conn.execute("SELECT id, name FROM organisations").fetchall()
        conn.close()
        org_names = {r["id"]: r["name"] for r in org_rows}

    def iter_csv():
        buf = io.StringIO()
        w = csv.writer(buf)

        w.writerow([
            "Case ID",
            "Org ID",
            "Org Name",
            "Submitted At",
            "Reopened",
            "Reopened At",
            "Reopened By",
            "Latest Decision",
            "Latest Decision At",
            "Latest Vetted By",
            "Latest Protocol",
            "Latest Protocol At",
            "Current Status",
            "Radiologist",
            "Patient ID",
            "Patient DOB",
            "Study",
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for r in rows:
            d = dict(r)
            events = events_map.get(d.get("id"), [])

            submitted_at = ""
            reopened = "N"
            reopened_at = ""
            reopened_by = ""
            latest_decision = ""
            latest_decision_at = ""
            latest_vetted_by = ""
            latest_protocol = ""
            latest_protocol_at = ""

            if events:
                submitted = next((e for e in events if e.get("event_type") == "SUBMITTED"), None)
                if submitted:
                    submitted_at = submitted.get("created_at") or ""

                reopened_events = [e for e in events if e.get("event_type") == "REOPENED"]
                if reopened_events:
                    reopened = "Y"
                    last_reopen = reopened_events[-1]
                    reopened_at = last_reopen.get("created_at") or ""
                    reopened_by = last_reopen.get("username") or ""

                vetted_events = [e for e in events if e.get("event_type") == "VETTED"]
                if vetted_events:
                    last_vet = vetted_events[-1]
                    latest_decision = last_vet.get("decision") or ""
                    latest_decision_at = last_vet.get("created_at") or ""
                    latest_vetted_by = last_vet.get("username") or ""
                    latest_protocol = last_vet.get("protocol") or ""
                    latest_protocol_at = last_vet.get("created_at") or ""

            w.writerow([
                d.get("id", ""),
                d.get("org_id", ""),
                org_names.get(d.get("org_id"), ""),
                format_csv_timestamp(submitted_at),
                reopened,
                format_csv_timestamp(reopened_at),
                reopened_by,
                latest_decision,
                format_csv_timestamp(latest_decision_at),
                latest_vetted_by,
                latest_protocol,
                format_csv_timestamp(latest_protocol_at),
                d.get("status", ""),
                d.get("radiologist", ""),
                d.get("patient_referral_id", ""),
                d.get("patient_dob", "") or "",
                d.get("study_description", ""),
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = f"cases_{tab}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(iter_csv(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/admin.events.csv")
def admin_events_csv(request: Request):
    user = require_admin(request)
    org_id = user.get("org_id")

    if not table_exists("case_events"):
        raise HTTPException(status_code=404, detail="case_events table not found")

    conn = get_db()
    if org_id and not user.get("is_superuser"):
        rows = conn.execute(
            "SELECT * FROM case_events WHERE org_id = ? ORDER BY created_at",
            (org_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM case_events ORDER BY created_at").fetchall()
    conn.close()

    def iter_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "Case ID",
            "Org ID",
            "Event",
            "Created At",
            "User ID",
            "Username",
            "Org Role",
            "Decision",
            "Protocol",
            "Comment",
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for r in rows:
            d = dict(r)
            w.writerow([
                d.get("case_id", ""),
                d.get("org_id", ""),
                d.get("event_type", ""),
                format_csv_timestamp(d.get("created_at", "")),
                d.get("user_id", ""),
                d.get("username", ""),
                d.get("org_role", ""),
                d.get("decision", ""),
                d.get("protocol", ""),
                d.get("comment", ""),
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = f"case_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(iter_csv(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/admin/notify-radiologist", response_class=HTMLResponse)
def notify_radiologist_page(request: Request, name: str = "", sent: str = "", error: str = ""):
    try:
        user = require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/admin/notify-radiologist")

    _uid, _su, org_id, _role = get_current_org_context(request)
    rads = list_radiologists(org_id)

    # Build pending count per radiologist
    conn = get_db()
    pending_counts: dict[str, int] = {}
    rad_emails: dict[str, str] = {}
    for r in rads:
        rname = r["name"]
        if org_id:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM cases WHERE radiologist = ? AND status IN ('pending','reopened') AND org_id = ?",
                (rname, org_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM cases WHERE radiologist = ? AND status IN ('pending','reopened')",
                (rname,),
            ).fetchone()
        pending_counts[rname] = row["c"] if row else 0
        rad_emails[rname] = r.get("email") or ""

    notify_history: list[dict[str, str]] = []
    since_dt = datetime.now(timezone.utc) - timedelta(days=7)
    since_iso = since_dt.isoformat()
    try:
        if org_id:
            rows = conn.execute(
                """
                SELECT radiologist_name, channel, recipient, message, created_at, created_by
                FROM notify_events
                WHERE org_id = ? AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (org_id, since_iso),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT radiologist_name, channel, recipient, message, created_at, created_by
                FROM notify_events
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (since_iso,),
            ).fetchall()
        for row in rows or []:
            data = row if isinstance(row, dict) else dict(row)
            created_at = data.get("created_at", "")
            dt = parse_iso_dt(created_at)
            created_display = format_display_datetime(created_at, created_at)
            notify_history.append(
                {
                    "radiologist_name": data.get("radiologist_name", ""),
                    "channel": data.get("channel", ""),
                    "recipient": data.get("recipient", ""),
                    "message": data.get("message", ""),
                    "created_at": created_at,
                    "created_display": created_display,
                    "created_by": data.get("created_by", ""),
                }
            )
    except Exception as exc:
        print(f"[NOTIFY] History load failed: {exc}")

    conn.close()

    return templates.TemplateResponse(
        "notify_radiologist.html",
        {
            "request": request,
            "radiologists": rads,
            "pending_counts": pending_counts,
            "rad_emails": rad_emails,
            "selected_name": name,
            "sent": sent,
            "error": error,
            "smtp_configured": bool(SMTP_HOST),
            "current_user": get_session_user(request),
            "notify_history": notify_history,
        },
    )


@app.post("/admin/notify-radiologist")
def notify_radiologist_send(
    request: Request,
    radiologist_name: str = Form(...),
    channel: str = Form(...),
    recipient: str = Form(""),
    message: str = Form(...),
):
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/admin/notify-radiologist")

    if channel == "email":
        if not recipient or "@" not in recipient:
            return RedirectResponse(
                url=f"/admin/notify-radiologist?name={radiologist_name}&error=no_email", status_code=303
            )
        if not SMTP_HOST:
            return RedirectResponse(
                url=f"/admin/notify-radiologist?name={radiologist_name}&error=smtp_not_configured", status_code=303
            )
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Cases Awaiting Your Review — Vetting Suite"
        msg["From"] = SMTP_FROM or SMTP_USER
        msg["To"] = recipient.strip()

        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:500px;padding:24px;background:#f9f9f9;border-radius:8px;">
          <h2 style="color:#1a1a2e;margin-top:0;">Cases Awaiting Your Review</h2>
          <p style="color:#333;white-space:pre-wrap;">{message}</p>
          <p style="font-size:12px;color:#888;margin-top:24px;">Sent via Vetting Suite &middot; Healthcare Applications</p>
        </div>
        """
        msg.attach(MIMEText(message, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls()
                if SMTP_USER:
                    smtp.login(SMTP_USER, SMTP_PASS)
                smtp.sendmail(msg["From"], [recipient.strip()], msg.as_string())
        except Exception as exc:
            print(f"[NOTIFY] Email send failed: {exc}")
            return RedirectResponse(
                url=f"/admin/notify-radiologist?name={radiologist_name}&error=send_failed", status_code=303
            )

        try:
            _uid, _su, org_id, _role = get_current_org_context(request)
            user = get_session_user(request) or {}
            conn = get_db()
            conn.execute(
                """
                INSERT INTO notify_events (org_id, radiologist_name, channel, recipient, message, created_at, created_by, created_by_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    org_id,
                    radiologist_name,
                    channel,
                    recipient.strip(),
                    message,
                    utc_now_iso(),
                    user.get("username"),
                    user.get("id"),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"[NOTIFY] History save failed: {exc}")
        return RedirectResponse(
            url=f"/admin/notify-radiologist?name={radiologist_name}&sent=1", status_code=303
        )

    elif channel == "sms":
        # SMS requires Twilio — not yet configured
        return RedirectResponse(
            url=f"/admin/notify-radiologist?name={radiologist_name}&error=sms_not_configured", status_code=303
        )

    return RedirectResponse(url="/admin/notify-radiologist", status_code=303)


@app.get("/admin/case/{case_id}", response_class=HTMLResponse)
def admin_case_view(request: Request, case_id: str):
    try:
        user = require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/admin/case/{case_id}")

    conn = get_db()
    org_id = user.get("org_id")
    org_name = None
    if org_id and not user.get("is_superuser"):
        row = conn.execute("SELECT * FROM cases WHERE id = ? AND org_id = ?", (case_id, org_id)).fetchone()
    else:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    case_dict = None
    if row is not None:
        case_dict = row if isinstance(row, dict) else dict(row)

    if case_dict:
        case_dict = normalize_case_attachment(case_dict)

    if case_dict and case_dict.get("org_id"):
        org_row = conn.execute("SELECT name FROM organisations WHERE id = ?", (case_dict.get("org_id"),)).fetchone()
        if org_row:
            org_name = org_row.get("name") if isinstance(org_row, dict) else org_row[0]

    events = []
    if case_dict and table_exists("case_events"):
        event_rows = conn.execute(
            "SELECT * FROM case_events WHERE case_id = ? ORDER BY created_at ASC",
            (case_id,),
        ).fetchall()
        events = [dict(e) for e in event_rows]

    conn.close()
    if not case_dict:
        raise HTTPException(status_code=404, detail="Case not found")
    # Summary counts for dashboard cards
    conn = get_db()
    if org_id and not user.get("is_superuser"):
        counts_rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM cases WHERE org_id = ? GROUP BY status",
            (org_id,),
        ).fetchall()
    else:
        counts_rows = conn.execute("SELECT status, COUNT(*) AS c FROM cases GROUP BY status").fetchall()
    conn.close()

    counts = {r["status"]: r["c"] for r in counts_rows}
    pending_count = counts.get("pending", counts.get("PENDING", 0))
    vetted_count = counts.get("vetted", counts.get("VETTED", 0))
    total_count = pending_count + vetted_count

    return templates.TemplateResponse(
        "admin_case.html",
        {"request": request, "case": case_dict, "org_name": org_name, "events": events},
    )


@app.get("/admin/case/{case_id}/timeline.pdf")
def admin_case_timeline_pdf(request: Request, case_id: str):
    try:
        user = require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/admin/case/{case_id}")

    conn = get_db()
    org_id = user.get("org_id")
    if org_id and not user.get("is_superuser"):
        row = conn.execute("SELECT * FROM cases WHERE id = ? AND org_id = ?", (case_id, org_id)).fetchone()
    else:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Case not found")

    case_dict = row if isinstance(row, dict) else dict(row)
    org_name = ""
    if case_dict.get("org_id"):
        org_row = conn.execute("SELECT name FROM organisations WHERE id = ?", (case_dict.get("org_id"),)).fetchone()
        if org_row:
            org_name = org_row.get("name") if isinstance(org_row, dict) else org_row[0]

    events: list[dict] = []
    if table_exists("case_events"):
        event_rows = conn.execute(
            "SELECT * FROM case_events WHERE case_id = ? ORDER BY created_at ASC",
            (case_id,),
        ).fetchall()
        events = [dict(e) for e in event_rows]
    conn.close()

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "Case Timeline Audit Report")
    y -= 22

    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Case ID: {case_id}")
    y -= 14
    if org_name:
        c.drawString(40, y, f"Organisation: {org_name}")
        y -= 14
    c.drawString(40, y, f"Generated (UTC): {format_display_datetime(utc_now_iso())}")
    y -= 20

    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Timestamp (UTC)")
    c.drawString(155, y, "Event")
    c.drawString(235, y, "User")
    c.drawString(315, y, "Details")
    y -= 10
    c.line(40, y, width - 40, y)
    y -= 14

    def wrap_text(text_value: str, max_width: int) -> list[str]:
        words = (text_value or "").split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if c.stringWidth(candidate, "Helvetica", 9) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    if not events:
        c.setFont("Helvetica", 10)
        c.drawString(40, y, "No timeline events recorded for this case.")
    else:
        for event in events:
            ts = format_display_datetime(event.get("created_at"), event.get("created_at") or "")
            event_type = str(event.get("event_type") or "-")
            username = str(event.get("username") or "-")
            details = str(event.get("comment") or "")
            detail_lines = wrap_text(details, 250)

            required_height = max(14, 12 * len(detail_lines)) + 6
            if y - required_height < 40:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica-Bold", 10)
                c.drawString(40, y, "Timestamp (UTC)")
                c.drawString(155, y, "Event")
                c.drawString(235, y, "User")
                c.drawString(315, y, "Details")
                y -= 10
                c.line(40, y, width - 40, y)
                y -= 14

            c.setFont("Helvetica", 9)
            c.drawString(40, y, ts)
            c.drawString(155, y, event_type)
            c.drawString(235, y, username)
            line_y = y
            for line in detail_lines:
                c.drawString(315, line_y, line)
                line_y -= 12
            y = line_y - 6

    c.save()
    buffer.seek(0)
    filename = f"{case_id}_timeline_audit.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@app.get("/admin/case/{case_id}/timeline.csv")
def admin_case_timeline_csv(request: Request, case_id: str):
    try:
        user = require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/admin/case/{case_id}")

    conn = get_db()
    org_id = user.get("org_id")
    if org_id and not user.get("is_superuser"):
        row = conn.execute("SELECT * FROM cases WHERE id = ? AND org_id = ?", (case_id, org_id)).fetchone()
    else:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Case not found")

    case_dict = row if isinstance(row, dict) else dict(row)
    org_name = ""
    if case_dict.get("org_id"):
        org_row = conn.execute("SELECT name FROM organisations WHERE id = ?", (case_dict.get("org_id"),)).fetchone()
        if org_row:
            org_name = org_row.get("name") if isinstance(org_row, dict) else org_row[0]

    events: list[dict] = []
    if table_exists("case_events"):
        event_rows = conn.execute(
            "SELECT * FROM case_events WHERE case_id = ? ORDER BY created_at ASC",
            (case_id,),
        ).fetchall()
        events = [dict(e) for e in event_rows]
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header with case info
    writer.writerow(["Case Timeline Audit Report"])
    writer.writerow([f"Case ID: {case_id}"])
    if org_name:
        writer.writerow([f"Organisation: {org_name}"])
    writer.writerow([f"Generated (UTC): {format_display_datetime(utc_now_iso())}"])
    writer.writerow([])  # Empty row
    
    # Write column headers
    writer.writerow(["Timestamp (UTC)", "Event Type", "User", "Details"])
    
    # Write events
    if not events:
        writer.writerow(["No timeline events recorded for this case."])
    else:
        for event in events:
            ts = format_display_datetime(event.get("created_at"), event.get("created_at") or "")
            event_type = str(event.get("event_type") or "-")
            username = str(event.get("username") or "-")
            details = str(event.get("comment") or "")
            writer.writerow([ts, event_type, username, details])
    
    output.seek(0)
    filename = f"{case_id}_timeline_audit.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# -------------------------
# Case edit
# -------------------------
@app.get("/admin/case/{case_id}/edit", response_class=HTMLResponse)
def admin_case_edit_view(request: Request, case_id: str):
    try:
        user = require_admin(request)
    except HTTPException as e:
        return redirect_to_login("admin", f"/admin/case/{case_id}/edit")

    conn = get_db()
    org_id = user.get("org_id")
    if org_id and not user.get("is_superuser"):
        case = conn.execute("SELECT * FROM cases WHERE id = ? AND org_id = ?", (case_id, org_id)).fetchone()
    else:
        case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    institutions = list_institutions(org_id)
    radiologists = list_radiologists(org_id)
    protocols = conn.execute("SELECT DISTINCT protocol FROM cases WHERE protocol IS NOT NULL AND protocol != '' ORDER BY protocol").fetchall()
    conn.close()
    
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Bug 9: Check if case is approved and prevent editing
    case_dict = dict(case)
    if case_dict.get("status") == "vetted" and case_dict.get("decision") == "Approve":
        raise HTTPException(status_code=403, detail="Cannot edit approved cases")
    
    return templates.TemplateResponse(
        "case_edit.html",
        {
            "request": request,
            "case": case_dict,
            "institutions": institutions,
            "radiologists": radiologists,
            "protocols": [p["protocol"] for p in protocols] if protocols else [],
            "user_org_id": org_id,
        }
    )

@app.post("/admin/case/{case_id}/edit")
async def admin_case_edit_save(
    request: Request,
    case_id: str,
    patient_first_name: str = Form(""),
    patient_surname: str = Form(""),
    patient_referral_id: str = Form(""),
    patient_dob: str = Form(""),
    institution_id: str = Form(""),
    study_description: str = Form(""),
    admin_notes: str = Form(""),
    radiologist: str = Form(""),
    modality: str = Form(""),
    protocol: str = Form(""),
    attachment: UploadFile | None = File(None),
):
    try:
        user = require_admin(request)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Not authorized")

    conn = get_db()
    org_id = user.get("org_id")
    if org_id and not user.get("is_superuser"):
        case = conn.execute("SELECT * FROM cases WHERE id = ? AND org_id = ?", (case_id, org_id)).fetchone()
    else:
        case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        conn.close()
        raise HTTPException(status_code=404, detail="Case not found")

    # Bug 9: Prevent editing approved cases
    case_dict = dict(case)
    if case_dict.get("status") == "vetted" and case_dict.get("decision") == "Approve":
        conn.close()
        raise HTTPException(status_code=403, detail="Cannot edit approved cases")

    cleaned_first_name = patient_first_name.strip()
    cleaned_surname = patient_surname.strip()
    cleaned_referral_id = patient_referral_id.strip()
    cleaned_dob = patient_dob.strip() or None
    cleaned_study_description = study_description.strip()
    cleaned_admin_notes = admin_notes.strip()
    cleaned_protocol = protocol.strip() or None
    cleaned_modality = modality.strip() or None

    institution_raw = institution_id.strip()
    cleaned_institution_id = int(institution_raw) if institution_raw.isdigit() else None

    # Keep existing radiologist if the form submits an empty value.
    # Empty string is allowed by current app flow; avoid writing NULL.
    cleaned_radiologist = radiologist.strip() or (case_dict.get("radiologist") or "")

    replacement_uploaded_filename: str | None = None
    replacement_stored_path: str | None = None
    old_stored_path = case_dict.get("stored_filepath")
    if attachment and attachment.filename:
        replacement_uploaded_filename = attachment.filename
        replacement_bytes = await attachment.read()
        if replacement_bytes:
            if BLOB_STORAGE_ENABLED:
                blob_name = upload_to_blob(case_id, replacement_bytes, replacement_uploaded_filename)
                if blob_name:
                    replacement_stored_path = blob_name

            if not replacement_stored_path:
                safe_name = f"{case_id}_{Path(replacement_uploaded_filename).name}"
                replacement_stored_path = str(UPLOAD_DIR / safe_name)
                with open(replacement_stored_path, "wb") as f:
                    f.write(replacement_bytes)

            if old_stored_path and old_stored_path != replacement_stored_path and str(old_stored_path).startswith(str(UPLOAD_DIR)):
                try:
                    old_path_obj = Path(str(old_stored_path))
                    if old_path_obj.exists():
                        old_path_obj.unlink()
                except Exception:
                    pass

    def _clean(value: str | None) -> str:
        return (value or "").strip()

    update_fields: list[tuple[str, str | int | None]] = []

    def add_field_if_exists(column_name: str, value: str | int | None) -> None:
        if table_has_column("cases", column_name):
            update_fields.append((column_name, value))

    add_field_if_exists("patient_first_name", cleaned_first_name)
    add_field_if_exists("patient_surname", cleaned_surname)
    add_field_if_exists("patient_referral_id", cleaned_referral_id)
    add_field_if_exists("patient_dob", cleaned_dob)
    add_field_if_exists("institution_id", cleaned_institution_id)
    add_field_if_exists("study_description", cleaned_study_description)
    add_field_if_exists("admin_notes", cleaned_admin_notes)
    add_field_if_exists("radiologist", cleaned_radiologist)
    add_field_if_exists("protocol", cleaned_protocol)
    add_field_if_exists("modality", cleaned_modality)
    if replacement_uploaded_filename is not None:
        add_field_if_exists("uploaded_filename", replacement_uploaded_filename)
        add_field_if_exists("stored_filepath", replacement_stored_path)

    if not update_fields:
        conn.close()
        raise HTTPException(status_code=400, detail="No editable fields available for this case")

    changes: list[str] = []
    old_case = dict(case)
    for col, new_val in update_fields:
        if col == "admin_notes":
            continue
        old_val = old_case.get(col)
        old_text = _clean(str(old_val)) if old_val is not None else ""
        new_text = _clean(str(new_val)) if new_val is not None else ""
        if old_text != new_text:
            changes.append(f"{col}: {old_text or '-'} -> {new_text or '-'}")

    update_sql = "UPDATE cases SET " + ", ".join([f"{col} = ?" for col, _ in update_fields]) + " WHERE id = ?"
    update_params = [value for _, value in update_fields] + [case_id]
    try:
        conn.execute(update_sql, update_params)
        conn.commit()
    except Exception as exc:
        conn.close()
        print(f"[ERROR] Failed to save case edits for case {case_id}: {exc}")
        raise HTTPException(status_code=400, detail="Unable to save case changes")
    conn.close()

    if replacement_uploaded_filename is not None:
        changes.append(f"attachment: replaced with {replacement_uploaded_filename}")

    change_summary = "; ".join(changes) if changes else "No field changes"
    note_text = cleaned_admin_notes
    event_comment = change_summary
    if note_text:
        event_comment = f"{change_summary}. Notes: {note_text}"

    event_org_id = org_id or case_dict.get("org_id")
    insert_case_event(
        case_id=case_id,
        org_id=event_org_id,
        event_type="EDITED",
        user=user,
        comment=event_comment,
    )

    return RedirectResponse(url=f"/admin/case/{case_id}", status_code=303)


@app.post("/admin/case/{case_id}/assign-radiologist")
def assign_radiologist(request: Request, case_id: str, radiologist: str = Form("")):
    user = require_admin(request)
    org_id = user.get("org_id")

    radiologist = (radiologist or "").strip()

    conn = get_db()
    if org_id and not user.get("is_superuser"):
        case = conn.execute("SELECT id, radiologist, org_id FROM cases WHERE id = ? AND org_id = ?", (case_id, org_id)).fetchone()
    else:
        case = conn.execute("SELECT id, radiologist, org_id FROM cases WHERE id = ?", (case_id,)).fetchone()

    if not case:
        conn.close()
        raise HTTPException(status_code=404, detail="Case not found")

    valid_rads = {r["name"] for r in list_radiologists(org_id)}
    if radiologist and radiologist not in valid_rads:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid radiologist selection")

    old_rad = case["radiologist"] if isinstance(case, dict) else case[1]
    conn.execute(
        "UPDATE cases SET radiologist = ? WHERE id = ?",
        (radiologist or None, case_id),
    )
    conn.commit()
    conn.close()

    comment = f"{old_rad or 'unassigned'} -> {radiologist or 'unassigned'}"
    insert_case_event(
        case_id=case_id,
        org_id=case["org_id"] if isinstance(case, dict) else case[2],
        event_type="ASSIGNED",
        user=user,
        comment=comment,
    )

    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin/case/{case_id}/reopen", response_class=HTMLResponse)
def admin_reopen_case_form(request: Request, case_id: str):
    try:
        user = require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/admin/case/{case_id}/reopen")

    org_id = user.get("org_id")
    conn = get_db()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    # Org isolation
    if org_id and row["org_id"] != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    case = dict(row)
    
    # Only allow reopening vetted or rejected cases
    if case["status"] not in ["vetted", "rejected"]:
        return RedirectResponse(url=f"/admin/case/{case_id}", status_code=303)

    return templates.TemplateResponse(
        "admin_reopen_case.html",
        {"request": request, "case": case, "user": user}
    )


@app.post("/admin/case/{case_id}/reopen")
def admin_reopen_case_submit(
    request: Request,
    case_id: str,
    reopen_notes: str = Form(...),
):
    try:
        user = require_admin(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)

    org_id = user.get("org_id")
    conn = get_db()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Case not found")

    # Org isolation
    if org_id and row["org_id"] != org_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Access denied")

    # Append reopen notes to admin_notes
    current_notes = row["admin_notes"] or ""
    updated_notes = f"{current_notes}\n\n[REOPENED] {reopen_notes}".strip()
    
    # Change status to 'reopened' and clear previous decision
    conn.execute(
        "UPDATE cases SET status = ?, admin_notes = ?, decision = NULL, decision_comment = NULL, vetted_at = NULL WHERE id = ?",
        ("reopened", updated_notes, case_id)
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/admin/case/{case_id}", status_code=303)


# -------------------------
# Radiologist dashboard
# -------------------------
@app.get("/radiologist", response_class=HTMLResponse)
def radiologist_dashboard(request: Request, tab: str = "all"):
    try:
        user = require_radiologist(request)
    except HTTPException:
        return redirect_to_login("radiologist", "/radiologist")

    org_id = user.get("org_id")
    rad_name = user.get("radiologist_name")
    if not rad_name:
        raise HTTPException(status_code=400, detail="Radiologist account not linked to a radiologist name")

    tab = (tab or "all").strip().lower()
    if tab not in ("all", "pending", "vetted", "rejected", "reopened"):
        tab = "all"

    sql = "SELECT c.*, i.sla_hours FROM cases c LEFT JOIN institutions i ON c.institution_id = i.id WHERE c.radiologist = ?"
    params: list[str] = [rad_name]

    if org_id:
        sql += " AND c.org_id = ?"
        params.append(org_id)

    if tab == "pending":
        sql += " AND c.status IN (?, ?)"
        params.extend(["pending", "reopened"])
    elif tab == "vetted":
        sql += " AND c.status = ?"
        params.append("vetted")
    elif tab == "rejected":
        sql += " AND c.status = ?"
        params.append("rejected")
    elif tab == "reopened":
        sql += " AND c.status = ?"
        params.append("reopened")

    sql += " ORDER BY c.created_at DESC"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    cases: list[dict] = []
    for r in rows:
        d = dict(r)
        created_dt = parse_iso_dt(d.get("created_at"))
        d["created_display"] = format_display_datetime(d.get("created_at"), d.get("created_at") or "")

        secs = tat_seconds(d.get("created_at"), d.get("vetted_at"))
        d["tat_display"] = format_tat(secs)
        
        # Use institution-specific SLA or default to 48 hours
        sla_hours = d.get("sla_hours") or 48
        sla_seconds = sla_hours * 3600
        d["sla_breached"] = (d.get("status") == "pending") and (secs > sla_seconds)

        cases.append(d)

    return templates.TemplateResponse(
        "radiologist_dashboard.html",
        {
            "request": request,
            "cases": cases,
            "tab": tab,
            "current_user": get_session_user(request),
        },
    )


# -------------------------
# Settings (admin)
# -------------------------
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, error: str = ""):
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/settings")

    org_id = get_request_org_id(request)
    
    # Ensure default institution exists for this org
    if org_id:
        institutions = list_institutions(org_id)
        if not institutions:
            # Create default institution with org name
            conn = get_db()
            org_row = conn.execute("SELECT name FROM organisations WHERE id = ?", (org_id,)).fetchone()
            if org_row:
                org_name = org_row["name"]
                now = utc_now_iso()
                if table_has_column("institutions", "org_id"):
                    conn.execute(
                        """
                        INSERT INTO institutions (name, sla_hours, org_id, created_at, modified_at)
                        VALUES (?, 48, ?, ?, ?)
                        """,
                        (org_name, org_id, now, now)
                    )
                    conn.commit()
            conn.close()
            # Refresh institutions list
            institutions = list_institutions(org_id)
    else:
        institutions = list_institutions(org_id)
    
    rads = list_radiologists(org_id)
    users = list_users(org_id)
    rad_names = [r["name"] for r in rads]
    protocols = list_protocol_rows(org_id)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "institutions": institutions,
            "radiologists": rads,
            "users": users,
            "rad_names": rad_names,
            "protocols": protocols,
            "current_user": get_session_user(request),
            "error": error,
        },
    )


@app.post("/settings/institution/add")
def add_institution(request: Request, name: str = Form(...), sla_hours: str = Form(...)):
    user = require_admin(request)
    org_id = user.get("org_id")
    try:
        sla_val = int(sla_hours)
        if sla_val <= 0 or sla_val > 999:
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=400, detail="SLA must be a number of hours (1-999)")
    
    upsert_institution(name.strip(), sla_val, org_id)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/institution/edit/{inst_id}")
def edit_institution(request: Request, inst_id: int, name: str = Form(...), sla_hours: str = Form(...)):
    user = require_admin(request)
    org_id = user.get("org_id")
    try:
        sla_val = int(sla_hours)
        if sla_val <= 0 or sla_val > 999:
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=400, detail="SLA must be a number of hours (1-999)")
    
    # Verify institution exists
    inst = get_institution(inst_id, org_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")
    
    conn = get_db()
    if org_id and table_has_column("institutions", "org_id"):
        conn.execute(
            "UPDATE institutions SET name = ?, sla_hours = ?, modified_at = ? WHERE id = ? AND org_id = ?",
            (name.strip(), sla_val, utc_now_iso(), inst_id, org_id),
        )
    else:
        conn.execute("UPDATE institutions SET name = ?, sla_hours = ?, modified_at = ? WHERE id = ?", (name.strip(), sla_val, utc_now_iso(), inst_id))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/institution/delete/{inst_id}")
def delete_institution_route(request: Request, inst_id: int):
    user = require_admin(request)
    org_id = user.get("org_id")
    inst = get_institution(inst_id, org_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")
    
    delete_institution(inst_id, org_id)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/radiologist/add")
def add_radiologist(request: Request, name: str = Form(...), email: str = Form(""), surname: str = Form(""), gmc: str = Form(""), speciality: str = Form("")):
    require_admin(request)
    conn = get_db()
    # Use upsert to allow both creation and update
    conn.execute(
        "INSERT INTO radiologists (name, email, surname, gmc, speciality) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET email=excluded.email, surname=excluded.surname, gmc=excluded.gmc, speciality=excluded.speciality",
        (name.strip(), email.strip(), surname.strip(), gmc.strip(), speciality.strip())
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/radiologist/delete")
def remove_radiologist(request: Request, name: str = Form(...)):
    require_admin(request)
    delete_radiologist(name)
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/settings/radiologist/edit/{name}", response_class=HTMLResponse)
def edit_radiologist_page(request: Request, name: str):
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/settings")

    rad = get_radiologist(name)
    if not rad:
        raise HTTPException(status_code=404, detail="Radiologist not found")

    return templates.TemplateResponse("radiologist_edit.html", {"request": request, "rad": rad})


@app.post("/settings/radiologist/update")
def update_radiologist(request: Request, name: str = Form(...), email: str = Form(""), surname: str = Form(""), gmc: str = Form(""), speciality: str = Form("")):
    require_admin(request)
    conn = get_db()
    conn.execute(
        "UPDATE radiologists SET email = ?, surname = ?, gmc = ?, speciality = ? WHERE name = ?",
        (email.strip(), surname.strip(), gmc.strip(), speciality.strip(), name.strip())
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/protocol/add")
def settings_add_protocol(request: Request, name: str = Form(...), institution_id: str = Form(...), instructions: str = Form("")):
    user = require_admin(request)
    org_id = user.get("org_id")
    
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Protocol name is required")
    
    if not institution_id or institution_id.strip() == "":
        raise HTTPException(status_code=400, detail="Please select an institution")
    
    try:
        inst_id = int(institution_id)
        inst = get_institution(inst_id, org_id)
        if not inst:
            raise HTTPException(status_code=400, detail="Invalid institution or institution not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid institution ID format")
    
    conn = get_db()
    try:
        if org_id and table_has_column("protocols", "org_id"):
            if using_postgres():
                conn.execute(
                    """
                    INSERT INTO protocols (name, institution_id, instructions, last_modified, is_active, org_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (name, institution_id) DO UPDATE SET
                      instructions = EXCLUDED.instructions,
                      last_modified = EXCLUDED.last_modified,
                      is_active = EXCLUDED.is_active,
                      org_id = EXCLUDED.org_id
                    """,
                    (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), 1, org_id)
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO protocols (name, institution_id, instructions, last_modified, is_active, org_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), 1, org_id)
                )
        else:
            if using_postgres():
                conn.execute(
                    """
                    INSERT INTO protocols (name, institution_id, instructions, last_modified, is_active)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (name, institution_id) DO UPDATE SET
                      instructions = EXCLUDED.instructions,
                      last_modified = EXCLUDED.last_modified,
                      is_active = EXCLUDED.is_active
                    """,
                    (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), 1)
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO protocols (name, institution_id, instructions, last_modified, is_active) VALUES (?, ?, ?, ?, ?)",
                    (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), 1)
                )
        conn.commit()
    except Exception as e:
        if hasattr(conn, "rollback"):
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to add protocol: {str(e)}")
    finally:
        conn.close()
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/protocol/delete")
def settings_delete_protocol(request: Request, name: str = Form(...)):
    user = require_admin(request)
    org_id = user.get("org_id")
    deactivate_protocol(name, org_id)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/user/add")
def add_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    radiologist_name: str = Form(""),
    first_name: str = Form(""),
    surname: str = Form(""),
    email: str = Form(""),
    gmc: str = Form(""),
    speciality: str = Form(""),
):
    user = require_admin(request)
    # get_current_org_context is already called inside require_admin; fetch org_id from it
    # to ensure we always have it even if the session dict wasn't updated yet.
    _uid, _su, org_id, _role = get_current_org_context(request)
    if not org_id:
        org_id = user.get("org_id")
    username = username.strip()
    role = role.strip()
    radiologist_name = radiologist_name.strip() or None
    gmc = gmc.strip()
    speciality = speciality.strip()

    # For radiologist users, create profile with their name
    if role == "radiologist":
        if not first_name.strip():
            raise HTTPException(status_code=400, detail="Radiologist must have a first name")
        radiologist_name = f"{first_name.strip()} {surname.strip()}".strip() or first_name.strip()
    
    # For admin users, radiologist_name should be None
    if role == "admin" or role == "user":
        radiologist_name = None

    # Multi-tenant schema: create user + membership
    if table_has_column("users", "is_superuser") and org_id:
        salt = secrets.token_bytes(16)
        pw_hash = hash_password(password, salt)
        now = utc_now_iso()

        conn = get_db()
        try:
            email_val = email.strip() or None  # store NULL not '' to avoid UNIQUE constraint clashes
            if using_postgres():
                user_row = conn.execute(
                    """
                    INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at, first_name, surname)
                    VALUES(?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (username, email_val, pw_hash.hex(), salt.hex(), now, now, first_name.strip(), surname.strip()),
                ).fetchone()
                user_id = user_row["id"] if isinstance(user_row, dict) else user_row[0]
            else:
                try:
                    conn.execute(
                        """
                        INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at, first_name, surname)
                        VALUES(?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                        """,
                        (username, email_val, pw_hash.hex(), salt.hex(), now, now, first_name.strip(), surname.strip()),
                    )
                except Exception as _insert_err:
                    _msg = str(_insert_err).lower()
                    if "unique" in _msg and "username" in _msg:
                        return RedirectResponse(url="/settings?error=username_taken", status_code=303)
                    if "unique" in _msg and "email" in _msg:
                        return RedirectResponse(url="/settings?error=email_taken", status_code=303)
                    raise

                user_row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
                user_id = user_row["id"] if user_row else None
            if not user_id:
                raise HTTPException(status_code=500, detail="Failed to create user")

            org_role = "org_admin" if role == "admin" else "radiologist" if role == "radiologist" else "org_user"
            conn.execute(
                """
                INSERT INTO memberships (org_id, user_id, org_role, is_active, created_at, modified_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (org_id, user_id, org_role, now, now),
            )

            if role == "radiologist":
                display = radiologist_name or f"{first_name.strip()} {surname.strip()}".strip() or username
                if using_postgres():
                    conn.execute(
                        """
                        INSERT INTO radiologists(name, first_name, email, surname, gmc, speciality)
                        VALUES(?, ?, ?, ?, ?, ?)
                        ON CONFLICT DO NOTHING
                        """,
                        (display, first_name.strip(), email.strip(), surname.strip(), gmc, speciality),
                    )
                    conn.execute(
                        """
                        INSERT INTO radiologist_profiles(user_id, gmc, specialty, display_name, created_at, modified_at)
                        VALUES(?, ?, ?, ?, ?, ?)
                        ON CONFLICT (user_id) DO NOTHING
                        """,
                        (user_id, gmc or None, speciality or None, display, now, now),
                    )
                else:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO radiologists(name, first_name, email, surname, gmc, speciality)
                        VALUES(?, ?, ?, ?, ?, ?)
                        """,
                        (display, first_name.strip(), email.strip(), surname.strip(), gmc, speciality),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO radiologist_profiles(user_id, gmc, specialty, display_name, created_at, modified_at)
                        VALUES(?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, gmc or None, speciality or None, display, now, now),
                    )

            conn.commit()
        finally:
            conn.close()
    elif table_has_column("users", "is_superuser"):
        # New schema but no org_id context — create user only (no membership row)
        salt = secrets.token_bytes(16)
        pw_hash = hash_password(password, salt)
        now = utc_now_iso()
        conn = get_db()
        email_val = email.strip() or None
        try:
            conn.execute(
                """
                INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at, first_name, surname)
                VALUES(?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                """,
                (username, email_val, pw_hash.hex(), salt.hex(), now, now, first_name.strip(), surname.strip()),
            )
            conn.commit()
        finally:
            conn.close()
    else:
        create_user(username, password, role, radiologist_name, first_name, surname, email)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/user/delete")
def remove_user(request: Request, username: str = Form(...)):
    require_admin(request)
    if username.strip() == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete admin user")
    delete_user(username.strip())
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/user/edit")
def edit_user(
    request: Request,
    username: str = Form(...),
    first_name: str = Form(""),
    surname: str = Form(""),
    email: str = Form(""),
    role: str = Form(...),
    radiologist_name: str = Form(""),
    password: str = Form(""),
):
    user = require_admin(request)
    org_id = user.get("org_id")
    username = username.strip()
    role = role.strip()
    radiologist_name = radiologist_name.strip() or None
    
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Resolve current email to avoid false UniqueViolation when email is unchanged
    current_email = (user["email"] if isinstance(user, dict) else dict(user).get("email", "")) or ""
    new_email = email.strip()
    email_changed = new_email and new_email != current_email

    if email_changed:
        # Check if new email is already taken by another user
        conn2 = get_db()
        conflict = conn2.execute(
            "SELECT id FROM users WHERE email = ? AND username != ?",
            (new_email, username),
        ).fetchone()
        conn2.close()
        if conflict:
            return RedirectResponse(url="/settings?error=email_taken", status_code=303)
    
    if table_has_column("users", "is_superuser"):
        # Multi-tenant schema
        conn = get_db()
        if password.strip():
            salt = secrets.token_bytes(16)
            pw_hash = hash_password(password, salt)
            if email_changed:
                conn.execute(
                    "UPDATE users SET first_name = ?, surname = ?, email = ?, password_hash = ?, salt_hex = ? WHERE username = ?",
                    (first_name.strip(), surname.strip(), new_email, pw_hash.hex(), salt.hex(), username)
                )
            else:
                conn.execute(
                    "UPDATE users SET first_name = ?, surname = ?, password_hash = ?, salt_hex = ? WHERE username = ?",
                    (first_name.strip(), surname.strip(), pw_hash.hex(), salt.hex(), username)
                )
        else:
            if email_changed:
                conn.execute(
                    "UPDATE users SET first_name = ?, surname = ?, email = ? WHERE username = ?",
                    (first_name.strip(), surname.strip(), new_email, username)
                )
            else:
                conn.execute(
                    "UPDATE users SET first_name = ?, surname = ? WHERE username = ?",
                    (first_name.strip(), surname.strip(), username)
                )

        if org_id and table_exists("memberships"):
            org_role = "org_admin" if role == "admin" else "radiologist" if role == "radiologist" else "org_user"
            target = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            target_id = target["id"] if target else None
            if target_id:
                conn.execute(
                    "UPDATE memberships SET org_role = ?, modified_at = ? WHERE user_id = ? AND org_id = ? AND is_active = 1",
                    (org_role, utc_now_iso(), target_id, org_id),
                )
    else:
        # Legacy schema
        if password.strip():
            salt = secrets.token_bytes(16)
            pw_hash = hash_password(password, salt)
            conn = get_db()
            if email_changed:
                conn.execute(
                    "UPDATE users SET first_name = ?, surname = ?, email = ?, role = ?, radiologist_name = ?, salt_hex = ?, pw_hash_hex = ? WHERE username = ?",
                    (first_name.strip(), surname.strip(), new_email, role, radiologist_name, salt.hex(), pw_hash.hex(), username)
                )
            else:
                conn.execute(
                    "UPDATE users SET first_name = ?, surname = ?, role = ?, radiologist_name = ?, salt_hex = ?, pw_hash_hex = ? WHERE username = ?",
                    (first_name.strip(), surname.strip(), role, radiologist_name, salt.hex(), pw_hash.hex(), username)
                )
        else:
            conn = get_db()
            if email_changed:
                conn.execute(
                    "UPDATE users SET first_name = ?, surname = ?, email = ?, role = ?, radiologist_name = ? WHERE username = ?",
                    (first_name.strip(), surname.strip(), new_email, role, radiologist_name, username)
                )
            else:
                conn.execute(
                    "UPDATE users SET first_name = ?, surname = ?, role = ?, radiologist_name = ? WHERE username = ?",
                    (first_name.strip(), surname.strip(), role, radiologist_name, username)
                )
    
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/user/access")
def update_user_access(
    request: Request,
    org_role: str = Form(...),
    user_id: int | None = Form(None),
    username: str = Form(""),
):
    user = require_admin(request)
    org_id = user.get("org_id")

    allowed_roles = {"org_admin", "radiologist", "org_user"}
    if org_role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Invalid access level")

    conn = get_db()
    try:
        if table_exists("memberships") and org_id:
            if not user_id and username:
                row = conn.execute("SELECT id FROM users WHERE username = ?", (username.strip(),)).fetchone()
                user_id = row["id"] if row else None

            if not user_id:
                raise HTTPException(status_code=400, detail="User not found")

            conn.execute(
                "UPDATE memberships SET org_role = ?, modified_at = ? WHERE user_id = ? AND org_id = ? AND is_active = 1",
                (org_role, utc_now_iso(), user_id, org_id),
            )
        else:
            # Legacy fallback
            role = "admin" if org_role == "org_admin" else "radiologist" if org_role == "radiologist" else "user"
            conn.execute("UPDATE users SET role = ? WHERE username = ?", (role, username.strip()))

        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/protocol/edit/{protocol_id}")
def edit_protocol(
    request: Request,
    protocol_id: int,
    name: str = Form(...),
    institution_id: str = Form(...),
    instructions: str = Form(""),
):
    user = require_admin(request)
    org_id = user.get("org_id")
    try:
        inst_id = int(institution_id)
        inst = get_institution(inst_id, org_id)
        if not inst:
            raise HTTPException(status_code=400, detail="Invalid institution")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid institution ID")
    
    conn = get_db()
    if org_id and table_has_column("protocols", "org_id"):
        conn.execute(
            "UPDATE protocols SET name = ?, institution_id = ?, instructions = ?, last_modified = ? WHERE id = ? AND org_id = ?",
            (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), protocol_id, org_id)
        )
    else:
        conn.execute(
            "UPDATE protocols SET name = ?, institution_id = ?, instructions = ?, last_modified = ? WHERE id = ?",
            (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), protocol_id)
        )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/protocol/delete/{protocol_id}")
def delete_protocol_route(request: Request, protocol_id: int):
    user = require_admin(request)
    org_id = user.get("org_id")
    conn = get_db()
    if org_id and table_has_column("protocols", "org_id"):
        conn.execute("DELETE FROM protocols WHERE id = ? AND org_id = ?", (protocol_id, org_id))
    else:
        conn.execute("DELETE FROM protocols WHERE id = ?", (protocol_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings", status_code=303)

# -------------------------
# Study Description Presets (Multitenant - By Organization)
# -------------------------
@app.get("/api/study-descriptions/by-modality/{modality}")
def get_study_descriptions(modality: str, request: Request, org_id: str = None):
    """Get study description presets by modality for user's organization (searchable via form)"""
    # If org_id is provided as query parameter, use it; otherwise get from session
    if org_id:
        try:
            org_id = int(org_id)
        except (ValueError, TypeError):
            org_id = None
    
    if not org_id:
        # Get user's organization from session
        user = request.session.get("user")
        if not user:
            return []
        
        # Try both org_id and organization_id for backward compatibility
        org_id = user.get("org_id") or user.get("organization_id")
    
    if not org_id:
        return []
    
    conn = get_db()
    modality = modality.upper().strip()
    rows = conn.execute(
        "SELECT id, description FROM study_description_presets WHERE organization_id = ? AND modality = ? ORDER BY description",
        (org_id, modality)
    ).fetchall()
    if not rows and org_id != 1:
        rows = conn.execute(
            "SELECT id, description FROM study_description_presets WHERE organization_id = 1 AND modality = ? ORDER BY description",
            (modality,)
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/settings/study-descriptions", response_class=HTMLResponse)
def study_descriptions_page(request: Request):
    """Superuser page to manage study description presets for their organization"""
    user = require_superuser(request)
    org_id = user.get("org_id") or user.get("organization_id")
    
    conn = get_db()
    presets = conn.execute(
        "SELECT id, modality, description, created_at, updated_at FROM study_description_presets WHERE organization_id = ? ORDER BY modality, description",
        (org_id,)
    ).fetchall()
    conn.close()
    return templates.TemplateResponse("superuser_study_descriptions.html", {
        "request": request,
        "current_user": user,
        "presets": [dict(row) for row in presets],
        "modalities": ["MRI", "CT", "XR", "PET", "DEXA"]
    })

@app.post("/settings/study-descriptions/add")
def add_study_description(request: Request, modality: str = Form(...), description: str = Form(...), org_id: str = Form("")):
    """Add new study description preset for user's organization"""
    user = require_superuser(request)
    target_org_id = user.get("org_id") or user.get("organization_id")
    if org_id:
        try:
            target_org_id = int(org_id)
        except Exception:
            pass
    modality = modality.upper().strip()
    description = description.strip()
    
    if not modality or not description:
        return RedirectResponse(url="/settings/study-descriptions?error=empty", status_code=303)
    
    creator_id = user.get("id") or 1
    try:
        creator_id = int(creator_id)
    except Exception:
        creator_id = 1

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO study_description_presets (organization_id, modality, description, created_at, updated_at, created_by) VALUES (?, ?, ?, ?, ?, ?)",
            (target_org_id, modality, description, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), creator_id)
        )
        conn.commit()
    except (sqlite3.IntegrityError, SQLAlchemyError):
        conn.close()
        return RedirectResponse(url="/settings/study-descriptions?error=duplicate", status_code=303)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    
    return RedirectResponse(url="/settings/study-descriptions", status_code=303)

@app.post("/settings/study-descriptions/delete/{preset_id}")
def delete_study_description(request: Request, preset_id: int):
    """Delete study description preset from user's organization"""
    user = require_superuser(request)
    org_id = user.get("org_id") or user.get("organization_id")
    conn = get_db()
    conn.execute("DELETE FROM study_description_presets WHERE id = ? AND organization_id = ?", (preset_id, org_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings/study-descriptions", status_code=303)

@app.post("/settings/study-descriptions/edit/{preset_id}")
def edit_study_description(request: Request, preset_id: int, modality: str = Form(...), description: str = Form(...)):
    """Edit study description preset for user's organization"""
    user = require_superuser(request)
    org_id = user.get("org_id") or user.get("organization_id")
    modality = modality.upper().strip()
    description = description.strip()
    
    if not modality or not description:
        return RedirectResponse(url="/settings/study-descriptions?error=empty", status_code=303)
    
    try:
        conn = get_db()
        conn.execute(
            "UPDATE study_description_presets SET modality = ?, description = ?, updated_at = ? WHERE id = ? AND organization_id = ?",
            (modality, description, datetime.now(timezone.utc).isoformat(), preset_id, org_id)
        )
        conn.commit()
        conn.close()
    except sqlite3.IntegrityError:
        return RedirectResponse(url="/settings/study-descriptions?error=duplicate", status_code=303)
    
    return RedirectResponse(url="/settings/study-descriptions", status_code=303)

# -------------------------
# Admin submit
# -------------------------
@app.get("/intake/{org_id}", response_class=HTMLResponse)
def intake_form(request: Request, org_id: int, token: str = ""):
    token = (token or "").strip()
    expected = get_setting(f"intake_token:{org_id}", "")
    if not expected or token != expected:
        raise HTTPException(status_code=403, detail="Invalid intake token")

    institutions = list_institutions(org_id)
    return templates.TemplateResponse(
        "intake_submit.html",
        {"request": request, "institutions": institutions},
    )


@app.post("/intake/{org_id}")
async def intake_submit(
    request: Request,
    org_id: int,
    token: str = "",
    patient_first_name: str = Form(...),
    patient_surname: str = Form(...),
    patient_referral_id: str = Form(...),
    patient_dob: str = Form(""),
    institution_id: str = Form(...),
    study_description: str = Form(...),
    admin_notes: str = Form(""),
    attachment: UploadFile | None = File(...),
):
    token = (token or request.query_params.get("token") or "").strip()
    expected = get_setting(f"intake_token:{org_id}", "")
    if not expected or token != expected:
        raise HTTPException(status_code=403, detail="Invalid intake token")

    try:
        inst_id = int(institution_id)
        inst = get_institution(inst_id, org_id)
        if not inst:
            raise HTTPException(status_code=400, detail="Invalid institution selection")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid institution ID")

    if not attachment or not attachment.filename:
        raise HTTPException(status_code=400, detail="Attachment is required")

    case_id = generate_case_id()
    original_name = attachment.filename
    
    file_bytes = await attachment.read()
    
    # Try blob storage first, fallback to local
    stored_path = None
    if BLOB_STORAGE_ENABLED:
        blob_name = upload_to_blob(case_id, file_bytes, original_name)
        if blob_name:
            stored_path = blob_name
    
    # Fallback: store locally if blob upload failed or disabled
    if not stored_path:
        safe_name = f"{case_id}_{Path(original_name).name}"
        stored_path = str(UPLOAD_DIR / safe_name)
        with open(stored_path, "wb") as f:
            f.write(file_bytes)

    created_at = utc_now_iso()
    conn = get_db()
    
    # Build insert conditionally based on columns that exist
    has_dob_col = table_has_column("cases", "patient_dob")
    if has_dob_col:
        conn.execute(
            "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, patient_dob, institution_id, study_description, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, created_at, patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), patient_dob.strip() or None, inst_id, study_description.strip(), admin_notes.strip(), "", original_name, stored_path, "pending", None, org_id),
        )
    else:
        # PostgreSQL doesn't have patient_dob column, exclude it
        conn.execute(
            "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, institution_id, study_description, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, created_at, patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), inst_id, study_description.strip(), admin_notes.strip(), "", original_name, stored_path, "pending", None, org_id),
        )
    conn.commit()
    conn.close()

    insert_case_event(
        case_id=case_id,
        org_id=org_id,
        event_type="SUBMITTED",
        user={"username": "external"},
        comment=admin_notes.strip() or None,
    )

    return RedirectResponse(url="/", status_code=303)


@app.get("/submit", response_class=HTMLResponse)
def submit_form(request: Request):
    try:
        user = require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/submit")

    org_id = user.get("org_id")
    institutions = list_institutions(org_id)
    radiologists = list_radiologists(org_id)
    
    # Ensure each institution has org_id for multitenant study description filtering
    for inst in institutions:
        if "org_id" not in inst and org_id:
            inst["org_id"] = org_id
    
    return templates.TemplateResponse(
        "submit.html",
        {
            "request": request,
            "institutions": institutions,
            "radiologists": radiologists,
            "user_org_id": org_id,
        },
    )


@app.post("/submit")
async def submit_case(
    request: Request,
    patient_first_name: str = Form(...),
    patient_surname: str = Form(...),
    patient_referral_id: str = Form(...),
    patient_dob: str = Form(""),
    institution_id: str = Form(...),
    org_id_form: str = Form(""),
    modality: str = Form(""),
    study_description: str = Form(...),
    admin_notes: str = Form(""),
    radiologist: str = Form(""),
    attachment: UploadFile | None = File(...),
    action: str = Form("submit"),
    extra_study_description: list[str] = Form([]),
    extra_modality: list[str] = Form([]),
    extra_radiologist: list[str] = Form([]),
):
    user = require_admin(request)
    org_id = user.get("org_id")
    form_org_id = (org_id_form or "").strip()
    if not user.get("is_superuser") and not org_id:
        raise HTTPException(status_code=403, detail="Organisation access required")

    # Validate institution
    try:
        inst_id = int(institution_id)
        inst = get_institution(inst_id, org_id)
        if not inst:
            raise HTTPException(status_code=400, detail="Invalid institution selection")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid institution ID")

    if user.get("is_superuser"):
        inst_org_id = inst.get("org_id") if isinstance(inst, dict) else None
        if inst_org_id:
            org_id = inst_org_id
        elif form_org_id:
            try:
                org_id = int(form_org_id)
            except ValueError:
                pass

    # Validate radiologist (optional - can assign later via bulk assignment)
    radiologist = radiologist.strip() if radiologist else ""
    if radiologist:
        valid_rads = {r["name"] for r in list_radiologists(org_id)}
        if radiologist not in valid_rads:
            raise HTTPException(status_code=400, detail="Invalid radiologist selection")

    # Validate attachment is provided
    if not attachment or not attachment.filename:
        raise HTTPException(status_code=400, detail="Attachment is required")

    cleaned_extra_cases: list[tuple[str, str | None, str]] = []
    if extra_study_description:
        valid_rads = {r["name"] for r in list_radiologists(org_id)}
        for i, extra_desc in enumerate(extra_study_description):
            normalized_desc = (extra_desc or "").strip()
            if not normalized_desc:
                continue
            normalized_rad = extra_radiologist[i].strip() if i < len(extra_radiologist) else ""
            if normalized_rad and normalized_rad not in valid_rads:
                normalized_rad = ""
            normalized_modality = (
                extra_modality[i].strip().upper()
                if i < len(extra_modality) and extra_modality[i].strip()
                else None
            )
            cleaned_extra_cases.append((normalized_desc, normalized_modality, normalized_rad))

    generated_case_ids = generate_case_ids(1 + len(cleaned_extra_cases))
    case_id = generated_case_ids[0]
    original_name = attachment.filename
    
    file_bytes = await attachment.read()
    
    # Try blob storage first, fallback to local
    stored_path = None
    if BLOB_STORAGE_ENABLED:
        blob_name = upload_to_blob(case_id, file_bytes, original_name)
        if blob_name:
            stored_path = blob_name
    
    # Fallback: store locally if blob upload failed or disabled
    if not stored_path:
        safe_name = f"{case_id}_{Path(original_name).name}"
        stored_path = str(UPLOAD_DIR / safe_name)
        with open(stored_path, "wb") as f:
            f.write(file_bytes)

    created_at = utc_now_iso()

    conn = get_db()
    
    # Build insert conditionally based on columns that exist
    has_dob_col = table_has_column("cases", "patient_dob")
    has_modality_col = table_has_column("cases", "modality")
    case_modality = modality.strip().upper() if modality else None
    if has_dob_col and has_modality_col:
        conn.execute(
            "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, patient_dob, institution_id, study_description, modality, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, created_at, patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), patient_dob.strip() or None, inst_id, study_description.strip(), case_modality, admin_notes.strip(), radiologist, original_name, stored_path, "pending", None, org_id),
        )
    elif has_dob_col:
        conn.execute(
            "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, patient_dob, institution_id, study_description, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, created_at, patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), patient_dob.strip() or None, inst_id, study_description.strip(), admin_notes.strip(), radiologist, original_name, stored_path, "pending", None, org_id),
        )
    elif has_modality_col:
        conn.execute(
            "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, institution_id, study_description, modality, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, created_at, patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), inst_id, study_description.strip(), case_modality, admin_notes.strip(), radiologist, original_name, stored_path, "pending", None, org_id),
        )
    else:
        conn.execute(
            "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, institution_id, study_description, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, created_at, patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), inst_id, study_description.strip(), admin_notes.strip(), radiologist, original_name, stored_path, "pending", None, org_id),
        )
    conn.commit()
    conn.close()

    # Create additional cases for extra studies (same patient/institution/attachment)
    if cleaned_extra_cases:
        for idx, (extra_desc, extra_modality_value, extra_rad) in enumerate(cleaned_extra_cases, start=1):
            extra_case_id = generated_case_ids[idx]
            # Copy attachment for the extra case
            extra_stored_path = stored_path
            if stored_path and original_name:
                if BLOB_STORAGE_ENABLED and not stored_path.startswith("/"):
                    # Blob storage: copy blob
                    blob_bytes = download_from_blob(stored_path)
                    if blob_bytes:
                        extra_blob_name = upload_to_blob(extra_case_id, blob_bytes, original_name)
                        if extra_blob_name:
                            extra_stored_path = extra_blob_name
                else:
                    # Local fallback: copy file
                    extra_safe_name = f"{extra_case_id}_{Path(original_name).name}"
                    extra_stored_path = str(UPLOAD_DIR / extra_safe_name)
                    shutil.copy2(stored_path, extra_stored_path)
            conn2 = get_db()
            
            # Build insert conditionally based on columns that exist
            if has_dob_col and has_modality_col:
                conn2.execute(
                    "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, patient_dob, institution_id, study_description, modality, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (extra_case_id, utc_now_iso(), patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), patient_dob.strip() or None, inst_id, extra_desc, extra_modality_value, admin_notes.strip(), extra_rad, original_name, extra_stored_path, "pending", None, org_id),
                )
            elif has_dob_col:
                conn2.execute(
                    "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, patient_dob, institution_id, study_description, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (extra_case_id, utc_now_iso(), patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), patient_dob.strip() or None, inst_id, extra_desc, admin_notes.strip(), extra_rad, original_name, extra_stored_path, "pending", None, org_id),
                )
            elif has_modality_col:
                conn2.execute(
                    "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, institution_id, study_description, modality, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (extra_case_id, utc_now_iso(), patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), inst_id, extra_desc, extra_modality_value, admin_notes.strip(), extra_rad, original_name, extra_stored_path, "pending", None, org_id),
                )
            else:
                conn2.execute(
                    "INSERT INTO cases (id, created_at, patient_first_name, patient_surname, patient_referral_id, institution_id, study_description, admin_notes, radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (extra_case_id, utc_now_iso(), patient_first_name.strip(), patient_surname.strip(), patient_referral_id.strip(), inst_id, extra_desc, admin_notes.strip(), extra_rad, original_name, extra_stored_path, "pending", None, org_id),
                )
            conn2.commit()
            conn2.close()

    # Redirect to admin dashboard
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/submitted/{case_id}", response_class=HTMLResponse)
def submitted(request: Request, case_id: str):
    user = require_admin(request)
    conn = get_db()
    org_id = user.get("org_id")
    if org_id and not user.get("is_superuser"):
        row = conn.execute("SELECT * FROM cases WHERE id = ? AND org_id = ?", (case_id, org_id)).fetchone()
    else:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return templates.TemplateResponse("submitted.html", {"request": request, "case": row})


# -------------------------
# iRefer Guidelines lookup (radiologist only)
# -------------------------

@app.get("/irefer/search")
def irefer_search(request: Request, q: str = ""):
    """Proxy iRefer guidelines search. Results are cached in memory after first fetch."""
    require_radiologist(request)  # radiologist-only endpoint

    global _irefer_guidelines_cache

    # Fetch and cache on first call
    if not _irefer_guidelines_cache and IREFER_API_KEY:
        try:
            url = "https://api.irefer.org.uk/prod-irefer/guidelines?language=en"
            req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": IREFER_API_KEY})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode())
                _irefer_guidelines_cache = data.get("value", [])
        except Exception as exc:
            return JSONResponse({"error": f"iRefer API error: {exc}", "results": []})

    if not _irefer_guidelines_cache:
        return JSONResponse({
            "error": "iRefer API key not configured. Set IREFER_API_KEY environment variable.",
            "results": []
        })

    # Filter by query
    q_lower = q.lower().strip()
    matches = []
    for g in _irefer_guidelines_cache:
        haystack = " ".join(filter(None, [
            g.get("ClinicalDiagnosticIssue", ""),
            g.get("SearchTerms", ""),
            " ".join(g.get("Section", []))
        ])).lower()
        if not q_lower or q_lower in haystack:
            investigations = [
                {
                    "investigation": inv.get("Investigation", ""),
                    "recommendation": inv.get("Recommendation", ""),
                    "grade": inv.get("Grade", ""),
                    "min_dose": inv.get("MinDose", ""),
                    "max_dose": inv.get("MaxDose", ""),
                    "comment": inv.get("Comment", ""),
                }
                for inv in g.get("Investigations", [])
            ]
            matches.append({
                "id": g.get("Id", ""),
                "code": g.get("Code", ""),
                "title": g.get("ClinicalDiagnosticIssue", ""),
                "section": g.get("Section", []),
                "body": g.get("Body", ""),
                "last_updated": g.get("LastUpdated", ""),
                "investigations": investigations,
            })
            if len(matches) >= 10:  # cap results for performance
                break

    return JSONResponse({"results": matches})


# -------------------------
# Vet (radiologist)
# -------------------------
@app.get("/vet/{case_id}", response_class=HTMLResponse)
def vet_form(request: Request, case_id: str):
    user = require_radiologist(request)
    rad_name = user.get("radiologist_name")
    org_id = user.get("org_id")
    org_name = None

    conn = get_db()
    if org_id:
        row = conn.execute(
            "SELECT c.*, i.name as institution_name FROM cases c LEFT JOIN institutions i ON c.institution_id = i.id WHERE c.id = ? AND c.org_id = ?",
            (case_id, org_id),
        ).fetchone()
    else:
        row = conn.execute("SELECT c.*, i.name as institution_name FROM cases c LEFT JOIN institutions i ON c.institution_id = i.id WHERE c.id = ?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    case = dict(row)
    case = normalize_case_attachment(case)
    if case["radiologist"] != rad_name:
        raise HTTPException(status_code=403, detail="Not your case")

    # Get institution-specific protocols
    protocols = []
    if case.get("institution_id"):
        conn = get_db()
        if org_id and table_has_column("protocols", "org_id"):
            proto_rows = conn.execute(
                "SELECT name, instructions FROM protocols WHERE institution_id = ? AND is_active = 1 AND org_id = ? ORDER BY name",
                (case.get("institution_id"), org_id)
            ).fetchall()
        else:
            proto_rows = conn.execute(
                "SELECT name, instructions FROM protocols WHERE institution_id = ? AND is_active = 1 ORDER BY name",
                (case.get("institution_id"),)
            ).fetchall()
        conn.close()
        protocols = [dict(p) for p in proto_rows]
    else:
        # Fallback to active protocols if no institution
        protocols = list_protocols(active_only=True, org_id=org_id)

    if org_id:
        conn = get_db()
        org_row = conn.execute("SELECT name FROM organisations WHERE id = ?", (org_id,)).fetchone()
        conn.close()
        if org_row:
            org_name = org_row.get("name") if isinstance(org_row, dict) else org_row[0]

    return templates.TemplateResponse(
        "vet.html",
        {
            "request": request,
            "case": case,
            "decisions": DECISIONS,
            "protocols": protocols,
            "org_name": org_name,
        },
    )


@app.post("/vet/{case_id}")
def vet_submit(
    request: Request,
    case_id: str,
    protocol: str = Form(""),
    decision: str = Form(...),
    decision_comment: str = Form(""),
    contrast_required: str = Form(""),
    contrast_details: str = Form(""),
):
    user = require_radiologist(request)
    rad_name = user.get("radiologist_name")
    org_id = user.get("org_id")

    if decision not in DECISIONS:
        raise HTTPException(status_code=400, detail="Invalid decision")

    # If decision is "Reject", comment is mandatory and protocol is not required
    if decision == "Reject":
        if not decision_comment.strip():
            raise HTTPException(status_code=400, detail="Comment is required when rejecting a case")
        protocol = ""  # Clear protocol for rejected cases
    else:
        # For Approve/Approve with comment, protocol is required
        if not protocol.strip():
            raise HTTPException(status_code=400, detail="Protocol is required for approved cases")

    conn = get_db()
    if org_id:
        row = conn.execute("SELECT radiologist FROM cases WHERE id = ? AND org_id = ?", (case_id, org_id)).fetchone()
    else:
        row = conn.execute("SELECT radiologist FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Case not found")
    if row["radiologist"] != rad_name:
        conn.close()
        raise HTTPException(status_code=403, detail="Not your case")

    # Determine status based on decision
    if decision == "Reject":
        case_status = "rejected"
    else:
        case_status = "vetted"

    conn.execute(
        """
        UPDATE cases
        SET status = ?,
            protocol = ?,
            decision = ?,
            decision_comment = ?,
            vetted_at = ?,
            contrast_required = ?,
            contrast_details = ?
        WHERE id = ?
        """,
        (case_status, protocol.strip(), decision, decision_comment.strip(), utc_now_iso(),
         contrast_required.strip() or None, contrast_details.strip() or None, case_id),
    )
    conn.commit()
    conn.close()

    insert_case_event(
        case_id=case_id,
        org_id=org_id,
        event_type="VETTED",
        user=user,
        decision=decision,
        protocol=protocol.strip() or None,
        comment=decision_comment.strip() or None,
    )

    return RedirectResponse(url="/radiologist", status_code=303)


# -------------------------
# Attachments + PDF
# -------------------------
@app.get("/case/{case_id}/attachment")
def download_attachment(request: Request, case_id: str):
    user = require_login(request)

    if user["role"] == "radiologist":
        raise HTTPException(status_code=403, detail="Radiologists are not allowed to download attachments")

    conn = get_db()
    row = conn.execute(
        "SELECT stored_filepath, uploaded_filename, radiologist, org_id FROM cases WHERE id = ?",
        (case_id,),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="No attachment found")

    case_data = row if isinstance(row, dict) else dict(row)

    if not case_data.get("stored_filepath"):
        raise HTTPException(status_code=410, detail="Referral file has expired and is no longer available (7-day retention policy).")

    if user.get("role") == "radiologist" and case_data.get("radiologist") != user.get("radiologist_name"):
        raise HTTPException(status_code=403, detail="Not your case")

    org_id = user.get("org_id")
    if org_id and not user.get("is_superuser") and case_data.get("org_id") and case_data.get("org_id") != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    stored_path = case_data.get("stored_filepath")
    
    # Try blob storage first
    file_bytes = None
    if BLOB_STORAGE_ENABLED and stored_path and not stored_path.startswith("/"):
        file_bytes = download_from_blob(stored_path)
        if file_bytes:
            return FileResponse(
                io.BytesIO(file_bytes),
                filename=case_data.get("uploaded_filename") or Path(stored_path).name
            )
    
    # Fallback to local filesystem
    if os.path.exists(stored_path):
        return FileResponse(stored_path, filename=case_data.get("uploaded_filename") or Path(stored_path).name)
    
    # File not found
    clear_case_stored_filepath(case_id)
    raise HTTPException(status_code=410, detail="Referral file missing or expired")


@app.get("/case/{case_id}/attachment/inline")
def view_attachment_inline(request: Request, case_id: str):
    user = require_login(request)

    conn = get_db()
    row = conn.execute(
        "SELECT stored_filepath, uploaded_filename, radiologist, org_id FROM cases WHERE id = ?",
        (case_id,),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="No attachment found")

    case_data = row if isinstance(row, dict) else dict(row)

    if not case_data.get("stored_filepath"):
        raise HTTPException(status_code=410, detail="Referral file has expired and is no longer available (7-day retention policy).")

    if user.get("role") == "radiologist" and case_data.get("radiologist") != user.get("radiologist_name"):
        raise HTTPException(status_code=403, detail="Not your case")

    org_id = user.get("org_id")
    if org_id and not user.get("is_superuser") and case_data.get("org_id") and case_data.get("org_id") != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    stored_path = case_data.get("stored_filepath")
    filename = case_data.get("uploaded_filename") or Path(stored_path).name
    media_type, _ = mimetypes.guess_type(filename)
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    
    # Try blob storage first
    file_bytes = None
    if BLOB_STORAGE_ENABLED and stored_path and not stored_path.startswith("/"):
        file_bytes = download_from_blob(stored_path)
        if file_bytes:
            return FileResponse(
                io.BytesIO(file_bytes),
                media_type=media_type or "application/octet-stream",
                headers=headers
            )
    
    # Fallback to local filesystem
    if os.path.exists(stored_path):
        return FileResponse(stored_path, media_type=media_type or "application/octet-stream", headers=headers)
    
    # File not found
    clear_case_stored_filepath(case_id)
    raise HTTPException(status_code=410, detail="Referral file missing or expired")


@app.get("/case/{case_id}/pdf")
def case_pdf(request: Request, case_id: str, inline: bool = False):
    try:
        user = require_login(request)

        conn = get_db()
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Case not found")
        if user.get("role") == "radiologist":
            raise HTTPException(status_code=403, detail="Radiologists are not allowed to download PDFs")

        org_id = user.get("org_id")
        case_data = row if isinstance(row, dict) else dict(row)

        if org_id and not user.get("is_superuser") and case_data.get("org_id") and case_data.get("org_id") != org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        pdf_path = UPLOAD_DIR / f"{case_id}_vetting.pdf"

        c = canvas.Canvas(str(pdf_path), pagesize=A4)
        width, height = A4
        y = height - 60

        def line(label: str, value: str):
            nonlocal y
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, y, f"{label}:")
            c.setFont("Helvetica", 10)
            c.drawString(170, y, str(value or ""))
            y -= 18

        # Helper function to format datetime
        def format_datetime(iso_string: str) -> str:
            return format_display_datetime(iso_string)

        # Bug 8: Convert row to dict to avoid sqlite3.Row.get() issues
        if isinstance(row, dict):
            case_data = row
        else:
            case_data = dict(row)

        # Organisation name
        org_name = ""
        if case_data.get("org_id"):
            conn = get_db()
            org_row = conn.execute("SELECT name FROM organisations WHERE id = ?", (case_data.get("org_id"),)).fetchone()
            conn.close()
            if org_row:
                org_name = org_row.get("name") if isinstance(org_row, dict) else org_row[0]

        # Radiologist details (profile + GMC)
        rad_name = case_data.get("radiologist", "")
        rad_display = rad_name
        rad_gmc = ""
        rad_position = ""
        if rad_name and table_exists("radiologist_profiles") and table_exists("users"):
            conn = get_db()
            params = [rad_name, rad_name]
            sql = (
                "SELECT rp.display_name, rp.gmc, rp.specialty, u.username, u.first_name, u.surname "
                "FROM radiologist_profiles rp "
                "JOIN users u ON u.id = rp.user_id "
            )
            if table_exists("memberships") and case_data.get("org_id"):
                sql += "LEFT JOIN memberships m ON m.user_id = u.id "
                sql += "WHERE (rp.display_name = ? OR u.username = ?) AND m.org_id = ? "
                params.append(case_data.get("org_id"))
            else:
                sql += "WHERE rp.display_name = ? OR u.username = ? "
            sql += "LIMIT 1"
            prof = conn.execute(sql, params).fetchone()
            conn.close()
            if prof:
                prof = dict(prof)
                rad_display = prof.get("display_name") or rad_display
                rad_gmc = prof.get("gmc") or ""
                rad_position = prof.get("specialty") or ""
        elif rad_name:
            rad = get_radiologist(rad_name)
            if rad:
                rad_gmc = rad.get("gmc", "")

        # Get institution details
        institution_name = ""
        if case_data.get("institution_id"):
            inst = get_institution(case_data.get("institution_id"))
            if inst:
                institution_name = inst["name"]

        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, "Vetting Decision Report")
        y -= 30

        # Case Details Section
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "Case Details")
        y -= 15
        c.setFont("Helvetica", 10)

        if org_name:
            line("Organisation", org_name)

        line("Case ID", case_data.get("id", ""))
        
        # Created timestamp in DD-MM-YYYY HH:MM format
        created_formatted = format_datetime(case_data.get("created_at", ""))
        line("Created", created_formatted)

        # Patient Information
        patient_name = f"{case_data.get('patient_first_name') or ''} {case_data.get('patient_surname') or ''}".strip() or "N/A"
        line("Patient Name", patient_name)
        
        if case_data.get("patient_referral_id"):
            line("Patient ID", case_data.get("patient_referral_id", ""))

        if case_data.get("patient_dob"):
            line("Patient DOB", case_data.get("patient_dob", ""))

        # Institution
        line("Institution", institution_name or "N/A")

        # Radiologist
        line("Radiologist", rad_display or "N/A")
        if rad_position:
            line("Position", rad_position)

        # GNC Number (if available)
        if rad_gmc:
            line("GMC/GNC Number", rad_gmc)
        elif rad_name:
            line("GMC/GNC Number", "MISSING")

        # Study Description
        if case_data.get("study_description"):
            line("Study Description", case_data.get("study_description", ""))

        # Admin Notes
        if case_data.get("admin_notes"):
            y -= 10
            c.setFont("Helvetica-Bold", 11)
            c.drawString(50, y, "Admin Notes")
            y -= 15
            c.setFont("Helvetica", 10)
            
            admin_note_lines = (case_data.get("admin_notes", "") or "").split('\n')
            for note_line in admin_note_lines:
                # Wrap long lines at 80 characters
                line_text = note_line.strip()
                while len(line_text) > 80:
                    if y < 100:
                        c.showPage()
                        y = height - 60
                    c.drawString(70, y, line_text[:80])
                    y -= 12
                    line_text = line_text[80:]
                
                if line_text:
                    if y < 100:
                        c.showPage()
                        y = height - 60
                    c.drawString(70, y, line_text)
                    y -= 12

        y -= 10
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "Vetting Decision")
        y -= 15
        c.setFont("Helvetica", 10)

        # Decision
        line("Decision", case_data.get("decision", "N/A"))

        # Protocol (only if not rejected)
        protocol_name = case_data.get("protocol")
        if case_data.get("decision") != "Reject" and protocol_name:
            line("Protocol", protocol_name)
            
            # Get protocol instructions from protocols table
            try:
                conn = get_db()
                protocol_row = conn.execute(
                    "SELECT instructions FROM protocols WHERE name = ? AND org_id = ? LIMIT 1",
                    (protocol_name, case_data.get("org_id"))
                ).fetchone()
                conn.close()
                
                if protocol_row:
                    # Handle both dict and Row objects
                    protocol_instructions = protocol_row.get("instructions") if isinstance(protocol_row, dict) else protocol_row["instructions"]
                    if protocol_instructions:
                        c.setFont("Helvetica-Bold", 10)
                        c.drawString(50, y, "Protocol Notes:")
                        c.setFont("Helvetica", 10)
                        y -= 15
                        
                        # Split instructions into lines and handle multi-line text
                        instruction_lines = protocol_instructions.split('\n')
                        for instruction_line in instruction_lines:
                            # Wrap long lines at 80 characters
                            line_text = instruction_line.strip()
                            while len(line_text) > 80:
                                if y < 100:
                                    c.showPage()
                                    y = height - 60
                                c.drawString(70, y, line_text[:80])
                                y -= 12
                                line_text = line_text[80:]
                            
                            if line_text:
                                if y < 100:
                                    c.showPage()
                                    y = height - 60
                                c.drawString(70, y, line_text)
                                y -= 12
                        y += 2  # Small spacing adjustment
            except Exception as e:
                print(f"Error fetching protocol instructions: {e}")

        # Decision Comment
        if case_data.get("decision_comment"):
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, y, "Comment:")
            c.setFont("Helvetica", 10)
            y -= 15
            comment_lines = (case_data.get("decision_comment", "") or "").split('\n')
            for comment_line in comment_lines:
                if y < 100:
                    c.showPage()
                    y = height - 60
                c.drawString(70, y, comment_line[:80])
                y -= 12

        y -= 10
        # Vetted timestamp in DD-MM-YYYY HH:MM format
        vetted_formatted = format_datetime(case_data.get("vetted_at", ""))
        if vetted_formatted:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, y, "Vetted:")
            c.setFont("Helvetica", 10)
            c.drawString(170, y, vetted_formatted)

        c.showPage()
        c.save()

        if inline:
            headers = {"Content-Disposition": f'inline; filename="vetting_{case_id}.pdf"'}
            return FileResponse(str(pdf_path), media_type="application/pdf", headers=headers)

        return FileResponse(str(pdf_path), filename=f"vetting_{case_id}.pdf")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


# -------------------------
# SUPERUSER ROUTES - Multi-Tenant Management
# -------------------------

@app.get("/mt", response_class=HTMLResponse)
@app.get("/mt/dashboard", response_class=HTMLResponse)
def mt_dashboard(request: Request):
    """Superuser: Multi-tenant dashboard overview"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt")
    
    user = get_session_user(request)
    conn = get_db()
    
    # Check if user is superuser
    row = conn.execute("SELECT is_superuser FROM users WHERE username = ?", (user["username"],)).fetchone()
    if not row or not row["is_superuser"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    # Get stats
    stats = {}
    stats['org_count'] = conn.execute("SELECT COUNT(*) as count FROM organisations").fetchone()['count']
    stats['user_count'] = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()['count']
    stats['case_count'] = conn.execute("SELECT COUNT(*) as count FROM cases").fetchone()['count']
    stats['superuser_count'] = conn.execute("SELECT COUNT(*) as count FROM users WHERE is_superuser = 1").fetchone()['count']
    
    # Get organisations with member counts
    orgs = conn.execute("""
        SELECT o.id, o.name, o.slug, o.is_active,
               COUNT(DISTINCT m.user_id) as member_count,
               COUNT(DISTINCT c.id) as case_count
        FROM organisations o
        LEFT JOIN memberships m ON o.id = m.org_id AND m.is_active = 1
        LEFT JOIN cases c ON o.id = c.org_id
        GROUP BY o.id
        ORDER BY o.name
    """).fetchall()
    
    conn.close()
    
    # Create simple HTML dashboard with improved visuals
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Multi-Tenant Dashboard</title>
        <link rel="stylesheet" href="/static/css/site.css">
        <style>
            .mt-stats {{ 
                display: grid; 
                grid-template-columns: repeat(4, 1fr); 
                gap: 20px; 
                margin-bottom: 30px; 
            }}
            .stat-card {{ 
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                padding: 24px; 
                border-radius: 10px; 
                text-align: center;
            }}
            .stat-number {{ 
                font-size: 2.8em; 
                font-weight: bold; 
                color: white; 
                margin-bottom: 8px; 
            }}
            .stat-label {{ 
                color: var(--muted); 
                font-size: 0.95em; 
                text-transform: uppercase; 
                letter-spacing: 1px; 
            }}
            .org-table {{ 
                width: 100%; 
                margin-top: 20px;
            }}
            .org-table td {{ padding: 14px 10px; }}
            .org-table th {{ padding: 14px 10px; }}
            .active-badge {{ 
                background: #2fbf71; 
                color: #04210d; 
                padding: 6px 12px; 
                border-radius: 999px; 
                font-size: 12px; 
                font-weight: 700; 
                text-transform: uppercase;
            }}
            .inactive-badge {{ 
                background: #d9534f; 
                color: #2b0e0e; 
                padding: 6px 12px; 
                border-radius: 999px; 
                font-size: 12px; 
                font-weight: 700; 
                text-transform: uppercase;
            }}
            .info-card {{ 
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                padding: 22px;
                border-radius: 10px;
                margin-top: 30px;
            }}
            .info-card h3 {{ 
                color: white; 
                margin-bottom: 15px; 
                font-size: 1.3em; 
            }}
            .info-card ul {{ 
                margin-left: 20px; 
                line-height: 1.8; 
            }}
            .info-card li {{ 
                font-size: 1em; 
                color: var(--muted); 
            }}
            .page-title {{ 
                font-size: 2.2em; 
                color: white; 
                margin-bottom: 8px; 
            }}
            .page-subtitle {{ 
                color: var(--muted); 
                font-size: 1.1em; 
                margin-bottom: 24px; 
            }}
            .section-title {{ 
                font-size: 1.5em; 
                color: white; 
                margin: 30px 0 15px 0; 
            }}
            .topbar {{ 
                display: flex; 
                justify-content: flex-start; 
                gap: 12px; 
                margin-bottom: 24px; 
            }}
            .page-header {{
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 24px;
                margin-bottom: 24px;
            }}
            .page-header-left {{
                flex: 1;
            }}
            .brand-logo {{
                width: 180px;
                max-width: 100%;
                height: auto;
                display: block;
                border-radius: 10px;
                flex-shrink: 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="page-header">
                <div class="page-header-left">
                    <h1 class="page-title">Multi-Tenant Management Dashboard</h1>
                    <p class="page-subtitle">Welcome, <strong>{user['username']}</strong> (Superuser)</p>
                    <div class="topbar">
                        <a href="/logout" class="btn secondary">Logout</a>
                        <a href="/mt/create-org" class="btn">Create Organisation</a>
                        <a href="/mt/users" class="btn">View All Superusers</a>
                        <a href="/mt/protocols" class="btn">Protocol Templates</a>
                    </div>
                </div>
                <img class="brand-logo" src="{LOGO_DARK_URL}" alt="Lumos Lab"
                     onerror="this.style.display='none';">
            </div>
            
            <h2 class="section-title">Platform Statistics</h2>
            <div class="mt-stats">
                <div class="stat-card">
                    <div class="stat-number">{stats['org_count']}</div>
                    <div class="stat-label">Organisations</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['user_count']}</div>
                    <div class="stat-label">Total Users</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['case_count']}</div>
                    <div class="stat-label">Total Cases</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['superuser_count']}</div>
                    <div class="stat-label">Superusers</div>
                </div>
            </div>
            
            <h2 class="section-title">Organisations</h2>
            <table class="org-table">
                <thead>
                    <tr>
                        <th style="width: 60px;">ID</th>
                        <th>Name</th>
                        <th>Slug</th>
                        <th style="width: 120px;">Members</th>
                        <th style="width: 120px;">Cases</th>
                        <th style="width: 100px;">Status</th>
                        <th style="width: 150px;">Actions</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    for org in orgs:
        status_badge = '<span class="active-badge">Active</span>' if org['is_active'] else '<span class="inactive-badge">Inactive</span>'
        html += f"""
                    <tr>
                        <td><strong>#{org['id']}</strong></td>
                        <td><strong style="font-size: 1.05em;">{org['name']}</strong></td>
                        <td><span class="pill">{org['slug']}</span></td>
                        <td><strong>{org['member_count']}</strong> users</td>
                        <td><strong>{org['case_count']}</strong> cases</td>
                        <td>{status_badge}</td>
                        <td>
                            <a href="/mt/org/{org['id']}" class="btn btn-primary">View Details</a>
                        </td>
                    </tr>
        """
    
    html += """
                </tbody>
            </table>
            
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)


@app.get("/super/orgs", response_class=HTMLResponse)
def super_orgs_page(request: Request):
    require_superuser(request)
    conn = get_db()
    orgs = conn.execute(
        """
        SELECT o.id, o.name, o.slug, o.is_active,
               COUNT(DISTINCT m.user_id) as member_count
        FROM organisations o
        LEFT JOIN memberships m ON o.id = m.org_id AND m.is_active = 1
        GROUP BY o.id
        ORDER BY o.name
        """
    ).fetchall()
    conn.close()
    orgs = [dict(o) for o in orgs]
    return templates.TemplateResponse("admin_orgs.html", {"request": request, "orgs": orgs})


@app.get("/super/users", response_class=HTMLResponse)
def super_users_page(request: Request):
    require_superuser(request)
    conn = get_db()
    rows = conn.execute(
        """
        SELECT u.id as user_id, u.username, u.email, u.is_active,
               m.org_role as org_role,
               o.name as org_name
        FROM users u
        LEFT JOIN memberships m ON m.user_id = u.id AND m.is_active = 1
        LEFT JOIN organisations o ON o.id = m.org_id
        ORDER BY u.username
        """
    ).fetchall()
    conn.close()
    users = [dict(r) for r in rows]
    return templates.TemplateResponse("admin_users.html", {"request": request, "users": users})


@app.get("/super/billing", response_class=HTMLResponse)
def super_billing_page(request: Request):
    require_superuser(request)
    return templates.TemplateResponse("admin_billing.html", {"request": request})


@app.get("/super/billing.csv")
def super_billing_csv(request: Request, from_date: str = "", to_date: str = ""):
    require_superuser(request)
    if not from_date or not to_date:
        raise HTTPException(status_code=400, detail="from and to dates are required")

    try:
        start_dt = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    if not table_exists("case_events"):
        raise HTTPException(status_code=404, detail="case_events table not found")

    conn = get_db()
    events = conn.execute(
        """
        SELECT org_id, event_type, created_at
        FROM case_events
        WHERE created_at >= ? AND created_at <= ?
        """,
        (start_dt.isoformat(), end_dt.isoformat()),
    ).fetchall()

    orgs = conn.execute("SELECT id, name FROM organisations").fetchall()
    conn.close()

    org_names = {o["id"]: o["name"] for o in orgs}
    submitted_counts: dict[int, int] = {}
    vetted_counts: dict[int, int] = {}

    for e in events:
        org_id = e.get("org_id")
        if e.get("event_type") == "SUBMITTED":
            submitted_counts[org_id] = submitted_counts.get(org_id, 0) + 1
        elif e.get("event_type") == "VETTED":
            vetted_counts[org_id] = vetted_counts.get(org_id, 0) + 1

    def iter_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["org_id", "org_name", "submitted_count", "vetted_count", "period_from", "period_to"])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for org_id, org_name in org_names.items():
            w.writerow([
                org_id,
                org_name,
                submitted_counts.get(org_id, 0),
                vetted_counts.get(org_id, 0),
                from_date,
                to_date,
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = f"billing_{from_date}_{to_date}.csv"
    return StreamingResponse(iter_csv(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/mt/create-org", response_class=HTMLResponse)
def mt_create_org_page(request: Request):
    """Superuser: Create new organisation form"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt/create-org")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Create Organisation</title>
        <link rel="stylesheet" href="/static/css/site.css">
        <style>
            .form-card {{
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                padding: 30px;
                border-radius: 10px;
                max-width: 600px;
                margin: 20px auto;
            }}
            .form-group {{
                margin-bottom: 20px;
            }}
            .form-group label {{
                display: block;
                color: var(--muted);
                margin-bottom: 8px;
                font-weight: 600;
            }}
            .form-group input {{
                width: 100%;
                padding: 12px;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.06);
                background: rgba(0,0,0,0.3);
                color: white;
                font-size: 14px;
                box-sizing: border-box;
            }}
            .form-group input:focus {{
                outline: none;
                border-color: var(--accent);
            }}
            .form-group small {{
                display: block;
                color: rgba(255,255,255,0.6);
                margin-top: 5px;
                font-size: 12px;
            }}
            .btn-submit {{
                background: var(--accent);
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                font-size: 14px;
            }}
            .btn-submit:hover {{
                filter: brightness(1.1);
            }}
            .page-title {{
                font-size: 2em;
                color: white;
                margin-bottom: 10px;
            }}
            .topbar {{
                display: flex;
                gap: 12px;
                margin-bottom: 30px;
            }}
            .brand-wrap {{
                margin-bottom: 16px;
            }}
            .brand-logo {{
                width: 220px;
                max-width: 100%;
                height: auto;
                display: block;
                border-radius: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="brand-wrap">
                <img class="brand-logo" src="{LOGO_DARK_URL}" alt="Lumos Lab"
                     onerror="this.style.display='none';">
            </div>
            <div class="topbar">
                <a href="/mt" class="btn secondary">← Back to Dashboard</a>
                <a href="/logout" class="btn secondary">🚪 Logout</a>
            </div>
            
            <h1 class="page-title">➕ Create New Organisation</h1>
            <p style="color: var(--muted); margin-bottom: 30px;">Add a new tenant organisation to the platform. Each organisation will have isolated data.</p>
            
            <div class="form-card">
                <form method="post" action="/mt/create-org">
                    <div class="form-group">
                        <label for="name">Organisation Name *</label>
                        <input type="text" id="name" name="name" required placeholder="e.g., Acme Hospital">
                        <small>The full name of the organisation</small>
                    </div>
                    
                    <div class="form-group">
                        <label for="slug">Slug *</label>
                        <input type="text" id="slug" name="slug" required placeholder="e.g., acme-hospital" pattern="[a-z0-9-]+">
                        <small>URL-friendly identifier (lowercase, hyphens only)</small>
                    </div>
                    
                    <div class="form-group">
                        <button type="submit" class="btn-submit">Create Organisation</button>
                    </div>
                </form>
            </div>
            
            <script>
                // Auto-generate slug from name
                document.getElementById('name').addEventListener('input', function(e) {{
                    const slug = e.target.value
                        .toLowerCase()
                        .replace(/[^a-z0-9\\s-]/g, '')
                        .replace(/\\s+/g, '-')
                        .replace(/-+/g, '-')
                        .trim();
                    document.getElementById('slug').value = slug;
                }});
            </script>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)


@app.post("/mt/create-org")
def mt_create_org_submit(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...)
):
    """Superuser: Create new organisation"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt/create-org")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    # Validate inputs
    name = name.strip()
    slug = slug.strip().lower()
    
    if not name or not slug:
        raise HTTPException(status_code=400, detail="Name and slug are required")
    
    # Check slug format
    import re
    if not re.match(r'^[a-z0-9-]+$', slug):
        raise HTTPException(status_code=400, detail="Slug must contain only lowercase letters, numbers, and hyphens")
    
    # Create organisation
    conn = get_db()
    try:
        now = utc_now_iso()
        if using_postgres():
            row = conn.execute(
                """
                INSERT INTO organisations (name, slug, is_active, created_at, modified_at)
                VALUES (?, ?, 1, ?, ?)
                RETURNING id
                """,
                (name, slug, now, now),
            ).fetchone()
            org_id = row["id"] if isinstance(row, dict) else row[0]
            conn.commit()
        else:
            conn.execute(
                """
                INSERT INTO organisations (name, slug, is_active, created_at, modified_at)
                VALUES (?, ?, 1, ?, ?)
                """,
                (name, slug, now, now)
            )
            conn.commit()
            org_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        # Create default institution with same name as org
        if table_has_column("institutions", "org_id"):
            conn.execute(
                """
                INSERT INTO institutions (name, sla_hours, org_id, created_at, modified_at)
                VALUES (?, 48, ?, ?, ?)
                """,
                (name, org_id, now, now)
            )
            conn.commit()
        
        conn.close()
        
        # Redirect to new org details
        return RedirectResponse(url=f"/mt/org/{org_id}", status_code=303)
    except Exception as e:
        conn.close()
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail=f"Organisation with slug '{slug}' already exists")
        raise HTTPException(status_code=500, detail=f"Failed to create organisation: {str(e)}")


@app.get("/mt/org/{org_id}/edit", response_class=HTMLResponse)
def mt_edit_org_page(request: Request, org_id: int):
    """Superuser: Edit organisation form"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/mt/org/{org_id}/edit")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    conn = get_db()
    org = conn.execute("SELECT * FROM organisations WHERE id = ?", (org_id,)).fetchone()
    conn.close()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Edit {org['name']}</title>
        <link rel="stylesheet" href="/static/css/site.css">
        <style>
            .form-card {{
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                padding: 30px;
                border-radius: 10px;
                max-width: 600px;
                margin: 20px auto;
            }}
            .form-group {{
                margin-bottom: 20px;
            }}
            .form-group label {{
                display: block;
                color: var(--muted);
                margin-bottom: 8px;
                font-weight: 600;
            }}
            .form-group input, .form-group select {{
                width: 100%;
                padding: 12px;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.06);
                background: rgba(0,0,0,0.3);
                color: white;
                font-size: 14px;
                box-sizing: border-box;
            }}
            .form-group input:focus, .form-group select:focus {{
                outline: none;
                border-color: var(--accent);
            }}
            .form-group small {{
                display: block;
                color: rgba(255,255,255,0.6);
                margin-top: 5px;
                font-size: 12px;
            }}
            .btn-submit {{
                background: var(--accent);
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                font-size: 14px;
            }}
            .page-title {{
                font-size: 2em;
                color: white;
                margin-bottom: 10px;
            }}
            .topbar {{
                display: flex;
                gap: 12px;
                margin-bottom: 30px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="topbar">
                <a href="/mt/org/{org_id}" class="btn secondary">← Back to Org</a>
                <a href="/mt" class="btn secondary">Dashboard</a>
                <a href="/logout" class="btn secondary">🚪 Logout</a>
            </div>
            
            <h1 class="page-title">✏️ Edit Organisation</h1>
            <p style="color: var(--muted); margin-bottom: 30px;">Update organisation details</p>
            
            <div class="form-card">
                <form method="post" action="/mt/org/{org_id}/edit">
                    <div class="form-group">
                        <label for="name">Organisation Name *</label>
                        <input type="text" id="name" name="name" value="{org['name']}" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="slug">Slug *</label>
                        <input type="text" id="slug" name="slug" value="{org['slug']}" required pattern="[a-z0-9-]+">
                        <small>URL-friendly identifier (lowercase, hyphens only)</small>
                    </div>
                    
                    <div class="form-group">
                        <label for="is_active">Status</label>
                        <select id="is_active" name="is_active">
                            <option value="1" {'selected' if org['is_active'] else ''}>Active</option>
                            <option value="0" {'selected' if not org['is_active'] else ''}>Inactive</option>
                        </select>
                        <small>Inactive organisations cannot be accessed by users</small>
                    </div>
                    
                    <div class="form-group">
                        <button type="submit" class="btn-submit">Save Changes</button>
                    </div>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)


@app.post("/mt/org/{org_id}/edit")
def mt_edit_org_submit(
    request: Request,
    org_id: int,
    name: str = Form(...),
    slug: str = Form(...),
    is_active: int = Form(...)
):
    """Superuser: Update organisation"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/mt/org/{org_id}/edit")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    name = name.strip()
    slug = slug.strip().lower()
    
    if not name or not slug:
        raise HTTPException(status_code=400, detail="Name and slug are required")
    
    import re
    if not re.match(r'^[a-z0-9-]+$', slug):
        raise HTTPException(status_code=400, detail="Invalid slug format")
    
    conn = get_db()
    try:
        now = utc_now_iso()
        conn.execute(
            """
            UPDATE organisations
            SET name = ?, slug = ?, is_active = ?, modified_at = ?
            WHERE id = ?
            """,
            (name, slug, is_active, now, org_id)
        )
        conn.commit()
        conn.close()
        return RedirectResponse(url=f"/mt/org/{org_id}", status_code=303)
    except Exception as e:
        conn.close()
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail=f"Slug '{slug}' is already in use")
        raise HTTPException(status_code=500, detail=f"Failed to update: {str(e)}")


@app.get("/mt/org/{org_id}/add-user", response_class=HTMLResponse)
def mt_add_user_page(request: Request, org_id: int):
    """Superuser: Add user to organisation form"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/mt/org/{org_id}/add-user")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    conn = get_db()
    org = conn.execute("SELECT * FROM organisations WHERE id = ?", (org_id,)).fetchone()
    conn.close()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Add User to {org['name']}</title>
        <link rel="stylesheet" href="/static/css/site.css">
        <style>
            .form-card {{
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                padding: 30px;
                border-radius: 10px;
                max-width: 600px;
                margin: 20px auto;
            }}
            .form-group {{
                margin-bottom: 20px;
            }}
            .form-group label {{
                display: block;
                color: var(--muted);
                margin-bottom: 8px;
                font-weight: 600;
            }}
            .form-group input, .form-group select {{
                width: 100%;
                padding: 12px;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.06);
                background: rgba(0,0,0,0.3);
                color: white;
                font-size: 14px;
                box-sizing: border-box;
            }}
            .form-group small {{
                display: block;
                color: rgba(255,255,255,0.6);
                margin-top: 5px;
                font-size: 12px;
            }}
            .btn-submit {{
                background: var(--accent);
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                font-size: 14px;
            }}
            .page-title {{
                font-size: 2em;
                color: white;
                margin-bottom: 10px;
            }}
            .topbar {{
                display: flex;
                gap: 12px;
                margin-bottom: 30px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="topbar">
                <a href="/mt/org/{org_id}" class="btn secondary">← Back to Org</a>
                <a href="/logout" class="btn secondary">Logout</a>
            </div>
            
            <h1 class="page-title">Add User to {org['name']}</h1>
            <p style="color: var(--muted); margin-bottom: 30px;">Create a new user and assign an access level for this organisation</p>
            
            <div class="form-card">
                <form method="post" action="/mt/org/{org_id}/add-user">
                    <div class="form-group">
                        <label for="username">Username *</label>
                        <input type="text" id="username" name="username" required>
                    </div>

                    <div class="form-group">
                        <label for="email">Email *</label>
                        <input type="email" id="email" name="email" required>
                    </div>

                    <div class="form-group">
                        <label for="first_name">First Name *</label>
                        <input type="text" id="first_name" name="first_name" required>
                    </div>

                    <div class="form-group">
                        <label for="surname">Surname *</label>
                        <input type="text" id="surname" name="surname" required>
                    </div>

                    <div class="form-group">
                        <label for="password">Password *</label>
                        <input type="password" id="password" name="password" required>
                    </div>

                    <div class="form-group">
                        <label for="role">Access Level *</label>
                        <select id="role" name="role" required>
                            <option value="admin">Admin</option>
                            <option value="radiologist">Radiologist</option>
                            <option value="user">User</option>
                        </select>
                        <small>Admin: full org access. Radiologist: vetting queue only. User: limited access.</small>
                    </div>

                    <div class="form-group">
                        <label for="display_name">Radiologist Display Name</label>
                        <input type="text" id="display_name" name="display_name" placeholder="e.g., Dr John Smith">
                        <small>Only required for radiologists</small>
                    </div>

                    <div class="form-group">
                        <label for="gmc">GMC</label>
                        <input type="text" id="gmc" name="gmc">
                        <small>Only required for radiologists</small>
                    </div>

                    <div class="form-group">
                        <label for="speciality">Speciality</label>
                        <input type="text" id="speciality" name="speciality">
                        <small>Only required for radiologists</small>
                    </div>

                    <div class="form-group">
                        <button type="submit" class="btn-submit">Create User</button>
                    </div>
                </form>
            """
    
    html += """
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)


@app.post("/mt/org/{org_id}/add-user")
def mt_add_user_submit(
    request: Request,
    org_id: int,
    username: str = Form(...),
    email: str = Form(...),
    first_name: str = Form(...),
    surname: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    display_name: str = Form(""),
    gmc: str = Form(""),
    speciality: str = Form("")
):
    """Superuser: Add user to organisation"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/mt/org/{org_id}/add-user")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    username = username.strip()
    email = email.strip()
    first_name = first_name.strip()
    surname = surname.strip()
    role = role.strip().lower()
    display_name = display_name.strip()
    gmc = gmc.strip()
    speciality = speciality.strip()

    if role not in ("admin", "radiologist", "user"):
        raise HTTPException(status_code=400, detail="Invalid role")

    if not username or not email or not first_name or not surname or not password:
        raise HTTPException(status_code=400, detail="All required fields must be completed")

    org_role = "org_user"
    if role == "admin":
        org_role = "org_admin"
    elif role == "radiologist":
        org_role = "radiologist"

    conn = get_db()
    try:
        now = utc_now_iso()
        salt = secrets.token_bytes(16)
        pw_hash = hash_password(password, salt)

        email_val = email or None  # store NULL not '' to avoid UNIQUE constraint clashes
        if using_postgres():
            user_row = conn.execute(
                """
                INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at, first_name, surname)
                VALUES(?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                RETURNING id
                """,
                (username, email_val, pw_hash.hex(), salt.hex(), now, now, first_name, surname),
            ).fetchone()
            user_id = user_row["id"] if isinstance(user_row, dict) else user_row[0]
        else:
            conn.execute(
                """
                INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at, first_name, surname)
                VALUES(?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                """,
                (username, email_val, pw_hash.hex(), salt.hex(), now, now, first_name, surname),
            )

            user_row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            user_id = user_row["id"] if user_row else None
        if not user_id:
            raise HTTPException(status_code=500, detail="Failed to create user")

        conn.execute(
            """
            INSERT INTO memberships (org_id, user_id, org_role, is_active, created_at, modified_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (org_id, user_id, org_role, now, now),
        )

        if role == "radiologist":
            display = display_name or f"{first_name} {surname}".strip() or username
            if using_postgres():
                conn.execute(
                    """
                    INSERT INTO radiologists(name, first_name, email, surname, gmc, speciality)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (display, first_name, email, surname, gmc, speciality),
                )
                conn.execute(
                    """
                    INSERT INTO radiologist_profiles(user_id, gmc, specialty, display_name, created_at, modified_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (user_id, gmc or None, speciality or None, display, now, now),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO radiologists(name, first_name, email, surname, gmc, speciality)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (display, first_name, email, surname, gmc, speciality),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO radiologist_profiles(user_id, gmc, specialty, display_name, created_at, modified_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, gmc or None, speciality or None, display, now, now),
                )

        conn.commit()
        conn.close()
        return RedirectResponse(url=f"/mt/org/{org_id}", status_code=303)
    except Exception as e:
        conn.close()
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail="Username or email already exists")
        raise HTTPException(status_code=500, detail=f"Failed to add user: {str(e)}")


@app.get("/mt/org/{org_id}/edit-user/{user_id}", response_class=HTMLResponse)
def mt_edit_user_page(request: Request, org_id: int, user_id: int):
    """Superuser: Edit user form"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/mt/org/{org_id}/edit-user/{user_id}")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    conn = get_db()
    
    # Get user details
    user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user_row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get membership
    membership = conn.execute(
        "SELECT org_role, is_active FROM memberships WHERE user_id = ? AND org_id = ?",
        (user_id, org_id)
    ).fetchone()
    
    if not membership:
        conn.close()
        raise HTTPException(status_code=404, detail="User not member of this org")
    
    # Get org
    org = conn.execute("SELECT name FROM organisations WHERE id = ?", (org_id,)).fetchone()
    conn.close()
    
    org_role = membership["org_role"]
    role_display = "Admin" if org_role == "org_admin" else "Radiologist" if org_role == "radiologist" else "User"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Edit {user_row['username']} - {org['name']}</title>
        <link rel="stylesheet" href="/static/css/site.css">
        <style>
            .form-card {{
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                padding: 24px;
                border-radius: 10px;
                max-width: 600px;
                margin: 30px 0;
            }}
            .form-group {{
                margin-bottom: 20px;
            }}
            .form-group label {{
                display: block;
                margin-bottom: 8px;
                color: rgba(255,255,255,0.9);
                font-weight: 500;
            }}
            .form-group input,
            .form-group select {{
                width: 100%;
                padding: 10px;
                border: 1px solid rgba(31, 111, 235, 0.2);
                border-radius: 6px;
                background: rgba(255, 255, 255, 0.05);
                color: rgba(255, 255, 255, 0.95);
                font-size: 14px;
                box-sizing: border-box;
            }}
            .form-group select option {{
                background: #07133a;
                color: rgba(255, 255, 255, 0.95);
            }}
            .button-group {{
                display: flex;
                gap: 10px;
                margin-top: 30px;
            }}
            .btn {{
                padding: 10px 20px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-weight: 500;
                text-decoration: none;
                display: inline-block;
            }}
            .btn-primary {{
                background: #1f6feb;
                color: white;
            }}
            .btn-primary:hover {{
                background: #388bfd;
            }}
            .btn-secondary {{
                background: rgba(255, 255, 255, 0.1);
                color: rgba(255, 255, 255, 0.9);
            }}
            .btn-secondary:hover {{
                background: rgba(255, 255, 255, 0.15);
            }}
            .page-title {{
                font-size: 2.2em;
                color: white;
                margin-bottom: 8px;
            }}
            .page-subtitle {{
                color: var(--muted);
                font-size: 1.1em;
                margin-bottom: 24px;
            }}
            .info-box {{
                background: rgba(31, 111, 235, 0.1);
                border: 1px solid rgba(31, 111, 235, 0.3);
                padding: 12px;
                border-radius: 6px;
                margin-bottom: 20px;
                color: rgba(255, 255, 255, 0.8);
                font-size: 0.95em;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="page-title">✏️ Edit User</h1>
            <p class="page-subtitle">Editing <strong>{user_row['username']}</strong> in <strong>{org['name']}</strong></p>
            
            <div class="form-card">
                <div class="info-box">
                    <strong>User ID:</strong> {user_id} | <strong>Created:</strong> {user_row['created_at'][:10] if user_row['created_at'] else 'N/A'}
                </div>
                
                <form method="post" action="/mt/org/{org_id}/edit-user/{user_id}">
                    <div class="form-group">
                        <label>Username</label>
                        <input type="text" value="{user_row['username']}" disabled style="background: rgba(255,255,255,0.03); cursor: not-allowed;">
                    </div>
                    
                    <div class="form-group">
                        <label>Email</label>
                        <input type="email" name="email" value="{user_row['email'] or ''}">
                    </div>
                    
                    <div class="form-group">
                        <label>First Name</label>
                        <input type="text" name="first_name" value="{user_row['first_name'] or ''}">
                    </div>
                    
                    <div class="form-group">
                        <label>Surname</label>
                        <input type="text" name="surname" value="{user_row['surname'] or ''}">
                    </div>
                    
                    <div class="form-group">
                        <label>Change Password (leave blank to keep current)</label>
                        <input type="password" name="password" placeholder="Leave blank if no change">
                    </div>
                    
                    <div class="form-group">
                        <label>Role in {org['name']}</label>
                        <select name="org_role" required>
                            <option value="org_admin" {'selected' if org_role == 'org_admin' else ''}>Admin (can manage users & settings)</option>
                            <option value="radiologist" {'selected' if org_role == 'radiologist' else ''}>Radiologist (can vet cases)</option>
                            <option value="org_user" {'selected' if org_role == 'org_user' else ''}>User (limited access)</option>
                        </select>
                    </div>
                    
                    <div class="button-group">
                        <button type="submit" class="btn btn-primary">Save Changes</button>
                        <a href="/mt/org/{org_id}" class="btn btn-secondary">Cancel</a>
                    </div>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)


@app.post("/mt/org/{org_id}/edit-user/{user_id}")
def mt_edit_user_submit(request: Request, org_id: int, user_id: int, 
                        email: str = Form(""), first_name: str = Form(""),
                        surname: str = Form(""), password: str = Form(""),
                        org_role: str = Form(...)):
    """Superuser: Save user changes"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/mt/org/{org_id}")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    # Validate org_role
    if org_role not in ["org_admin", "radiologist", "org_user"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    conn = get_db()
    try:
        # Update user details
        now = utc_now_iso()
        conn.execute(
            """
            UPDATE users 
            SET email = ?, first_name = ?, surname = ?, modified_at = ?
            WHERE id = ?
            """,
            (email.strip(), first_name.strip(), surname.strip(), now, user_id)
        )
        
        # Update password if provided
        if password.strip():
            salt = secrets.token_bytes(16)
            pw_hash = hash_password(password, salt)
            conn.execute(
                "UPDATE users SET password_hash = ?, salt_hex = ? WHERE id = ?",
                (pw_hash.hex(), salt.hex(), user_id)
            )
        
        # Update role
        conn.execute(
            "UPDATE memberships SET org_role = ?, modified_at = ? WHERE user_id = ? AND org_id = ?",
            (org_role, now, user_id, org_id)
        )
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update user: {str(e)}")
    finally:
        conn.close()
    
    return RedirectResponse(url=f"/mt/org/{org_id}", status_code=303)


@app.get("/mt/org/{org_id}/remove-user/{user_id}")
def mt_remove_user(request: Request, org_id: int, user_id: int):
    """Superuser: Remove user from organisation"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/mt/org/{org_id}")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    conn = get_db()
    # Soft delete - set is_active to 0
    conn.execute(
        """
        UPDATE memberships
        SET is_active = 0, modified_at = ?
        WHERE org_id = ? AND user_id = ?
        """,
        (utc_now_iso(), org_id, user_id)
    )
    conn.commit()
    conn.close()
    
    return RedirectResponse(url=f"/mt/org/{org_id}", status_code=303)


@app.get("/mt/org/{org_id}", response_class=HTMLResponse)
def mt_org_detail(request: Request, org_id: int):
    """Superuser: View organisation details"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/mt/org/{org_id}")
    
    user = get_session_user(request)
    conn = get_db()
    
    # Check superuser
    row = conn.execute("SELECT is_superuser FROM users WHERE username = ?", (user["username"],)).fetchone()
    if not row or not row["is_superuser"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    # Get org details
    org = conn.execute("SELECT * FROM organisations WHERE id = ?", (org_id,)).fetchone()
    if not org:
        conn.close()
        raise HTTPException(status_code=404, detail="Organisation not found")
    
    # Get members (exclude superusers)
    members = conn.execute("""
        SELECT u.id, u.username, u.email, u.is_superuser, m.org_role, m.is_active
        FROM memberships m
        JOIN users u ON m.user_id = u.id
        WHERE m.org_id = ? AND u.is_superuser = 0
        ORDER BY u.username
    """, (org_id,)).fetchall()
    
    # Get cases for this org
    cases = conn.execute("""
        SELECT id, patient_first_name, patient_surname, status, created_at, radiologist
        FROM cases
        WHERE org_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    """, (org_id,)).fetchall()
    
    conn.close()
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{org['name']} - Details</title>
        <link rel="stylesheet" href="/static/css/site.css">
        <style>
            .page-title {{
                font-size: 2.2em;
                color: white;
                margin-bottom: 8px;
            }}
            .page-subtitle {{
                color: var(--muted);
                font-size: 1.1em;
                margin-bottom: 24px;
            }}
            .section-card {{
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                padding: 24px;
                border-radius: 10px;
                margin-bottom: 30px;
            }}
            .section-title {{
                font-size: 1.4em;
                color: white;
                margin-bottom: 16px;
            }}
            .empty-state {{
                color: var(--muted);
                padding: 40px;
                text-align: center;
                font-size: 1.1em;
            }}
            .topbar {{
                display: flex;
                gap: 12px;
                margin-bottom: 24px;
            }}
            .data-table {{
                width: 100%;
                margin-top: 15px;
            }}
            .data-table th {{
                padding: 12px;
                text-align: left;
            }}
            .data-table td {{
                padding: 12px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="page-title">{org['name']}</h1>
            <p class="page-subtitle">Slug: <strong>{org['slug']}</strong> | ID: {org['id']}</p>
            
            <div class="topbar">
                <a href="/mt" class="btn secondary">← Back to Dashboard</a>
                <a href="/mt/org/{org_id}/edit" class="btn">✏️ Edit Organisation</a>
                <a href="/mt/org/{org_id}/add-user" class="btn">➕ Add User</a>
                <a href="/logout" class="btn secondary">🚪 Logout</a>
            </div>
            
            <div class="section-card">
                <h2 class="section-title">👥 Members ({len(members)})</h2>
    """
    
    if members:
        html += """
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Username</th>
                            <th>Email</th>
                            <th>Role</th>
                            <th>Status</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for member in members:
            role = member['org_role']
            if member['is_superuser']:
                role = 'superuser'
            status = '✅ Active' if member['is_active'] else '❌ Inactive'
            edit_btn = '' if member['is_superuser'] else f'<a href="/mt/org/{org_id}/edit-user/{member["id"]}" class="btn secondary">✏️ Edit</a>'
            remove_btn = '' if member['is_superuser'] else f'<a href="/mt/org/{org_id}/remove-user/{member["id"]}" class="btn secondary" onclick="return confirm(\'Remove {member["username"]} from this organisation?\')">🗑️ Remove</a>'
            html += f"""
                            <tr>
                                <td><strong>{member['username']}</strong></td>
                                <td>{member['email'] or 'N/A'}</td>
                                <td><span class="pill">{role}</span></td>
                                <td>{status}</td>
                                <td>{edit_btn} {remove_btn}</td>
                            </tr>
            """
        
        html += """
                    </tbody>
                </table>
        """
    else:
        html += """
                <div class="empty-state">
                    <p>👤 No members yet</p>
                    <p style="font-size: 0.9em;">Users will appear here when they are added to this organisation</p>
                </div>
        """
    
    html += f"""
            </div>
            
            <div class="section-card">
                <h2 class="section-title">📋 Recent Cases ({len(cases)})</h2>
    """
    
    if cases:
        html += """
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Case ID</th>
                            <th>Patient</th>
                            <th>Status</th>
                            <th>Radiologist</th>
                            <th>Created</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for case in cases:
            patient_name = f"{case['patient_first_name']} {case['patient_surname']}"
            status_color = "color: #2fbf71;" if case['status'] == 'vetted' else "color: #ff9900;" if case['status'] == 'pending' else "color: #d9534f;"
            html += f"""
                            <tr>
                                <td><strong>#{case['id']}</strong></td>
                                <td>{patient_name}</td>
                                <td><span class="pill" data-status="{case['status']}" style="{status_color}">{case['status']}</span></td>
                                <td>{case['radiologist'] or 'Unassigned'}</td>
                                <td>{case['created_at'][:10] if case['created_at'] else 'N/A'}</td>
                            </tr>
            """
        
        html += """
                    </tbody>
                </table>
        """
    else:
        html += """
                <div class="empty-state">
                    <p>📋 No cases yet</p>
                    <p style="font-size: 0.9em;">Cases will appear here when they are submitted to this organisation</p>
                </div>
        """
    
    html += """
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)


@app.get("/mt/organisations", response_class=HTMLResponse)
def mt_organisations(request: Request):
    """Superuser: View and manage all organisations"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt/organisations")
    
    # Check if user is superuser
    user = get_session_user(request)
    conn = get_db()
    row = conn.execute("SELECT is_superuser FROM users WHERE username = ?", (user["username"],)).fetchone()
    conn.close()
    
    if not row or not row["is_superuser"]:
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    # Get all organisations
    conn = get_db()
    orgs = conn.execute("""
        SELECT o.*, COUNT(DISTINCT m.user_id) as member_count
        FROM organisations o
        LEFT JOIN memberships m ON o.id = m.org_id AND m.is_active = 1
        GROUP BY o.id
        ORDER BY o.name
    """).fetchall()
    conn.close()
    
    return templates.TemplateResponse(
        "mt_organisations.html",
        {"request": request, "user": user, "organisations": [dict(o) for o in orgs]}
    )


@app.get("/mt/users", response_class=HTMLResponse)
def mt_users(request: Request):
    """Superuser: View and manage all superusers (system-level admins)"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt/users")
    
    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")
    
    conn = get_db()
    
    # Get all superusers
    superusers = conn.execute("""
        SELECT id, username, email, is_active, created_at
        FROM users
        WHERE is_superuser = 1
        ORDER BY username
    """).fetchall()
    
    conn.close()
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Superusers - Multitenant Management</title>
        <link rel="stylesheet" href="/static/css/site.css">
        <style>
            .page-title {{
                font-size: 2.2em;
                color: white;
                margin-bottom: 8px;
            }}
            .page-subtitle {{
                color: var(--muted);
                font-size: 1.1em;
                margin-bottom: 24px;
            }}
            .section-card {{
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                padding: 24px;
                border-radius: 10px;
                margin-bottom: 30px;
            }}
            .section-title {{
                font-size: 1.4em;
                color: white;
                margin-bottom: 16px;
            }}
            .topbar {{
                display: flex;
                gap: 12px;
                margin-bottom: 24px;
            }}
            .data-table {{
                width: 100%;
                margin-top: 15px;
                border-collapse: collapse;
            }}
            .data-table th {{
                padding: 12px;
                text-align: left;
                background: rgba(255, 255, 255, 0.05);
                border-bottom: 1px solid rgba(31, 111, 235, 0.3);
            }}
            .data-table td {{
                padding: 12px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }}
            .badge {{
                display: inline-block;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 0.85em;
            }}
            .badge-active {{
                background: rgba(47, 191, 113, 0.2);
                color: #2fbf71;
            }}
            .badge-inactive {{
                background: rgba(217, 83, 79, 0.2);
                color: #d9534f;
            }}
            .empty-state {{
                color: var(--muted);
                padding: 40px;
                text-align: center;
                font-size: 1.1em;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="page-title">👑 System Superusers</h1>
            <p class="page-subtitle">Platform-level administrators</p>
            
            <div class="topbar">
                <a href="/mt" class="btn secondary">← Back to Dashboard</a>
                <a href="/logout" class="btn secondary">Logout</a>
            </div>
            
            <div class="section-card">
                <h2 class="section-title">All Superusers ({len(superusers)})</h2>
    """
    
    if superusers:
        html += """
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Username</th>
                            <th>Email</th>
                            <th>Status</th>
                            <th>Created</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for su in superusers:
            status = '✅ Active' if su['is_active'] else '❌ Inactive'
            status_badge = 'badge-active' if su['is_active'] else 'badge-inactive'
            created_date = su['created_at'][:10] if su['created_at'] else 'N/A'
            
            html += f"""
                        <tr>
                            <td><strong>👤 {su['username']}</strong></td>
                            <td>{su['email'] or 'N/A'}</td>
                            <td><span class="badge {status_badge}">{status}</span></td>
                            <td>{created_date}</td>
                        </tr>
            """
        
        html += """
                    </tbody>
                </table>
        """
    else:
        html += """
                <div class="empty-state">
                    <p>No superusers found</p>
                </div>
        """
    
    html += """
            </div>
            
            <div class="section-card" style="background: rgba(31, 111, 235, 0.1); border: 1px solid rgba(31, 111, 235, 0.3);">
                <h3 style="color: #1f6feb; margin-top: 0;">ℹ️ About Superusers</h3>
                <p style="color: rgba(255,255,255,0.8); margin: 0;">
                    Superusers have platform-wide access and can manage all organisations, users, and configurations. 
                    They are separate from organisation members and have system-level administrative privileges.
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)


@app.get("/mt/test", response_class=HTMLResponse)
def mt_test(request: Request):
    """Test page to check multi-tenant database"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt/test")
    
    user = get_session_user(request)
    conn = get_db()
    
    # Get database info
    info = {}
    
    # Check if multi-tenant tables exist
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    info["tables"] = [t["name"] for t in tables]
    
    # Check organisations
    orgs = conn.execute("SELECT * FROM organisations LIMIT 5").fetchall()
    info["organisations"] = [dict(o) for o in orgs]
    
    # Check users
    users = conn.execute("SELECT username, email, is_superuser, is_active FROM users LIMIT 10").fetchall()
    info["users"] = [dict(u) for u in users]
    
    # Check memberships
    members = conn.execute("""
        SELECT m.*, u.username, o.name as org_name
        FROM memberships m
        JOIN users u ON m.user_id = u.id
        JOIN organisations o ON m.org_id = o.id
        LIMIT 10
    """).fetchall()
    info["memberships"] = [dict(m) for m in members]
    
    conn.close()
    
    # Simple HTML response
    html = f"""
    <html>
    <head><title>Multi-Tenant Test</title></head>
    <body style="font-family: Arial; padding: 20px;">
        <h1>Multi-Tenant Database Test</h1>
        <p><a href="/admin">← Back to Admin</a></p>
        
        <h2>Tables ({len(info['tables'])})</h2>
        <ul>{''.join(f'<li>{t}</li>' for t in info['tables'])}</ul>
        
        <h2>Organisations ({len(info['organisations'])})</h2>
        <pre>{info['organisations']}</pre>
        
        <h2>Users ({len(info['users'])})</h2>
        <pre>{info['users']}</pre>
        
        <h2>Memberships ({len(info['memberships'])})</h2>
        <pre>{info['memberships']}</pre>
        
        <h2>Current User</h2>
        <pre>{user}</pre>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# ─────────────────────────────────────────────
# My Account — self-service user profile edit
# ─────────────────────────────────────────────

@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, msg: str = "", error: str = ""):
    """Any authenticated user can view/edit their own profile (name, email, password)."""
    user = get_session_user(request)
    if not user:
        return RedirectResponse(url="/login?expired=1", status_code=303)

    conn = get_db()
    db_user = conn.execute(
        "SELECT id, username, first_name, surname, email FROM users WHERE username = ?",
        (user["username"],)
    ).fetchone()
    conn.close()

    if not db_user:
        return RedirectResponse(url="/login?expired=1", status_code=303)

    db_user = dict(db_user)
    if user.get("is_superuser"):
        back_url = "/mt"
    elif user.get("org_role") in ("org_admin",) or user.get("role") in ("admin",):
        back_url = "/admin"
    else:
        back_url = "/radiologist"

    msg_html = ""
    if msg == "saved":
        msg_html = '<div style="background:rgba(74,222,128,0.12);border:1px solid rgba(74,222,128,0.3);color:#4ade80;padding:12px 16px;border-radius:8px;margin-bottom:16px;">✅ Your profile has been updated.</div>'
    elif msg == "pw_changed":
        msg_html = '<div style="background:rgba(74,222,128,0.12);border:1px solid rgba(74,222,128,0.3);color:#4ade80;padding:12px 16px;border-radius:8px;margin-bottom:16px;">✅ Password changed successfully.</div>'

    error_html = ""
    if error == "email_taken":
        error_html = '<div style="background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);color:#fca5a5;padding:12px 16px;border-radius:8px;margin-bottom:16px;">⚠️ That email address is already in use by another account.</div>'
    elif error == "pw_mismatch":
        error_html = '<div style="background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);color:#fca5a5;padding:12px 16px;border-radius:8px;margin-bottom:16px;">⚠️ New passwords do not match. Please try again.</div>'
    elif error == "pw_wrong":
        error_html = '<div style="background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);color:#fca5a5;padding:12px 16px;border-radius:8px;margin-bottom:16px;">⚠️ Current password is incorrect.</div>'
    elif error == "pw_short":
        error_html = '<div style="background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);color:#fca5a5;padding:12px 16px;border-radius:8px;margin-bottom:16px;">⚠️ New password must be at least 8 characters.</div>'

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>My Account</title>
    <link rel="stylesheet" href="/static/css/site.css">
    <style>
        .account-wrap {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
        .page-title {{ font-size: 2em; color: white; margin-bottom: 6px; }}
        .page-sub {{ color: var(--muted); margin-bottom: 28px; }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .card h3 {{ margin-top: 0; color: rgba(255,255,255,0.9); font-size: 1.15em; }}
        .form-group {{ display: flex; flex-direction: column; gap: 5px; margin-bottom: 16px; }}
        .form-group label {{ font-size: 0.88em; color: rgba(255,255,255,0.65); font-weight: 500; }}
        .form-group input {{
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 6px;
            color: #fff;
            padding: 9px 12px;
            font-size: 0.95em;
        }}
        .form-group input:focus {{ outline: none; border-color: rgba(31,111,235,0.6); }}
        .topbar {{ display: flex; gap: 10px; margin-bottom: 24px; }}
        .read-only {{ color: rgba(255,255,255,0.5); font-size: 0.92em; padding: 8px 0; }}
    </style>
</head>
<body>
<div id="session-expiry-warning" style="display:none;position:fixed;top:0;left:0;right:0;z-index:9999;
    background:rgba(234,179,8,0.95);color:#1a1200;text-align:center;padding:10px 16px;font-weight:600;font-size:14px;">
    ⚠️ Your session will expire soon due to inactivity.
    <button onclick="document.getElementById('session-expiry-warning').style.display='none'"
        style="margin-left:16px;background:rgba(0,0,0,0.15);border:none;border-radius:4px;padding:4px 10px;cursor:pointer;font-weight:600;">
        Dismiss
    </button>
</div>
<div class="account-wrap">
    <div class="topbar">
        <a href="{back_url}" class="btn secondary">&larr; Back</a>
        <a href="/logout" class="btn secondary">Logout</a>
    </div>
    <h1 class="page-title">My Account</h1>
    <p class="page-sub">Edit your personal details. Role and permissions are managed by your administrator.</p>

    {msg_html}{error_html}

    <!-- Profile Details -->
    <div class="card">
        <h3>Personal Details</h3>
        <form method="POST" action="/account/edit">
            <div style="display:flex;gap:16px;">
                <div class="form-group" style="flex:1;">
                    <label>First Name</label>
                    <input type="text" name="first_name" value="{db_user.get('first_name') or ''}">
                </div>
                <div class="form-group" style="flex:1;">
                    <label>Surname</label>
                    <input type="text" name="surname" value="{db_user.get('surname') or ''}">
                </div>
            </div>
            <div class="form-group">
                <label>Email Address</label>
                <input type="email" name="email" value="{db_user.get('email') or ''}">
            </div>
            <div class="form-group">
                <label>Username <span style="color:var(--muted);font-weight:400;">(cannot be changed)</span></label>
                <div class="read-only">{db_user['username']}</div>
            </div>
            <button type="submit" class="btn btn-primary">Save Details</button>
        </form>
    </div>

    <!-- Change Password -->
    <div class="card">
        <h3>Change Password</h3>
        <form method="POST" action="/account/change-password">
            <div class="form-group">
                <label>Current Password</label>
                <input type="password" name="current_password" required autocomplete="current-password">
            </div>
            <div class="form-group">
                <label>New Password</label>
                <input type="password" name="new_password" required autocomplete="new-password"
                       minlength="8" placeholder="At least 8 characters">
            </div>
            <div class="form-group">
                <label>Confirm New Password</label>
                <input type="password" name="confirm_password" required autocomplete="new-password">
            </div>
            <button type="submit" class="btn btn-primary">Change Password</button>
        </form>
    </div>
</div>
<script src="/static/js/session.js"></script>
</body>
</html>"""

    return HTMLResponse(content=html)


@app.post("/account/edit")
def account_edit(
    request: Request,
    first_name: str = Form(""),
    surname: str = Form(""),
    email: str = Form(""),
):
    """Any authenticated user: update own name/email (not role)."""
    user = get_session_user(request)
    if not user:
        return RedirectResponse(url="/login?expired=1", status_code=303)

    username = user["username"]
    new_email = email.strip()

    conn = get_db()
    db_user = conn.execute("SELECT email FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not db_user:
        return RedirectResponse(url="/login?expired=1", status_code=303)

    current_email = db_user["email"] or ""
    email_changed = new_email and new_email != current_email

    if email_changed:
        conn2 = get_db()
        conflict = conn2.execute(
            "SELECT id FROM users WHERE email = ? AND username != ?", (new_email, username)
        ).fetchone()
        conn2.close()
        if conflict:
            return RedirectResponse(url="/account?error=email_taken", status_code=303)

    conn = get_db()
    if email_changed:
        conn.execute(
            "UPDATE users SET first_name = ?, surname = ?, email = ? WHERE username = ?",
            (first_name.strip(), surname.strip(), new_email, username),
        )
    else:
        conn.execute(
            "UPDATE users SET first_name = ?, surname = ? WHERE username = ?",
            (first_name.strip(), surname.strip(), username),
        )
    conn.commit()
    conn.close()

    # Update session display name if changed
    if first_name.strip() or surname.strip():
        user["first_name"] = first_name.strip()
        user["surname"] = surname.strip()
        request.session["user"] = user

    return RedirectResponse(url="/account?msg=saved", status_code=303)


@app.post("/account/change-password")
def account_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    """Any authenticated user: change own password with current-password verification."""
    user = get_session_user(request)
    if not user:
        return RedirectResponse(url="/login?expired=1", status_code=303)

    username = user["username"]

    if new_password != confirm_password:
        return RedirectResponse(url="/account?error=pw_mismatch", status_code=303)

    if len(new_password) < 8:
        return RedirectResponse(url="/account?error=pw_short", status_code=303)

    # Verify current password
    conn = get_db()
    db_user = conn.execute(
        "SELECT salt_hex, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    if not db_user or not db_user["salt_hex"]:
        return RedirectResponse(url="/account?error=pw_wrong", status_code=303)

    try:
        salt = bytes.fromhex(db_user["salt_hex"])
        expected_hash = db_user["password_hash"]
        actual_hash = hash_password(current_password, salt).hex()
        if actual_hash != expected_hash:
            return RedirectResponse(url="/account?error=pw_wrong", status_code=303)
    except Exception:
        return RedirectResponse(url="/account?error=pw_wrong", status_code=303)

    # Set new password
    new_salt = secrets.token_bytes(16)
    new_hash = hash_password(new_password, new_salt)

    conn = get_db()
    conn.execute(
        "UPDATE users SET salt_hex = ?, password_hash = ? WHERE username = ?",
        (new_salt.hex(), new_hash.hex(), username),
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url="/account?msg=pw_changed", status_code=303)


@app.get("/mt/protocols", response_class=HTMLResponse)
def mt_protocols_page(request: Request):
    """Superuser: Manage protocol templates across all organisations"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt/protocols")

    user = get_session_user(request)
    conn = get_db()

    row = conn.execute("SELECT is_superuser FROM users WHERE username = ?", (user["username"],)).fetchone()
    if not row or not row["is_superuser"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Superuser access required")

    # Fetch all protocols joined with org name
    protocols = conn.execute(
        """
        SELECT p.id, p.name, p.instructions, p.last_modified, p.is_active,
               p.org_id, o.name as org_name
        FROM protocols p
        LEFT JOIN organisations o ON p.org_id = o.id
        ORDER BY COALESCE(o.name, ''), p.name
        """
    ).fetchall()
    protocols = [dict(r) for r in protocols]

    # Fetch all organisations for the add-form org selector
    orgs = conn.execute("SELECT id, name FROM organisations WHERE is_active = 1 ORDER BY name").fetchall()
    orgs = [dict(r) for r in orgs]

    conn.close()

    # Format last_modified
    for p in protocols:
        if p.get("last_modified"):
            p["last_modified"] = format_display_datetime(p.get("last_modified"), p.get("last_modified") or "")

    def _proto_rows_html():
        if not protocols:
            return '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:30px;">No protocol templates found</td></tr>'
        out = ""
        for p in protocols:
            org_label = p["org_name"] if p["org_name"] else '<span style="color:var(--muted);">Global</span>'
            status_color = "#4ade80" if p["is_active"] else "rgba(255,255,255,0.4)"
            status_label = "Active" if p["is_active"] else "Inactive"
            instr_preview = (p["instructions"] or "")[:80]
            if p["instructions"] and len(p["instructions"]) > 80:
                instr_preview += "…"
            modified = p["last_modified"] if p["last_modified"] else "—"
            edit_js = (
                f"editMtProtocol({p['id']}, {_js_str(p['name'])}, "
                f"{p['org_id'] or 'null'}, {_js_str(p['instructions'] or '')}, "
                f"{1 if p['is_active'] else 0})"
            )
            out += f"""
            <tr>
                <td><strong>{p['name']}</strong></td>
                <td>{org_label}</td>
                <td style="color:{status_color};font-weight:500;">{status_label}</td>
                <td style="font-size:0.9em;color:var(--muted);">{instr_preview}</td>
                <td>{modified}</td>
                <td>
                    <div style="display:flex;gap:6px;">
                        <button class="btn btn-secondary btn-small" onclick="{edit_js}">Edit</button>
                        <form method="POST" action="/mt/protocols/delete/{p['id']}" style="display:inline;"
                              onsubmit="return confirm('Delete this protocol template?')">
                            <button type="submit" class="btn btn-danger btn-small">Delete</button>
                        </form>
                    </div>
                </td>
            </tr>"""
        return out

    def _org_options(selected_id=None):
        out = '<option value="">Global (all orgs)</option>'
        for o in orgs:
            sel = 'selected' if selected_id and o["id"] == selected_id else ''
            out += f'<option value="{o["id"]}" {sel}>{o["name"]}</option>'
        return out

    rows_html = _proto_rows_html()
    org_options = _org_options()

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Protocol Templates - MT Dashboard</title>
    <link rel="stylesheet" href="/static/css/site.css">
    <style>
        .page-title {{ font-size: 2.2em; color: white; margin-bottom: 8px; }}
        .page-subtitle {{ color: var(--muted); font-size: 1.1em; margin-bottom: 24px; }}
        .topbar {{ display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }}
        .section-card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            padding: 24px;
            border-radius: 10px;
            margin-bottom: 28px;
        }}
        .section-card h3 {{ margin-top: 0; color: rgba(255,255,255,0.9); }}
        .form-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 14px; }}
        .form-group {{ display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 200px; }}
        .form-group label {{ font-size: 0.9em; color: rgba(255,255,255,0.7); font-weight: 500; }}
        .form-group input, .form-group select, .form-group textarea {{
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 6px;
            color: #fff;
            padding: 9px 12px;
            font-size: 0.95em;
            color-scheme: dark;
        }}
        .form-group select option {{
            background: #1a1d27;
            color: #fff;
        }}
        .form-group textarea {{ resize: vertical; min-height: 90px; }}
        .proto-table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
        .proto-table th {{ padding:12px 10px; text-align:left; background:rgba(255,255,255,0.05);
                           border-bottom:1px solid rgba(31,111,235,0.3); font-size:0.85em; text-transform:uppercase; letter-spacing:0.5px; }}
        .proto-table td {{ padding:12px 10px; border-bottom:1px solid rgba(255,255,255,0.05); vertical-align:top; }}
        .modal-overlay {{
            display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7);
            z-index:1000; align-items:center; justify-content:center;
        }}
        .modal-overlay.open {{ display:flex; }}
        .modal-box {{
            background:#1a1d27; border:1px solid var(--card-border);
            border-radius:12px; padding:28px; width:100%; max-width:560px;
        }}
        .modal-box h3 {{ margin-top:0; color:white; }}
        .modal-footer {{ display:flex; gap:10px; justify-content:flex-end; margin-top:18px; }}
    </style>
</head>
<body>
<div class="container">
    <div class="brand-wrap">
        <img class="brand-logo" src="{LOGO_DARK_URL}" alt="Lumos Lab" onerror="this.style.display='none';"
             style="width:180px;max-width:100%;height:auto;border-radius:8px;display:block;margin-bottom:10px;">
    </div>
    <h1 class="page-title">Protocol Templates</h1>
    <p class="page-subtitle">Define and manage imaging protocol templates for each organisation.</p>

    <div class="topbar">
        <a href="/mt" class="btn secondary">&larr; Back to Dashboard</a>
        <a href="/logout" class="btn secondary">Logout</a>
    </div>

    <!-- Add Protocol Form -->
    <div class="section-card">
        <h3>Add New Protocol Template</h3>
        <form method="POST" action="/mt/protocols/add">
            <div class="form-row">
                <div class="form-group">
                    <label>Protocol Name</label>
                    <input type="text" name="name" required placeholder="e.g., CT Head Standard">
                </div>
                <div class="form-group">
                    <label>Organisation</label>
                    <select name="org_id">
                        {org_options}
                    </select>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group" style="flex:1;">
                    <label>Instructions <span style="color:var(--muted);font-weight:400;">(optional)</span></label>
                    <textarea name="instructions" placeholder="Detailed instructions for radiologists using this protocol..."></textarea>
                </div>
            </div>
            <div style="display:flex;gap:10px;align-items:center;">
                <button type="submit" class="btn btn-primary">Add Protocol</button>
                <label style="display:flex;align-items:center;gap:6px;font-size:0.9em;color:rgba(255,255,255,0.7);cursor:pointer;">
                    <input type="checkbox" name="is_active" value="1" checked style="width:auto;"> Active
                </label>
            </div>
        </form>
    </div>

    <!-- Protocol List -->
    <div class="section-card">
        <h3>All Protocol Templates ({len(protocols)})</h3>
        <table class="proto-table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Organisation</th>
                    <th>Status</th>
                    <th>Instructions Preview</th>
                    <th>Last Modified</th>
                    <th style="width:140px;">Actions</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>
</div>

<!-- Edit Modal -->
<div id="editModal" class="modal-overlay">
    <div class="modal-box">
        <h3>Edit Protocol Template</h3>
        <form method="POST" id="editProtoForm">
            <div class="form-row">
                <div class="form-group">
                    <label>Protocol Name</label>
                    <input type="text" id="editProtoName" name="name" required>
                </div>
                <div class="form-group">
                    <label>Organisation</label>
                    <select id="editProtoOrg" name="org_id">
                        {org_options}
                    </select>
                </div>
            </div>
            <div class="form-group" style="margin-bottom:14px;">
                <label>Instructions</label>
                <textarea id="editProtoInstr" name="instructions" rows="5"></textarea>
            </div>
            <label style="display:flex;align-items:center;gap:8px;font-size:0.9em;color:rgba(255,255,255,0.7);cursor:pointer;margin-bottom:14px;">
                <input type="checkbox" id="editProtoActive" name="is_active" value="1" style="width:auto;"> Active
            </label>
            <div class="modal-footer">
                <button type="button" class="btn secondary" onclick="closeEditModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Save Changes</button>
            </div>
        </form>
    </div>
</div>

<script>
function editMtProtocol(id, name, orgId, instructions, isActive) {{
    document.getElementById('editProtoName').value = name;
    document.getElementById('editProtoInstr').value = instructions;
    document.getElementById('editProtoActive').checked = (isActive === 1);
    var sel = document.getElementById('editProtoOrg');
    for (var i = 0; i < sel.options.length; i++) {{
        sel.options[i].selected = (orgId && sel.options[i].value == orgId);
        if (!orgId && sel.options[i].value === '') {{ sel.options[i].selected = true; }}
    }}
    document.getElementById('editProtoForm').action = '/mt/protocols/edit/' + id;
    document.getElementById('editModal').classList.add('open');
}}
function closeEditModal() {{
    document.getElementById('editModal').classList.remove('open');
}}
document.getElementById('editModal').addEventListener('click', function(e) {{
    if (e.target === this) closeEditModal();
}});
</script>
</body>
</html>"""

    return HTMLResponse(content=html)


def _js_str(s: str) -> str:
    """Escape a Python string for safe inline JS string literal (single-quoted)."""
    import json
    return json.dumps(s)


@app.post("/mt/protocols/add")
def mt_protocols_add(
    request: Request,
    name: str = Form(...),
    org_id: str = Form(""),
    instructions: str = Form(""),
    is_active: str = Form(""),
):
    """Superuser: Add a new protocol template"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt/protocols")

    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")

    org_id_val = int(org_id) if org_id.strip().isdigit() else None
    active = 1 if is_active == "1" else 0

    conn = get_db()
    if org_id_val:
        conn.execute(
            "INSERT INTO protocols (name, instructions, is_active, org_id, last_modified) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), instructions.strip() or None, active, org_id_val, datetime.now().isoformat()),
        )
    else:
        conn.execute(
            "INSERT INTO protocols (name, instructions, is_active, last_modified) VALUES (?, ?, ?, ?)",
            (name.strip(), instructions.strip() or None, active, datetime.now().isoformat()),
        )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/mt/protocols", status_code=303)


@app.post("/mt/protocols/edit/{protocol_id}")
def mt_protocols_edit(
    request: Request,
    protocol_id: int,
    name: str = Form(...),
    org_id: str = Form(""),
    instructions: str = Form(""),
    is_active: str = Form(""),
):
    """Superuser: Edit a protocol template"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt/protocols")

    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")

    org_id_val = int(org_id) if org_id.strip().isdigit() else None
    active = 1 if is_active == "1" else 0

    conn = get_db()
    conn.execute(
        "UPDATE protocols SET name = ?, instructions = ?, is_active = ?, org_id = ?, last_modified = ? WHERE id = ?",
        (name.strip(), instructions.strip() or None, active, org_id_val, datetime.now().isoformat(), protocol_id),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/mt/protocols", status_code=303)


@app.post("/mt/protocols/delete/{protocol_id}")
def mt_protocols_delete(request: Request, protocol_id: int):
    """Superuser: Delete a protocol template"""
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/mt/protocols")

    user = get_session_user(request)
    if not user.get("is_superuser"):
        raise HTTPException(status_code=403, detail="Superuser access required")

    conn = get_db()
    conn.execute("DELETE FROM protocols WHERE id = ?", (protocol_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/mt/protocols", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
