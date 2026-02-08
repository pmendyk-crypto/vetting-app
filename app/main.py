from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse, StreamingResponse
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
from datetime import datetime, timezone
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

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


# -------------------------
# Paths / App
# -------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("DB_PATH", str(BASE_DIR / "hub.db")))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)

# Log paths at startup for debugging persistence issues
print(f"[startup] BASE_DIR={BASE_DIR}, DB_PATH={DB_PATH}, UPLOAD_DIR={UPLOAD_DIR}")

# -------------------------
# Helper Functions
# -------------------------
def generate_case_id() -> str:
    """Generate a unique readable case ID in format: YYYYMMDD-XXXX"""
    date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{date_prefix}-{random_suffix}"

app = FastAPI(title="Vetting App")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

APP_SECRET = os.environ.get("APP_SECRET", "dev-secret-change-me")
SESSION_TIMEOUT_MINUTES = 30  # Session expires after 30 minutes of inactivity

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
                    try:
                        res = self._conn.execute(text(sql_named), param_map)
                        return SAResult(res)
                    except SQLAlchemyError:
                        return SAResult(self._conn.execute(text(sql)))
                else:
                    # assume dict or none
                    if isinstance(params, (list, tuple)):
                        # convert to positional mapping p0..pn
                        param_map = {f"p{i}": v for i, v in enumerate(params)}
                        try:
                            return SAResult(self._conn.execute(text(sql), param_map))
                        except SQLAlchemyError:
                            return SAResult(self._conn.execute(text(sql)))
                    else:
                        return SAResult(self._conn.execute(text(sql), params or {}))

            def commit(self):
                try:
                    self._trans.commit()
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
                org_id INTEGER
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
    if "institution_id" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN institution_id INTEGER")

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

    conn.commit()
    conn.close()


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
    from datetime import datetime
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
        # Format last_modified as DD-MM-YYYY HH:MM
        if d.get("last_modified"):
            try:
                dt = datetime.fromisoformat(d["last_modified"])
                d["last_modified"] = dt.strftime("%d-%m-%Y %H:%M")
            except:
                pass
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
    # Ensure superadmin always exists for multi-tenant oversight
    if normalized_username.lower() == "superadmin":
        normalized_username = "superadmin"
        ensure_superadmin_user()

        # Allow fixed superadmin credentials for dashboard access
        normalized_password = " ".join(password.split())
        if normalized_password == "admin 111" or normalized_password == "admin111":
            conn = get_db()
            row = conn.execute("SELECT * FROM users WHERE username = ?", (normalized_username,)).fetchone()
            conn.close()
            if row:
                user_dict = dict(row)
                row_keys = row.keys()
                if "is_superuser" in row_keys:
                    user_dict["role"] = "admin"
                    user_dict["is_superuser"] = True
                    user_dict["radiologist_name"] = None
                return user_dict

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
    Username: superadmin
    Password: admin 111
    """
    username = "superadmin"
    password = "admin 111"
    email = "superadmin@lumoslab.com"
    now = utc_now_iso()

    if table_has_column("users", "password_hash") and table_has_column("users", "is_superuser"):
        conn = get_db()
        salt = secrets.token_bytes(16)
        pw_hash = hash_password(password, salt)
        conn.execute(
            """
            INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at)
            VALUES(?, ?, ?, ?, 1, 1, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
              email=excluded.email,
              password_hash=excluded.password_hash,
              salt_hex=excluded.salt_hex,
              is_superuser=1,
              is_active=1,
              modified_at=excluded.modified_at
            """,
            (username, email, pw_hash.hex(), salt.hex(), now, now),
        )
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
    if org_id and table_has_column("institutions", "org_id"):
        rows = conn.execute(
            "SELECT id, name, sla_hours, created_at, modified_at FROM institutions WHERE org_id = ? ORDER BY name",
            (org_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, name, sla_hours, created_at, modified_at FROM institutions ORDER BY name").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        # Format created_at as DD-MM-YYYY HH:MM (Bug 2: Add timestamps)
        if d.get("created_at"):
            try:
                dt = parse_iso_dt(d["created_at"])
                if dt:
                    d["created_at"] = dt.strftime("%d-%m-%Y %H:%M")
            except:
                pass
        # Format modified_at as DD-MM-YYYY HH:MM (Bug 2: Add timestamps)
        if d.get("modified_at"):
            try:
                dt = parse_iso_dt(d["modified_at"])
                if dt:
                    d["modified_at"] = dt.strftime("%d-%m-%Y %H:%M")
            except:
                pass
        else:
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
    """Get current user from session with expiration check"""
    user = request.session.get("user")
    if not user:
        return None
    
    # Check if session has login timestamp and if it's expired
    login_time = request.session.get("login_time")
    if login_time:
        try:
            import time
            current_time = time.time()
            # Session timeout = 30 minutes of inactivity
            if current_time - login_time > SESSION_TIMEOUT_MINUTES * 60:
                request.session.clear()
                return None
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


def require_admin(request: Request) -> dict:
    user = require_login(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_radiologist(request: Request) -> dict:
    user = require_login(request)
    if user.get("role") != "radiologist":
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
    ensure_seed_data()
    ensure_superadmin_user()
    ensure_default_protocols()
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
def landing(request: Request):
    user = get_session_user(request)
    if user:
        if user.get("is_superuser"):
            return RedirectResponse(url="/mt", status_code=303)
        if user.get("role") == "admin":
            return RedirectResponse(url="/admin", status_code=303)
        return RedirectResponse(url="/radiologist", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # Redirect to home if already logged in
    user = get_session_user(request)
    if user:
        if user.get("is_superuser"):
            return RedirectResponse(url="/mt", status_code=303)
        if user.get("role") == "admin":
            return RedirectResponse(url="/admin", status_code=303)
        return RedirectResponse(url="/radiologist", status_code=303)
    return RedirectResponse(url="/", status_code=303)


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
def forgot_password_submit(request: Request, role: str = Form("admin"), username: str = Form(...)):
    role = (role or "admin").strip().lower()
    if role not in ("admin", "radiologist"):
        role = "admin"

    return templates.TemplateResponse(
        "forgot_password.html",
        {"request": request, "role": role, "submitted": True},
    )


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
        d["created_display"] = created_dt.strftime("%d/%m/%Y %H:%M") if created_dt else ""

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

    def iter_csv():
        buf = io.StringIO()
        w = csv.writer(buf)

        w.writerow(["ID", "Status", "Created", "Patient First", "Patient Surname", "Referral ID", "Institution", "Study", "Radiologist", "TAT (mins)", "Vetted At"])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for r in rows:
            d = dict(r)
            secs = tat_seconds(d.get("created_at"), d.get("vetted_at"))
            w.writerow([
                d.get("id", ""),
                d.get("status", ""),
                d.get("created_at", ""),
                d.get("patient_first_name", ""),
                d.get("patient_surname", ""),
                d.get("patient_referral_id", ""),
                d.get("institution_name", ""),
                d.get("study_description", ""),
                d.get("radiologist", ""),
                secs // 60,
                d.get("vetted_at", ""),
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = f"cases_{tab}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(iter_csv(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/admin/case/{case_id}", response_class=HTMLResponse)
def admin_case_view(request: Request, case_id: str):
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
    conn.close()
    if not row:
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

    return templates.TemplateResponse("admin_case.html", {"request": request, "case": row})

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
            "case": case,
            "institutions": institutions,
            "radiologists": radiologists,
            "protocols": [p["protocol"] for p in protocols] if protocols else [],
        }
    )

@app.post("/admin/case/{case_id}/edit")
def admin_case_edit_save(
    request: Request,
    case_id: str,
    patient_first_name: str = Form(""),
    patient_surname: str = Form(""),
    patient_referral_id: str = Form(""),
    institution_id: str = Form(""),
    study_description: str = Form(""),
    admin_notes: str = Form(""),
    radiologist: str = Form(""),
    protocol: str = Form(""),
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

    # Update case with new values
    conn.execute(
        """UPDATE cases 
           SET patient_first_name = ?, patient_surname = ?, patient_referral_id = ?, 
               institution_id = ?, study_description = ?, admin_notes = ?, 
               radiologist = ?, protocol = ?
           WHERE id = ?""",
        (
            patient_first_name.strip(),
            patient_surname.strip(),
            patient_referral_id.strip(),
            institution_id.strip() or None,
            study_description.strip(),
            admin_notes.strip(),
            radiologist.strip() or None,
            protocol.strip() or None,
            case_id
        )
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/admin/case/{case_id}", status_code=303)


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
        d["created_display"] = created_dt.strftime("%d/%m/%Y %H:%M") if created_dt else (d.get("created_at") or "")

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
def settings_page(request: Request):
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
            conn.execute(
                "INSERT OR REPLACE INTO protocols (name, institution_id, instructions, last_modified, is_active, org_id) VALUES (?, ?, ?, ?, ?, ?)",
                (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), 1, org_id)
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO protocols (name, institution_id, instructions, last_modified, is_active) VALUES (?, ?, ?, ?, ?)",
                (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), 1)
            )
        conn.commit()
    except Exception as e:
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
            if using_postgres():
                user_row = conn.execute(
                    """
                    INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at, first_name, surname)
                    VALUES(?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (username, email.strip(), pw_hash.hex(), salt.hex(), now, now, first_name.strip(), surname.strip()),
                ).fetchone()
                user_id = user_row["id"] if isinstance(user_row, dict) else user_row[0]
            else:
                conn.execute(
                    """
                    INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at, first_name, surname)
                    VALUES(?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                    """,
                    (username, email.strip(), pw_hash.hex(), salt.hex(), now, now, first_name.strip(), surname.strip()),
                )

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
    
    if table_has_column("users", "is_superuser"):
        # Multi-tenant schema
        conn = get_db()
        if password.strip():
            salt = secrets.token_bytes(16)
            pw_hash = hash_password(password, salt)
            conn.execute(
                "UPDATE users SET first_name = ?, surname = ?, email = ?, password_hash = ?, salt_hex = ? WHERE username = ?",
                (first_name.strip(), surname.strip(), email.strip(), pw_hash.hex(), salt.hex(), username)
            )
        else:
            conn.execute(
                "UPDATE users SET first_name = ?, surname = ?, email = ? WHERE username = ?",
                (first_name.strip(), surname.strip(), email.strip(), username)
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
            conn.execute(
                "UPDATE users SET first_name = ?, surname = ?, email = ?, role = ?, radiologist_name = ?, salt_hex = ?, pw_hash_hex = ? WHERE username = ?",
                (first_name.strip(), surname.strip(), email.strip(), role, radiologist_name, salt.hex(), pw_hash.hex(), username)
            )
        else:
            conn = get_db()
            conn.execute(
                "UPDATE users SET first_name = ?, surname = ?, email = ?, role = ?, radiologist_name = ? WHERE username = ?",
                (first_name.strip(), surname.strip(), email.strip(), role, radiologist_name, username)
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
# Admin submit
# -------------------------
@app.get("/submit", response_class=HTMLResponse)
def submit_form(request: Request):
    try:
        user = require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/submit")

    org_id = user.get("org_id")
    institutions = list_institutions(org_id)
    radiologists = list_radiologists(org_id)
    return templates.TemplateResponse(
        "submit.html",
        {
            "request": request,
            "institutions": institutions,
            "radiologists": radiologists,
        },
    )


@app.post("/submit")
async def submit_case(
    request: Request,
    patient_first_name: str = Form(...),
    patient_surname: str = Form(...),
    patient_referral_id: str = Form(...),
    institution_id: str = Form(...),
    study_description: str = Form(...),
    admin_notes: str = Form(""),
    radiologist: str = Form(""),
    attachment: UploadFile | None = File(...),
    action: str = Form("submit"),
):
    user = require_admin(request)
    org_id = user.get("org_id")
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

    # Validate radiologist (optional - can assign later via bulk assignment)
    radiologist = radiologist.strip() if radiologist else ""
    if radiologist:
        valid_rads = {r["name"] for r in list_radiologists(org_id)}
        if radiologist not in valid_rads:
            raise HTTPException(status_code=400, detail="Invalid radiologist selection")

    # Validate attachment is provided
    if not attachment or not attachment.filename:
        raise HTTPException(status_code=400, detail="Attachment is required")

    case_id = generate_case_id()
    stored_path: str | None = None
    original_name: str | None = None

    if attachment and attachment.filename:
        original_name = attachment.filename
        safe_name = f"{case_id}_{Path(original_name).name}"
        stored_path = str(UPLOAD_DIR / safe_name)

        file_bytes = await attachment.read()
        with open(stored_path, "wb") as f:
            f.write(file_bytes)

    created_at = utc_now_iso()

    conn = get_db()
    conn.execute(
        """
        INSERT INTO cases (
            id, created_at, patient_first_name, patient_surname, patient_referral_id,
            institution_id, study_description, admin_notes,
            radiologist, uploaded_filename, stored_filepath, status, vetted_at, org_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            created_at,
            patient_first_name.strip(),
            patient_surname.strip(),
            patient_referral_id.strip(),
            inst_id,
            study_description.strip(),
            admin_notes.strip(),
            radiologist,
            original_name,
            stored_path,
            "pending",
            None,
            org_id,
        ),
    )
    conn.commit()
    conn.close()

    # If action is "submit_another", redirect back to form; otherwise go to admin dashboard
    if action == "submit_another":
        return RedirectResponse(url="/submit", status_code=303)
    else:
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
# Vet (radiologist)
# -------------------------
@app.get("/vet/{case_id}", response_class=HTMLResponse)
def vet_form(request: Request, case_id: str):
    user = require_radiologist(request)
    rad_name = user.get("radiologist_name")
    org_id = user.get("org_id")

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

    return templates.TemplateResponse(
        "vet.html",
        {
            "request": request,
            "case": case,
            "decisions": DECISIONS,
            "protocols": protocols,
        },
    )


@app.post("/vet/{case_id}")
def vet_submit(
    request: Request,
    case_id: str,
    protocol: str = Form(""),
    decision: str = Form(...),
    decision_comment: str = Form(""),
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
            vetted_at = ?
        WHERE id = ?
        """,
        (case_status, protocol.strip(), decision, decision_comment.strip(), utc_now_iso(), case_id),
    )
    conn.commit()
    conn.close()

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
        "SELECT stored_filepath, uploaded_filename, radiologist FROM cases WHERE id = ?",
        (case_id,),
    ).fetchone()
    conn.close()

    if not row or not row["stored_filepath"]:
        raise HTTPException(status_code=404, detail="No attachment found")

    if user["role"] == "radiologist" and row["radiologist"] != user.get("radiologist_name"):
        raise HTTPException(status_code=403, detail="Not your case")

    path = row["stored_filepath"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File missing on disk")

    return FileResponse(path, filename=row["uploaded_filename"] or Path(path).name)


@app.get("/case/{case_id}/attachment/inline")
def view_attachment_inline(request: Request, case_id: str):
    user = require_login(request)

    conn = get_db()
    row = conn.execute(
        "SELECT stored_filepath, uploaded_filename, radiologist FROM cases WHERE id = ?",
        (case_id,),
    ).fetchone()
    conn.close()

    if not row or not row["stored_filepath"]:
        raise HTTPException(status_code=404, detail="No attachment found")

    if user["role"] == "radiologist" and row["radiologist"] != user.get("radiologist_name"):
        raise HTTPException(status_code=403, detail="Not your case")

    path = row["stored_filepath"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File missing on disk")

    filename = row["uploaded_filename"] or Path(path).name
    media_type, _ = mimetypes.guess_type(filename)
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}

    return FileResponse(path, media_type=media_type or "application/octet-stream", headers=headers)


@app.get("/case/{case_id}/pdf")
def case_pdf(request: Request, case_id: str, inline: bool = False):
    try:
        user = require_login(request)

        conn = get_db()
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Case not found")

        if user["role"] == "radiologist" and row["radiologist"] != user.get("radiologist_name"):
            raise HTTPException(status_code=403, detail="Not your case")

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
            if not iso_string:
                return ""
            try:
                dt = parse_iso_dt(iso_string)
                if dt:
                    return dt.strftime("%d-%m-%Y %H:%M")
                return ""
            except:
                return ""

        # Bug 8: Convert row to dict to avoid sqlite3.Row.get() issues
        if isinstance(row, dict):
            case_data = row
        else:
            case_data = dict(row)

        # Get radiologist details (for GNC number)
        rad_name = case_data.get("radiologist", "")
        rad_gmc = ""
        if rad_name:
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

        line("Case ID", case_data.get("id", ""))
        
        # Created timestamp in DD-MM-YYYY HH:MM format
        created_formatted = format_datetime(case_data.get("created_at", ""))
        line("Created", created_formatted)

        # Patient Information
        patient_name = f"{case_data.get('patient_first_name') or ''} {case_data.get('patient_surname') or ''}".strip() or "N/A"
        line("Patient Name", patient_name)
        
        if case_data.get("patient_referral_id"):
            line("Referral ID", case_data.get("patient_referral_id", ""))

        # Institution
        line("Institution", institution_name or "N/A")

        # Radiologist
        line("Radiologist", rad_name or "N/A")

        # GNC Number (if available)
        if rad_gmc:
            line("GMC/GNC Number", rad_gmc)

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
    except Exception as e:
        print(f"PDF generation error: {e}")


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
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="page-title">Multi-Tenant Management Dashboard</h1>
            <p class="page-subtitle">Welcome, <strong>{user['username']}</strong> (Superuser)</p>
            
            <div class="topbar">
                <a href="/logout" class="btn secondary">Logout</a>
                <a href="/mt/create-org" class="btn">Create Organisation</a>
                <a href="/mt/users" class="btn">View All Superusers</a>
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
        </style>
    </head>
    <body>
        <div class="container">
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

        if using_postgres():
            user_row = conn.execute(
                """
                INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at, first_name, surname)
                VALUES(?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                RETURNING id
                """,
                (username, email, pw_hash.hex(), salt.hex(), now, now, first_name, surname),
            ).fetchone()
            user_id = user_row["id"] if isinstance(user_row, dict) else user_row[0]
        else:
            conn.execute(
                """
                INSERT INTO users(username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at, first_name, surname)
                VALUES(?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                """,
                (username, email, pw_hash.hex(), salt.hex(), now, now, first_name, surname),
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
            <h1 class="page-title">🏥 {org['name']}</h1>
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
