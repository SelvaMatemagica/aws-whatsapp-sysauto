import json
import uuid
import anyio
import redis.asyncio as aioredis
from app.config import settings
from app.db import get_sync_conn

EVENTS_QUEUE = settings.AUTOMATION_EVENTS_QUEUE

def _persist_event_sync(event_type: str, account_id: str, payload: dict, idempotency_key: str | None):
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            INSERT INTO domain_events (id, account_id, event_type, idempotency_key, payload)
            VALUES (:id, :account_id, :event_type, :idempotency_key, :payload::jsonb)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            id=str(uuid.uuid4()),
            account_id=account_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            payload=json.dumps(payload),
        )
        return str(rows[0][0]) if rows else None

async def publish_event(
    event_type: str,
    account_id: str,
    payload: dict,
    *,
    idempotency_key: str | None = None,
) -> str | None:
    event_id = await anyio.to_thread.run_sync(
        _persist_event_sync, event_type, account_id, payload, idempotency_key
    )
    if not event_id:
        return None  # duplicado, idempotente

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await r.rpush(settings.AUTOMATION_EVENTS_QUEUE, json.dumps({"event_id": event_id}))
    return event_id