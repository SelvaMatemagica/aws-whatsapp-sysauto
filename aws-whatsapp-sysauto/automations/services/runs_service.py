import json
import uuid
from datetime import datetime, timezone
from typing import Any

import anyio

from app.db import get_sync_conn
from app.utils.general_utils import make_json_safe


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _rows_to_dicts(conn, rows) -> list[dict]:
    if not rows:
        return []
    column_names = [col["name"] for col in conn.columns]
    return [make_json_safe(dict(zip(column_names, row))) for row in rows]


def _row_to_dict(conn, rows) -> dict | None:
    data = _rows_to_dicts(conn, rows)
    return data[0] if data else None


def get_event_sync(event_id: str) -> dict | None:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT id, account_id, event_type, payload, status, attempts, idempotency_key
            FROM domain_events
            WHERE id = :event_id
            LIMIT 1
            """,
            event_id=event_id,
        )
        event = _row_to_dict(conn, rows)
        if event:
            event["payload"] = _parse_json(event.get("payload")) or {}
        return event


def mark_event_processing_sync(event_id: str) -> None:
    with get_sync_conn() as conn:
        conn.run(
            """
            UPDATE domain_events
            SET status = 'processing',
                attempts = attempts + 1
            WHERE id = :event_id
            """,
            event_id=event_id,
        )


def mark_event_processed_sync(event_id: str) -> None:
    with get_sync_conn() as conn:
        conn.run(
            """
            UPDATE domain_events
            SET status = 'processed',
                processed_at = NOW(),
                last_error = NULL
            WHERE id = :event_id
            """,
            event_id=event_id,
        )


def mark_event_failed_sync(event_id: str, error: str) -> None:
    with get_sync_conn() as conn:
        conn.run(
            """
            UPDATE domain_events
            SET status = 'failed',
                last_error = :error
            WHERE id = :event_id
            """,
            event_id=event_id,
            error=error,
        )


def is_conversation_automation_paused_sync(conversation_id: str) -> bool:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT automation_paused
            FROM conversations
            WHERE id = :conversation_id
            LIMIT 1
            """,
            conversation_id=conversation_id,
        )
        if not rows:
            return False
        return bool(rows[0][0])


def get_active_run_for_contact_sync(account_id: str, contact_id: str) -> dict | None:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT id, automation_id, account_id, contact_id, conversation_id,
                   status, current_step_index, variables, wait_until, wait_type
            FROM automation_runs
            WHERE account_id = :account_id
              AND contact_id = :contact_id
              AND status IN ('running', 'waiting')
            LIMIT 1
            """,
            account_id=account_id,
            contact_id=contact_id,
        )
        run = _row_to_dict(conn, rows)
        if run:
            run["variables"] = _parse_json(run.get("variables")) or {}
        return run


def create_run_sync(
    automation: dict,
    account_id: str,
    contact_id: str,
    conversation_id: str,
) -> dict:
    run_id = str(uuid.uuid4())
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            INSERT INTO automation_runs (
                id, automation_id, account_id, contact_id, conversation_id, status
            )
            VALUES (
                :id, :automation_id, :account_id, :contact_id, :conversation_id, 'running'
            )
            RETURNING id, automation_id, account_id, contact_id, conversation_id,
                      status, current_step_index, variables, wait_until, wait_type
            """,
            id=run_id,
            automation_id=automation["id"],
            account_id=account_id,
            contact_id=contact_id,
            conversation_id=conversation_id,
        )
        run = _row_to_dict(conn, rows)
        run["automation"] = automation
        run["variables"] = _parse_json(run.get("variables")) or {}
        return run


def load_run_sync(run_id: str) -> dict | None:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT r.id, r.automation_id, r.account_id, r.contact_id, r.conversation_id,
                   r.status, r.current_step_index, r.variables, r.wait_until, r.wait_type,
                   a.trigger_config, a.actions, a.name AS automation_name
            FROM automation_runs r
            JOIN automations a ON a.id = r.automation_id
            WHERE r.id = :run_id
            LIMIT 1
            """,
            run_id=run_id,
        )
        run = _row_to_dict(conn, rows)
        if not run:
            return None
        run["variables"] = _parse_json(run.get("variables")) or {}
        run["automation"] = {
            "id": run["automation_id"],
            "name": run.get("automation_name"),
            "trigger_config": _parse_json(run.pop("trigger_config")) or {},
            "actions": _parse_json(run.pop("actions")) or [],
        }
        return run


def update_run_step_index_sync(run_id: str, step_index: int) -> None:
    with get_sync_conn() as conn:
        conn.run(
            """
            UPDATE automation_runs
            SET current_step_index = :step_index, updated_at = NOW()
            WHERE id = :run_id
            """,
            run_id=run_id,
            step_index=step_index,
        )


def update_run_waiting_sync(run_id: str, wait_until: datetime, wait_type: str) -> None:
    with get_sync_conn() as conn:
        conn.run(
            """
            UPDATE automation_runs
            SET status = 'waiting',
                wait_until = :wait_until,
                wait_type = :wait_type,
                updated_at = NOW()
            WHERE id = :run_id
            """,
            run_id=run_id,
            wait_until=wait_until,
            wait_type=wait_type,
        )


def mark_run_completed_sync(run_id: str) -> None:
    with get_sync_conn() as conn:
        conn.run(
            """
            UPDATE automation_runs
            SET status = 'completed',
                completed_at = NOW(),
                updated_at = NOW(),
                wait_until = NULL,
                wait_type = NULL
            WHERE id = :run_id
            """,
            run_id=run_id,
        )


def mark_run_failed_sync(run_id: str, error: str) -> None:
    with get_sync_conn() as conn:
        conn.run(
            """
            UPDATE automation_runs
            SET status = 'failed',
                last_error = :error,
                updated_at = NOW(),
                completed_at = NOW()
            WHERE id = :run_id
            """,
            run_id=run_id,
            error=error,
        )


def resume_run_sync(run_id: str) -> None:
    with get_sync_conn() as conn:
        conn.run(
            """
            UPDATE automation_runs
            SET status = 'running',
                wait_until = NULL,
                wait_type = NULL,
                updated_at = NOW()
            WHERE id = :run_id
            """,
            run_id=run_id,
        )


def log_step_sync(
    run_id: str,
    step_index: int | None,
    event_type: str,
    input_data: dict | None = None,
    output_data: dict | None = None,
    error: str | None = None,
) -> None:
    with get_sync_conn() as conn:
        conn.run(
            """
            INSERT INTO automation_run_logs (run_id, step_index, event_type, input, output, error)
            VALUES (:run_id, :step_index, :event_type, :input::jsonb, :output::jsonb, :error)
            """,
            run_id=run_id,
            step_index=step_index,
            event_type=event_type,
            input=json.dumps(input_data) if input_data else None,
            output=json.dumps(output_data) if output_data else None,
            error=error,
        )


async def get_event(event_id: str) -> dict | None:
    return await anyio.to_thread.run_sync(get_event_sync, event_id)


async def mark_event_processing(event_id: str) -> None:
    await anyio.to_thread.run_sync(mark_event_processing_sync, event_id)


async def mark_event_processed(event_id: str) -> None:
    await anyio.to_thread.run_sync(mark_event_processed_sync, event_id)


async def mark_event_failed(event_id: str, error: str) -> None:
    await anyio.to_thread.run_sync(mark_event_failed_sync, event_id, error)


async def is_conversation_automation_paused(conversation_id: str) -> bool:
    return await anyio.to_thread.run_sync(is_conversation_automation_paused_sync, conversation_id)


async def get_active_run_for_contact(account_id: str, contact_id: str) -> dict | None:
    return await anyio.to_thread.run_sync(get_active_run_for_contact_sync, account_id, contact_id)


async def create_run(automation: dict, account_id: str, contact_id: str, conversation_id: str) -> dict:
    return await anyio.to_thread.run_sync(
        create_run_sync, automation, account_id, contact_id, conversation_id
    )


async def load_run(run_id: str) -> dict | None:
    return await anyio.to_thread.run_sync(load_run_sync, run_id)


async def update_run_step_index(run_id: str, step_index: int) -> None:
    await anyio.to_thread.run_sync(update_run_step_index_sync, run_id, step_index)


async def update_run_waiting(run_id: str, wait_until: datetime, wait_type: str) -> None:
    await anyio.to_thread.run_sync(update_run_waiting_sync, run_id, wait_until, wait_type)


async def mark_run_completed(run_id: str) -> None:
    await anyio.to_thread.run_sync(mark_run_completed_sync, run_id)


async def mark_run_failed(run_id: str, error: str) -> None:
    await anyio.to_thread.run_sync(mark_run_failed_sync, run_id, error)


async def resume_run(run_id: str) -> None:
    await anyio.to_thread.run_sync(resume_run_sync, run_id)


async def log_step(
    run_id: str,
    step_index: int | None,
    event_type: str,
    input_data: dict | None = None,
    output_data: dict | None = None,
    error: str | None = None,
) -> None:
    await anyio.to_thread.run_sync(
        log_step_sync, run_id, step_index, event_type, input_data, output_data, error
    )


def list_runs_for_automation_sync(
    automation_id: str,
    account_id: str,
    limit: int = 50,
) -> list[dict]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT id, automation_id, account_id, contact_id, conversation_id,
                   status, current_step_index, variables, wait_until, wait_type,
                   last_error, started_at, updated_at, completed_at
            FROM automation_runs
            WHERE automation_id = :automation_id
              AND account_id = :account_id
            ORDER BY started_at DESC
            LIMIT :limit
            """,
            automation_id=automation_id,
            account_id=account_id,
            limit=limit,
        )
        runs = _rows_to_dicts(conn, rows)
        for run in runs:
            run["variables"] = _parse_json(run.get("variables")) or {}
        return runs


async def list_runs_for_automation(
    automation_id: str,
    account_id: str,
    limit: int = 50,
) -> list[dict]:
    return await anyio.to_thread.run_sync(
        list_runs_for_automation_sync, automation_id, account_id, limit
    )


def get_run_sync(run_id: str, account_id: str) -> dict | None:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT id, automation_id, account_id, contact_id, conversation_id,
                   status, current_step_index, variables, wait_until, wait_type,
                   last_error, started_at, updated_at, completed_at
            FROM automation_runs
            WHERE id = :run_id AND account_id = :account_id
            LIMIT 1
            """,
            run_id=run_id,
            account_id=account_id,
        )
        run = _row_to_dict(conn, rows)
        if run:
            run["variables"] = _parse_json(run.get("variables")) or {}
        return run


def list_run_logs_sync(run_id: str, account_id: str) -> list[dict]:
    with get_sync_conn() as conn:
        run = get_run_sync(run_id, account_id)
        if not run:
            return []

        rows = conn.run(
            """
            SELECT id, run_id, step_index, node_id, event_type,
                   input, output, error, created_at
            FROM automation_run_logs
            WHERE run_id = :run_id
            ORDER BY created_at ASC
            """,
            run_id=run_id,
        )
        logs = _rows_to_dicts(conn, rows)
        for log in logs:
            log["input"] = _parse_json(log.get("input"))
            log["output"] = _parse_json(log.get("output"))
        return logs


async def get_run(run_id: str, account_id: str) -> dict | None:
    return await anyio.to_thread.run_sync(get_run_sync, run_id, account_id)


async def list_run_logs(run_id: str, account_id: str) -> list[dict] | None:
    run = await get_run(run_id, account_id)
    if not run:
        return None
    return await anyio.to_thread.run_sync(list_run_logs_sync, run_id, account_id)
