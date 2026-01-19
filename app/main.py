from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from starlette.middleware.sessions import SessionMiddleware

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
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET, same_site="lax")

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


def init_db() -> None:
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


def ensure_radiologists_schema() -> None:
    """
    Safe schema upgrades for the radiologists table.
    """
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
def list_radiologists() -> list[dict]:
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
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM protocols").fetchone()
    if row and row["c"] == 0:
        for p in DEFAULT_PROTOCOLS:
            conn.execute("INSERT OR IGNORE INTO protocols(name, is_active) VALUES(?, 1)", (p,))
        conn.commit()
    conn.close()


def list_protocols(active_only: bool = True) -> list[str]:
    conn = get_db()
    if active_only:
        rows = conn.execute("SELECT name FROM protocols WHERE is_active = 1 ORDER BY name").fetchall()
    else:
        rows = conn.execute("SELECT name FROM protocols ORDER BY name").fetchall()
    conn.close()
    return [r["name"] for r in rows]


def list_protocol_rows() -> list[dict]:
    from datetime import datetime
    conn = get_db()
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
    conn.execute("INSERT OR IGNORE INTO protocols(name, is_active) VALUES(?, 1)", (name,))
    conn.execute("UPDATE protocols SET is_active = 1 WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def deactivate_protocol(name: str) -> None:
    conn = get_db()
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
    if role not in ("admin", "radiologist"):
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
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    conn.close()
    if not row:
        return None

    salt = bytes.fromhex(row["salt_hex"])
    expected = bytes.fromhex(row["pw_hash_hex"])
    provided = hash_password(password, salt)
    if secrets.compare_digest(provided, expected):
        return dict(row)
    return None


def list_users() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT username, first_name, surname, email, role, radiologist_name FROM users ORDER BY username").fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


# -------------------------
# Init DB on startup
# -------------------------
init_db()
ensure_cases_schema()
ensure_radiologists_schema()
ensure_users_schema()
ensure_protocols_schema()
ensure_seed_data()
ensure_default_protocols()


# -------------------------
# Institutions
# -------------------------
def list_institutions() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT id, name, sla_hours, created_at FROM institutions ORDER BY name").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        # Format created_at as DD-MM-YYYY HH:MM
        if d.get("created_at"):
            try:
                dt = parse_iso_dt(d["created_at"])
                if dt:
                    d["created_at"] = dt.strftime("%d-%m-%Y %H:%M")
            except:
                pass
        result.append(d)
    return result


def get_institution(inst_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT id, name, sla_hours FROM institutions WHERE id = ?", (inst_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_institution(name: str, sla_hours: int) -> int:
    conn = get_db()
    conn.execute(
        "INSERT INTO institutions(name, sla_hours, created_at) VALUES(?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET sla_hours=excluded.sla_hours",
        (name.strip(), sla_hours, utc_now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name.strip(),)).fetchone()
    inst_id = row["id"] if row else None
    conn.close()
    return inst_id


def delete_institution(inst_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM institutions WHERE id = ?", (inst_id,))
    conn.commit()
    conn.close()


# -------------------------
# Auth helpers
# -------------------------
def get_session_user(request: Request) -> dict | None:
    return request.session.get("user")


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
    return user


def redirect_to_login(role: str, next_path: str):
    return RedirectResponse(url=f"/login?role={role}&next={next_path}", status_code=303)


# -------------------------
# Landing + login/logout
# -------------------------
@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    user = get_session_user(request)
    if user:
        if user.get("role") == "admin":
            return RedirectResponse(url="/admin", status_code=303)
        return RedirectResponse(url="/radiologist", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # Redirect to home if already logged in
    user = get_session_user(request)
    if user:
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
    user = verify_user(username, password)
    if not user:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )

    request.session["user"] = {
        "username": user["username"],
        "role": user["role"],
        "radiologist_name": user["radiologist_name"],
    }

    # Auto-route based on user role
    if user["role"] == "admin":
        return RedirectResponse(url="/admin", status_code=303)
    else:
        return RedirectResponse(url="/radiologist", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


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
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/admin")

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
    counts_rows = conn.execute(
        "SELECT LOWER(status) AS status, COUNT(*) AS c FROM cases GROUP BY LOWER(status)"
    ).fetchall()
    conn.close()

    counts = {r["status"]: r["c"] for r in counts_rows}
    pending_count = counts.get("pending", 0)
    vetted_count = counts.get("vetted", 0)
    rejected_count = counts.get("rejected", 0)
    total_count = pending_count + vetted_count + rejected_count

    institutions = list_institutions()
    radiologists = [r["name"] for r in list_radiologists()]

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
    require_admin(request)

    tab = (tab or "all").strip().lower()
    if tab not in ("all", "pending", "vetted", "rejected"):
        tab = "all"

    sql = "SELECT c.*, i.name as institution_name FROM cases c LEFT JOIN institutions i ON c.institution_id = i.id WHERE 1=1"
    params: list = []

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
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", f"/admin/case/{case_id}")

    conn = get_db()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    # Summary counts for dashboard cards
    conn = get_db()
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
    case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    institutions = conn.execute("SELECT id, name FROM institutions ORDER BY name").fetchall()
    radiologists = conn.execute("SELECT name FROM radiologists ORDER BY name").fetchall()
    protocols = conn.execute("SELECT DISTINCT protocol FROM cases WHERE protocol IS NOT NULL AND protocol != '' ORDER BY protocol").fetchall()
    conn.close()
    
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
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
        require_admin(request)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Not authorized")

    conn = get_db()
    case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        conn.close()
        raise HTTPException(status_code=404, detail="Case not found")

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

# -------------------------
# Radiologist dashboard
# -------------------------
@app.get("/radiologist", response_class=HTMLResponse)
def radiologist_dashboard(request: Request, tab: str = "all"):
    try:
        user = require_radiologist(request)
    except HTTPException:
        return redirect_to_login("radiologist", "/radiologist")

    rad_name = user.get("radiologist_name")
    if not rad_name:
        raise HTTPException(status_code=400, detail="Radiologist account not linked to a radiologist name")

    tab = (tab or "all").strip().lower()
    if tab not in ("all", "pending", "vetted", "rejected"):
        tab = "all"

    sql = "SELECT c.*, i.sla_hours FROM cases c LEFT JOIN institutions i ON c.institution_id = i.id WHERE c.radiologist = ?"
    params: list[str] = [rad_name]

    if tab == "pending":
        sql += " AND c.status = ?"
        params.append("pending")
    elif tab == "vetted":
        sql += " AND c.status = ?"
        params.append("vetted")
    elif tab == "rejected":
        sql += " AND c.status = ?"
        params.append("rejected")

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

    institutions = list_institutions()
    rads = list_radiologists()
    users = list_users()
    rad_names = [r["name"] for r in rads]
    protocols = list_protocol_rows()

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
    require_admin(request)
    try:
        sla_val = int(sla_hours)
        if sla_val <= 0 or sla_val > 999:
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=400, detail="SLA must be a number of hours (1-999)")
    
    upsert_institution(name.strip(), sla_val)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/institution/edit/{inst_id}")
def edit_institution(request: Request, inst_id: int, name: str = Form(...), sla_hours: str = Form(...)):
    require_admin(request)
    try:
        sla_val = int(sla_hours)
        if sla_val <= 0 or sla_val > 999:
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=400, detail="SLA must be a number of hours (1-999)")
    
    # Verify institution exists
    inst = get_institution(inst_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")
    
    conn = get_db()
    conn.execute("UPDATE institutions SET name = ?, sla_hours = ? WHERE id = ?", (name.strip(), sla_val, inst_id))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/institution/delete/{inst_id}")
def delete_institution_route(request: Request, inst_id: int):
    require_admin(request)
    inst = get_institution(inst_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")
    
    delete_institution(inst_id)
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
    require_admin(request)
    try:
        inst_id = int(institution_id)
        inst = get_institution(inst_id)
        if not inst:
            raise HTTPException(status_code=400, detail="Invalid institution")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid institution ID")
    
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO protocols (name, institution_id, instructions, last_modified, is_active) VALUES (?, ?, ?, ?, ?)",
        (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), 1)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/protocol/delete")
def settings_delete_protocol(request: Request, name: str = Form(...)):
    require_admin(request)
    deactivate_protocol(name)
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
):
    require_admin(request)
    username = username.strip()
    role = role.strip()
    radiologist_name = radiologist_name.strip() or None

    # Only require radiologist_name for radiologist role
    if role == "radiologist" and not radiologist_name:
        raise HTTPException(status_code=400, detail="Radiologist user must be linked to a radiologist name")
    
    # For admin users, radiologist_name should be None
    if role == "admin":
        radiologist_name = None

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
    require_admin(request)
    username = username.strip()
    role = role.strip()
    radiologist_name = radiologist_name.strip() or None
    
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # If password is provided, hash and update it
    if password.strip():
        salt = secrets.token_bytes(16)
        pw_hash = hash_password(password, salt)
        conn = get_db()
        conn.execute(
            "UPDATE users SET first_name = ?, surname = ?, email = ?, role = ?, radiologist_name = ?, salt_hex = ?, pw_hash_hex = ? WHERE username = ?",
            (first_name.strip(), surname.strip(), email.strip(), role, radiologist_name, salt.hex(), pw_hash.hex(), username)
        )
    else:
        # Just update details without password
        conn = get_db()
        conn.execute(
            "UPDATE users SET first_name = ?, surname = ?, email = ?, role = ?, radiologist_name = ? WHERE username = ?",
            (first_name.strip(), surname.strip(), email.strip(), role, radiologist_name, username)
        )
    
    conn.commit()
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
    require_admin(request)
    try:
        inst_id = int(institution_id)
        inst = get_institution(inst_id)
        if not inst:
            raise HTTPException(status_code=400, detail="Invalid institution")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid institution ID")
    
    conn = get_db()
    conn.execute(
        "UPDATE protocols SET name = ?, institution_id = ?, instructions = ?, last_modified = ? WHERE id = ?",
        (name.strip(), inst_id, instructions.strip(), datetime.now().isoformat(), protocol_id)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/protocol/delete/{protocol_id}")
def delete_protocol_route(request: Request, protocol_id: int):
    require_admin(request)
    conn = get_db()
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
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/submit")

    institutions = list_institutions()
    radiologists = list_radiologists()
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
    radiologist: str = Form(...),
    attachment: UploadFile | None = File(...),
    action: str = Form("submit"),
):
    require_admin(request)

    # Validate institution
    try:
        inst_id = int(institution_id)
        inst = get_institution(inst_id)
        if not inst:
            raise HTTPException(status_code=400, detail="Invalid institution selection")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid institution ID")

    # Validate radiologist
    valid_rads = {r["name"] for r in list_radiologists()}
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
            radiologist, uploaded_filename, stored_filepath, status, vetted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            radiologist.strip(),
            original_name,
            stored_path,
            "pending",
            None,
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
    require_admin(request)
    conn = get_db()
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

    conn = get_db()
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
        proto_rows = conn.execute(
            "SELECT name, instructions FROM protocols WHERE institution_id = ? AND is_active = 1 ORDER BY name",
            (case.get("institution_id"),)
        ).fetchall()
        conn.close()
        protocols = [dict(p) for p in proto_rows]
    else:
        # Fallback to active protocols if no institution
        protocols = list_protocols(active_only=True)

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
def case_pdf(request: Request, case_id: str):
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

        # Convert row to dict to avoid Row.get() issues
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

        y -= 10
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "Vetting Decision")
        y -= 15
        c.setFont("Helvetica", 10)

        # Decision
        line("Decision", case_data.get("decision", "N/A"))

        # Protocol (only if not rejected)
        if case_data.get("decision") != "Reject" and case_data.get("protocol"):
            line("Protocol", case_data.get("protocol", ""))

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

        return FileResponse(str(pdf_path), filename=f"vetting_{case_id}.pdf")
    except Exception as e:
        print(f"PDF generation error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
