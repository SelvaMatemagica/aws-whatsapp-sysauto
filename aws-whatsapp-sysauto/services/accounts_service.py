import anyio
from app.db import get_sync_conn
from typing import Optional, Dict, Any, List
from ..auth import verify_user_admin
from ..utils.general_utils import make_json_safe


def _rows_to_dicts(conn, rows) -> List[Dict[str, Any]]:
    if not rows:
        return []
    column_names = [col["name"] for col in conn.columns]
    return [make_json_safe(dict(zip(column_names, row))) for row in rows]


def _row_to_dict(conn, rows) -> Optional[Dict[str, Any]]:
    data = _rows_to_dicts(conn, rows)
    return data[0] if data else None


_ACCOUNT_SELECT = """
    SELECT
        wa.*,
        ed.name AS department_name,
        mt.name AS notification_template_name
    FROM whatsapp_accounts wa
    LEFT JOIN email_departments ed ON wa.department_id = ed.id
    LEFT JOIN message_templates2 mt ON wa.notification_template_id = mt.id
"""


def get_account_id_by_phone_number_id(phone_number_id: str):
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT id FROM whatsapp_accounts WHERE phone_number_id = :phone_number_id;
            """,
            phone_number_id=phone_number_id
        )
        if not rows:
            return None

        return str(rows[0][0])


async def get_by_phone_id(phone_number_id: str):
    return await anyio.to_thread.run_sync(get_account_id_by_phone_number_id, phone_number_id)


def get_whatapp_accounts_by_user_id(user_id: str, is_admin: bool):
    with get_sync_conn() as conn:
        if is_admin:
            query = """
                SELECT
                    wa.*,
                    ed.name AS department_name,
                    mt.name AS notification_template_name,
                    NULL AS permission_created_at,
                    TRUE AS is_admin
                FROM whatsapp_accounts wa
                LEFT JOIN email_departments ed ON wa.department_id = ed.id
                LEFT JOIN message_templates2 mt ON wa.notification_template_id = mt.id
                WHERE wa.is_active = TRUE;
            """
            params = {}
        else:
            query = f"""
                SELECT
                    wa.*,
                    ed.name AS department_name,
                    mt.name AS notification_template_name,
                    uwa.created_at AS permission_created_at,
                    uwa.is_admin AS is_admin
                FROM user_whatsapp_accounts uwa
                JOIN whatsapp_accounts wa
                    ON wa.id = uwa.whatsapp_account_id
                LEFT JOIN email_departments ed ON wa.department_id = ed.id
                LEFT JOIN message_templates2 mt ON wa.notification_template_id = mt.id
                WHERE uwa.user_id = :user_id
                AND wa.is_active = TRUE;
            """
            params = {"user_id": user_id}

        rows = conn.run(query, **params)
        return _rows_to_dicts(conn, rows)


def get_whatapp_accounts_data(is_admin: bool):
    with get_sync_conn() as conn:
        if is_admin:
            query = """
                SELECT
                    wa.*,
                    ed.name AS department_name,
                    mt.name AS notification_template_name,
                    NULL AS permission_created_at,
                    TRUE AS is_admin
                FROM whatsapp_accounts wa
                LEFT JOIN email_departments ed ON wa.department_id = ed.id
                LEFT JOIN message_templates2 mt ON wa.notification_template_id = mt.id;
            """
            params = {}
        else:
            query = """
                SELECT
                    wa.*,
                    ed.name AS department_name,
                    mt.name AS notification_template_name,
                    NULL AS permission_created_at,
                    FALSE AS is_admin
                FROM whatsapp_accounts wa
                LEFT JOIN email_departments ed ON wa.department_id = ed.id
                LEFT JOIN message_templates2 mt ON wa.notification_template_id = mt.id;
            """
            params = {}

        rows = conn.run(query, **params)
        return _rows_to_dicts(conn, rows)


async def get_accounts_by_user_id(user_id: str):
    is_admin = await verify_user_admin(user_id)
    return await anyio.to_thread.run_sync(get_whatapp_accounts_by_user_id, user_id, is_admin)


def get_by_account_id(account_id: str):
    with get_sync_conn() as conn:
        rows = conn.run(
            f"""
            {_ACCOUNT_SELECT}
            WHERE wa.id = :account_id;
            """,
            account_id=account_id,
        )
        return _row_to_dict(conn, rows)


async def get_data_by_account_id(account_id: str):
    return await anyio.to_thread.run_sync(get_by_account_id, account_id)


def _phone_number_id_exists(conn, phone_number_id: str, exclude_account_id: Optional[str] = None) -> bool:
    query = """
        SELECT 1 FROM whatsapp_accounts
        WHERE phone_number_id = :phone_number_id
    """
    params = {"phone_number_id": phone_number_id}
    if exclude_account_id:
        query += " AND id <> :exclude_account_id"
        params["exclude_account_id"] = exclude_account_id
    query += " LIMIT 1;"
    return bool(conn.run(query, **params))


def _department_exists(conn, department_id: str) -> bool:
    return bool(conn.run(
        "SELECT 1 FROM email_departments WHERE id = :department_id LIMIT 1;",
        department_id=department_id,
    ))


def _notification_template_exists(conn, template_id: str) -> bool:
    return bool(conn.run(
        "SELECT 1 FROM message_templates2 WHERE id = :template_id LIMIT 1;",
        template_id=template_id,
    ))


def create_account_sync(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        if _phone_number_id_exists(conn, data["phone_number_id"]):
            return {"error": "Ya existe una cuenta con ese phone_number_id"}

        rows = conn.run(
            """
            WITH inserted AS (
                INSERT INTO whatsapp_accounts (
                    phone_number,
                    phone_number_id,
                    access_token,
                    waba_id,
                    display_name,
                    business_id,
                    app_id,
                    webhook_verify_token,
                    is_active,
                    estatus,
                    department_id
                )
                VALUES (
                    :phone_number,
                    :phone_number_id,
                    :access_token,
                    :waba_id,
                    :display_name,
                    :business_id,
                    :app_id,
                    :webhook_verify_token,
                    :is_active,
                    :estatus,
                    :department_id
                )
                RETURNING *
            )
            SELECT
                inserted.*,
                ed.name AS department_name,
                mt.name AS notification_template_name
            FROM inserted
            LEFT JOIN email_departments ed ON inserted.department_id = ed.id
            LEFT JOIN message_templates2 mt ON inserted.notification_template_id = mt.id;
            """,
            **data,
        )
        result = _row_to_dict(conn, rows)
        if not result:
            return {"error": "Error al crear la cuenta de WhatsApp"}
        return result


def update_account_sync(account_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        existing = conn.run(
            "SELECT 1 FROM whatsapp_accounts WHERE id = :account_id LIMIT 1;",
            account_id=account_id,
        )
        if not existing:
            return {"error": "Cuenta de WhatsApp no encontrada"}

        if data.get("phone_number_id") and _phone_number_id_exists(
            conn, data["phone_number_id"], exclude_account_id=account_id
        ):
            return {"error": "Ya existe una cuenta con ese phone_number_id"}

        params = {
            "phone_number": None,
            "phone_number_id": None,
            "access_token": None,
            "waba_id": None,
            "display_name": None,
            "business_id": None,
            "app_id": None,
            "webhook_verify_token": None,
            "is_active": None,
            "estatus": None,
        }
        params.update(data)

        rows = conn.run(
            """
            WITH updated AS (
                UPDATE whatsapp_accounts
                SET
                    phone_number = COALESCE(:phone_number, phone_number),
                    phone_number_id = COALESCE(:phone_number_id, phone_number_id),
                    access_token = COALESCE(:access_token, access_token),
                    waba_id = COALESCE(:waba_id, waba_id),
                    display_name = COALESCE(:display_name, display_name),
                    business_id = COALESCE(:business_id, business_id),
                    app_id = COALESCE(:app_id, app_id),
                    webhook_verify_token = COALESCE(:webhook_verify_token, webhook_verify_token),
                    is_active = COALESCE(:is_active, is_active),
                    estatus = COALESCE(:estatus, estatus),
                    updated_at = NOW()
                WHERE id = :account_id
                RETURNING *
            )
            SELECT
                updated.*,
                ed.name AS department_name,
                mt.name AS notification_template_name
            FROM updated
            LEFT JOIN email_departments ed ON updated.department_id = ed.id
            LEFT JOIN message_templates2 mt ON updated.notification_template_id = mt.id;
            """,
            account_id=account_id,
            **params,
        )
        return _row_to_dict(conn, rows)


def update_account_department_sync(account_id: str, department_id: Optional[str]) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        existing = conn.run(
            "SELECT 1 FROM whatsapp_accounts WHERE id = :account_id LIMIT 1;",
            account_id=account_id,
        )
        if not existing:
            return {"error": "Cuenta de WhatsApp no encontrada"}

        if department_id and not _department_exists(conn, department_id):
            return {"error": "Departamento no encontrado"}

        rows = conn.run(
            """
            WITH updated AS (
                UPDATE whatsapp_accounts
                SET department_id = :department_id, updated_at = NOW()
                WHERE id = :account_id
                RETURNING *
            )
            SELECT
                updated.*,
                ed.name AS department_name,
                mt.name AS notification_template_name
            FROM updated
            LEFT JOIN email_departments ed ON updated.department_id = ed.id
            LEFT JOIN message_templates2 mt ON updated.notification_template_id = mt.id;
            """,
            account_id=account_id,
            department_id=department_id,
        )
        return _row_to_dict(conn, rows)


def update_account_notification_template_sync(
    account_id: str,
    notification_template_id: Optional[str],
) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        existing = conn.run(
            "SELECT 1 FROM whatsapp_accounts WHERE id = :account_id LIMIT 1;",
            account_id=account_id,
        )
        if not existing:
            return {"error": "Cuenta de WhatsApp no encontrada"}

        if notification_template_id and not _notification_template_exists(conn, notification_template_id):
            return {"error": "Plantilla de notificación no encontrada"}

        rows = conn.run(
            """
            WITH updated AS (
                UPDATE whatsapp_accounts
                SET notification_template_id = :notification_template_id, updated_at = NOW()
                WHERE id = :account_id
                RETURNING *
            )
            SELECT
                updated.*,
                ed.name AS department_name,
                mt.name AS notification_template_name
            FROM updated
            LEFT JOIN email_departments ed ON updated.department_id = ed.id
            LEFT JOIN message_templates2 mt ON updated.notification_template_id = mt.id;
            """,
            account_id=account_id,
            notification_template_id=notification_template_id,
        )
        return _row_to_dict(conn, rows)


def delete_account_sync(account_id: str) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            WITH updated AS (
                UPDATE whatsapp_accounts
                SET is_active = FALSE, estatus = 'inactivo', updated_at = NOW()
                WHERE id = :account_id
                RETURNING *
            )
            SELECT
                updated.*,
                ed.name AS department_name,
                mt.name AS notification_template_name
            FROM updated
            LEFT JOIN email_departments ed ON updated.department_id = ed.id
            LEFT JOIN message_templates2 mt ON updated.notification_template_id = mt.id;
            """,
            account_id=account_id,
        )
        if not rows:
            return {"error": "Cuenta de WhatsApp no encontrada"}
        return _row_to_dict(conn, rows)


async def create_account(data: Dict[str, Any]) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(create_account_sync, data)


async def update_account(account_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(update_account_sync, account_id, data)


async def update_account_department(account_id: str, department_id: Optional[str]) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(update_account_department_sync, account_id, department_id)


async def update_account_notification_template(
    account_id: str,
    notification_template_id: Optional[str],
) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(
        update_account_notification_template_sync,
        account_id,
        notification_template_id,
    )


async def delete_account(account_id: str) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(delete_account_sync, account_id)


async def get_active_phone_number_ids():
    def get_active_phone_number_ids_sync():
        with get_sync_conn() as conn:
            query = """
                SELECT phone_number_id FROM whatsapp_accounts WHERE is_active = TRUE;
            """
            rows = conn.run(query)
            if not rows:
                return []
            return [row[0] for row in rows]
    return await anyio.to_thread.run_sync(get_active_phone_number_ids_sync)


def get_departments_sync() -> List[Dict[str, Any]]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT *
            FROM email_departments
            ORDER BY name ASC;
            """
        )
        return _rows_to_dicts(conn, rows)


async def get_departments() -> List[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(get_departments_sync)


def get_department_by_id_sync(department_id: str) -> Optional[Dict[str, Any]]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT *
            FROM email_departments
            WHERE id = :department_id
            LIMIT 1;
            """,
            department_id=department_id,
        )
        return _row_to_dict(conn, rows)


async def get_department_by_id(department_id: str) -> Optional[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(get_department_by_id_sync, department_id)
