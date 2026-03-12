import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

# Azure PostgreSQL connection
DATABASE_URL = "postgresql+psycopg2://pgadminlumos:Polonez1!@lumosradflow.postgres.database.azure.com:5432/vetting_app?sslmode=require"

print("Connecting to Azure PostgreSQL...")
try:
    engine = create_engine(
        DATABASE_URL, 
        poolclass=NullPool,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=5000"
        }
    )
    
    with engine.connect() as conn:
        # Get all tables
        result = conn.execute(text("""
            SELECT tablename 
            FROM pg_tables 
            WHERE schemaname = 'public' 
            ORDER BY tablename
        """))
        tables = [row[0] for row in result.fetchall()]
        
        print("\n✅ AZURE PRODUCTION DATABASE TABLES:")
        print("   " + "\n   ".join(tables))
        
        # Check institutions table structure
        if 'institutions' in tables:
            result = conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'institutions'
                ORDER BY ordinal_position
            """))
            columns = result.fetchall()
            
            print("\n✅ INSTITUTIONS TABLE COLUMNS:")
            for col in columns:
                print(f"   {col[0]} ({col[1]})")
            
            has_modified_at = any(col[0] == 'modified_at' for col in columns)
            if has_modified_at:
                print("   ✅ Bug Fix #2 APPLIED: modified_at column exists")
            else:
                print("   ❌ Bug Fix #2 MISSING: modified_at column NOT found")
        
        # Check if case_events exists
        has_case_events = 'case_events' in tables
        if has_case_events:
            print("\n✅ case_events table EXISTS (V3 ready)")
        else:
            print("\n❌ case_events table MISSING (needs migration 002)")
        
        # Check if password_reset_tokens exists  
        has_password_reset = 'password_reset_tokens' in tables
        if has_password_reset:
            print("✅ password_reset_tokens table EXISTS (V3 ready)")
        else:
            print("❌ password_reset_tokens table MISSING (needs migration 002)")
            
        # Check for study_description_presets
        has_presets = 'study_description_presets' in tables
        if has_presets:
            print("✅ study_description_presets table EXISTS")
            result = conn.execute(text("SELECT COUNT(*) FROM study_description_presets"))
            count = result.scalar()
            print(f"   {count} study descriptions loaded")
        else:
            print("❌ study_description_presets table MISSING")
        
        print("\n" + "="*60)
        print("SUMMARY:")
        print("="*60)
        if has_modified_at and has_case_events and has_password_reset:
            print("✅ Production database is UP TO DATE with all V2 fixes")
        elif has_modified_at and not has_case_events:
            print("⚠️  Production has V2 bug fixes but missing V3 tables")
            print("   Run migration 002 before V3 features")
        else:
            print("❌ Production database needs schema updates")
            print("   Missing V2 bug fixes - deployment required")
        
except Exception as e:
    print(f"\n❌ Error connecting to Azure database:")
    print(f"   {type(e).__name__}: {e}")
    print("\nThis could mean:")
    print("  - Database is not accessible from this network")
    print("  - Firewall rules need updating")
    print("  - Connection credentials are incorrect")
    sys.exit(1)
