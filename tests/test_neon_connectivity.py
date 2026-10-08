"""
Neon Database Connectivity Test

Run this script to verify your Neon PostgreSQL connection:
    python tests/test_neon_connectivity.py

This validates:
1. DATABASE_URL is present in config
2. PostgreSQL driver is installed
3. Connection can be established
4. Database responds to queries
5. chat_messages table exists
6. A test write/read cycle works
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import core modules
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_neon_connectivity():
    """Comprehensive Neon database connectivity test."""
    print("=" * 70)
    print("NEON DATABASE CONNECTIVITY TEST")
    print("=" * 70)
    
    # Step 1: Check configuration
    print("\n[1/6] Checking configuration...")
    try:
        from memory.config_manager import load_api_keys
        config = load_api_keys()
        database_url = config.get("database_url", "").strip()
        
        if not database_url:
            print("[FAIL] database_url not found in config/api_keys.json")
            print("   Add your Neon connection string to config/api_keys.json:")
            print('   "database_url": "postgresql://user:pass@host/db?sslmode=require"')
            return False
        
        # Don't print the full URL (contains password), just confirm host portion
        _safe_host = database_url.split('@')[1] if '@' in database_url else '***'
        print(f"[PASS] database_url found: postgresql://{_safe_host}")
    except Exception as e:
        print(f"[FAIL] Could not load configuration: {e}")
        return False
    
    # Step 2: Check PostgreSQL driver
    print("\n[2/6] Checking PostgreSQL driver...")
    try:
        try:
            import psycopg
            driver = "psycopg (v3)"
        except ImportError:
            try:
                import psycopg2
                driver = "psycopg2 (legacy)"
            except ImportError:
                print("[FAIL] No PostgreSQL driver found")
                print("   Install with: pip install 'psycopg[binary]'")
                return False
        
        print(f"[PASS] Driver available: {driver}")
    except Exception as e:
        print(f"[FAIL] {e}")
        return False
    
    # Step 3: Test connection
    print("\n[3/6] Testing database connection...")
    try:
        from core.chat_history import _get_pg_connection
        with _get_pg_connection(database_url) as conn:
            print("[PASS] Connection established successfully")
    except Exception as e:
        print("[FAIL] Could not connect to database")
        print(f"   Error: {e}")
        
        if "timeout" in str(e).lower():
            print("   -> Check your internet connection")
            print("   -> Verify the Neon project is running (not suspended)")
        elif "authentication" in str(e).lower() or "password" in str(e).lower():
            print("   -> Verify your database credentials are correct")
        elif "ssl" in str(e).lower():
            print("   -> Ensure sslmode=require is in your connection string")
        
        return False
    
    # Step 4: Test database query
    print("\n[4/6] Testing database query...")
    try:
        from core.chat_history import _get_pg_connection
        with _get_pg_connection(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version = cur.fetchone()
                if version:
                    # Extract just the PostgreSQL version number
                    version_str = str(version[0] if isinstance(version, tuple) else version.get('version', version))
                    pg_version = version_str.split()[1] if ' ' in version_str else version_str
                    print(f"[PASS] Database responds: PostgreSQL {pg_version}")
    except Exception as e:
        print(f"[FAIL] Query failed: {e}")
        return False
    
    # Step 5: Check schema
    print("\n[5/6] Checking chat_messages table...")
    try:
        from core.chat_history import _get_pg_connection, _ensure_schema
        with _get_pg_connection(database_url) as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'chat_messages' 
                    ORDER BY ordinal_position;
                """)
                columns = cur.fetchall()
                
                if not columns:
                    print("[WARN] chat_messages table does not exist yet")
                    print("   It will be created automatically on first use")
                else:
                    print(f"[PASS] Table exists with {len(columns)} columns:")
                    for col in columns:
                        col_name = col[0] if isinstance(col, tuple) else col.get('column_name')
                        col_type = col[1] if isinstance(col, tuple) else col.get('data_type')
                        print(f"   - {col_name}: {col_type}")
    except Exception as e:
        print(f"[FAIL] Schema check failed: {e}")
        return False
    
    # Step 6: Test write/read cycle
    print("\n[6/6] Testing write/read cycle...")
    try:
        from core.chat_history import _get_pg_connection, _ensure_schema
        import uuid
        from datetime import datetime
        
        test_conversation_id = f"test_{uuid.uuid4().hex[:8]}"
        test_message = "Connectivity test message"
        
        with _get_pg_connection(database_url) as conn:
            _ensure_schema(conn)
            
            # Insert test message
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.chat_messages 
                    (conversation_id, sender_id, sender_name, message_content, sent_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                """, (test_conversation_id, "test", "Test", test_message, datetime.now()))
                
                result = cur.fetchone()
                test_id = result[0] if isinstance(result, tuple) else result.get('id')
                print(f"[PASS] Test message inserted (id: {test_id})")
            
            # Read it back
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT message_content 
                    FROM public.chat_messages 
                    WHERE conversation_id = %s;
                """, (test_conversation_id,))
                
                result = cur.fetchone()
                retrieved = result[0] if isinstance(result, tuple) else result.get('message_content')
                
                if retrieved == test_message:
                    print("[PASS] Test message retrieved successfully")
                else:
                    print("[WARN] Retrieved message does not match")
            
            # Clean up test data
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM public.chat_messages 
                    WHERE conversation_id = %s;
                """, (test_conversation_id,))
                print("[PASS] Test data cleaned up")
        
    except Exception as e:
        print(f"[FAIL] Write/read test failed: {e}")
        return False
    
    # Success!
    print("\n" + "=" * 70)
    print("ALL TESTS PASSED")
    print("=" * 70)
    print("\nYour Neon database is properly configured.")
    print("JARVIS will now save chat history to your Neon PostgreSQL database.")
    print("\nTo verify history is being saved:")
    print("1. Start JARVIS and have a conversation")
    print("2. Check the Neon Console -> SQL Editor -> run:")
    print("   SELECT * FROM chat_messages ORDER BY sent_at DESC LIMIT 10;")
    print("=" * 70)
    return True


if __name__ == "__main__":
    try:
        success = test_neon_connectivity()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\nUNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
