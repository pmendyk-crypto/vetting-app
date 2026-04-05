#!/usr/bin/env python3
"""Create or update the canonical owner account in any environment.

Usage examples:

  .\\.venv\\Scripts\\python.exe .\\scripts\\seed_owner_account.py --env-file .env.local
  .\\.venv\\Scripts\\python.exe .\\scripts\\seed_owner_account.py --demote-other-superusers

Environment variables used by default:
  OWNER_ADMIN_USERNAME
  OWNER_ADMIN_PASSWORD
  OWNER_ADMIN_EMAIL
  DATABASE_URL / DB_PATH
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_env_file(env_file: str) -> None:
    env_path = (ROOT / env_file).resolve()
    if not env_path.exists():
        raise FileNotFoundError(f"Env file not found: {env_path}")

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        os.environ[name] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update the canonical owner account.")
    parser.add_argument(
        "--env-file",
        default="",
        help="Optional env file to load before connecting, for example .env.local or .env.test.local.",
    )
    parser.add_argument("--username", default=os.environ.get("OWNER_ADMIN_USERNAME", "P.Mendyk"))
    parser.add_argument("--password", default=os.environ.get("OWNER_ADMIN_PASSWORD", ""))
    parser.add_argument("--email", default=os.environ.get("OWNER_ADMIN_EMAIL", ""))
    parser.add_argument(
        "--demote-other-superusers",
        action="store_true",
        help="Set all other superuser accounts to is_superuser=0.",
    )
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    username = (args.username or os.environ.get("OWNER_ADMIN_USERNAME", "P.Mendyk") or "").strip()
    password = (args.password or os.environ.get("OWNER_ADMIN_PASSWORD", "") or "").strip()
    email = (args.email or os.environ.get("OWNER_ADMIN_EMAIL", "") or "").strip()

    if not username:
        print("ERROR: owner username is required via --username or OWNER_ADMIN_USERNAME.")
        return 1
    if not password:
        print("ERROR: owner password is required via --password or OWNER_ADMIN_PASSWORD.")
        return 1

    from app.main import ensure_owner_account, get_db, using_postgres

    action = ensure_owner_account(
        username,
        password,
        email or None,
        demote_other_superusers=args.demote_other_superusers,
    )

    conn = get_db()
    row = conn.execute(
        "SELECT username, email, is_superuser, is_active FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()

    if not row:
        print(f"ERROR: owner account '{username}' was not found after seeding.")
        return 1

    data = dict(row)
    backend = "PostgreSQL" if using_postgres() else "SQLite"
    print(f"Owner account {action} successfully.")
    print(f"Database backend: {backend}")
    print(f"Username: {data.get('username')}")
    print(f"Email: {data.get('email') or '(not set)'}")
    print(f"Is superuser: {data.get('is_superuser')}")
    print(f"Is active: {data.get('is_active')}")
    if args.demote_other_superusers:
        print("Other superuser accounts were demoted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
