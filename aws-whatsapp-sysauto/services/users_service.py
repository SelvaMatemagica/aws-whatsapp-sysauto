import json
import hashlib
import secrets
import string
import anyio
import httpx
#from typing import list
from app.db import get_sync_conn
from app.config import settings
from ..utils.general_utils import make_json_safe
from typing import Optional, Dict, Any


def generar_cadena(longitud=12):
    caracteres = string.ascii_letters + string.digits + "!@#$%^&*()"
    return "".join(secrets.choice(caracteres) for _ in range(longitud))

# -------------- Public: get user by phone from DB -----------------
def get_user_by_phone_sync(number: str, account_id: str):
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT *
            FROM contacts
            WHERE phone_number = :phone_number
            AND account_id = :account_id
            LIMIT 1;
            """,
            phone_number=number,
            account_id=account_id,
            output_format="dict"
        )
        if not rows:
            return None
        #r = rows[0]
        column_names = [col["name"] for col in conn.columns]
        # 🔹 mapear filas a dicts
        data = [dict(zip(column_names, fila)) for fila in rows]
        return data[0]

async def get_by_phone(number: str, account_id: str):
    return await anyio.to_thread.run_sync(get_user_by_phone_sync, number, account_id)


def _email_exists(conn, email: str) -> bool:
    rows = conn.run(
        """
        SELECT 1 FROM users
        WHERE email = :email
            AND estatus != 'eliminado'
        LIMIT 1;
        """,
        email=email,
    )
    return bool(rows)


def _department_exists(conn, department_id: str) -> bool:
    rows = conn.run(
        "SELECT 1 FROM email_departments WHERE id = :department_id LIMIT 1;",
        department_id=department_id,
    )
    return bool(rows)


def _account_exists(conn, account_id: str) -> bool:
    rows = conn.run(
        "SELECT 1 FROM whatsapp_accounts WHERE id = :account_id LIMIT 1;",
        account_id=account_id,
    )
    return bool(rows)


def _upsert_permission(
    conn,
    user_id: str,
    account_id: str,
    is_admin: Optional[bool] = None,
    can_receive_notifications: Optional[bool] = None,
) -> None:
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
        conn.run(
            """
            UPDATE user_whatsapp_accounts
            SET is_admin = COALESCE(:is_admin, is_admin),
                can_receive_notifications = COALESCE(:can_receive_notifications, can_receive_notifications)
            WHERE user_id = :user_id
                AND whatsapp_account_id = :account_id;
            """,
            user_id=user_id,
            account_id=account_id,
            is_admin=is_admin,
            can_receive_notifications=can_receive_notifications,
        )
    else:
        conn.run(
            """
            INSERT INTO user_whatsapp_accounts (user_id, whatsapp_account_id, is_admin, can_receive_notifications)
            VALUES (:user_id, :account_id, COALESCE(:is_admin, FALSE), COALESCE(:can_receive_notifications, FALSE));
            """,
            user_id=user_id,
            account_id=account_id,
            is_admin=is_admin,
            can_receive_notifications=can_receive_notifications,
        )


def create_user_sync(
    name: str,
    email: str,
    password: str,
    phone: Optional[str] = None,
    department: Optional[str] = None,
    role: str = "user",
    authorized: bool = True,
    account_id: Optional[str] = None,
    is_admin: bool = False,
    can_receive_notifications: bool = False,
) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        if _email_exists(conn, email):
            return {"error": "El correo ya está registrado"}

        if department and not _department_exists(conn, department):
            return {"error": "Departamento no encontrado"}

        if account_id and not _account_exists(conn, account_id):
            return {"error": "Cuenta de WhatsApp no encontrada"}

        hashed_password = hashlib.sha256(password.encode("utf-8")).hexdigest()

        rows = conn.run(
            """
            WITH inserted AS (
                INSERT INTO users (name, email, password, phone, department, role, authorized)
                VALUES (:name, :email, :password, :phone, :department, :role, :authorized)
                RETURNING id, name, email, phone, department, role, authorized, estatus, created_at
            )
            SELECT
                inserted.id,
                inserted.name,
                inserted.email,
                inserted.phone,
                inserted.department,
                inserted.role,
                inserted.authorized,
                inserted.estatus,
                inserted.created_at,
                ed.name AS department_name
            FROM inserted
            LEFT JOIN email_departments ed ON ed.id = inserted.department;
            """,
            name=name,
            email=email,
            password=hashed_password,
            phone=phone,
            department=department,
            role=role,
            authorized=authorized,
        )
        if not rows:
            return {"error": "Error al crear usuario"}

        column_names = [col["name"] for col in conn.columns]
        user = make_json_safe(dict(zip(column_names, rows[0])))

        if account_id:
            _upsert_permission(
                conn,
                user_id=user["id"],
                account_id=account_id,
                is_admin=is_admin,
                can_receive_notifications=can_receive_notifications,
            )

        return user


async def create_user(
    name: str,
    email: str,
    password: str,
    phone: Optional[str] = None,
    department: Optional[str] = None,
    role: str = "user",
    authorized: bool = True,
    account_id: Optional[str] = None,
    is_admin: bool = False,
    can_receive_notifications: bool = False,
) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(
        create_user_sync,
        name,
        email,
        password,
        phone,
        department,
        role,
        authorized,
        account_id,
        is_admin,
        can_receive_notifications,
    )


def update_user_sync(user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(data)
    account_id = data.pop("account_id", None)
    is_admin = data.pop("is_admin", None)
    can_receive_notifications = data.pop("can_receive_notifications", None)

    with get_sync_conn() as conn:
        existing = conn.run(
            """
            SELECT 1 FROM users
            WHERE id = :user_id
                AND estatus != 'eliminado'
            LIMIT 1;
            """,
            user_id=user_id,
        )
        if not existing:
            return {"error": "Usuario no encontrado"}

        if account_id and not _account_exists(conn, account_id):
            return {"error": "Cuenta de WhatsApp no encontrada"}

        if data.get("email"):
            email_rows = conn.run(
                """
                SELECT 1 FROM users
                WHERE email = :email
                    AND id <> :user_id
                    AND estatus != 'eliminado'
                LIMIT 1;
                """,
                email=data["email"],
                user_id=user_id,
            )
            if email_rows:
                return {"error": "El correo ya está registrado"}

        if data.get("department") and not _department_exists(conn, data["department"]):
            return {"error": "Departamento no encontrado"}

        password = data.get("password")
        hashed_password = (
            hashlib.sha256(password.encode("utf-8")).hexdigest() if password else None
        )

        params = {
            "name": None,
            "email": None,
            "password": None,
            "phone": None,
            "department": None,
            "role": None,
            "authorized": None,
            "estatus": None,
        }
        params.update(data)
        params["password"] = hashed_password

        rows = conn.run(
            """
            WITH updated AS (
                UPDATE users
                SET
                    name = COALESCE(:name, name),
                    email = COALESCE(:email, email),
                    password = COALESCE(:password, password),
                    phone = COALESCE(:phone, phone),
                    department = COALESCE(:department, department),
                    role = COALESCE(:role, role),
                    authorized = COALESCE(:authorized, authorized),
                    estatus = COALESCE(:estatus, estatus)
                WHERE id = :user_id
                RETURNING id, name, email, phone, department, role, authorized, estatus, created_at
            )
            SELECT
                updated.id,
                updated.name,
                updated.email,
                updated.phone,
                updated.department,
                updated.role,
                updated.authorized,
                updated.estatus,
                updated.created_at,
                ed.name AS department_name
            FROM updated
            LEFT JOIN email_departments ed ON ed.id = updated.department;
            """,
            user_id=user_id,
            **params,
        )
        if not rows:
            return {"error": "Error al actualizar usuario"}

        column_names = [col["name"] for col in conn.columns]
        user = make_json_safe(dict(zip(column_names, rows[0])))

        if account_id:
            _upsert_permission(
                conn,
                user_id=user_id,
                account_id=account_id,
                is_admin=is_admin,
                can_receive_notifications=can_receive_notifications,
            )

        return user


def delete_user_sync(user_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            UPDATE users
            SET estatus = 'eliminado', authorized = FALSE
            WHERE id = :user_id
                AND estatus != 'eliminado'
            RETURNING id;
            """,
            user_id=user_id,
        )
        if not rows:
            return {"error": "Usuario no encontrado"}

        if account_id:
            conn.run(
                """
                DELETE FROM user_whatsapp_accounts
                WHERE user_id = :user_id
                    AND whatsapp_account_id = :account_id;
                """,
                user_id=user_id,
                account_id=account_id,
            )
        #else:
        #    conn.run(
        #        """
        #        DELETE FROM user_whatsapp_accounts
        #        WHERE user_id = :user_id;
        #        """,
        #        user_id=user_id,
        #    )

        return {"id": str(rows[0][0])}


async def update_user(user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(update_user_sync, user_id, data)


async def delete_user(user_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(delete_user_sync, user_id, account_id)

