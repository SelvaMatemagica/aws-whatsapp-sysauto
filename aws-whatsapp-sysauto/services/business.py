import json
import time
from datetime import datetime, timedelta, timezone
import anyio
from ..db import get_sync_conn
from ..config import settings
try:
    import redis.asyncio as aioredis
except ImportError:
    from redis import asyncio as aioredis

# Redis client (async); create one in app startup normally
redis_client: aioredis.Redis | None = None

async def init_redis():
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return redis_client

# Business rule: opt-in (synchronous DB check)
def has_opt_in_sync(contact_phone: str) -> bool:
    with get_sync_conn() as conn:
        q = "SELECT opt_in FROM contacts WHERE phone_number = :phone LIMIT 1;"############################ Relleno
        rows = conn.run(q, phone=contact_phone)
        if rows[0]:
            return bool(rows[0][0])
    return False

async def has_opt_in(contact_phone: str) -> bool:
    return await anyio.to_thread.run_sync(has_opt_in_sync, contact_phone)

# Business rule: 24h window (last incoming message within 24h)
def last_incoming_ts_sync(contact_phone: str, account_id: str) -> datetime | None:
    with get_sync_conn() as conn:
        q = """
            SELECT m.timestamp
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            JOIN contacts ct ON c.contact_id = ct.id
            WHERE ct.phone_number = :phone AND m.direction = 'in' AND c.account_id = :account_id
            ORDER BY m.timestamp DESC LIMIT 1;
        """
        rows = conn.run(q, phone=contact_phone, account_id=account_id)
        if rows:
            return rows[0][0]
    return None

async def within_24h_window(contact_phone: str, account_id: str) -> bool:
    ts = await anyio.to_thread.run_sync(last_incoming_ts_sync, contact_phone, account_id)
    if ts is None:
        return False
    now = datetime.now(timezone.utc)
    return (now - ts) <= timedelta(hours=24)

# Rate-limit: allow n per minute per phone_number_id
async def allowed_by_rate_limit(phone_number_id: str) -> bool:
    r = await init_redis()
    key = f"rate:{phone_number_id}:{int(time.time()//60)}"
    cur = await r.get(key)
    cur_int = int(cur) if cur else 0
    if cur_int >= settings.RATE_LIMIT_PER_MIN:
        return False
    # increment
    await r.incr(key)
    # set ttl for minute bucket
    await r.expire(key, 70)
    return True
