"""
Security utilities for the vetting app.
- Rate limiting per IP
- Account lockout helpers
"""

import time
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

from sqlalchemy import create_engine, text

# In-memory rate limiter
# Format: {ip: [(timestamp1, timestamp2, ...), ...]}
_rate_limit_store: Dict[str, list] = {}
_rate_limit_engine = None


def _get_rate_limit_engine():
    global _rate_limit_engine
    if _rate_limit_engine is None:
        _rate_limit_engine = create_engine(os.environ["DATABASE_URL"])
    return _rate_limit_engine


def _check_database_rate_limit(ip: str, max_attempts: int, window_seconds: int) -> Tuple[bool, int]:
    # Task 5: Share rate-limit counters through the config table in deployed database-backed environments.
    window_start = int(time.time() // window_seconds * window_seconds)
    key = f"ratelimit:{ip}:{window_start}"
    prefix = f"ratelimit:{ip}:%"
    engine = _get_rate_limit_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL)"))
        conn.execute(text("DELETE FROM config WHERE key LIKE :prefix AND key != :key"), {"prefix": prefix, "key": key})
        if engine.dialect.name == "postgresql":
            row = conn.execute(
                text(
                    """
                    INSERT INTO config(key, value) VALUES (:key, '1')
                    ON CONFLICT (key) DO UPDATE SET value = ((config.value)::integer + 1)::text
                    RETURNING value
                    """
                ),
                {"key": key},
            ).fetchone()
        else:
            row = conn.execute(
                text(
                    """
                    INSERT INTO config(key, value) VALUES (:key, '1')
                    ON CONFLICT(key) DO UPDATE SET value = CAST(config.value AS INTEGER) + 1
                    RETURNING value
                    """
                ),
                {"key": key},
            ).fetchone()
        attempt_count = int(row[0]) if row else max_attempts + 1
    remaining = max_attempts - attempt_count
    return attempt_count <= max_attempts, remaining


def get_client_ip(request) -> str:
    """Extract client IP from request, considering proxies."""
    # Check for X-Forwarded-For header (cloud providers)
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # Take the first IP if multiple are present
        return x_forwarded_for.split(",")[0].strip()
    
    # Fall back to direct connection
    return request.client.host if request.client else "unknown"


def check_rate_limit(ip: str, max_attempts: int = 5, window_seconds: int = 60) -> Tuple[bool, int]:
    """
    Check if IP has exceeded rate limit.
    
    Args:
        ip: Client IP address
        max_attempts: Max attempts allowed in window
        window_seconds: Time window in seconds
    
    Returns:
        (is_allowed, remaining_attempts)
        - is_allowed: True if request is allowed, False if rate limited
        - remaining_attempts: Number of remaining attempts (can be negative)
    """
    if os.environ.get("DATABASE_URL"):
        try:
            return _check_database_rate_limit(ip, max_attempts, window_seconds)
        except Exception:
            return False, 0

    now = time.time()
    cutoff = now - window_seconds
    
    # Clean old entries
    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = []
    
    # Remove timestamps outside the window
    _rate_limit_store[ip] = [ts for ts in _rate_limit_store[ip] if ts > cutoff]
    
    # Check if limit exceeded
    attempt_count = len(_rate_limit_store[ip])
    remaining = max_attempts - attempt_count
    
    if attempt_count >= max_attempts:
        return False, remaining
    
    # Record this attempt
    _rate_limit_store[ip].append(now)
    return True, remaining - 1


def reset_rate_limit(ip: str) -> None:
    """Reset rate limit counter for an IP."""
    if os.environ.get("DATABASE_URL"):
        try:
            engine = _get_rate_limit_engine()
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM config WHERE key LIKE :prefix"), {"prefix": f"ratelimit:{ip}:%"})
        except Exception:
            pass
        return

    if ip in _rate_limit_store:
        _rate_limit_store[ip] = []


def should_lock_account(failed_attempts: int, lockout_threshold: int = 10) -> bool:
    """Check if account should be locked based on failed attempts."""
    return failed_attempts >= lockout_threshold


def get_lockout_until(minutes: int = 15) -> str:
    """Get ISO format timestamp for account lockout duration."""
    locked_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return locked_until.isoformat()


def is_account_locked(locked_until_str: str | None) -> bool:
    """Check if account is currently locked."""
    if not locked_until_str:
        return False
    
    try:
        locked_until = datetime.fromisoformat(locked_until_str)
        # Make timezone-aware if needed
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        return now < locked_until
    except Exception:
        return False


def get_lockout_remaining_minutes(locked_until_str: str | None) -> int:
    """Get remaining lockout time in minutes."""
    if not locked_until_str:
        return 0
    
    try:
        locked_until = datetime.fromisoformat(locked_until_str)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        if now >= locked_until:
            return 0
        
        delta = locked_until - now
        return max(0, int(delta.total_seconds() / 60))
    except Exception:
        return 0
