from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
import anyio
from ..db import get_sync_conn
import httpx
import asyncio
from app.config import settings
from ..services.accounts_service import get_data_by_account_id
from ..utils.general_utils import make_json_safe, normalizar_telefono_mx, e164_a_mx_movil

async def get_contacts(account_id: Optional[str] = None, limit: int = 50, offset: int = 0, search: Optional[str] = None) -> List[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(
        get_contacts_sync,
        account_id,
        limit,
        offset,
        search
    )

def get_contacts_sync(account_id: Optional[str] = None, limit: int = 50, offset: int = 0, search: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_sync_conn() as conn:
        query = """
            SELECT 
                c.*, 
                wa.display_name AS account_name, 
                ed.name AS department_name,
                COUNT(*) OVER() AS total_count
            FROM contacts c
            LEFT JOIN whatsapp_accounts wa
                ON c.account_id = wa.id
            LEFT JOIN email_departments ed
                ON wa.department_id = ed.id
            WHERE c.account_id = :account_id
            AND c.is_deleted IS NOT TRUE
            AND (
                :search::text IS NULL OR (
                    c.name ILIKE '%' || :search::text || '%' OR
                    c.phone_number ILIKE '%' || :search::text || '%' OR
                    c.wa_id ILIKE '%' || :search::text || '%'
                )
            )
            ORDER BY c.name ASC
            LIMIT :limit OFFSET :offset;
        """
        
        rows = conn.run(query, account_id=account_id, limit=limit, offset=offset, search=search)
        if not rows:
            return {
                "contacts": [],
                "total": 0,
                "page": (offset // limit) + 1,
                "total_pages": 0,
                "limit": limit,
                "offset": offset
            }
        
        column_names = [col["name"] for col in conn.columns]
        contacts = [dict(zip(column_names, row)) for row in rows]

        total = contacts[0]["total_count"]

        # asegurar que cada contacto entregue tag y tag_color al frontend
        for c in contacts:
            c.setdefault("tag", None)
            c.setdefault("tag_color", None)
            c.pop("total_count", None)

        #print("contacts: ", contacts)
        print("total_pages: ", (total + limit - 1) // limit if limit > 0 else 0)
        return {
            "contacts": contacts,
            "total": total,
            "page": (offset // limit) + 1,
            "total_pages": (total + limit - 1) // limit if limit > 0 else 0,
            "limit": limit,
            "offset": offset
        }
    
async def create_contact(name: str, area_code: str, phone_number: str, account_id: Optional[str] = None, tag: Optional[List[str]] = None, tag_color: Optional[List[str]] = None) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(
        create_contact_sync, name, area_code, phone_number, account_id, tag, tag_color
    )
        
def create_contact_sync(name: str, area_code: str, number: str, account_id: Optional[str] = None, tag: Optional[List[str]] = None, tag_color: Optional[List[str]] = None) -> Dict[str, Any]:

    phone_number = f"{area_code}{number}"
    wa_id = e164_a_mx_movil(phone_number)
    phone_number_normalized = normalizar_telefono_mx(phone_number)
    normalized_tag = tag if tag is not None else None
    normalized_tag_color = tag_color if tag_color is not None else None

    if normalized_tag is not None and not isinstance(normalized_tag, list):
        normalized_tag = [normalized_tag]
    if normalized_tag_color is not None and not isinstance(normalized_tag_color, list):
        normalized_tag_color = [normalized_tag_color]

    new_contact = True
    
    with get_sync_conn() as conn:
        rows = conn.run(
"""
                SELECT 
                    c.*, 
                    wa.display_name AS account_name,
                    ed.name AS department_name
                FROM contacts c
                LEFT JOIN whatsapp_accounts wa 
                    ON c.account_id = wa.id
                LEFT JOIN email_departments ed 
                    ON wa.department_id = ed.id
                WHERE c.wa_id = :wa_id 
                AND c.account_id = :account_id
                LIMIT 1;
            """,
            wa_id=wa_id,
            account_id=account_id
        )
        if rows:
            new_contact = False

        else: 
            query = """
                WITH inserted AS (
                    INSERT INTO contacts (wa_id, name, phone_number, account_id, tag, tag_color)
                    VALUES (:wa_id, :name, :phone_number, :account_id, :tag, :tag_color)
                    RETURNING *
                )
                SELECT 
                    inserted.*, 
                    wa.display_name AS account_name,
                    ed.name AS department_name
                FROM inserted
                LEFT JOIN whatsapp_accounts wa 
                    ON inserted.account_id = wa.id
                LEFT JOIN email_departments ed 
                    ON wa.department_id = ed.id;
            """
            rows = conn.run(
                query,
                wa_id=wa_id,
                name=name,
                phone_number=phone_number_normalized,
                account_id=account_id,
                tag=normalized_tag,
                tag_color=normalized_tag_color,
            )
        column_names = [col["name"] for col in conn.columns]
        contact = dict(zip(column_names, rows[0]))
        contact["new_contact"] = new_contact
        return contact
    
async def get_contact_account_id(contact_id: str) -> Optional[str]:
    return await anyio.to_thread.run_sync(get_contact_account_id_sync, contact_id)


def get_contact_account_id_sync(contact_id: str) -> Optional[str]:
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT account_id
            FROM contacts
            WHERE id = :contact_id
            AND is_deleted IS NOT TRUE
            LIMIT 1;
            """,
            contact_id=contact_id,
        )
        if not rows:
            return None
        return rows[0][0]

async def update_contact(contact_id: str, name: Optional[str] = None, phone_number: Optional[str] = None, account_id: Optional[str] = None, tag: Optional[List[str]] = None, tag_color: Optional[List[str]] = None) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(
        update_contact_sync, contact_id, name, phone_number, account_id, tag, tag_color
    )

def update_contact_sync(contact_id: str, name: Optional[str] = None, phone_number: Optional[str] = None, account_id: Optional[str] = None, tag: Optional[List[str]] = None, tag_color: Optional[List[str]] = None) -> Dict[str, Any]:
    normalized_tag = tag if tag is not None else None
    normalized_tag_color = tag_color if tag_color is not None else None

    if normalized_tag is not None and not isinstance(normalized_tag, list):
        normalized_tag = [normalized_tag]
    if normalized_tag_color is not None and not isinstance(normalized_tag_color, list):
        normalized_tag_color = [normalized_tag_color]

    with get_sync_conn() as conn:
        existing_contact = conn.run(
            """
            SELECT id, phone_number, wa_id, is_deleted
            FROM contacts
            WHERE id = :contact_id
              AND (is_deleted IS NULL OR is_deleted IS NOT TRUE)
            LIMIT 1;
            """,
            contact_id=contact_id,
        )
        if not existing_contact and phone_number and account_id:
            phone_number_normalized = normalizar_telefono_mx(phone_number)
            wa_id = e164_a_mx_movil(phone_number)
            existing_contact = conn.run(
                """
                SELECT id, phone_number, wa_id, is_deleted
                FROM contacts
                WHERE account_id = :account_id
                  AND (
                        phone_number = :phone_number
                        OR wa_id = :wa_id
                    )
                  AND (is_deleted IS NULL OR is_deleted IS NOT TRUE)
                LIMIT 1;
                """,
                account_id=account_id,
                phone_number=phone_number_normalized,
                wa_id=wa_id,
            )
            if existing_contact:
                contact_id = existing_contact[0][0]

        if not existing_contact:
            return {"error": "Contacto no encontrado"}

        table_columns = {
            col[0] for col in conn.run(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'contacts';
                """
            )
        }
        update_fields = [
            "name = COALESCE(:name, name)",
            "phone_number = COALESCE(:phone_number, phone_number)",
            "wa_id = COALESCE(:wa_id, wa_id)",
            "account_id = COALESCE(:account_id, account_id)",
        ]
        if "tag" in table_columns:
            update_fields.append("tag = COALESCE(:tag, tag)")
        if "tag_color" in table_columns:
            update_fields.append("tag_color = COALESCE(:tag_color, tag_color)")
        update_fields.append("updated_at = NOW()")

        phone_number_normalized = None
        wa_id = None
        if phone_number:
            phone_number_normalized = normalizar_telefono_mx(phone_number)
            wa_id = e164_a_mx_movil(phone_number)

            exists = conn.run(
                """
                SELECT 1
                FROM contacts
                WHERE account_id = :account_id
                AND id <> :contact_id
                AND (
                        phone_number = :phone_number
                        OR wa_id = :wa_id
                    )
                LIMIT 1;
                """,
                contact_id=contact_id,
                account_id=account_id,
                phone_number=phone_number_normalized,
                wa_id=wa_id
            )

            if exists:
                current = conn.run(
                    """
                    SELECT phone_number, wa_id
                    FROM contacts
                    WHERE id = :contact_id
                    LIMIT 1;
                    """,
                    contact_id=contact_id,
                )
                if not (current and current[0][0] == phone_number_normalized and current[0][1] == wa_id):
                    print("Skipping duplicate block for update", {
                        "contact_id": contact_id,
                        "phone_number": phone_number,
                        "phone_number_normalized": phone_number_normalized,
                        "wa_id": wa_id,
                        "current": current,
                    })

        set_clause = ",\n                ".join(update_fields)
        query = "UPDATE contacts SET " + set_clause + " WHERE id = :contact_id RETURNING *;"
        try:
            rows = conn.run(
                query,
                contact_id=contact_id,
                name=name,
                phone_number=phone_number_normalized,
                wa_id=wa_id,
                account_id=account_id,
                tag=normalized_tag,
                tag_color=normalized_tag_color,
            )
        except Exception as exc:
            print("update_contact_sync DB error:", repr(exc))
            raise Exception(f"Error al actualizar contacto: {exc}") from exc

        if not rows:
            return {"error": "Contacto no encontrado"}
        
        column_names = [col["name"] for col in conn.columns]
        contact = dict(zip(column_names, rows[0]))
        return contact
    
async def delete_contact(contact_id: str) -> Dict[str, Any]:
    return await anyio.to_thread.run_sync(
        delete_contact_sync, contact_id
    )

def delete_contact_sync(contact_id: str) -> Dict[str, Any]:
    with get_sync_conn() as conn:
        query = """
            UPDATE contacts
            SET is_deleted = TRUE, updated_at = NOW()
            WHERE id = :contact_id
            RETURNING *;
        """
        rows = conn.run(query, contact_id=contact_id)
        if not rows:
            return {"error": "Contacto no encontrado"}
        
        column_names = [col["name"] for col in conn.columns]
        contact = dict(zip(column_names, rows[0]))
        return contact