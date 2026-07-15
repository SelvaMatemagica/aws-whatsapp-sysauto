import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import anyio

from app.config import settings
from app.db import get_sync_conn
from app.utils.general_utils import make_json_safe


def _rows_to_dicts(conn, rows) -> list[dict]:
    if not rows:
        return []
    column_names = [col["name"] for col in conn.columns]
    return [make_json_safe(dict(zip(column_names, row))) for row in rows]


def _row_to_dict(conn, rows) -> dict | None:
    data = _rows_to_dicts(conn, rows)
    return data[0] if data else None


def _conversation_exists_sync(conversation_id: str, account_id: str) -> bool:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT 1 FROM conversations
            WHERE id = :conversation_id AND account_id = :account_id
            LIMIT 1
            """,
            conversation_id=conversation_id,
            account_id=account_id,
        )
        return bool(rows)


def cancel_active_runs_for_conversation_sync(account_id: str, conversation_id: str) -> int:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            UPDATE automation_runs
            SET status = 'cancelled',
                completed_at = NOW(),
                updated_at = NOW(),
                last_error = COALESCE(last_error, 'cancelled_by_human_takeover')
            WHERE account_id = :account_id
              AND conversation_id = :conversation_id
              AND status IN ('running', 'waiting')
            RETURNING id
            """,
            account_id=account_id,
            conversation_id=conversation_id,
        )
        return len(rows)


def pause_conversation_automation_sync(
    conversation_id: str,
    account_id: str,
    user_id: Optional[str] = None,
) -> dict | None:
    if not _conversation_exists_sync(conversation_id, account_id):
        return None

    with get_sync_conn() as conn:
        rows = conn.run(
            """
            UPDATE conversations
            SET automation_paused = TRUE,
                automation_paused_at = NOW(),
                automation_paused_by = :user_id
            WHERE id = :conversation_id AND account_id = :account_id
            RETURNING id, automation_paused, automation_paused_at, automation_paused_by
            """,
            conversation_id=conversation_id,
            account_id=account_id,
            user_id=user_id,
        )
        cancel_active_runs_for_conversation_sync(account_id, conversation_id)
        return _row_to_dict(conn, rows)


def resume_conversation_automation_sync(conversation_id: str, account_id: str) -> dict | None:
    if not _conversation_exists_sync(conversation_id, account_id):
        return None

    with get_sync_conn() as conn:
        rows = conn.run(
            """
            UPDATE conversations
            SET automation_paused = FALSE,
                automation_paused_at = NULL,
                automation_paused_by = NULL
            WHERE id = :conversation_id AND account_id = :account_id
            RETURNING id, automation_paused, automation_paused_at, automation_paused_by
            """,
            conversation_id=conversation_id,
            account_id=account_id,
        )
        return _row_to_dict(conn, rows)


def try_auto_resume_conversation_sync(conversation_id: str, account_id: str) -> bool:
    minutes = settings.AUTOMATION_AUTO_RESUME_MINUTES
    if minutes <= 0:
        return False

    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT automation_paused, automation_paused_at
            FROM conversations
            WHERE id = :conversation_id AND account_id = :account_id
            LIMIT 1
            """,
            conversation_id=conversation_id,
            account_id=account_id,
        )
        if not rows or not rows[0][0]:
            return False

        paused_at = rows[0][1]
        if paused_at is None:
            return False

        if isinstance(paused_at, str):
            paused_at = datetime.fromisoformat(paused_at.replace("Z", "+00:00"))
        if paused_at.tzinfo is None:
            paused_at = paused_at.replace(tzinfo=timezone.utc)

        threshold = paused_at + timedelta(minutes=minutes)
        if datetime.now(timezone.utc) < threshold:
            return False

        conn.run(
            """
            UPDATE conversations
            SET automation_paused = FALSE,
                automation_paused_at = NULL,
                automation_paused_by = NULL
            WHERE id = :conversation_id AND account_id = :account_id
            """,
            conversation_id=conversation_id,
            account_id=account_id,
        )
        return True


def get_conversation_automation_status_sync(
    conversation_id: str,
    account_id: str,
) -> dict | None:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT id, automation_paused, automation_paused_at, automation_paused_by
            FROM conversations
            WHERE id = :conversation_id AND account_id = :account_id
            LIMIT 1
            """,
            conversation_id=conversation_id,
            account_id=account_id,
        )
        row = _row_to_dict(conn, rows)
        if not row:
            return None

        auto_resume_at = None
        paused_at = row.get("automation_paused_at")
        if row.get("automation_paused") and paused_at and settings.AUTOMATION_AUTO_RESUME_MINUTES > 0:
            if isinstance(paused_at, str):
                paused_at = datetime.fromisoformat(paused_at.replace("Z", "+00:00"))
            if paused_at.tzinfo is None:
                paused_at = paused_at.replace(tzinfo=timezone.utc)
            auto_resume_at = paused_at + timedelta(minutes=settings.AUTOMATION_AUTO_RESUME_MINUTES)

        row["auto_resume_minutes"] = settings.AUTOMATION_AUTO_RESUME_MINUTES
        row["auto_resume_at"] = auto_resume_at.isoformat() if auto_resume_at else None
        return row


async def pause_conversation_automation(
    conversation_id: str,
    account_id: str,
    user_id: Optional[str] = None,
) -> dict | None:
    return await anyio.to_thread.run_sync(
        pause_conversation_automation_sync, conversation_id, account_id, user_id
    )


async def resume_conversation_automation(conversation_id: str, account_id: str) -> dict | None:
    return await anyio.to_thread.run_sync(
        resume_conversation_automation_sync, conversation_id, account_id
    )


async def try_auto_resume_conversation(conversation_id: str, account_id: str) -> bool:
    return await anyio.to_thread.run_sync(
        try_auto_resume_conversation_sync, conversation_id, account_id
    )


async def get_conversation_automation_status(conversation_id: str, account_id: str) -> dict | None:
    return await anyio.to_thread.run_sync(
        get_conversation_automation_status_sync, conversation_id, account_id
    )
