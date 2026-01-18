"""
Simple migration script: copy SQLite hub.db tables to a Postgres database.
Requires: SQLAlchemy and psycopg2-binary installed.

Usage:
  export DATABASE_URL=postgres://user:pass@host:5432/dbname
  python scripts/migrate_sqlite_to_postgres.py --sqlite hub.db

This script is intentionally conservative: it creates the target tables if missing
and copies rows. It does not attempt to dedupe or drop existing data.
"""
import argparse
import os
import sqlite3
from urllib.parse import urlparse

from sqlalchemy import create_engine, text


def create_tables_pg(engine):
    create_sql = [
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
        """,
        """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS radiologists (
            name TEXT PRIMARY KEY,
            email TEXT,
            surname TEXT,
            gmc TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            radiologist_name TEXT,
            salt_hex TEXT NOT NULL,
            pw_hash_hex TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS protocols (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """,
    ]
    with engine.begin() as conn:
        for s in create_sql:
            conn.execute(text(s))


def copy_table(sqlite_conn, engine, table_name, columns):
    cur = sqlite_conn.cursor()
    cols_sql = ",".join(columns)
    cur.execute(f"SELECT {cols_sql} FROM {table_name}")
    rows = cur.fetchall()
    if not rows:
        print(f"No rows to copy for {table_name}")
        return
    placeholders = ",".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders})"
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text(insert_sql), tuple(r))
    print(f"Copied {len(rows)} rows into {table_name}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sqlite", default="hub.db", help="Path to sqlite db")
    args = p.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("Set DATABASE_URL environment variable to a Postgres DSN")

    if not os.path.exists(args.sqlite):
        raise SystemExit(f"SQLite file not found: {args.sqlite}")

    sqlite_conn = sqlite3.connect(args.sqlite)
    sqlite_conn.row_factory = sqlite3.Row

    engine = create_engine(database_url)

    print("Creating target tables if missing...")
    create_tables_pg(engine)

    # Copy simple tables
    copy_table(sqlite_conn, engine, "radiologists", ["name", "email", "surname", "gmc"])
    copy_table(sqlite_conn, engine, "users", ["username", "role", "radiologist_name", "salt_hex", "pw_hash_hex"])
    copy_table(sqlite_conn, engine, "protocols", ["id", "name", "is_active"])
    copy_table(sqlite_conn, engine, "config", ["key", "value"])

    # Cases may be large - copy with explicit columns
    copy_table(sqlite_conn, engine, "cases", [
        "id","created_at","patient_id","study_description","admin_notes",
        "radiologist","uploaded_filename","stored_filepath","status","protocol",
        "decision","decision_comment","vetted_at"
    ])

    sqlite_conn.close()
    print("Migration complete. Please verify data in Postgres.")


if __name__ == '__main__':
    main()
