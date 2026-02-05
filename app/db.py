"""
Database connection helper for multi-tenant app.
Update your existing db.py or create this file.
"""

import sqlite3
from pathlib import Path
import os
from typing import Optional
from sqlalchemy import create_engine

# ================================================================================
# DATABASE CONFIGURATION
# ================================================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("DB_PATH", str(BASE_DIR / "hub.db")))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)

# Log paths at startup
print(f"[startup] BASE_DIR={BASE_DIR}, DB_PATH={DB_PATH}, UPLOAD_DIR={UPLOAD_DIR}")


# ================================================================================
# DATABASE CONNECTION
# ================================================================================

# Global SQLAlchemy engine (for PostgreSQL support)
SA_ENGINE = None


def get_db() -> sqlite3.Connection:
    """
    Get database connection.
    Supports SQLite (default) or PostgreSQL via DATABASE_URL env var.
    
    For FastAPI dependency injection:
        @app.get("/example")
        async def example(db_conn: sqlite3.Connection = Depends(get_db)):
            ...
    """
    database_url = os.environ.get("DATABASE_URL")
    
    if database_url:
        # PostgreSQL mode via SQLAlchemy
        return get_db_sqlalchemy(database_url)
    else:
        # SQLite mode (default)
        return get_db_sqlite()


def get_db_sqlite() -> sqlite3.Connection:
    """Get SQLite connection."""
    if not DB_PATH.exists():
        # Create DB if not exists
        DB_PATH.touch()
    
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def get_db_sqlalchemy(database_url: str) -> sqlite3.Connection:
    """
    Get PostgreSQL connection via SQLAlchemy.
    Wraps SQLAlchemy connection in a SQLite-like interface.
    """
    global SA_ENGINE
    
    if SA_ENGINE is None:
        SA_ENGINE = create_engine(database_url)
    
    # Wrapper to make SQLAlchemy connection look like sqlite3
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
            """Execute SQL. Converts SQLite syntax to SQLAlchemy as needed."""
            from sqlalchemy import text
            
            if params is None:
                params = []
            
            # Convert SQLite ? parameters to named parameters
            if "?" in sql:
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
                except Exception:
                    return SAResult(self._conn.execute(text(sql)))
            else:
                if isinstance(params, (list, tuple)):
                    param_map = {f"p{i}": v for i, v in enumerate(params)}
                    try:
                        return SAResult(self._conn.execute(text(sql), param_map))
                    except Exception:
                        return SAResult(self._conn.execute(text(sql)))
                else:
                    return SAResult(self._conn.execute(text(sql), params or {}))
        
        def commit(self):
            """Commit transaction."""
            try:
                self._trans.commit()
            except Exception:
                pass
        
        def close(self):
            """Close connection."""
            try:
                self._conn.close()
            except Exception:
                pass
    
    return SAConn(SA_ENGINE)


# ================================================================================
# INITIALIZATION
# ================================================================================

def init_db() -> None:
    """
    Initialize database schema.
    Creates all tables if they don't exist.
    Call this once at app startup.
    
    Usage:
        app = FastAPI()
        @app.on_event("startup")
        async def startup():
            init_db()
    """
    conn = get_db()
    
    try:
        # This assumes you've already run the migration
        # If not, run: database/migrations/001_add_multi_tenant_schema.sql
        
        # Verify core tables exist
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='organisations'"
        )
        if not cursor.fetchone():
            print("""
            ⚠️  WARNING: Multi-tenant tables not found!
            
            Please run the migration:
            1. sqlite3 hub.db < database/migrations/001_add_multi_tenant_schema.sql
            2. python scripts/migrate_to_multitenant.py
            
            Then restart the app.
            """)
    
    finally:
        conn.close()


# ================================================================================
# UTILITY FUNCTIONS
# ================================================================================

def close_db(conn: sqlite3.Connection) -> None:
    """Close database connection."""
    if conn:
        try:
            conn.close()
        except Exception:
            pass


def execute_query(query: str, params: tuple = None) -> list:
    """Execute a query and return results."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor.fetchall()
    finally:
        conn.close()


def execute_update(query: str, params: tuple = None) -> int:
    """Execute an insert/update/delete and return affected rows."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


# ================================================================================
# FASTAPI STARTUP/SHUTDOWN HOOKS
# ================================================================================

async def setup_database(app):
    """
    Setup database at app startup.
    
    Usage in main.py:
        app = FastAPI()
        
        @app.on_event("startup")
        async def startup_event():
            await setup_database(app)
    """
    print("[startup] Initializing database...")
    init_db()
    print("[startup] Database ready")


async def shutdown_database(app):
    """
    Cleanup database at app shutdown.
    
    Usage in main.py:
        @app.on_event("shutdown")
        async def shutdown_event():
            await shutdown_database(app)
    """
    print("[shutdown] Closing database connections...")
    # SQLite connections are auto-closed
    # PostgreSQL connections will be cleaned up by SQLAlchemy
    if SA_ENGINE:
        SA_ENGINE.dispose()
