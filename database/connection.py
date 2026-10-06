import os
import time
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from config import Config

_connection_pool = None
_last_pool_failure_time = 0
_failure_cooldown_seconds = 20
_last_failure_error = None
_db_initialized = False


def _get_clean_dsn():
    url = Config.DATABASE_URL or ""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url and "connect_timeout=" not in url:
        timeout = os.getenv('DB_CONNECT_TIMEOUT', '3')
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}connect_timeout={timeout}"
    return url


def is_database_configured() -> bool:
    """Checks whether valid DB credentials or remote URL are configured."""
    url = _get_clean_dsn()
    if url:
        return True
    is_vercel = os.getenv('VERCEL') == '1' or os.getenv('VERCEL_ENV') is not None
    if is_vercel and Config.DB_HOST in ('localhost', '127.0.0.1'):
        return False
    return bool(Config.DB_HOST)


def init_connection_pool():
    global _connection_pool, _last_pool_failure_time, _last_failure_error

    # Fail fast if on Vercel without DATABASE_URL configured
    is_vercel = os.getenv('VERCEL') == '1' or os.getenv('VERCEL_ENV') is not None
    dsn = _get_clean_dsn()

    if is_vercel and not dsn and Config.DB_HOST in ('localhost', '127.0.0.1'):
        _last_failure_error = "DATABASE_URL environment variable is not configured on Vercel."
        raise ConnectionError(_last_failure_error)

    # Cooldown check: if recent connection attempt failed, fail immediately without blocking
    now = time.time()
    if (now - _last_pool_failure_time) < _failure_cooldown_seconds:
        raise psycopg2.OperationalError(f"Database connection cooling down ({_last_failure_error})")

    connect_timeout = int(os.getenv('DB_CONNECT_TIMEOUT', '3'))
    max_conn = int(os.getenv('DB_MAX_POOL_CONN', '5'))

    if _connection_pool is None:
        try:
            if dsn:
                _connection_pool = pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=max_conn,
                    dsn=dsn
                )
                print("[DB] PostgreSQL Connection Pool established via DATABASE_URL")
            else:
                _connection_pool = pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=max_conn,
                    host=Config.DB_HOST,
                    port=Config.DB_PORT,
                    dbname=Config.DB_NAME,
                    user=Config.DB_USER,
                    password=Config.DB_PASSWORD,
                    sslmode=Config.DB_SSLMODE,
                    connect_timeout=connect_timeout
                )
                print(f"[DB] PostgreSQL Connection Pool established for {Config.DB_NAME} at {Config.DB_HOST}:{Config.DB_PORT}")
            _last_failure_error = None
        except Exception as e:
            _last_pool_failure_time = time.time()
            _last_failure_error = str(e)
            _connection_pool = None
            print(f"[DB Error] Failed to initialize connection pool: {e}")
            raise e


def get_connection():
    global _connection_pool
    if _connection_pool is None:
        init_connection_pool()
    try:
        conn = _connection_pool.getconn()
        if conn and getattr(conn, 'closed', 0) != 0:
            try:
                _connection_pool.putconn(conn, close=True)
            except Exception:
                pass
            conn = _connection_pool.getconn()
        return conn
    except Exception as e:
        print(f"[DB Pool Warning] Connection failed ({e}), refreshing pool...")
        _connection_pool = None
        init_connection_pool()
        return _connection_pool.getconn()


def release_connection(conn):
    global _connection_pool
    if _connection_pool and conn:
        try:
            if getattr(conn, 'closed', 0) != 0:
                _connection_pool.putconn(conn, close=True)
            else:
                _connection_pool.putconn(conn)
        except Exception:
            pass


@contextmanager
def get_db_connection():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        if conn and getattr(conn, 'closed', 0) == 0:
            conn.rollback()
        raise
    finally:
        release_connection(conn)


@contextmanager
def get_db_cursor(commit=True):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        if commit and getattr(conn, 'closed', 0) == 0:
            conn.commit()
    except Exception:
        if conn and getattr(conn, 'closed', 0) == 0:
            conn.rollback()
        raise
    finally:
        release_connection(conn)


def init_db():
    """Idempotent database schema initialization. Safe for serverless environments."""
    global _db_initialized
    if _db_initialized:
        return

    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    if not os.path.exists(schema_path):
        print(f"[DB] schema.sql not found at {schema_path}")
        return

    try:
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
        _db_initialized = True
        print("[DB] Schema initialized and default users verified.")
    except Exception as e:
        print(f"[DB Notice] Could not auto-initialize schema at startup: {e}")
        raise e
