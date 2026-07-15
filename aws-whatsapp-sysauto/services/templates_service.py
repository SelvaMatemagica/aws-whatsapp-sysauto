from fastapi import HTTPException
import json
import anyio
import httpx
import requests
#from typing import list
from app.db import get_sync_conn
from app.config import settings
from app.utils.general_utils import generar_cadena, e164_a_mx_movil
from typing import Optional
from ..services.accounts_service import get_by_phone_id
import redis.asyncio as aioredis
from app.utils.s3 import upload_to_s3_sync

# -------------- Public: get template from DB -----------------
def get_template_sync(name: str, waba_id: str, language: str):
    with get_sync_conn() as conn:
        rows = conn.run(
            """
            SELECT id, waba_id, name, language, components, namespace, raw, header_media_type, header_media_url
            FROM message_templates2
            WHERE waba_id = :waba AND name = :name AND language = :lang
            LIMIT 1
            """,
            waba=waba_id, name=name, lang=language
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0],
            "waba_id": r[1],
            "name": r[2],
            "language": r[3],
            "components": r[4],
            "namespace": r[5],
            "raw": r[6],
            "header_media_type": r[7],
            "header_media_url": r[8],
        }

async def get_template(name: str, waba_id: str, language: str):
    return await anyio.to_thread.run_sync(get_template_sync, name, waba_id, language)

async def get_template_by_id(template_id: str):
    def get_template_by_id_sync(template_id: str):
        with get_sync_conn() as conn:
            rows = conn.run(
                """
                SELECT * FROM message_templates2 WHERE id = :template_id;
                """,
                template_id=template_id
            )
            column_names = [col["name"] for col in conn.columns]
            data = [dict(zip(column_names, fila)) for fila in rows]
            return data[0] if data else None
        
    return await anyio.to_thread.run_sync(get_template_by_id_sync, template_id)

# -------------- Queue one template message (create DB + push to Redis) ----------
async def queue_template_message(
    number: str,
    template_payload: dict,
    template_id: str,
    account: dict,
    name: Optional[str] = "Desconocido",
    message: Optional[str] = "",
    media_url: Optional[str] = None,
    message_id: Optional[str] = None,
    creator_user_id: Optional[str] = None,
):
    async def sync_insert():
        with get_sync_conn() as conn:
            print("creator_user_id: ", creator_user_id)
            #account_id = await get_by_phone_id('929775720225683')
            account_id = account.get("id")
            phone_number_id = account.get("phone_number_id")

            wa_id = e164_a_mx_movil(number)

            print("number: ", number)
            print("wa_id: ", wa_id)
            print("account_id: ", account_id)
            print("content: ", template_payload)

            # --- CONTACTO ---
            r = conn.run(
                """
                SELECT id FROM contacts 
                WHERE wa_id = :wa_id
                AND account_id = :account_id
                LIMIT 1;
                """,
                wa_id=wa_id,
                account_id=account_id
            )

            if r:
                contact_id = str(r[0][0])
            else:
                r = conn.run(
                    """
                    INSERT INTO contacts (wa_id, phone_number, name, account_id)
                    VALUES (:wa_id, :phone_number, :name, :account_id)
                    RETURNING id
                    """,
                    wa_id=wa_id,
                    phone_number=number,
                    name=name,
                    account_id=account_id
                )
                contact_id = str(r[0][0])

            # --- CUENTA DE WHATSAPP ---
            #r = conn.run(
                #"SELECT id FROM whatsapp_accounts WHERE phone_number_id = :phone_number_id",
                #phone_number_id='929775720225683'
            #)
            #account_id = str(r[0][0])

            # --- CONVERSACIÓN ---
            r = conn.run(
                """
                SELECT id FROM conversations 
                WHERE contact_id = :cid AND account_id = :aid
                LIMIT 1
                """,
                cid=contact_id,
                aid=account_id
            )
            if r:
                conv_id = str(r[0][0])
                conn.run(
                    """
                    UPDATE conversations 
                    SET last_message_at = NOW(), general_last_message_at = NOW()
                    WHERE id = :coid
                    """,
                    coid=conv_id
                )
            else:
                r = conn.run(
                    """
                    INSERT INTO conversations (contact_id, account_id, last_message_at, general_last_message_at)
                    VALUES (:cid, :aid, NOW(), NOW())
                    RETURNING id
                    """,
                    cid=contact_id,
                    aid=account_id
                )
                conv_id = str(r[0][0])

            rows = conn.run(
                """
                INSERT INTO messages
                  (id, conversation_id, direction, type, content, status, wamid, is_from_user, updated_at, template_id, message_text, media_url)
                VALUES (
                  COALESCE(:id, gen_random_uuid()),
                  (SELECT id FROM conversations WHERE contact_id = (
                      SELECT id FROM contacts WHERE wa_id = :wa_id AND account_id = :account_id LIMIT 1
                   ) AND account_id = :account_id LIMIT 1),
                  'out',
                  'template',
                  :content::jsonb,
                  'queued',
                  :wamid,
                  FALSE,
                  NULL,
                  :template_id,
                  :message_text,
                  :media_url
                )
                ON CONFLICT (id) DO NOTHING
                RETURNING id, conversation_id
                """,
                id=message_id,
                wa_id=wa_id,
                account_id=account_id,
                content=json.dumps(template_payload),
                wamid=generar_cadena(30),
                template_id=template_id,
                message_text=message,
                media_url=media_url
            )
            msg_id = rows[0][0] if rows else None
            conversation_id = rows[0][1] if rows else None
            return msg_id, conversation_id, account_id, phone_number_id

    msg_id, conversation_id, account_id, phone_number_id = await sync_insert()

    # Asegurarnos de que se obtuvo un message_id válido. Si no, fallamos en lugar de insertar un log incompleto.
    if not msg_id:
        raise HTTPException(status_code=500, detail="Error al insertar en la base de datos: message_id no generado")

    # push to redis
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    job = {"message_id": str(msg_id), "conversation_id": str(conversation_id)}
    #await r.rpush(f"queue:929775720225683", json.dumps(job))
    await r.rpush(f"queue:{phone_number_id}", json.dumps(job))

    # 6) Registrar log en whatsapp_send_logs usando phone_number_id
    def get_account_user_info(account_id: str):
        with get_sync_conn() as conn:
            sql = """
                SELECT 
                    wa.id AS whatsapp_account_id,
                    wa.display_name ,
                    uwa.user_id,
                    u.department
                FROM public.whatsapp_accounts wa
                JOIN public.user_whatsapp_accounts uwa 
                    ON wa.id = uwa.whatsapp_account_id
                JOIN public.users u 
                    ON uwa.user_id = u.id
                WHERE wa.id = :account_id;
            """
            rows = conn.run(sql, account_id=account_id)
            column_names = [col["name"] for col in conn.columns]
            # 🔹 mapear filas a dicts
            data = [dict(zip(column_names, fila)) for fila in rows]
            return data[0] if data else None

    # aquí ya no usamos req.account_id, sino phone_number_id
    info = await anyio.to_thread.run_sync(lambda: get_account_user_info(account_id))

    # Soportar sender_email (o senderEmail) dentro del template_payload
    sender_email = None
    if isinstance(template_payload, dict):
        sender_email = template_payload.get("sender_email") or template_payload.get("senderEmail")

    resolved_user_id = creator_user_id if creator_user_id else (info["user_id"] if info else None)
    department_name = info["department"] if info else None 

    if sender_email:
        # Normalizar email: trim y lower
        sender_email_norm = sender_email.strip().lower() if isinstance(sender_email, str) else None

        def find_user_by_email():
            with get_sync_conn() as conn:
                q = """
                    SELECT id, department, email
                    FROM public.users
                    WHERE lower(trim(email)) = :email_norm
                    LIMIT 1
                """
                rows = conn.run(q, email_norm=sender_email_norm)
                column_names = [col["name"] for col in conn.columns]
                data = [dict(zip(column_names, fila)) for fila in rows]
                return data[0] if data else None

        user_row = await anyio.to_thread.run_sync(find_user_by_email)

        # Debug prints para investigar asignación de user_id
        print("[templates][debug] sender_email (raw):", sender_email)
        print("[templates][debug] sender_email (norm):", sender_email_norm)
        print("[templates][debug] creator_user_id:", creator_user_id)
        print("[templates][debug] account info user_id:", info["user_id"] if info else None)
        print("[templates][debug] find_user_by_email result:", user_row)

        if not user_row:
            # Búsqueda diagnóstica con LIKE para detectar entradas cercanas (no usar como fallback automático)
            def like_search():
                with get_sync_conn() as conn:
                    q2 = """
                        SELECT id, email
                        FROM public.users
                        WHERE lower(email) LIKE '%' || :part || '%'
                        LIMIT 5
                    """
                    rows2 = conn.run(q2, part=sender_email_norm)
                    column_names2 = [col["name"] for col in conn.columns]
                    return [dict(zip(column_names2, fila)) for fila in rows2]

            like_results = await anyio.to_thread.run_sync(like_search)
            print("[templates][debug] like search results:", like_results)

        if user_row:
            resolved_user_id = user_row.get("id") or resolved_user_id
            department_name = user_row.get("department") or department_name

    log_payload = {
        "recipient_phone": number,
        "department_name": department_name,
        "api_name": info["display_name"] if info else None,
        "status": "queued",
        "message_body": message,
        "delivery_time": None,
        "server": "api-gateway",
        "message_id": str(msg_id),
        "error_message": None,
        "retry_attempt": 0,
        "user_id": resolved_user_id,
        "sending_type": "Template Massive",
        "related_phones": json.dumps([number]),
    }

    # Mostrar el payload que se va a insertar en whatsapp_send_logs
    print("[templates] whatsapp_send_logs payload:", log_payload)

    def insert_log():
        with get_sync_conn() as conn:
            sql = """
                INSERT INTO whatsapp_send_logs (
                    recipient_phone, department_name, api_name, status,
                    message_body, delivery_time, server, message_id,
                    error_message, retry_attempt, user_id, sending_type, related_phones
                )
                VALUES (
                    :recipient_phone, :department_name, :api_name, :status,
                    :message_body, :delivery_time, :server, :message_id,
                    :error_message, :retry_attempt, :user_id, :sending_type, :related_phones::jsonb
                )
                RETURNING *;
            """
            return conn.run(sql, **log_payload)

    await anyio.to_thread.run_sync(insert_log)

    return msg_id




# -------------- Sync templates from Meta (to call periodically) ---------------
async def sync_templates_from_meta(waba_id: str, access_token: str):
    """
    Fetch message_templates for the WABA_ID and store/update local DB.
    """
    ####### CAMBIO #######
    ####### CAMBIO headers también #######
    #url = f"https://graph.facebook.com/{settings.META_API_VERSION}/737390112775476/message_templates"
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{waba_id}/message_templates"
    #headers = {"Authorization": f"Bearer EAAUNZA3KhKW0BQl6Oh04Xr4Hsg530z7M3zlzj3P0Q1PfSpf3yK6WRslyNkOZBwkeiqxTDrCRhpoYFsr3InHpDTriQPZBS0KMhYor5oCYZChP2Rq7vmfvhsvLyaTsLhZCbSawSfPzDFgldM7oHxwPUkOocHuPCaAhwhWHyv10DSGjdeEqYQsSbFgvZCPoWfUwZDZD"}
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json().get("data", [])
        #print("data: ", data)
    # store in DB
    def store_sync(items):
        with get_sync_conn() as conn:
            print("trata de sincronizar plantillas")
            for it in items:
                name = it.get("name")
                lang = it.get("language")
                # components might be on top-level or nested
                comps = it.get("components", [])
                namespace = it.get("id")  # Meta returns id; namespace may need another call
                raw = json.dumps(it)

                header_media_type = None
                header_media_url = None

                for c in comps:
                    if c.get("type") == "HEADER":
                        if c.get("format") == "IMAGE":
                            header_media_url = c.get("example", {}).get("header_handle", [None])[0]
                            header_media_type = "IMAGE"
                        if c.get("format") == "DOCUMENT":
                            header_media_url = c.get("example", {}).get("header_handle", [None])[0]
                            header_media_type = "DOCUMENT"

                if header_media_url:
                    try:
                        # Descarga la imagen de Meta
                        r = requests.get(header_media_url, timeout=30)
                        r.raise_for_status()
                        file_bytes = r.content
                        content_type = r.headers.get("content-type", "image/jpeg")

                        # Sube a S3
                        header_media_url, filename = upload_to_s3_sync(
                            file_bytes, content_type, get_name=f"plantilla-{name}-{lang}"
                        )

                    except Exception as e:
                        print(f"No se pudo copiar imagen de {name}: {e}")
                        header_media_type = None
                        header_media_url = None

                # upsert
                conn.run(
                    """
                    INSERT INTO message_templates2 (waba_id, template_id, name, language, components, namespace, status, raw, updated_at, category, header_media_type, header_media_url)
                    VALUES (:waba, :tid, :name, :lang, :components::jsonb, :namespace, :status, :raw::jsonb, NOW(), :category, :header_media_type, :header_media_url)
                    ON CONFLICT (waba_id, name, language)
                    DO UPDATE SET components = EXCLUDED.components, namespace = EXCLUDED.namespace, status = EXCLUDED.status, raw = EXCLUDED.raw, updated_at = NOW(), category = EXCLUDED.category
                    """,
                    #waba='737390112775476',####### CAMBIO #######
                    waba=waba_id,
                    tid=it.get("id"),
                    name=name,
                    lang=lang,
                    components=json.dumps(comps),
                    namespace=namespace,
                    status=it.get("status", "APPROVED"),
                    raw=raw,
                    category=it.get("category", None),
                    header_media_type=header_media_type, 
                    header_media_url=header_media_url
                )
    await anyio.to_thread.run_sync(store_sync, data)
    return len(data)



async def get_template_from_meta(template_id: str, access_token: str):
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{template_id}"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    print("url: ", url)
    print("headers: ", headers)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data



async def send_template_to_meta(payload: dict, waba_id: str, access_token: str):
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    print("url: ", url)
    print("headers: ", headers)
    print("payload: ", payload)

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            print("Meta raw response for template creation:", r.text)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            error_response = e.response.json()
            print("Meta error response:", error_response)

            user_msg = error_response.get("error", {}).get("error_user_msg") \
                or error_response.get("error", {}).get("message")

            raise HTTPException(
                status_code=e.response.status_code,
                detail=user_msg or f"Error al crear plantilla en Meta: {e.response.text}"
            )
        except Exception as e:
            print("Error inesperado:", str(e))
            raise HTTPException(
                status_code=500,
                detail=f"Error inesperado: {str(e)}"
            )
    

async def save_template_to_db(payload: dict, waba_id: str):
    def sync_save():

        id = payload.get("id")
        name = payload.get("name")
        lang = payload.get("language")
        # components might be on top-level or nested
        comps = payload.get("components", [])
        namespace = payload.get("id")  # Meta returns id; namespace may need another call
        raw = json.dumps(payload)

        header_media_type = None
        header_media_url = None

        for c in comps:
            if c.get("type") == "HEADER":
                if c.get("format") == "IMAGE":
                    header_media_url = c.get("example", {}).get("header_handle", [None])[0]
                    header_media_type = "IMAGE"
                if c.get("format") == "DOCUMENT":
                    header_media_url = c.get("example", {}).get("header_handle", [None])[0]
                    header_media_type = "DOCUMENT"

        if header_media_url:
            try:
                # Descarga la imagen de Meta
                r = requests.get(header_media_url, timeout=30)
                r.raise_for_status()
                file_bytes = r.content
                content_type = r.headers.get("content-type", "image/jpeg")

                # Sube a S3
                header_media_url, filename = upload_to_s3_sync(
                    file_bytes, content_type, get_name=f"plantilla-{name}-{lang}"
                )

            except Exception as e:
                print(f"No se pudo copiar imagen de {name}: {e}")
                header_media_type = None
                header_media_url = None
        with get_sync_conn() as conn:
            rows = conn.run(
                """
                INSERT INTO message_templates2 (waba_id, template_id, name, language, components, namespace, status, raw, category, header_media_type, header_media_url)
                VALUES (:waba, :tid, :name, :lang, :components::jsonb, :namespace, :status, :raw::jsonb, :category, :header_media_type, :header_media_url)
                RETURNING *;
                """,
                waba=waba_id,
                tid=id,
                name=name,
                lang=lang,
                components=json.dumps(comps),
                namespace=namespace,
                status=payload.get("status", "PENDING"),
                raw=raw,
                category=payload.get("category", None),
                header_media_type=header_media_type, 
                header_media_url=header_media_url
            )
            column_names = [col["name"] for col in conn.columns]
            data = [dict(zip(column_names, fila)) for fila in rows]
            return data[0]
    return await anyio.to_thread.run_sync(sync_save)



####### Editorial


async def get_template_button(button: int):
    def sync_get_template_button(button: int):
        with get_sync_conn() as conn:
            rows = conn.run(
                """
                SELECT template_id FROM editorial_templates_buttons WHERE id = :id;
                """,
                id=button
            )
            if not rows:
                return None
            template_id = rows[0][0]
            return template_id
    return await anyio.to_thread.run_sync(sync_get_template_button, button)


async def get_all_templates_buttons():
    def sync_get_all_templates_buttons():
        with get_sync_conn() as conn:
            rows = conn.run(
                """
                SELECT 
                    etb.*,
                    mt.*,
                    mt.template_id AS message_template_id,
                    etb.template_id AS button_template_id,
	                etb.id AS button_id
                FROM editorial_templates_buttons etb
                LEFT JOIN message_templates2 mt
                    ON etb.template_id = mt.id
                ORDER BY button_id ASC;
                """
            )
            column_names = [col["name"] for col in conn.columns]
            data = [dict(zip(column_names, fila)) for fila in rows]
            return data if data else None
            """ resultado = {
                item["button_id"]: item
                for item in data
            }
            return resultado if resultado else None """
    return await anyio.to_thread.run_sync(sync_get_all_templates_buttons)


async def set_template_to_button(template_id: str, button: int):
    def sync_set_template_to_button(template_id: str, button: int):
        print("Antes update")
        with get_sync_conn() as conn:
            rows = conn.run(
                """
                UPDATE editorial_templates_buttons 
                SET template_id=:template_id 
                WHERE id=:button
                RETURNING *;
                """,
                template_id=template_id,
                button=button
            )
            column_names = [col["name"] for col in conn.columns]
            data = [dict(zip(column_names, fila)) for fila in rows]
            return data[0]
    return await anyio.to_thread.run_sync(sync_set_template_to_button, template_id, button)