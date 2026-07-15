from pg8000.native import Connection
from contextlib import contextmanager
from .config import settings

@contextmanager
def get_sync_conn():
    conn = Connection(
        user=settings.PG_USER,
        password=settings.PG_PASS,
        host=settings.PG_HOST,
        port=settings.PG_PORT,
        database=settings.PG_DB,
    )
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass
 