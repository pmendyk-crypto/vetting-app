"""
Multi-tenant authentication and authorization dependencies.
Provides FastAPI dependency functions for role checking, org context, and access control.
"""

from fastapi import Depends, Request, HTTPException, status
from typing import Optional, List
import sqlite3

from app.models import User, Membership, Organisation, OrgRole, get_user, get_user_by_username, get_membership, get_organisation, list_memberships_for_user
from app.db import get_db


# ================================================================================
# SESSION HELPERS
# ================================================================================

def get_current_user_from_session(request: Request) -> Optional[dict]:
    """Extract current user info from session. Returns dict with user_id and username."""
    user_id = request.session.get("user_id")
    username = request.session.get("username")
    is_superuser = request.session.get("is_superuser", False)
    
    if not user_id:
        return None
    
    return {
        "user_id": user_id,
        "username": username,
        "is_superuser": is_superuser
    }


def get_current_org_id_from_session(request: Request) -> Optional[int]:
    """Extract current organisation context from session."""
    return request.session.get("current_org_id")


# ================================================================================
# DEPENDENCY FUNCTIONS (for FastAPI Depends)
# ================================================================================

async def require_login(request: Request, db_conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """
    Require user to be logged in.
    Returns dict: {user_id, username, is_superuser}
    Raises 401 if not logged in.
    """
    user_info = get_current_user_from_session(request)
    
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    # Verify user still exists and is active in DB
    user = get_user(db_conn, user_info["user_id"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer active"
        )
    
    return user_info


async def require_org_context(
    request: Request,
    current_user: dict = Depends(require_login),
    db_conn: sqlite3.Connection = Depends(get_db)
) -> tuple:
    """
    Require user to have an active org context in session.
    Returns tuple: (current_user_dict, org_id)
    Raises 400 if no org context set.
    """
    org_id = get_current_org_id_from_session(request)
    
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No organisation context set. Please select an organisation."
        )
    
    # If superuser, org_id is just context preference, allow bypass
    if current_user["is_superuser"]:
        return current_user, org_id
    
    # For normal users, verify they have active membership in this org
    membership = get_membership_by_org_user(db_conn, org_id, current_user["user_id"])
    if not membership or not membership.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organisation"
        )
    
    return current_user, org_id


async def require_superuser(current_user: dict = Depends(require_login)) -> dict:
    """
    Require user to be a superuser.
    Returns current_user dict.
    Raises 403 if not superuser.
    """
    if not current_user.get("is_superuser"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser access required"
        )
    
    return current_user


async def require_org_admin(
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
) -> tuple:
    """
    Require user to be org_admin or superuser in current org.
    Returns tuple: (current_user_dict, org_id)
    Raises 403 if insufficient privileges.
    """
    current_user, org_id = org_user
    
    # Superuser always has org_admin privileges
    if current_user.get("is_superuser"):
        return current_user, org_id
    
    # Check membership role
    membership = get_membership_by_org_user(db_conn, org_id, current_user["user_id"])
    if not membership or not membership.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    if membership.org_role not in [OrgRole.ORG_ADMIN, OrgRole.SUPERUSER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Org admin access required"
        )
    
    return current_user, org_id


async def require_membership_role(
    allowed_roles: List[str],
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
) -> tuple:
    """
    Require user to have one of the specified roles in current org.
    Usage: Depends(lambda: require_membership_role(["org_admin", "radiologist"]))
    Returns tuple: (current_user_dict, org_id)
    Raises 403 if role not in allowed list.
    """
    current_user, org_id = org_user
    
    # Superuser always passes
    if current_user.get("is_superuser"):
        return current_user, org_id
    
    membership = get_membership_by_org_user(db_conn, org_id, current_user["user_id"])
    if not membership or not membership.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    if membership.org_role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"One of these roles required: {', '.join(allowed_roles)}"
        )
    
    return current_user, org_id


# ================================================================================
# ORG SCOPING HELPERS
# ================================================================================

def enforce_org_id(conn: sqlite3.Connection, org_id: int, record_org_id: Optional[int]) -> None:
    """
    Validate that a record belongs to the specified organisation.
    Raises 404 if org_id mismatch.
    """
    if record_org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found"
        )
    
    if record_org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found"
        )


def set_org_context(request: Request, org_id: int, session_commit: bool = True) -> None:
    """Set the current organisation context in session."""
    request.session["current_org_id"] = org_id
    if session_commit:
        # Session is auto-saved by middleware, but this is explicit
        pass


async def get_user_orgs(user_id: int, db_conn: sqlite3.Connection = Depends(get_db)) -> List[Organisation]:
    """Get all organisations a user is a member of."""
    memberships = list_memberships_for_user(db_conn, user_id, active_only=True)
    orgs = []
    for m in memberships:
        org = get_organisation(db_conn, m.org_id)
        if org and org.is_active:
            orgs.append(org)
    return orgs


# ================================================================================
# QUERY SCOPE HELPERS (for use in route handlers)
# ================================================================================

class OrgScope:
    """
    Helper for building org-scoped database queries.
    Ensures all queries filter by org_id.
    """
    
    def __init__(self, org_id: int):
        self.org_id = org_id
    
    def add_org_filter(self, query: str, table_alias: str = "") -> str:
        """Add org_id filter to a WHERE clause."""
        alias = f"{table_alias}." if table_alias else ""
        if " WHERE " in query:
            return query + f" AND {alias}org_id = {self.org_id}"
        else:
            return query + f" WHERE {alias}org_id = {self.org_id}"
    
    def build_select(self, table: str, columns: str = "*", where: str = "", alias: str = "") -> str:
        """Build an org-scoped SELECT query."""
        alias_prefix = f"{alias}." if alias else ""
        base = f"SELECT {columns} FROM {table}"
        if alias:
            base = f"SELECT {columns} FROM {table} AS {alias}"
        
        if where:
            return f"{base} WHERE {alias_prefix}org_id = ? AND ({where})"
        else:
            return f"{base} WHERE {alias_prefix}org_id = ?"
    
    def build_insert_values(self, columns: str, values: str) -> tuple:
        """Helper for building org-scoped INSERT."""
        # Usage: columns = "name, org_id", values = ("My Name", org_scope.org_id)
        return values


# ================================================================================
# COMPATIBILITY HELPERS (for migrating from old code)
# ================================================================================

def get_membership_by_org_user(conn: sqlite3.Connection, org_id: int, user_id: int) -> Optional[Membership]:
    """Get a membership record by org and user."""
    from app.models import get_membership_by_org_user as _get_membership
    return _get_membership(conn, org_id, user_id)


def verify_user_in_org(conn: sqlite3.Connection, user_id: int, org_id: int, 
                       allowed_roles: Optional[List[str]] = None) -> bool:
    """
    Check if user has active membership in org with optional role check.
    Returns True if authorized, False otherwise.
    """
    membership = get_membership_by_org_user(conn, org_id, user_id)
    
    if not membership or not membership.is_active:
        return False
    
    if allowed_roles and membership.org_role not in allowed_roles:
        return False
    
    return True


def get_user_org_role(conn: sqlite3.Connection, user_id: int, org_id: int) -> Optional[str]:
    """Get the org role for a user in a specific organisation."""
    membership = get_membership_by_org_user(conn, org_id, user_id)
    if membership and membership.is_active:
        return membership.org_role
    return None
