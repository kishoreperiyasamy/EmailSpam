import sys
from config import Config
from database.connection import init_db, get_db_cursor

def test_connection():
    print("=" * 60)
    print("  SpamShield AI - Supabase Database Connection Tester  ")
    print("=" * 60)
    
    if Config.DATABASE_URL:
        # Mask password in logs
        masked_url = Config.DATABASE_URL
        if "@" in masked_url and ":" in masked_url:
            prefix, rest = masked_url.split("://", 1) if "://" in masked_url else ("", masked_url)
            userinfo, hostinfo = rest.split("@", 1)
            if ":" in userinfo:
                u, _ = userinfo.split(":", 1)
                userinfo = f"{u}:******"
            masked_url = f"{prefix}://{userinfo}@{hostinfo}"
        print(f"[Config] Using DATABASE_URL: {masked_url}")
    else:
        print(f"[Config] Using DB_HOST: {Config.DB_HOST}")
        print(f"[Config] Using DB_PORT: {Config.DB_PORT}")
        print(f"[Config] Using DB_NAME: {Config.DB_NAME}")
        print(f"[Config] Using DB_USER: {Config.DB_USER}")
        print(f"[Config] Using DB_SSLMODE: {Config.DB_SSLMODE}")

    print("\n1. Testing connection & initializing database schema...")
    try:
        init_db()
        print("   -> Schema initialized successfully (tables and default users created)!")
    except Exception as e:
        print(f"   [Error] Connection or schema creation failed: {e}")
        return False

    print("\n2. Verifying default users in database...")
    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT id, name, email, role, is_active FROM users ORDER BY id;")
            users = cur.fetchall()
            print(f"   -> Found {len(users)} user(s):")
            for u in users:
                print(f"      - [{u['role']}] {u['name']} ({u['email']}) [Active: {u['is_active']}]")
    except Exception as e:
        print(f"   [Error] Failed to query users: {e}")
        return False

    print("\n3. Verifying model metrics table...")
    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT COUNT(*) AS count FROM model_metrics;")
            res = cur.fetchone()
            print(f"   -> Existing model evaluation metrics records: {res['count']}")
    except Exception as e:
        print(f"   [Error] Failed to query model_metrics: {e}")
        return False

    print("\n" + "=" * 60)
    print("  SUCCESS! Supabase PostgreSQL connection is fully working.  ")
    print("============================================================")
    return True

if __name__ == '__main__':
    success = test_connection()
    sys.exit(0 if success else 1)
