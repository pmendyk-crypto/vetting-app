from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from starlette.middleware.sessions import SessionMiddleware

from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
import sqlite3
import os
import hashlib
import secrets
import mimetypes
import csv
import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


# -------------------------
# Paths / App
# -------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "hub.db"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            study_description TEXT NOT NULL,
            admin_notes TEXT,
            radiologist TEXT NOT NULL,
            uploaded_filename TEXT,
            stored_filepath TEXT,
            status TEXT NOT NULL,
            protocol TEXT,
            decision TEXT,
            decision_comment TEXT,
            vetted_at TEXT
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
        CREATE TABLE IF NOT EXISTS radiologists (
            name TEXT PRIMARY KEY,
            email TEXT,
            surname TEXT,
            gmc TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            radiologist_name TEXT,
            salt_hex TEXT NOT NULL,
            pw_hash_hex TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS protocols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1
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

    # ensure decision fields exist if you added them later
    if "protocol" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN protocol TEXT")
    if "decision" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN decision TEXT")
    if "decision_comment" not in cols:
        cur.execute("ALTER TABLE cases ADD COLUMN decision_comment TEXT")

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

    if "surname" not in cols:
        cur.execute("ALTER TABLE radiologists ADD COLUMN surname TEXT")
    if "gmc" not in cols:
        cur.execute("ALTER TABLE radiologists ADD COLUMN gmc TEXT")

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
    rows = conn.execute("SELECT name, email, surname, gmc FROM radiologists ORDER BY name").fetchall()
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
    row = conn.execute("SELECT name, email, surname, gmc FROM radiologists WHERE name = ?", (name,)).fetchone()
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
    conn = get_db()
    rows = conn.execute("SELECT name, is_active FROM protocols ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


def create_user(username: str, password: str, role: str, radiologist_name: str | None = None) -> None:
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
        INSERT INTO users(username, role, radiologist_name, salt_hex, pw_hash_hex)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
          role=excluded.role,
          radiologist_name=excluded.radiologist_name,
          salt_hex=excluded.salt_hex,
          pw_hash_hex=excluded.pw_hash_hex
        """,
        (username, role, radiologist_name, salt.hex(), pw_hash.hex()),
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
    rows = conn.execute("SELECT username, role, radiologist_name FROM users ORDER BY username").fetchall()
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


def ensure_seed_data() -> None:
    if not get_setting("sla_hours", ""):
        set_setting("sla_hours", "48")

    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM radiologists").fetchone()
    if row and row["c"] == 0:
        for n in RADIOLOGISTS_SEED:
            conn.execute("INSERT OR IGNORE INTO radiologists(name, email, surname, gmc) VALUES(?, ?, ?, ?)", (n, "", "", ""))
        conn.commit()
    conn.close()

    conn2 = get_db()
    row2 = conn2.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    conn2.close()
    if row2 and row2["c"] == 0:
        create_user("admin", "admin123", "admin", None)


# -------------------------
# Init DB on startup
# -------------------------
init_db()
ensure_cases_schema()
ensure_radiologists_schema()
ensure_seed_data()
ensure_default_protocols()


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
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, role: str = "admin", next: str = "/"):
    if role not in ("admin", "radiologist"):
        role = "admin"
    return templates.TemplateResponse("login.html", {"request": request, "role": role, "next": next, "error": ""})


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("admin"),
    next: str = Form("/"),
):
    if role not in ("admin", "radiologist"):
        role = "admin"

    user = verify_user(username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "role": role, "next": next, "error": "Invalid username or password"},
            status_code=401,
        )

    if user["role"] != role:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "role": role, "next": next, "error": "This account does not have access to that area"},
            status_code=403,
        )

    request.session["user"] = {
        "username": user["username"],
        "role": user["role"],
        "radiologist_name": user["radiologist_name"],
    }

    return RedirectResponse(url="/admin" if role == "admin" else "/radiologist", status_code=303)


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
    tab: str = "all",               # all | pending | vetted
    radiologist: str | None = None,
    q: str | None = None,
):
    try:
        require_admin(request)
    except HTTPException:
        return redirect_to_login("admin", "/admin")

    tab = (tab or "all").strip().lower()
    if tab not in ("all", "pending", "vetted"):
        tab = "all"

    sql = "SELECT * FROM cases WHERE 1=1"
    params: list[str] = []

    if tab == "pending":
        sql += " AND status = ?"
        params.append(STATUS_PENDING)
    elif tab == "vetted":
        sql += " AND status = ?"
        params.append(STATUS_VETTED)

    if radiologist and radiologist.strip():
        sql += " AND radiologist = ?"
        params.append(radiologist.strip())

    if q and q.strip():
        sql += " AND (patient_id LIKE ? OR study_description LIKE ?)"
        like = f"%{q.strip()}%"
        params.extend([like, like])

    sql += " ORDER BY created_at DESC"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    # Dashboard counts (total/pending/vetted)
    conn = get_db()
    counts_rows = conn.execute(
        "SELECT lower(status) AS status, COUNT(*) AS c FROM cases GROUP BY lower(status)"
        ).fetchall()
    conn.close()

    counts = {r["status"]: r["c"] for r in counts_rows}
    pending_count = counts.get("pending", 0)
    vetted_count = counts.get("vetted", 0)
    total_count = pending_count + vetted_count

    sla_hours = int(get_setting("sla_hours", "48"))
    sla_seconds = sla_hours * 3600

    cases: list[dict] = []
    for r in rows:
        d = dict(r)

        created_dt = parse_iso_dt(d.get("created_at"))
        d["created_display"] = created_dt.strftime("%d/%m/%Y %H:%M") if created_dt else (d.get("created_at") or "")

        secs = tat_seconds(d.get("created_at"), d.get("vetted_at"))
        d["tat_display"] = format_tat(secs)

        # SLA breach only applies while pending
        d["sla_breached"] = (d.get("status") == STATUS_PENDING) and (secs > sla_seconds)

        cases.append(d)

    rad_names = [r["name"] for r in list_radiologists()]

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "tab": tab,
            "cases": cases,
            "sla_hours": sla_hours,
            "radiologists": rad_names,
            "selected_radiologist": radiologist or "",
            "q": q or "",
            "current_user": get_session_user(request),
        },
    )


@app.get("/admin.csv")
def admin_dashboard_csv(
    request: Request,
    tab: str = "all",
    radiologist: str | None = None,
    q: str | None = None,
):
    require_admin(request)

    tab = (tab or "all").strip().lower()
    if tab not in ("all", "pending", "vetted"):
        tab = "all"

    sql = "SELECT * FROM cases WHERE 1=1"
    params: list[str] = []

    if tab == "pending":
        sql += " AND status = ?"
        params.append(STATUS_PENDING)
    elif tab == "vetted":
        sql += " AND status = ?"
        params.append(STATUS_VETTED)

    if radiologist and radiologist.strip():
        sql += " AND radiologist = ?"
        params.append(radiologist.strip())

    if q and q.strip():
        sql += " AND (patient_id LIKE ? OR study_description LIKE ?)"
        like = f"%{q.strip()}%"
        params.extend([like, like])

    sql += " ORDER BY created_at DESC"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    def iter_csv():
        buf = io.StringIO()
        w = csv.writer(buf)

        w.writerow(["id", "patient_id", "study_description", "radiologist", "status", "created_at", "vetted_at", "tat_minutes"])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for r in rows:
            d = dict(r)
            secs = tat_seconds(d.get("created_at"), d.get("vetted_at"))
            w.writerow([
                d.get("id", ""),
                d.get("patient_id", ""),
                d.get("study_description", ""),
                d.get("radiologist", ""),
                d.get("status", ""),
                d.get("created_at", ""),
                d.get("vetted_at", ""),
                secs // 60
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
    if tab not in ("all", "pending", "vetted"):
        tab = "all"

    sql = "SELECT * FROM cases WHERE radiologist = ?"
    params: list[str] = [rad_name]

    if tab == "pending":
        sql += " AND status = ?"
        params.append(STATUS_PENDING)
    elif tab == "vetted":
        sql += " AND status = ?"
        params.append(STATUS_VETTED)

    sql += " ORDER BY created_at DESC"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    sla_hours = int(get_setting("sla_hours", "48"))
    sla_seconds = sla_hours * 3600

    cases: list[dict] = []
    for r in rows:
        d = dict(r)
        created_dt = parse_iso_dt(d.get("created_at"))
        d["created_display"] = created_dt.strftime("%d/%m/%Y %H:%M") if created_dt else (d.get("created_at") or "")

        secs = tat_seconds(d.get("created_at"), d.get("vetted_at"))
        d["tat_display"] = format_tat(secs)
        d["sla_breached"] = (d.get("status") == STATUS_PENDING) and (secs > sla_seconds)

        cases.append(d)

    return templates.TemplateResponse(
        "radiologist_dashboard.html",
        {
            "request": request,
            "cases": cases,
            "sla_hours": sla_hours,
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

    sla_hours = get_setting("sla_hours", "48")
    rads = list_radiologists()
    users = list_users()
    rad_names = [r["name"] for r in rads]
    protocols = list_protocol_rows()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "sla_hours": sla_hours,
            "radiologists": rads,
            "users": users,
            "rad_names": rad_names,
            "protocols": protocols,
            "current_user": get_session_user(request),
        },
    )


@app.post("/settings/sla")
def update_sla(request: Request, sla_hours: str = Form(...)):
    require_admin(request)
    try:
        v = int(sla_hours)
        if v <= 0 or v > 999:
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=400, detail="SLA must be a number of hours (1-999)")
    set_setting("sla_hours", str(v))
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/radiologist/add")
def add_radiologist(request: Request, name: str = Form(...), email: str = Form(""), surname: str = Form(""), gmc: str = Form("")):
    require_admin(request)
    upsert_radiologist(name, email, surname, gmc)
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
def update_radiologist(request: Request, name: str = Form(...), email: str = Form("")):
    require_admin(request)
    upsert_radiologist(name, email)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/protocol/add")
def settings_add_protocol(request: Request, name: str = Form(...)):
    require_admin(request)
    upsert_protocol(name)
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
):
    require_admin(request)
    username = username.strip()
    role = role.strip()
    radiologist_name = radiologist_name.strip() or None

    if role == "radiologist" and not radiologist_name:
        raise HTTPException(status_code=400, detail="Radiologist user must be linked to a radiologist name")

    create_user(username, password, role, radiologist_name)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/user/delete")
def remove_user(request: Request, username: str = Form(...)):
    require_admin(request)
    if username.strip() == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete admin user")
    delete_user(username.strip())
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

    rad_names = [r["name"] for r in list_radiologists()]
    return templates.TemplateResponse("submit.html", {"request": request, "radiologists": rad_names})


@app.post("/submit")
async def submit_case(
    request: Request,
    patient_id: str = Form(...),
    study_description: str = Form(...),
    admin_notes: str = Form(""),
    radiologist: str = Form(...),
    attachment: UploadFile | None = File(None),
):
    require_admin(request)

    valid_rads = {r["name"] for r in list_radiologists()}
    if radiologist not in valid_rads:
        raise HTTPException(status_code=400, detail="Invalid radiologist selection")

    case_id = str(uuid4())
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
            id, created_at, patient_id, study_description, admin_notes,
            radiologist, uploaded_filename, stored_filepath, status, vetted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            created_at,
            patient_id.strip(),
            study_description.strip(),
            admin_notes.strip(),
            radiologist.strip(),
            original_name,
            stored_path,
            STATUS_PENDING,
            None,
        ),
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/submitted/{case_id}", status_code=303)


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
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    if row["radiologist"] != rad_name:
        raise HTTPException(status_code=403, detail="Not your case")

    return templates.TemplateResponse(
        "vet.html",
        {
            "request": request,
            "case": row,
            "decisions": DECISIONS,
            "protocols": list_protocols(active_only=True),
        },
    )


@app.post("/vet/{case_id}")
def vet_submit(
    request: Request,
    case_id: str,
    protocol: str = Form(...),
    decision: str = Form(...),
    decision_comment: str = Form(""),
):
    user = require_radiologist(request)
    rad_name = user.get("radiologist_name")

    if decision not in DECISIONS:
        raise HTTPException(status_code=400, detail="Invalid decision")

    conn = get_db()
    row = conn.execute("SELECT radiologist FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Case not found")
    if row["radiologist"] != rad_name:
        conn.close()
        raise HTTPException(status_code=403, detail="Not your case")

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
        (STATUS_VETTED, protocol.strip(), decision, decision_comment.strip(), utc_now_iso(), case_id),
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
        c.drawString(170, y, value or "")
        y -= 18

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Vetting Summary")
    y -= 30

    line("Case ID", row["id"])
    line("Created (UTC)", row["created_at"])
    line("Patient ID", row["patient_id"])
    line("Study description", row["study_description"])
    line("Radiologist", row["radiologist"])
    line("Admin notes", row["admin_notes"] or "")
    line("Attachment", row["uploaded_filename"] or "None")
    line("Status", row["status"])
    line("Protocol", row["protocol"] or "")
    line("Decision", row["decision"] or "")
    line("Decision comment", row["decision_comment"] or "")
    line("Vetted at (UTC)", row["vetted_at"] or "")

    c.showPage()
    c.save()

    return FileResponse(str(pdf_path), filename=f"vetting_{case_id}.pdf")
