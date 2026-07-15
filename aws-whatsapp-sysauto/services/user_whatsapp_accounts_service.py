from typing import Dict, Any, List, Optional
import anyio
from ..db import get_sync_conn
from ..utils.general_utils import make_json_safe


def _rows_to_dicts(conn, rows) -> List[Dict[str, Any]]:
    if not rows:
        return []
    column_names = [col["name"] for col in conn.columns]
    return [make_json_safe(dict(zip(column_names, row))) for row in rows]


def _row_to_dict(conn, rows) -> Optional[Dict[str, Any]]:
    data = _rows_to_dicts(conn, rows)
    return data[0] if data else None


def get_users_by_account_id_sync(account_id: str) -> List[Dict[str, Any]]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT
                uwa.id,
                uwa.user_id,
                uwa.whatsapp_account_id,
                uwa.created_at,
                uwa.is_admin,
                uwa.can_receive_notifications,
                u.name,
                u.email,
                u.role,
                u.estatus,
                u.phone,
                u.department
            FROM user_whatsapp_accounts uwa
            JOIN users u ON u.id = uwa.user_id
            WHERE uwa.whatsapp_account_id = :account_id
            ORDER BY uwa.created_at ASC;
            """,
            account_id=account_id,
        )
        return _rows_to_dicts(conn, rows)


def get_notification_recipients_sync(account_id: str) -> List[Dict[str, Any]]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT
                u.id AS user_id,
                u.name,
                u.email,
                u.phone,
                uwa.is_admin,
                uwa.can_receive_notifications,
                uwa.created_at
            FROM user_whatsapp_accounts uwa
            JOIN users u ON u.id = uwa.user_id
            JOIN whatsapp_accounts wa ON wa.id = uwa.whatsapp_account_id
            WHERE uwa.whatsapp_account_id = :account_id
                AND uwa.can_receive_notifications = TRUE
                AND u.authorized = TRUE
                AND u.estatus = 'activo'
                AND wa.is_active = TRUE
                /* AND wa.estatus = 'activo' */
            ORDER BY u.name ASC;
            """,
            account_id=account_id,
        )
        return _rows_to_dicts(conn, rows)


def _account_exists(conn, account_id: str) -> bool:
    rows = conn.run(
        "SELECT 1 FROM whatsapp_accounts WHERE id = :account_id LIMIT 1;",
        account_id=account_id,
    )
    return bool(rows)


def _user_exists_and_active(conn, user_id: str) -> bool:
    rows = conn.run(
        """
        SELECT 1 FROM users
        WHERE id = :user_id
            AND authorized = TRUE
            AND estatus = 'activo'
        LIMIT 1;
        """,
        user_id=user_id,
    )
    return bool(rows)


def create_permission_sync(
    account_id: str,
    user_id: str,
    is_admin: bool = False,
    can_receive_notifications: bool = False,
) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        if not _account_exists(conn, account_id):
            return {"error": "Cuenta de WhatsApp no encontrada"}

        if not _user_exists_and_active(conn, user_id):
            return {"error": "Usuario no encontrado o no está activo"}

        existing = conn.run(
            """
            SELECT 1 FROM user_whatsapp_accounts
            WHERE user_id = :user_id
                AND whatsapp_account_id = :account_id
            LIMIT 1;
            """,
            user_id=user_id,
            account_id=account_id,
        )
        if existing:
            return {"error": "El usuario ya tiene acceso a esta cuenta"}

        rows = conn.run(
            """
            WITH inserted AS (
                INSERT INTO user_whatsapp_accounts (
                    user_id,
                    whatsapp_account_id,
                    is_admin,
                    can_receive_notifications
                )
                VALUES (
                    :user_id,
                    :account_id,
                    :is_admin,
                    :can_receive_notifications
                )
                RETURNING *
            )
            SELECT
                inserted.*,
                u.name,
                u.email,
                u.role,
                u.estatus
            FROM inserted
            JOIN users u ON u.id = inserted.user_id;
            """,
            user_id=user_id,
            account_id=account_id,
            is_admin=is_admin,
            can_receive_notifications=can_receive_notifications,
        )
        result = _row_to_dict(conn, rows)
        if not result:
            return {"error": "Error al otorgar acceso"}
        return result


def update_permission_sync(
    account_id: str,
    user_id: str,
    is_admin: Optional[bool] = None,
    can_receive_notifications: Optional[bool] = None,
) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            UPDATE user_whatsapp_accounts
            SET
                is_admin = COALESCE(:is_admin, is_admin),
                can_receive_notifications = COALESCE(:can_receive_notifications, can_receive_notifications)
            WHERE user_id = :user_id
                AND whatsapp_account_id = :account_id
            RETURNING *;
            """,
            user_id=user_id,
            account_id=account_id,
            is_admin=is_admin,
            can_receive_notifications=can_receive_notifications,
        )
        if not rows:
            return {"error": "Permiso no encontrado"}

        permission = _row_to_dict(conn, rows)
        user_rows = conn.run(
            "SELECT name, email, role, estatus FROM users WHERE id = :user_id LIMIT 1;",
            user_id=user_id,
        )
        if user_rows:
            permission["name"] = user_rows[0][0]
            permission["email"] = user_rows[0][1]
            permission["role"] = user_rows[0][2]
            permission["estatus"] = user_rows[0][3]
        return permission


def delete_permission_sync(account_id: str, user_id: str) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            DELETE FROM user_whatsapp_accounts
            WHERE user_id = :user_id
                AND whatsapp_account_id = :account_id
            RETURNING *;
            """,
            user_id=user_id,
            account_id=account_id,
        )
        if not rows:
            return {"error": "Permiso no encontrado"}
        return _row_to_dict(conn, rows)


def get_users_with_whatsapp_access_sync() -> List[Dict[str, Any]]:
    with get_sync_conn() as conn:
        users_rows = conn.run(
            """
            SELECT
                u.id,
                u.name,
                u.email,
                u.role,
                u.authorized,
                u.estatus,
                u.created_at
            FROM users u
            WHERE u.estatus != 'eliminado'
            ORDER BY u.name ASC;
            """
        )
        if not users_rows:
            return []

        users = _rows_to_dicts(conn, users_rows)
        users_by_id = {user["id"]: user for user in users}
        for user in users:
            user["has_full_access"] = user["role"] == "admin"
            user["whatsapp_accounts"] = []

        permissions_rows = conn.run(
            """
            SELECT
                uwa.user_id,
                uwa.whatsapp_account_id,
                uwa.is_admin,
                uwa.can_receive_notifications,
                uwa.created_at AS permission_created_at,
                wa.phone_number,
                wa.phone_number_id,
                wa.display_name,
                wa.is_active,
                wa.estatus AS account_estatus
            FROM user_whatsapp_accounts uwa
            JOIN whatsapp_accounts wa ON wa.id = uwa.whatsapp_account_id
            ORDER BY wa.display_name ASC NULLS LAST, wa.phone_number ASC;
            """
        )
        for row in _rows_to_dicts(conn, permissions_rows):
            user = users_by_id.get(row["user_id"])
            if not user:
                continue
            user["whatsapp_accounts"].append({
                "whatsapp_account_id": row["whatsapp_account_id"],
                "phone_number": row["phone_number"],
                "phone_number_id": row["phone_number_id"],
                "display_name": row["display_name"],
                "is_active": row["is_active"],
                "estatus": row["account_estatus"],
                "is_admin": row["is_admin"],
                "can_receive_notifications": row["can_receive_notifications"],
                "permission_created_at": row["permission_created_at"],
            })

        all_accounts_rows = conn.run(
            """
            SELECT
                id AS whatsapp_account_id,
                phone_number,
                phone_number_id,
                display_name,
                is_active,
                estatus
            FROM whatsapp_accounts
            WHERE is_active = TRUE
            ORDER BY display_name ASC NULLS LAST, phone_number ASC;
            """
        )
        all_accounts = _rows_to_dicts(conn, all_accounts_rows)

        for user in users:
            if not user["has_full_access"]:
                continue
            user["whatsapp_accounts"] = [
                {
                    **account,
                    "is_admin": True,
                    "can_receive_notifications": False,
                    "permission_created_at": None,
                }
                for account in all_accounts
            ]

        return users


async def get_users_by_account_id(account_id: str) -> List[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(get_users_by_account_id_sync, account_id)


async def get_users_with_whatsapp_access() -> List[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(get_users_with_whatsapp_access_sync)


async def get_notification_recipients(account_id: str) -> List[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(get_notification_recipients_sync, account_id)


async def create_permission(
    account_id: str,
    user_id: str,
    is_admin: bool = False,
    can_receive_notifications: bool = False,
) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(
        create_permission_sync,
        account_id,
        user_id,
        is_admin,
        can_receive_notifications,
    )


async def update_permission(
    account_id: str,
    user_id: str,
    is_admin: Optional[bool] = None,
    can_receive_notifications: Optional[bool] = None,
) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(
        update_permission_sync,
        account_id,
        user_id,
        is_admin,
        can_receive_notifications,
    )


async def delete_permission(account_id: str, user_id: str) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(delete_permission_sync, account_id, user_id)
