import asyncio
import base64
import hashlib
import json
import secrets
import string
import sys
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path 
from typing import Any, Optional
 
ROOT = Path(__file__).resolve().parent
VENDOR_ROOT = ROOT / "vendor"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(VENDOR_ROOT))

import boto3     

from jose import jwt 

IMPORT_ERRORS: dict[str, str] = {}

try:
    from auth import verify_account_permission
except Exception as exc:
    verify_account_permission = None 
    IMPORT_ERRORS["auth"] = str(exc)

try:
    from config import settings
except Exception as exc:
    settings = None
    IMPORT_ERRORS["config"] = str(exc)

try:
    from db import get_sync_conn
except Exception as exc:
    get_sync_conn = None
    IMPORT_ERRORS["db"] = str(exc)

try:
    from automations.engine.registry import ACTION_REGISTRY
except Exception as exc:
    ACTION_REGISTRY = {}
    IMPORT_ERRORS["automations_registry"] = str(exc)

try:
    from automations.services import automations_service, conversation_automation_service
except Exception as exc:
    automations_service = None
    conversation_automation_service = None
    IMPORT_ERRORS["automations_services"] = str(exc)

try:
    from services import business, contacts_service, tags_service, templates_service, users_service
except Exception as exc:
    business = None
    contacts_service = None
    tags_service = None
    templates_service = None
    users_service = None
    IMPORT_ERRORS["lambda_services"] = str(exc)

try:
    from services.accounts_service import (
        create_account,
        get_accounts_by_user_id,
        get_data_by_account_id,
        get_departments,
        get_department_by_id,
        get_whatapp_accounts_data,
        update_account,
        update_account_department,
    )
except Exception as exc:
    create_account = None
    get_accounts_by_user_id = None
    get_data_by_account_id = None
    get_departments = None
    get_department_by_id = None
    get_whatapp_accounts_data = None
    update_account = None
    update_account_department = None
    IMPORT_ERRORS["accounts_service"] = str(exc)

try:
    from services.conversations_service import conversation_service
except Exception as exc:
    conversation_service = None
    IMPORT_ERRORS["conversation_service"] = str(exc)

s3 = boto3.client("s3")
BUCKET = "email-metrics-control"
S3_REGION = "us-east-2"
s3_client = boto3.client("s3", region_name=S3_REGION)


def normalize_json(obj):
    if isinstance(obj, list):
        return [normalize_json(i) for i in obj]
    if isinstance(obj, dict):
        return {k: normalize_json(v) for k, v in obj.items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    return obj


def guardar_json_en_s3(data, prefix):
    key = f"data-to-json/{prefix}/{uuid.uuid4()}.json"
    body = json.dumps(normalize_json(data), ensure_ascii=False)
    s3_client.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=body,
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )
    return {"url": f"https://{BUCKET}.s3.{S3_REGION}.amazonaws.com/{key}", "key": key}


def eliminar_archivo_s3(bucket, key):
    try:
        s3_client.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass


def response(status: int, body: Any, method: str = "GET"):
    return {
        "statusCode": status,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
        "body": json.dumps(body, default=isoformat),
    }


def isoformat(o):
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, uuid.UUID):
        return str(o)
    return o


def parse_event_body(event: dict) -> dict:
    raw_body = event.get("body")
    headers = event.get("headers", {})
    content_type = headers.get("content-type") or headers.get("Content-Type")
    body = {}

    if raw_body and event.get("isBase64Encoded", False):
        raw_body = base64.b64decode(raw_body)

    if raw_body and content_type and "application/json" in content_type.lower():
        try:
            if isinstance(raw_body, str):
                body = json.loads(raw_body.strip())
            else:
                body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            body = {}

    return body


def get_actor(event: dict) -> Optional[dict]:
    headers = event.get("headers") or {}
    auth_header = headers.get("Authorization") or headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"], audience=settings.JWT_AUDIENCE or "core-api-whatsapp")
            user_id = payload.get("sub")
            if user_id:
                return {"id": user_id, "payload": payload}
        except Exception:
            return None
    params = event.get("queryStringParameters") or {}
    user_id = params.get("user_id")
    if user_id:
        return {"id": user_id}
    return None


def generate_token(user_id: str, expires_in_hours: int = 168) -> str:
    payload = {
        "sub": user_id,
        "aud": settings.JWT_AUDIENCE or "core-api-whatsapp",
        "exp": int(time.time()) + (expires_in_hours * 3600),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def generar_cadena(longitud=12):
    caracteres = string.ascii_letters + string.digits + "!@#$%^&*()"
    return "".join(secrets.choice(caracteres) for _ in range(longitud))


async def login_handler(event: dict, body: dict):
    def log_in_user(payload: dict):
        with get_sync_conn() as conn:
            payload["password"] = hashlib.sha256(payload["password"].encode("utf-8")).hexdigest()
            filas = conn.run(
                """
                SELECT u.id, u.name, u.email, u.role, u.authorized, u.created_at, u.estatus,
                       u.department, d.name AS department_name
                FROM users u
                LEFT JOIN email_departments d ON u.department = d.id
                WHERE u.email = :email
                  AND u.password = :password
                  AND u.authorized = TRUE
                  AND u.estatus = 'activo'
                """,
                **payload,
            )
            if not filas:
                return None
            fila = list(filas[0])
            return {
                "id": str(fila[0]),
                "name": fila[1],
                "email": fila[2],
                "role": fila[3],
                "authorized": fila[4],
                "created_at": fila[5],
                "estatus": fila[6],
                "department": str(fila[7]) if fila[7] else None,
                "department_name": fila[8],
            }

    user_data = await asyncio.to_thread(log_in_user, {"email": body.get("email", ""), "password": body.get("password", "")})
    if not user_data:
        return response(401, {"detail": "Credenciales inválidas o usuario no autorizado"}, "POST")
    token = generate_token(user_data["id"])
    return response(200, {"user": user_data, "token": token}, "POST")


async def create_user_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    result = await users_service.create_user(
        name=body.get("name"),
        email=body.get("email"),
        password=body.get("password"),
        phone=body.get("phone"),
        department=body.get("department"),
        role=body.get("role"),
        authorized=body.get("authorized", True),
        account_id=body.get("account_id"),
        is_admin=body.get("is_admin", False),
        can_receive_notifications=body.get("can_receive_notifications", False),
    )
    if "error" in result:
        return response(400, result, "POST")
    return response(201, result, "POST")


async def update_user_handler(event: dict, body: dict, user_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "PUT")
    result = await users_service.update_user(user_id, {k: v for k, v in body.items() if v is not None})
    if "error" in result:
        return response(400, result, "PUT")
    return response(200, result, "PUT")


async def delete_user_handler(event: dict, body: dict, user_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "DELETE")
    result = await users_service.delete_user(user_id, body.get("account_id"))
    if "error" in result:
        return response(400, result, "DELETE")
    return response(200, {"message": "Usuario eliminado exitosamente"}, "DELETE")


async def register_user_handler(event: dict, body: dict):
    return response(201, {"message": "Registro recibido", "data": body}, "POST")


async def auth_user_handler(event: dict, body: dict, user_id: str):
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            UPDATE users
            SET authorized = TRUE
            WHERE id = :id
            RETURNING id, name, email, role, authorized, created_at, estatus;
            """,
            id=user_id,
        )
        if not rows:
            return response(404, {"detail": "Usuario no encontrado"}, "GET")
        fila = rows[0]
        return response(200, {"id": str(fila[0]), "name": fila[1], "email": fila[2], "role": fila[3], "authorized": fila[4], "created_at": fila[5], "estatus": fila[6]}, "GET")


async def contacts_get_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "GET")
    account_id = (event.get("queryStringParameters") or {}).get("account_id")
    limit = int((event.get("queryStringParameters") or {}).get("limit", 50))
    offset = int((event.get("queryStringParameters") or {}).get("offset", 0))
    search = (event.get("queryStringParameters") or {}).get("search")
    await verify_account_permission(actor["id"], account_id)
    data = await contacts_service.get_contacts(account_id=account_id, limit=limit, offset=offset, search=search)
    return response(200, data, "GET")


async def contacts_create_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    await verify_account_permission(actor["id"], body.get("account_id"))
    data = await contacts_service.create_contact(body.get("name"), body.get("area_code"), body.get("phone_number"), body.get("account_id"), body.get("tag"), body.get("tag_color"))
    return response(200, data, "POST")


async def contacts_update_handler(event: dict, body: dict, contact_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "PUT")
    effective_account_id = body.get("account_id")
    if not effective_account_id:
        effective_account_id = await contacts_service.get_contact_account_id(contact_id)
    if not effective_account_id:
        return response(400, {"detail": "account_id es requerido para actualizar el contacto"}, "PUT")
    await verify_account_permission(actor["id"], effective_account_id)
    data = await contacts_service.update_contact(contact_id, body.get("name"), body.get("phone_number"), effective_account_id, body.get("tag"), body.get("tag_color"))
    return response(200, data, "PUT")


async def contacts_delete_handler(event: dict, body: dict, contact_id: str):
    result = await contacts_service.delete_contact(contact_id)
    return response(200, result, "DELETE")


async def tags_get_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "GET")
    account_id = (event.get("queryStringParameters") or {}).get("account_id")
    await verify_account_permission(actor["id"], account_id)
    data = await tags_service.get_tags(account_id)
    return response(200, data, "GET")


async def tags_create_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    await verify_account_permission(actor["id"], body.get("account_id"))
    data = await tags_service.create_tag(body.get("name"), body.get("color"), body.get("account_id"))
    return response(200, data, "POST")


async def tags_update_handler(event: dict, body: dict, tag_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "PUT")
    await verify_account_permission(actor["id"], body.get("account_id"))
    data = await tags_service.update_tag(tag_id, body.get("name"), body.get("color"), body.get("account_id"))
    return response(200, data, "PUT")


async def tags_delete_handler(event: dict, body: dict, tag_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "DELETE")
    account_id = (event.get("queryStringParameters") or {}).get("account_id") or body.get("account_id")
    await verify_account_permission(actor["id"], account_id)
    data = await tags_service.delete_tag(tag_id, account_id)
    return response(200, data, "DELETE")


async def templates_sync_handler(event: dict, body: dict):
    account_id = (event.get("queryStringParameters") or {}).get("account_id")
    account = await get_data_by_account_id(account_id)
    if not account:
        return response(404, {"detail": "Cuenta no encontrada"}, "GET")
    await templates_service.sync_templates_from_meta(account.get("waba_id"), account.get("access_token"))
    return response(200, {"status": "sync_started"}, "GET")


async def templates_get_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "GET")
    account_id = (event.get("queryStringParameters") or {}).get("account_id")
    await verify_account_permission(actor["id"], account_id)
    with get_sync_conn() as conn:
        account_rows = conn.run("SELECT waba_id FROM whatsapp_accounts WHERE id = :account_id AND is_active = TRUE AND estatus = 'activo' LIMIT 1", account_id=account_id)
        if not account_rows:
            return response(404, {"detail": "Cuenta no encontrada o inactiva"}, "GET")
        waba_id = account_rows[0][0]
        rows = conn.run(
            """
            SELECT id, waba_id, template_id, name, language, category, components, status, raw, header_media_type, header_media_url, created_at
            FROM message_templates2
            WHERE waba_id = :waba_id AND status = 'APPROVED' AND is_deleted = FALSE
            ORDER BY name, language
            """,
            waba_id=waba_id,
        )
        templates = []
        for row in rows:
            templates.append({
                "id": str(row[0]),
                "waba_id": str(row[1]),
                "template_id": str(row[2]),
                "name": row[3],
                "language": row[4],
                "category": row[5],
                "status": row[7],
                "raw": row[8] if row[8] else None,
                "header_media_type": row[9],
                "header_media_url": row[10],
                "created_at": str(row[11]),
                "components": row[6] or [],
            })
    return response(200, templates, "GET")


async def templates_create_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    account_id = body.get("account_id")
    await verify_account_permission(actor["id"], account_id)
    account = await get_data_by_account_id(account_id)
    if not account:
        return response(404, {"detail": "Cuenta no encontrada"}, "POST")
    payload = {
        "name": body.get("name"),
        "category": body.get("category"),
        "language": body.get("language", "es_MX"),
        "parameter_format": body.get("parameter_format", "POSITIONAL"),
        "components": body.get("components") or [],
    }
    template = await templates_service.send_template_to_meta(payload, account.get("waba_id"), account.get("access_token"))
    if template.get("id"):
        template_complete = await templates_service.get_template_from_meta(template.get("id"), account.get("access_token"))
        data = await templates_service.save_template_to_db(template_complete, account.get("waba_id"))
        return response(200, data, "POST")
    return response(500, {"detail": "No se pudo crear la plantilla"}, "POST")


async def templates_delete_handler(event: dict, body: dict, template_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "DELETE")
    account_id = (event.get("queryStringParameters") or {}).get("account_id")
    await verify_account_permission(actor["id"], account_id)
    with get_sync_conn() as conn:
        account_rows = conn.run("SELECT waba_id FROM whatsapp_accounts WHERE id = :account_id AND is_active = TRUE AND estatus = 'activo' LIMIT 1", account_id=account_id)
        if not account_rows:
            return response(404, {"detail": "Cuenta no encontrada o inactiva"}, "DELETE")
        waba_id = account_rows[0][0]
        rows = conn.run("SELECT id FROM message_templates2 WHERE id = :template_id AND waba_id = :waba_id AND is_deleted = FALSE LIMIT 1", template_id=template_id, waba_id=waba_id)
        if not rows:
            return response(404, {"detail": "Plantilla no encontrada o ya eliminada"}, "DELETE")
        conn.run("UPDATE message_templates2 SET is_deleted = TRUE WHERE id = :template_id AND waba_id = :waba_id", template_id=template_id, waba_id=waba_id)
    return response(200, {"message": "Plantilla eliminada correctamente"}, "DELETE")


async def messages_send_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    account_id = body.get("account_id")
    await verify_account_permission(actor["id"], account_id)
    content = {"to": body.get("to"), "type": body.get("type", "text"), "body": body.get("body", ""), "file_url": body.get("file_url"), "file_name": body.get("file_name")}
    errors = []
    ok_optin = await business.has_opt_in(body.get("to"))
    if not ok_optin:
        errors.append({"code": 400, "error_data": {"detail": "El contacto no ha dado su consentimiento"}})
    if body.get("type") != "template" and not await business.within_24h_window(body.get("to"), account_id):
        errors.append({"code": 403, "error_data": {"detail": "Fuera de la ventana de 24 horas. Solo se permiten plantillas."}})
    allowed = await business.allowed_by_rate_limit(settings.PHONE_NUMBER_ID)
    if not allowed:
        errors.append({"code": 429, "error_data": {"detail": "Se ha superado el límite de solicitudes"}})
    has_errors = bool(errors)
    status_value = "failed" if has_errors else "queued"
    error_text = json.dumps(errors) if has_errors else None

    def insert_and_get_id():
        with get_sync_conn() as conn:
            rows = conn.run(
                """
                INSERT INTO messages (id, conversation_id, direction, type, content, status, wamid, is_from_user, updated_at, media_url, file_name, message_text, error, errors)
                VALUES (
                    COALESCE(:id, gen_random_uuid()),
                    (SELECT id FROM conversations WHERE contact_id = (SELECT id FROM contacts WHERE phone_number = :number AND account_id = :account_id LIMIT 1) AND account_id = :account_id LIMIT 1),
                    'out',
                    :type,
                    :content::jsonb,
                    :status,
                    :wamid,
                    FALSE,
                    :updated_at,
                    :media_url,
                    :file_name,
                    :message_text,
                    :error,
                    :errors
                )
                ON CONFLICT (id) DO NOTHING
                RETURNING id, conversation_id;
                """,
                id=body.get("message_id"),
                number=body.get("to"),
                account_id=account_id,
                type=content["type"],
                content=json.dumps(content),
                status=status_value,
                wamid=generar_cadena(30),
                updated_at=None,
                media_url=body.get("file_url"),
                file_name=body.get("file_name"),
                message_text=body.get("body", ""),
                error=error_text,
                errors=error_text,
            )
            msg_id = rows[0][0] if rows else None
            conversation_id = rows[0][1] if rows else None
            return msg_id, conversation_id

    msg_id, conversation_id = await asyncio.to_thread(insert_and_get_id)
    if not msg_id:
        return response(500, {"detail": "Error al insertar en la base de datos: message_id no generado"}, "POST")
    if not has_errors:
        r = await business.init_redis()
        job = {"message_id": str(msg_id), "conversation_id": str(conversation_id)}
        account_data = await get_data_by_account_id(account_id)
        phone_number_id = account_data.get("phone_number_id") if account_data else None
        if not phone_number_id:
            return response(500, {"detail": f"No se encontró phone_number_id para la cuenta {account_id}"}, "POST")
        await r.rpush(f"queue:{phone_number_id}", json.dumps(job))
    else:
        return response(errors[0]["code"], {"message": "Mensaje guardado pero no enviado", "errors": errors, "message_id": str(msg_id)}, "POST")
    return response(200, {"message_id": msg_id, "status": "queued"}, "POST")


async def messages_send_template_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    account = await get_data_by_account_id(body.get("account_id"))
    if not account:
        return response(404, {"detail": "Cuenta de WhatsApp no encontrada"}, "POST")
    await verify_account_permission(actor["id"], body.get("account_id"))
    data = await templates_service.queue_template_message(
        number=body.get("to", [None])[0] if isinstance(body.get("to"), list) and body.get("to") else None,
        template_payload=body,
        template_id=body.get("template_id", ""),
        account=account,
        name=body.get("name"),
        message=body.get("name"),
        creator_user_id=actor["id"],
    )
    return response(200, {"message": "Plantilla encolada", "data": data}, "POST")


async def messages_reaction_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    await verify_account_permission(actor["id"], body.get("account_id"))
    success = await conversation_service.send_reaction_to_meta(wamid=body.get("message_id"), emoji=body.get("emoji"), to=body.get("to"), account_id=body.get("account_id"))
    if not success:
        return response(500, {"detail": "No se pudo enviar reacción a Meta"}, "POST")
    return response(200, {"status": "reaction_sent"}, "POST")


async def profile_get_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "GET")
    account_id = (event.get("queryStringParameters") or {}).get("account_id")
    await verify_account_permission(actor["id"], account_id)
    account = await get_data_by_account_id(account_id)
    if not account:
        return response(404, {"detail": "Cuenta de WhatsApp no encontrada"}, "GET")
    return response(200, account, "GET")


async def profile_update_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    account_id = body.get("account_id")
    await verify_account_permission(actor["id"], account_id)
    return response(200, {"message": "Perfil actualizado", "data": body}, "POST")


async def automations_actions_handler(event: dict, body: dict):
    return response(200, sorted(ACTION_REGISTRY.keys()), "GET")


async def automations_list_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "GET")
    account_id = (event.get("queryStringParameters") or {}).get("account_id")
    await verify_account_permission(actor["id"], account_id)
    data = await automations_service.list_automations(account_id)
    return response(200, data, "GET")


async def automations_create_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    await verify_account_permission(actor["id"], body.get("account_id"))
    data = await automations_service.create_automation(
        account_id=body.get("account_id"),
        name=body.get("name"),
        description=body.get("description"),
        priority=body.get("priority", 0),
        trigger_type=body.get("trigger_type"),
        trigger_config=body.get("trigger_config", {}),
        actions=body.get("actions", []),
        graph=body.get("graph"),
        stop_on_human_reply=body.get("stop_on_human_reply", False),
        status=body.get("status", "draft"),
        created_by=actor["id"],
    )
    return response(201, data, "POST")


async def automations_update_handler(event: dict, body: dict, automation_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "PUT")
    await verify_account_permission(actor["id"], body.get("account_id"))
    data = await automations_service.update_automation(automation_id, body.get("account_id"), {k: v for k, v in body.items() if k != "account_id"})
    return response(200, data, "PUT")


async def automations_delete_handler(event: dict, body: dict, automation_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "DELETE")
    account_id = (event.get("queryStringParameters") or {}).get("account_id") or body.get("account_id")
    await verify_account_permission(actor["id"], account_id)
    archived = await automations_service.archive_automation(automation_id, account_id)
    return response(200, archived, "DELETE")


async def automations_publish_handler(event: dict, body: dict, automation_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    account_id = (event.get("queryStringParameters") or {}).get("account_id") or body.get("account_id")
    await verify_account_permission(actor["id"], account_id)
    published = await automations_service.publish_automation(automation_id, account_id, published_by=actor["id"])
    return response(200, published, "POST")


async def automations_pause_handler(event: dict, body: dict, automation_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    account_id = (event.get("queryStringParameters") or {}).get("account_id") or body.get("account_id")
    await verify_account_permission(actor["id"], account_id)
    paused = await automations_service.pause_automation(automation_id, account_id)
    return response(200, paused, "POST") 


async def webhook_handler(event: dict, body: dict):
    if event.get("httpMethod", "GET") == "GET":
        params = event.get("queryStringParameters") or {}
        mode = params.get("hub.mode")
        challenge = params.get("hub.challenge") 
        token = params.get("hub.verify_token")
        if mode == "subscribe" and token == settings.VERIFY_TOKEN:
            return response(200, challenge, "GET")
        return response(403, {"detail": "Verification failed"}, "GET")
    return response(200, {"status": "ok"}, "POST")


async def whatsapp_accounts_list_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "GET")
    data = await get_accounts_by_user_id(actor["id"])
    return response(200, data, "GET")
 
 
async def whatsapp_accounts_data_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:  
        return response(401, {"detail": "No autorizado"}, "GET")
    data = await get_whatapp_accounts_data(True)
    return response(200, data, "GET") 


async def departments_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "GET")
    data = await get_departments()
    return response(200, data, "GET")


async def department_detail_handler(event: dict, body: dict, department_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "GET")
    data = await get_department_by_id(department_id)
    if not data:
        return response(404, {"detail": "Departamento no encontrado"}, "GET")
    return response(200, data, "GET")


async def whatsapp_accounts_create_handler(event: dict, body: dict):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "POST")
    result = await create_account(body)
    if "error" in result:
        return response(400, result, "POST")
    return response(201, result, "POST")


async def whatsapp_accounts_update_handler(event: dict, body: dict, account_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "PUT")
    result = await update_account(account_id, body)
    if "error" in result:
        return response(400, result, "PUT")
    return response(200, result, "PUT")


async def whatsapp_account_department_handler(event: dict, body: dict, account_id: str):
    actor = get_actor(event)
    if not actor:
        return response(401, {"detail": "No autorizado"}, "PUT")
    result = await update_account_department(account_id, body.get("department_id"))
    if "error" in result:
        return response(400, result, "PUT")
    return response(200, result, "PUT")


async def ws_handler(event: dict, body: dict):
    return response(200, {"message": "WebSocket endpoint requires API Gateway/WebSocket support"}, event.get("httpMethod", "GET"))


async def crear_token_handler(event: dict, body: dict):
    user_id = (event.get("queryStringParameters") or {}).get("user_id")
    if not user_id:
        return response(400, {"detail": "user_id es requerido"}, "GET")
    token = generate_token(user_id)
    return response(200, {"token": token}, "GET")





def lambda_handler(event, context):
    try:
        path = event.get("resource") or event.get("rawPath") or event.get("path") or ""
        method = event.get("httpMethod") or (event.get("requestContext") or {}).get("http", {}).get("method") or "GET"
        body = parse_event_body(event)

        if method == "OPTIONS":
            return response(200, {"status": "ok"}, method)

        if method == "GET" and path in ["/health", "/healthz"]:
            return response(200, {"status": "ok"}, "GET")

        if method == "POST" and path == "/login":
            return asyncio.run(login_handler(event, body))

        if method == "POST" and path == "/users":
            return asyncio.run(create_user_handler(event, body))

        if method == "PUT" and path.startswith("/users/"):
            user_id = path.split("/", 2)[2]
            return asyncio.run(update_user_handler(event, body, user_id))

        if method == "DELETE" and path.startswith("/users/"):
            user_id = path.split("/", 2)[2]
            return asyncio.run(delete_user_handler(event, body, user_id))

        if method == "POST" and path == "/Users/register":
            return asyncio.run(register_user_handler(event, body))

        if method == "GET" and path.startswith("/Users/Auth/"):
            user_id = path.split("/", 3)[3]
            return asyncio.run(auth_user_handler(event, body, user_id))

        if method == "GET" and path == "/contacts":
            return asyncio.run(contacts_get_handler(event, body))
        if method == "POST" and path == "/contacts":
            return asyncio.run(contacts_create_handler(event, body))
        if method == "PUT" and path.startswith("/contacts/"):
            contact_id = path.split("/", 2)[2]
            return asyncio.run(contacts_update_handler(event, body, contact_id))
        if method == "DELETE" and path.startswith("/contacts/"):
            contact_id = path.split("/", 2)[2]
            return asyncio.run(contacts_delete_handler(event, body, contact_id))

        if method == "GET" and path == "/tags":
            return asyncio.run(tags_get_handler(event, body))
        if method == "POST" and path == "/tags":
            return asyncio.run(tags_create_handler(event, body))
        if method == "PUT" and path.startswith("/tags/"):
            tag_id = path.split("/", 2)[2]
            return asyncio.run(tags_update_handler(event, body, tag_id))
        if method == "DELETE" and path.startswith("/tags/"):
            tag_id = path.split("/", 2)[2]
            return asyncio.run(tags_delete_handler(event, body, tag_id))

        if method == "GET" and path == "/sync_templates":
            return asyncio.run(templates_sync_handler(event, body))
        if method == "GET" and path == "/templates":
            return asyncio.run(templates_get_handler(event, body))
        if method == "POST" and path == "/templates":
            return asyncio.run(templates_create_handler(event, body))
        if method == "DELETE" and path.startswith("/templates/"):
            template_id = path.split("/", 2)[2]
            return asyncio.run(templates_delete_handler(event, body, template_id))

        if method == "POST" and path == "/messages/send":
            return asyncio.run(messages_send_handler(event, body))
        if method == "POST" and path == "/messages/send-template":
            return asyncio.run(messages_send_template_handler(event, body))
        if method == "POST" and path == "/messages/reaction":
            return asyncio.run(messages_reaction_handler(event, body))

        if method == "GET" and path == "/profile":
            return asyncio.run(profile_get_handler(event, body))
        if method == "POST" and path == "/profile":
            return asyncio.run(profile_update_handler(event, body))

        if method == "GET" and path == "/automations/actions":
            return asyncio.run(automations_actions_handler(event, body))
        if method == "GET" and path == "/automations":
            return asyncio.run(automations_list_handler(event, body))
        if method == "POST" and path == "/automations":
            return asyncio.run(automations_create_handler(event, body))
        if method == "PUT" and path.startswith("/automations/"):
            automation_id = path.split("/", 2)[2]
            return asyncio.run(automations_update_handler(event, body, automation_id))
        if method == "DELETE" and path.startswith("/automations/"):
            automation_id = path.split("/", 2)[2]
            return asyncio.run(automations_delete_handler(event, body, automation_id))
        if method == "POST" and path.startswith("/automations/") and path.endswith("/publish"):
            automation_id = path.split("/", 3)[2]
            return asyncio.run(automations_publish_handler(event, body, automation_id))
        if method == "POST" and path.startswith("/automations/") and path.endswith("/pause"):
            automation_id = path.split("/", 3)[2]
            return asyncio.run(automations_pause_handler(event, body, automation_id))

        if method in {"GET", "POST"} and path == "/webhook":
            return asyncio.run(webhook_handler(event, body))

        if method == "GET" and path == "/whatsapp_accounts":
            return asyncio.run(whatsapp_accounts_list_handler(event, body))
        if method == "GET" and path == "/whatsapp_accounts/data":
            return asyncio.run(whatsapp_accounts_data_handler(event, body))
        if method == "GET" and path == "/departments":
            return asyncio.run(departments_handler(event, body))
        if method == "GET" and path.startswith("/departments/"):
            department_id = path.split("/", 2)[2]
            return asyncio.run(department_detail_handler(event, body, department_id))
        if method == "POST" and path == "/whatsapp_accounts":
            return asyncio.run(whatsapp_accounts_create_handler(event, body))
        if method == "PUT" and path.startswith("/whatsapp_accounts/"):
            account_id = path.split("/", 2)[2]
            return asyncio.run(whatsapp_accounts_update_handler(event, body, account_id))
        if method == "PUT" and path.startswith("/whatsapp_accounts/") and path.endswith("/department"):
            account_id = path.split("/", 2)[2]
            return asyncio.run(whatsapp_account_department_handler(event, body, account_id))

        if method in {"GET", "POST", "PUT", "DELETE", "OPTIONS"} and path == "/ws":
            return asyncio.run(ws_handler(event, body))

        if method == "GET" and path == "/crear_token":
            return asyncio.run(crear_token_handler(event, body))

        return response(404, {"error": "Ruta no encontrada"}, method)
    except Exception as exc:
        print("Error inesperado:", repr(exc))
        return response(500, {"error": str(exc), "import_errors": IMPORT_ERRORS}, event.get("httpMethod", "GET"))


__all__ = [
    "lambda_handler",
    "response",
    "parse_event_body",
    "guardar_json_en_s3",
    "eliminar_archivo_s3",
]