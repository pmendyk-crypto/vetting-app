#!/usr/bin/env python3
"""Deprecated helper kept as a compatibility wrapper.

This script no longer contains embedded credentials.
Set DATABASE_URL plus OWNER_ADMIN_USERNAME / OWNER_ADMIN_PASSWORD / OWNER_ADMIN_EMAIL,
then use scripts/seed_owner_account.py.
"""

from pathlib import Path
import subprocess
import sys


def main() -> int:
    script = Path(__file__).resolve().parent / "scripts" / "seed_owner_account.py"
    print("init_azure_superadmin.py is deprecated.")
    print("Forwarding to scripts/seed_owner_account.py")
    return subprocess.call([sys.executable, str(script), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
