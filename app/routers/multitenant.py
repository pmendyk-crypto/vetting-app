"""
Multi-tenant route handlers and guards.
Provides FastAPI route examples and org-scoping patterns.
"""

from fastapi import APIRouter, Depends, Request, HTTPException, status, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from typing import Optional, List
import sqlite3

from app.models import (
    User, Organisation, Membership, OrgRole,
    create_user, get_user, get_user_by_username, list_memberships_for_user,
    create_membership, get_membership_by_org_user, update_membership,
    list_memberships_for_org, create_organisation, list_organisations,
    get_organisation, create_audit_log, list_audit_logs
)
from app.dependencies import (
    require_login, require_org_context, require_superuser, require_org_admin,
    get_current_user_from_session, get_current_org_id_from_session, set_org_context,
    verify_user_in_org, get_user_org_role, enforce_org_id
)
from app.db import get_db


router = APIRouter()


# ================================================================================
# AUTHENTICATION ROUTES
# ================================================================================

@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Login with username/password and set session."""
    import hashlib
    
    user = get_user_by_username(db_conn, username)
    if not user:
        return HTMLResponse("Invalid username or password", status_code=401)
    
    # Verify password (implement your hashing logic)
    # This is a simplified example
    if not verify_password(password, user.password_hash, user.salt_hex):
        return HTMLResponse("Invalid username or password", status_code=401)
    
    # Get user's organisations
    memberships = list_memberships_for_user(db_conn, user.id, active_only=True)
    if not memberships and not user.is_superuser:
        return HTMLResponse("User has no organisation access", status_code=403)
    
    # Set session
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["is_superuser"] = user.is_superuser
    
    # Auto-select org if only one, otherwise let user choose
    if len(memberships) == 1:
        request.session["current_org_id"] = memberships[0].org_id
        return RedirectResponse("/admin", status_code=302)
    elif user.is_superuser:
        # Let superuser select org on next page
        return RedirectResponse("/select-org", status_code=302)
    else:
        return RedirectResponse("/select-org", status_code=302)


@router.get("/select-org", response_class=HTMLResponse)
async def select_org(
    request: Request,
    current_user: dict = Depends(require_login),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Select an organisation to work in."""
    orgs = []
    
    if current_user["is_superuser"]:
        # Superuser can see all active organisations
        orgs = list_organisations(db_conn, active_only=True)
    else:
        # Regular user sees only their organisations
        memberships = list_memberships_for_user(db_conn, current_user["user_id"], active_only=True)
        for m in memberships:
            org = get_organisation(db_conn, m.org_id)
            if org:
                orgs.append(org)
    
    if not orgs:
        return HTMLResponse("No organisations available", status_code=403)
    
    # Build HTML with org selection form
    html = """
    <html>
    <head><title>Select Organisation</title></head>
    <body>
    <h1>Select Organisation</h1>
    <form method="post">
    """
    
    for org in orgs:
        html += f'<input type="radio" name="org_id" value="{org.id}" required> {org.name}<br>'
    
    html += """
    <br>
    <button type="submit">Continue</button>
    </form>
    </body>
    </html>
    """
    
    return html


@router.post("/select-org")
async def select_org_post(
    request: Request,
    current_user: dict = Depends(require_login),
    org_id: int = Form(...),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Set selected organisation in session."""
    org = get_organisation(db_conn, org_id)
    if not org or not org.is_active:
        raise HTTPException(status_code=404, detail="Organisation not found")
    
    # Verify user has access to this org
    if not current_user["is_superuser"]:
        if not verify_user_in_org(db_conn, current_user["user_id"], org_id):
            raise HTTPException(status_code=403, detail="Access denied")
    
    request.session["current_org_id"] = org_id
    return RedirectResponse("/admin", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Logout and clear session."""
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ================================================================================
# SUPERUSER ROUTES (Platform Admin)
# ================================================================================

@router.get("/superuser/organisations", response_class=HTMLResponse)
async def superuser_orgs(
    request: Request,
    current_user: dict = Depends(require_superuser),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Superuser view: List all organisations."""
    orgs = list_organisations(db_conn, active_only=False)
    
    html = """
    <html>
    <head><title>Organisations</title></head>
    <body>
    <h1>Manage Organisations</h1>
    <form method="post" action="/superuser/organisations/create">
        <h2>Create Organisation</h2>
        <input type="text" name="name" placeholder="Name" required>
        <input type="text" name="slug" placeholder="Slug" required>
        <button type="submit">Create</button>
    </form>
    
    <h2>Existing Organisations</h2>
    <table border="1">
    <tr><th>Name</th><th>Slug</th><th>Active</th><th>Actions</th></tr>
    """
    
    for org in orgs:
        status_text = "Active" if org.is_active else "Inactive"
        html += f"""
        <tr>
            <td>{org.name}</td>
            <td>{org.slug}</td>
            <td>{status_text}</td>
            <td>
                <a href="/superuser/organisations/{org.id}/edit">Edit</a>
                <a href="/superuser/organisations/{org.id}/members">Members</a>
            </td>
        </tr>
        """
    
    html += """
    </table>
    </body>
    </html>
    """
    
    return html


@router.post("/superuser/organisations/create")
async def create_org(
    request: Request,
    current_user: dict = Depends(require_superuser),
    name: str = Form(...),
    slug: str = Form(...),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Superuser: Create new organisation."""
    try:
        org_id = create_organisation(db_conn, name, slug, is_active=True)
        
        # Audit log
        create_audit_log(
            db_conn,
            org_id=None,
            user_id=current_user["user_id"],
            action="org_created",
            target_org_id=org_id
        )
        
        return RedirectResponse("/superuser/organisations", status_code=302)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/superuser/organisations/{org_id}/members", response_class=HTMLResponse)
async def superuser_org_members(
    org_id: int,
    request: Request,
    current_user: dict = Depends(require_superuser),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Superuser: Manage members of an organisation."""
    org = get_organisation(db_conn, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    
    memberships = list_memberships_for_org(db_conn, org_id, active_only=False)
    
    html = f"""
    <html>
    <head><title>Members: {org.name}</title></head>
    <body>
    <h1>Members of {org.name}</h1>
    
    <h2>Add Existing User</h2>
    <form method="post" action="/superuser/organisations/{org_id}/members/add">
        <input type="text" name="username" placeholder="Username" required>
        <select name="org_role">
            <option value="org_user">User</option>
            <option value="radiologist">Radiologist</option>
            <option value="org_admin">Admin</option>
        </select>
        <button type="submit">Add</button>
    </form>
    
    <h2>Existing Members</h2>
    <table border="1">
    <tr><th>Username</th><th>Role</th><th>Active</th><th>Actions</th></tr>
    """
    
    for m in memberships:
        user = get_user(db_conn, m.user_id)
        if user:
            status_text = "Yes" if m.is_active else "No"
            html += f"""
            <tr>
                <td>{user.username}</td>
                <td>{m.org_role}</td>
                <td>{status_text}</td>
                <td>
                    <a href="/superuser/organisations/{org_id}/members/{m.id}/edit">Edit</a>
                    <a href="/superuser/organisations/{org_id}/members/{m.id}/remove">Remove</a>
                </td>
            </tr>
            """
    
    html += """
    </table>
    </body>
    </html>
    """
    
    return html


@router.post("/superuser/organisations/{org_id}/members/add")
async def superuser_add_member(
    org_id: int,
    username: str = Form(...),
    org_role: str = Form(...),
    request: Request = None,
    current_user: dict = Depends(require_superuser),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Superuser: Add existing user to organisation."""
    org = get_organisation(db_conn, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    
    user = get_user_by_username(db_conn, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if already a member
    existing = get_membership_by_org_user(db_conn, org_id, user.id)
    if existing:
        raise HTTPException(status_code=400, detail="User already member of this organisation")
    
    try:
        membership_id = create_membership(db_conn, org_id, user.id, org_role)
        
        # Audit log
        create_audit_log(
            db_conn,
            org_id=org_id,
            user_id=current_user["user_id"],
            action="membership_added",
            target_user_id=user.id
        )
        
        return RedirectResponse(f"/superuser/organisations/{org_id}/members", status_code=302)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ================================================================================
# ORG ADMIN ROUTES (Organisation Level)
# ================================================================================

@router.get("/admin/settings/users", response_class=HTMLResponse)
async def org_admin_users(
    request: Request,
    org_admin: tuple = Depends(require_org_admin),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Org admin: Manage users in their organisation."""
    current_user, org_id = org_admin
    org = get_organisation(db_conn, org_id)
    
    memberships = list_memberships_for_org(db_conn, org_id, active_only=False)
    
    html = f"""
    <html>
    <head><title>User Management - {org.name}</title></head>
    <body>
    <h1>Manage Users: {org.name}</h1>
    
    <h2>Create New User</h2>
    <form method="post" action="/admin/settings/users/create">
        <input type="text" name="username" placeholder="Username" required>
        <input type="email" name="email" placeholder="Email" required>
        <input type="password" name="password" placeholder="Password" required>
        <select name="org_role">
            <option value="org_user">User</option>
            <option value="radiologist">Radiologist</option>
            <option value="org_admin">Admin</option>
        </select>
        <button type="submit">Create User</button>
    </form>
    
    <h2>Members</h2>
    <table border="1">
    <tr><th>Username</th><th>Email</th><th>Role</th><th>Active</th><th>Actions</th></tr>
    """
    
    for m in memberships:
        user = get_user(db_conn, m.user_id)
        if user:
            status_text = "Yes" if m.is_active else "No"
            html += f"""
            <tr>
                <td>{user.username}</td>
                <td>{user.email or '-'}</td>
                <td>{m.org_role}</td>
                <td>{status_text}</td>
                <td>
                    <a href="/admin/settings/users/{m.id}/edit">Edit</a>
                    <a href="/admin/settings/users/{m.id}/deactivate">Deactivate</a>
                </td>
            </tr>
            """
    
    html += """
    </table>
    </body>
    </html>
    """
    
    return html


@router.post("/admin/settings/users/create")
async def org_admin_create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    org_role: str = Form(...),
    org_admin: tuple = Depends(require_org_admin),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Org admin: Create new user in their organisation."""
    current_user, org_id = org_admin
    org = get_organisation(db_conn, org_id)
    
    # Check if username already exists
    if get_user_by_username(db_conn, username):
        raise HTTPException(status_code=400, detail="Username already exists")
    
    try:
        # Hash password (implement your hashing logic)
        password_hash, salt_hex = hash_password(password)
        
        # Create user
        user_id = create_user(
            db_conn,
            username=username,
            email=email,
            password_hash=password_hash,
            salt_hex=salt_hex
        )
        
        # Create membership in org
        membership_id = create_membership(db_conn, org_id, user_id, org_role)
        
        # Audit log
        create_audit_log(
            db_conn,
            org_id=org_id,
            user_id=current_user["user_id"],
            action="user_created",
            target_user_id=user_id
        )
        
        return RedirectResponse("/admin/settings/users", status_code=302)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ================================================================================
# ORG-SCOPED DATA ROUTES (Example: Cases)
# ================================================================================

@router.get("/admin/cases", response_class=HTMLResponse)
async def org_cases(
    request: Request,
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """List cases for current organisation."""
    current_user, org_id = org_user
    org = get_organisation(db_conn, org_id)
    
    # IMPORTANT: Always filter by org_id
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT id, patient_first_name, patient_surname, status, created_at
        FROM cases WHERE org_id = ? ORDER BY created_at DESC
        """,
        (org_id,)
    )
    cases = cursor.fetchall()
    
    html = f"""
    <html>
    <head><title>Cases - {org.name}</title></head>
    <body>
    <h1>Cases: {org.name}</h1>
    <table border="1">
    <tr><th>ID</th><th>Patient</th><th>Status</th><th>Created</th><th>Actions</th></tr>
    """
    
    for case in cases:
        html += f"""
        <tr>
            <td>{case[0]}</td>
            <td>{case[1]} {case[2]}</td>
            <td>{case[3]}</td>
            <td>{case[4]}</td>
            <td><a href="/admin/case/{case[0]}">View</a></td>
        </tr>
        """
    
    html += """
    </table>
    </body>
    </html>
    """
    
    return html


@router.get("/admin/case/{case_id}", response_class=HTMLResponse)
async def get_case_detail(
    case_id: str,
    request: Request,
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    """Get case detail (with org_id validation)."""
    current_user, org_id = org_user
    
    # Query with org_id filter - PREVENTS URL GUESSING ATTACKS
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT id, org_id, patient_first_name, patient_surname, status, created_at
        FROM cases WHERE id = ? AND org_id = ?
        """,
        (case_id, org_id)
    )
    case = cursor.fetchone()
    
    # If case doesn't exist OR doesn't belong to current org, return 404
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Validate org_id matches (belt and suspenders)
    enforce_org_id(db_conn, org_id, case[1])
    
    return f"""
    <html>
    <body>
    <h1>Case: {case_id}</h1>
    <p>Patient: {case[2]} {case[3]}</p>
    <p>Status: {case[4]}</p>
    <p>Created: {case[5]}</p>
    </body>
    </html>
    """


# ================================================================================
# HELPER FUNCTIONS (Implement in your app)
# ================================================================================

def hash_password(password: str) -> tuple:
    """Hash a password. Returns (hash, salt)."""
    import hashlib
    import secrets
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return hash_obj.hex(), salt


def verify_password(password: str, password_hash: str, salt_hex: str) -> bool:
    """Verify a password."""
    import hashlib
    computed_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt_hex.encode(), 100000).hex()
    return computed_hash == password_hash
