import json
import uuid
from typing import Any, Optional

import anyio

from app.db import get_sync_conn
from app.utils.general_utils import make_json_safe

_AUTOMATION_SELECT = """
    SELECT
        id, account_id, name, description, status, priority, trigger_type,
        trigger_config, actions, graph, current_version, stop_on_human_reply,
        created_by, created_at, updated_at
    FROM automations
"""


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


def _normalize_automation(automation: dict | None) -> dict | None:
    if not automation:
        return None
    automation["trigger_config"] = _parse_json(automation.get("trigger_config")) or {}
    automation["actions"] = _parse_json(automation.get("actions")) or []
    automation["graph"] = _parse_json(automation.get("graph"))
    return automation


def list_automations_sync(
    account_id: str,
    status: Optional[str] = None,
    include_archived: bool = False,
) -> list[dict]:
    with get_sync_conn() as conn:
        query = f"""
            {_AUTOMATION_SELECT}
            WHERE account_id = :account_id
        """
        params: dict[str, Any] = {"account_id": account_id}

        if status:
            query += " AND status = :status"
            params["status"] = status
        elif not include_archived:
            query += " AND status <> 'archived'"

        query += " ORDER BY priority ASC, created_at DESC"
        rows = conn.run(query, **params)
        automations = _rows_to_dicts(conn, rows)
        return [_normalize_automation(a) for a in automations]


def get_automation_sync(automation_id: str, account_id: str) -> dict | None:
    with get_sync_conn() as conn:
        rows = conn.run(
            f"""
            {_AUTOMATION_SELECT}
            WHERE id = :automation_id AND account_id = :account_id
            LIMIT 1
            """,
            automation_id=automation_id,
            account_id=account_id,
        )
        return _normalize_automation(_row_to_dict(conn, rows))


def create_automation_sync(
    account_id: str,
    name: str,
    trigger_type: str,
    trigger_config: dict,
    actions: list,
    created_by: Optional[str] = None,
    description: Optional[str] = None,
    priority: int = 100,
    graph: Optional[dict] = None,
    stop_on_human_reply: bool = True,
    status: str = "draft",
) -> dict:
    automation_id = str(uuid.uuid4())
    with get_sync_conn() as conn:
        rows = conn.run(
            f"""
            INSERT INTO automations (
                id, account_id, name, description, status, priority,
                trigger_type, trigger_config, actions, graph,
                stop_on_human_reply, created_by
            )
            VALUES (
                :id, :account_id, :name, :description, :status, :priority,
                :trigger_type, :trigger_config::jsonb, :actions::jsonb, :graph::jsonb,
                :stop_on_human_reply, :created_by
            )
            RETURNING
                id, account_id, name, description, status, priority, trigger_type,
                trigger_config, actions, graph, current_version, stop_on_human_reply,
                created_by, created_at, updated_at
            """,
            id=automation_id,
            account_id=account_id,
            name=name,
            description=description,
            status=status,
            priority=priority,
            trigger_type=trigger_type,
            trigger_config=json.dumps(trigger_config),
            actions=json.dumps(actions),
            graph=json.dumps(graph) if graph else None,
            stop_on_human_reply=stop_on_human_reply,
            created_by=created_by,
        )
        return _normalize_automation(_row_to_dict(conn, rows))


def update_automation_sync(
    automation_id: str,
    account_id: str,
    updates: dict[str, Any],
) -> dict | None:
    if not updates:
        return get_automation_sync(automation_id, account_id)

    set_clauses = ["updated_at = NOW()"]
    params: dict[str, Any] = {
        "automation_id": automation_id,
        "account_id": account_id,
    }

    field_map = {
        "name": "name",
        "description": "description",
        "status": "status",
        "priority": "priority",
        "trigger_type": "trigger_type",
        "stop_on_human_reply": "stop_on_human_reply",
    }
    json_fields = {"trigger_config", "actions", "graph"}

    for key, column in field_map.items():
        if key in updates and updates[key] is not None:
            set_clauses.append(f"{column} = :{key}")
            params[key] = updates[key]

    for key in json_fields:
        if key in updates and updates[key] is not None:
            set_clauses.append(f"{key} = :{key}::jsonb")
            params[key] = json.dumps(updates[key])

    with get_sync_conn() as conn:
        rows = conn.run(
            f"""
            UPDATE automations
            SET {", ".join(set_clauses)}
            WHERE id = :automation_id AND account_id = :account_id
            RETURNING
                id, account_id, name, description, status, priority, trigger_type,
                trigger_config, actions, graph, current_version, stop_on_human_reply,
                created_by, created_at, updated_at
            """,
            **params,
        )
        return _normalize_automation(_row_to_dict(conn, rows))


def archive_automation_sync(automation_id: str, account_id: str) -> dict | None:
    return update_automation_sync(
        automation_id,
        account_id,
        {"status": "archived"},
    )


def publish_automation_sync(
    automation_id: str,
    account_id: str,
    published_by: Optional[str] = None,
) -> dict | None:
    with get_sync_conn() as conn:
        current = conn.run(
            f"""
            {_AUTOMATION_SELECT}
            WHERE id = :automation_id AND account_id = :account_id
            LIMIT 1
            """,
            automation_id=automation_id,
            account_id=account_id,
        )
        automation = _normalize_automation(_row_to_dict(conn, current))
        if not automation:
            return None

        new_version = int(automation.get("current_version") or 0) + 1
        conn.run(
            """
            INSERT INTO automation_versions (
                automation_id, version, trigger_type, trigger_config, actions, graph, published_by
            )
            VALUES (
                :automation_id, :version, :trigger_type, :trigger_config::jsonb,
                :actions::jsonb, :graph::jsonb, :published_by
            )
            """,
            automation_id=automation_id,
            version=new_version,
            trigger_type=automation["trigger_type"],
            trigger_config=json.dumps(automation["trigger_config"]),
            actions=json.dumps(automation["actions"]),
            graph=json.dumps(automation.get("graph")) if automation.get("graph") else None,
            published_by=published_by,
        )

        rows = conn.run(
            f"""
            UPDATE automations
            SET status = 'active',
                current_version = :version,
                updated_at = NOW()
            WHERE id = :automation_id AND account_id = :account_id
            RETURNING
                id, account_id, name, description, status, priority, trigger_type,
                trigger_config, actions, graph, current_version, stop_on_human_reply,
                created_by, created_at, updated_at
            """,
            automation_id=automation_id,
            account_id=account_id,
            version=new_version,
        )
        return _normalize_automation(_row_to_dict(conn, rows))


def pause_automation_sync(automation_id: str, account_id: str) -> dict | None:
    return update_automation_sync(
        automation_id,
        account_id,
        {"status": "paused"},
    )


def get_active_automations_sync(account_id: str, trigger_type: str) -> list[dict]:
    with get_sync_conn() as conn:
        rows = conn.run(
            f"""
            {_AUTOMATION_SELECT}
            WHERE account_id = :account_id
              AND trigger_type = :trigger_type
              AND status = 'active'
            ORDER BY priority ASC, created_at ASC
            """,
            account_id=account_id,
            trigger_type=trigger_type,
        )
        automations = _rows_to_dicts(conn, rows)
        return [_normalize_automation(a) for a in automations]


async def list_automations(
    account_id: str,
    status: Optional[str] = None,
    include_archived: bool = False,
) -> list[dict]:
    return await anyio.to_thread.run_sync(
        list_automations_sync, account_id, status, include_archived
    )


async def get_automation(automation_id: str, account_id: str) -> dict | None:
    return await anyio.to_thread.run_sync(get_automation_sync, automation_id, account_id)


async def create_automation(**kwargs) -> dict:
    return await anyio.to_thread.run_sync(lambda: create_automation_sync(**kwargs))


async def update_automation(
    automation_id: str,
    account_id: str,
    updates: dict[str, Any],
) -> dict | None:
    return await anyio.to_thread.run_sync(
        update_automation_sync, automation_id, account_id, updates
    )


async def archive_automation(automation_id: str, account_id: str) -> dict | None:
    return await anyio.to_thread.run_sync(archive_automation_sync, automation_id, account_id)


async def publish_automation(
    automation_id: str,
    account_id: str,
    published_by: Optional[str] = None,
) -> dict | None:
    return await anyio.to_thread.run_sync(
        publish_automation_sync, automation_id, account_id, published_by
    )


async def pause_automation(automation_id: str, account_id: str) -> dict | None:
    return await anyio.to_thread.run_sync(pause_automation_sync, automation_id, account_id)


async def get_active_automations(account_id: str, trigger_type: str) -> list[dict]:
    return await anyio.to_thread.run_sync(
        get_active_automations_sync, account_id, trigger_type
    )
