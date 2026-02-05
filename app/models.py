"""
Multi-tenant models and CRUD operations.
Defines the data structures and database operations for organisations, users, and memberships.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import sqlite3
from enum import Enum


# ================================================================================
# ENUMS
# ================================================================================

class OrgRole(str, Enum):
    """Allowed roles within an organisation."""
    SUPERUSER = "superuser"  # Platform-wide admin (special, not in membership)
    ORG_ADMIN = "org_admin"   # Admin for a specific organisation
    RADIOLOGIST = "radiologist"  # Medical professional role
    ORG_USER = "org_user"     # Standard user


class AuditAction(str, Enum):
    """Audit log action types."""
    USER_CREATED = "user_created"
    USER_DELETED = "user_deleted"
    USER_ACTIVATED = "user_activated"
    USER_DEACTIVATED = "user_deactivated"
    ROLE_CHANGED = "role_changed"
    ORG_CREATED = "org_created"
    ORG_DISABLED = "org_disabled"
    MEMBERSHIP_ADDED = "membership_added"
    MEMBERSHIP_REMOVED = "membership_removed"


# ================================================================================
# DATA MODELS (dataclasses)
# ================================================================================

@dataclass
class Organisation:
    """An organisation (tenant) in the system."""
    id: int
    name: str
    slug: str
    is_active: bool
    created_at: str
    modified_at: Optional[str] = None


@dataclass
class User:
    """A global user account."""
    id: int
    username: str
    password_hash: str
    salt_hex: str
    is_superuser: bool
    is_active: bool
    email: Optional[str] = None
    created_at: Optional[str] = None
    modified_at: Optional[str] = None


@dataclass
class Membership:
    """A user's membership in an organisation with their role."""
    id: int
    org_id: int
    user_id: int
    org_role: str  # OrgRole enum value
    is_active: bool
    created_at: str
    modified_at: Optional[str] = None


@dataclass
class RadiologistProfile:
    """Optional profile data for radiologist users."""
    id: int
    user_id: int
    gmc: Optional[str] = None
    specialty: Optional[str] = None
    display_name: Optional[str] = None
    created_at: Optional[str] = None
    modified_at: Optional[str] = None


@dataclass
class AuditLog:
    """Audit trail entry for user management actions."""
    id: int
    org_id: Optional[int]
    user_id: Optional[int]
    action: str
    target_user_id: Optional[int] = None
    target_org_id: Optional[int] = None
    details: Optional[str] = None
    created_at: Optional[str] = None


# ================================================================================
# CRUD OPERATIONS
# ================================================================================

def utc_now_iso() -> str:
    """Get current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# ---- ORGANISATIONS ----

def create_organisation(conn: sqlite3.Connection, name: str, slug: str, is_active: bool = True) -> int:
    """Create a new organisation. Returns org_id."""
    now = utc_now_iso()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO organisations (name, slug, is_active, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (name, slug, 1 if is_active else 0, now)
    )
    conn.commit()
    return cursor.lastrowid


def get_organisation(conn: sqlite3.Connection, org_id: int) -> Optional[Organisation]:
    """Fetch organisation by ID."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, slug, is_active, created_at, modified_at FROM organisations WHERE id = ?",
        (org_id,)
    )
    row = cursor.fetchone()
    if row:
        return Organisation(*row)
    return None


def get_organisation_by_slug(conn: sqlite3.Connection, slug: str) -> Optional[Organisation]:
    """Fetch organisation by slug."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, slug, is_active, created_at, modified_at FROM organisations WHERE slug = ?",
        (slug,)
    )
    row = cursor.fetchone()
    if row:
        return Organisation(*row)
    return None


def list_organisations(conn: sqlite3.Connection, active_only: bool = False) -> List[Organisation]:
    """List all organisations."""
    cursor = conn.cursor()
    if active_only:
        cursor.execute(
            "SELECT id, name, slug, is_active, created_at, modified_at FROM organisations WHERE is_active = 1 ORDER BY name"
        )
    else:
        cursor.execute(
            "SELECT id, name, slug, is_active, created_at, modified_at FROM organisations ORDER BY name"
        )
    return [Organisation(*row) for row in cursor.fetchall()]


def update_organisation(conn: sqlite3.Connection, org_id: int, name: Optional[str] = None, 
                       slug: Optional[str] = None, is_active: Optional[bool] = None) -> bool:
    """Update organisation details. Returns success."""
    updates = []
    params = []
    
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if slug is not None:
        updates.append("slug = ?")
        params.append(slug)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)
    
    if not updates:
        return True
    
    updates.append("modified_at = ?")
    params.append(utc_now_iso())
    params.append(org_id)
    
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE organisations SET {', '.join(updates)} WHERE id = ?",
        params
    )
    conn.commit()
    return cursor.rowcount > 0


# ---- USERS ----

def create_user(conn: sqlite3.Connection, username: str, password_hash: str, salt_hex: str,
                email: Optional[str] = None, is_superuser: bool = False) -> int:
    """Create a new user. Returns user_id."""
    now = utc_now_iso()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (username, email, password_hash, salt_hex, is_superuser, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (username, email, password_hash, salt_hex, 1 if is_superuser else 0, 1, now)
    )
    conn.commit()
    return cursor.lastrowid


def get_user(conn: sqlite3.Connection, user_id: int) -> Optional[User]:
    """Fetch user by ID."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, username, password_hash, salt_hex, is_superuser, is_active, email, created_at, modified_at
        FROM users WHERE id = ?
        """,
        (user_id,)
    )
    row = cursor.fetchone()
    if row:
        return User(*row)
    return None


def get_user_by_username(conn: sqlite3.Connection, username: str) -> Optional[User]:
    """Fetch user by username."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, username, password_hash, salt_hex, is_superuser, is_active, email, created_at, modified_at
        FROM users WHERE username = ? AND is_active = 1
        """,
        (username,)
    )
    row = cursor.fetchone()
    if row:
        return User(*row)
    return None


def list_users(conn: sqlite3.Connection, active_only: bool = True) -> List[User]:
    """List all users."""
    cursor = conn.cursor()
    where = "WHERE is_active = 1" if active_only else ""
    cursor.execute(
        f"""
        SELECT id, username, password_hash, salt_hex, is_superuser, is_active, email, created_at, modified_at
        FROM users {where} ORDER BY username
        """
    )
    return [User(*row) for row in cursor.fetchall()]


def update_user(conn: sqlite3.Connection, user_id: int, email: Optional[str] = None,
                is_active: Optional[bool] = None, is_superuser: Optional[bool] = None) -> bool:
    """Update user details. Returns success."""
    updates = []
    params = []
    
    if email is not None:
        updates.append("email = ?")
        params.append(email)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)
    if is_superuser is not None:
        updates.append("is_superuser = ?")
        params.append(1 if is_superuser else 0)
    
    if not updates:
        return True
    
    updates.append("modified_at = ?")
    params.append(utc_now_iso())
    params.append(user_id)
    
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
        params
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_user(conn: sqlite3.Connection, user_id: int) -> bool:
    """Soft-delete a user (mark as inactive). Returns success."""
    return update_user(conn, user_id, is_active=False)


# ---- MEMBERSHIPS ----

def create_membership(conn: sqlite3.Connection, org_id: int, user_id: int, 
                     org_role: str = OrgRole.ORG_USER) -> int:
    """Create a user membership in an organisation. Returns membership_id."""
    now = utc_now_iso()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO memberships (org_id, user_id, org_role, is_active, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (org_id, user_id, org_role, 1, now)
    )
    conn.commit()
    return cursor.lastrowid


def get_membership(conn: sqlite3.Connection, membership_id: int) -> Optional[Membership]:
    """Fetch membership by ID."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, org_id, user_id, org_role, is_active, created_at, modified_at
        FROM memberships WHERE id = ?
        """,
        (membership_id,)
    )
    row = cursor.fetchone()
    if row:
        return Membership(*row)
    return None


def get_membership_by_org_user(conn: sqlite3.Connection, org_id: int, user_id: int) -> Optional[Membership]:
    """Fetch membership for a specific org/user pair."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, org_id, user_id, org_role, is_active, created_at, modified_at
        FROM memberships WHERE org_id = ? AND user_id = ?
        """,
        (org_id, user_id)
    )
    row = cursor.fetchone()
    if row:
        return Membership(*row)
    return None


def list_memberships_for_user(conn: sqlite3.Connection, user_id: int, active_only: bool = True) -> List[Membership]:
    """List all organisations a user is member of."""
    cursor = conn.cursor()
    where = "AND is_active = 1" if active_only else ""
    cursor.execute(
        f"""
        SELECT id, org_id, user_id, org_role, is_active, created_at, modified_at
        FROM memberships WHERE user_id = ? {where} ORDER BY created_at
        """,
        (user_id,)
    )
    return [Membership(*row) for row in cursor.fetchall()]


def list_memberships_for_org(conn: sqlite3.Connection, org_id: int, active_only: bool = True) -> List[Membership]:
    """List all members of an organisation."""
    cursor = conn.cursor()
    where = "AND is_active = 1" if active_only else ""
    cursor.execute(
        f"""
        SELECT id, org_id, user_id, org_role, is_active, created_at, modified_at
        FROM memberships WHERE org_id = ? {where} ORDER BY user_id
        """,
        (org_id,)
    )
    return [Membership(*row) for row in cursor.fetchall()]


def update_membership(conn: sqlite3.Connection, membership_id: int, org_role: Optional[str] = None,
                     is_active: Optional[bool] = None) -> bool:
    """Update membership details. Returns success."""
    updates = []
    params = []
    
    if org_role is not None:
        updates.append("org_role = ?")
        params.append(org_role)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)
    
    if not updates:
        return True
    
    updates.append("modified_at = ?")
    params.append(utc_now_iso())
    params.append(membership_id)
    
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE memberships SET {', '.join(updates)} WHERE id = ?",
        params
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_membership(conn: sqlite3.Connection, membership_id: int) -> bool:
    """Soft-delete a membership (mark as inactive). Returns success."""
    return update_membership(conn, membership_id, is_active=False)


# ---- RADIOLOGIST PROFILES ----

def create_radiologist_profile(conn: sqlite3.Connection, user_id: int, gmc: Optional[str] = None,
                              specialty: Optional[str] = None, display_name: Optional[str] = None) -> int:
    """Create a radiologist profile for a user. Returns profile_id."""
    now = utc_now_iso()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO radiologist_profiles (user_id, gmc, specialty, display_name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, gmc, specialty, display_name, now)
    )
    conn.commit()
    return cursor.lastrowid


def get_radiologist_profile(conn: sqlite3.Connection, user_id: int) -> Optional[RadiologistProfile]:
    """Fetch radiologist profile for a user."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, gmc, specialty, display_name, created_at, modified_at
        FROM radiologist_profiles WHERE user_id = ?
        """,
        (user_id,)
    )
    row = cursor.fetchone()
    if row:
        return RadiologistProfile(*row)
    return None


def update_radiologist_profile(conn: sqlite3.Connection, user_id: int, gmc: Optional[str] = None,
                              specialty: Optional[str] = None, display_name: Optional[str] = None) -> bool:
    """Update radiologist profile. Returns success."""
    updates = []
    params = []
    
    if gmc is not None:
        updates.append("gmc = ?")
        params.append(gmc)
    if specialty is not None:
        updates.append("specialty = ?")
        params.append(specialty)
    if display_name is not None:
        updates.append("display_name = ?")
        params.append(display_name)
    
    if not updates:
        return True
    
    updates.append("modified_at = ?")
    params.append(utc_now_iso())
    params.append(user_id)
    
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE radiologist_profiles SET {', '.join(updates)} WHERE user_id = ?",
        params
    )
    conn.commit()
    return cursor.rowcount > 0


# ---- AUDIT LOGS ----

def create_audit_log(conn: sqlite3.Connection, org_id: Optional[int], user_id: Optional[int],
                    action: str, target_user_id: Optional[int] = None, target_org_id: Optional[int] = None,
                    details: Optional[str] = None) -> int:
    """Log an audit entry. Returns log_id."""
    now = utc_now_iso()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO audit_logs (org_id, user_id, action, target_user_id, target_org_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (org_id, user_id, action, target_user_id, target_org_id, details, now)
    )
    conn.commit()
    return cursor.lastrowid


def list_audit_logs(conn: sqlite3.Connection, org_id: Optional[int] = None, limit: int = 100) -> List[AuditLog]:
    """List audit logs. If org_id provided, filter by that organisation."""
    cursor = conn.cursor()
    if org_id:
        cursor.execute(
            """
            SELECT id, org_id, user_id, action, target_user_id, target_org_id, details, created_at
            FROM audit_logs WHERE org_id = ? ORDER BY created_at DESC LIMIT ?
            """,
            (org_id, limit)
        )
    else:
        cursor.execute(
            """
            SELECT id, org_id, user_id, action, target_user_id, target_org_id, details, created_at
            FROM audit_logs ORDER BY created_at DESC LIMIT ?
            """,
            (limit,)
        )
    return [AuditLog(*row) for row in cursor.fetchall()]
