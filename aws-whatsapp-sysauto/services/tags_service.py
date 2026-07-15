import uuid
from typing import List, Dict, Any, Optional
import anyio
from ..db import get_sync_conn


def _rows_to_dicts(conn, rows) -> List[Dict[str, Any]]:
    if not rows:
        return []
    column_names = [col["name"] for col in conn.columns]
    return [dict(zip(column_names, row)) for row in rows]


def _row_to_dict(conn, rows) -> Optional[Dict[str, Any]]:
    data = _rows_to_dicts(conn, rows)
    return data[0] if data else None


def ensure_tags_table(conn):
    conn.run(
        """
        CREATE TABLE IF NOT EXISTS tags (
            id UUID PRIMARY KEY,
            account_id UUID REFERENCES whatsapp_accounts(id),
            name TEXT NOT NULL,
            color TEXT,
            is_deleted BOOLEAN DEFAULT FALSE,
            estatus VARCHAR(50) DEFAULT 'active',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )


def get_tags_sync(account_id: str) -> List[Dict[str, Any]]:
    with get_sync_conn() as conn:
        ensure_tags_table(conn)
        rows = conn.run(
            """
            SELECT *
            FROM tags
            WHERE account_id = :account_id
              AND is_deleted IS NOT TRUE
            ORDER BY name ASC;
            """,
            account_id=account_id,
        )
        return _rows_to_dicts(conn, rows)


async def get_tags(account_id: str) -> List[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(get_tags_sync, account_id)


def create_tag_sync(name: str, color: Optional[str], account_id: str) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        ensure_tags_table(conn)
        tag_id = str(uuid.uuid4())
        rows = conn.run(
            """
            INSERT INTO tags (id, account_id, name, color)
            VALUES (:id, :account_id, :name, :color)
            RETURNING *;
            """,
            id=tag_id,
            account_id=account_id,
            name=name,
            color=color,
        )
        return _row_to_dict(conn, rows)


async def create_tag(name: str, color: Optional[str], account_id: str) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(create_tag_sync, name, color, account_id)


def update_tag_sync(tag_id: str, name: Optional[str], color: Optional[str], account_id: str) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        ensure_tags_table(conn)
        rows = conn.run(
            """
            UPDATE tags
            SET
                name = COALESCE(:name, name),
                color = COALESCE(:color, color),
                updated_at = NOW()
            WHERE id = :tag_id
              AND account_id = :account_id
              AND is_deleted IS NOT TRUE
            RETURNING *;
            """,
            tag_id=tag_id,
            name=name,
            color=color,
            account_id=account_id,
        )
        return _row_to_dict(conn, rows)


async def update_tag(tag_id: str, name: Optional[str], color: Optional[str], account_id: str) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(update_tag_sync, tag_id, name, color, account_id)


def delete_tag_sync(tag_id: str, account_id: str) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        ensure_tags_table(conn)
        rows = conn.run(
            """
            UPDATE tags
            SET is_deleted = TRUE, updated_at = NOW()
            WHERE id = :tag_id
              AND account_id = :account_id
              AND is_deleted IS NOT TRUE
            RETURNING *;
            """,
            tag_id=tag_id,
            account_id=account_id,
        )
        return _row_to_dict(conn, rows)


async def delete_tag(tag_id: str, account_id: str) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(delete_tag_sync, tag_id, account_id)
