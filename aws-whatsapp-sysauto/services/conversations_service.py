from typing import List, Dict, Any, Tuple
from datetime import datetime
import anyio
from ..db import get_sync_conn
import httpx
import asyncio
from ..config import settings
from ..services.accounts_service import get_data_by_account_id
from ..utils.general_utils import make_json_safe


class ConversationService:
    @staticmethod
    def get_conversations_sync(user_id: str, account_id: str = None, is_admin: bool = False) -> List[Dict[str, Any]]:
        """Obtener todas las conversaciones de un usuario"""# select base de datos
        with get_sync_conn() as conn:
            params = {}

            # Si se especifica account_id, filtrar por ese account
            account_filter = ""
            if account_id:
                account_filter = "AND c.account_id = :account_id"
                params["account_id"] = account_id

            # Filtro de acceso a cuentas (solo si NO es admin)
            account_access_filter = ""
            if not is_admin:
                account_access_filter = """
                    AND c.account_id IN (
                        SELECT whatsapp_account_id FROM user_whatsapp_accounts WHERE user_id = :user_id
                    )
                """
                params["user_id"] = user_id

            query = f"""
                SELECT
                    c.id,
                    c.contact_id,
                    c.account_id,
                    c.last_user_message_at,
                    c.can_send_regular_message,
                    c.created_at,
                    c.estatus,
                    c.last_message_at,
                    c.general_last_message_at,
                    ct.phone_number,
                    ct.name,
                    ct.opt_in,
                    ct.tag,
                    ct.tag_color,
                    -- Último mensaje de la conversación
                    (
                        SELECT json_build_object(
                            'id', m.id,
                            'content', m.content,
                            'type', m.type,
                            'timestamp', m.timestamp,
                            'direction', m.direction,
                            'status', m.status,
                            'is_from_user', m.is_from_user,
                            'message_text',
                                CASE
                                    WHEN NULLIF(m.message_text, '') IS NOT NULL THEN m.message_text
                                    WHEN m.type = 'image' THEN '📷 Foto'
                                    WHEN m.type = 'video' THEN '🎥 Video'
                                    WHEN m.type = 'document' THEN '📄 Documento'
                                    WHEN m.type = 'sticker' THEN '😀 Sticker'
                                    ELSE ''
                                END
                        )
                        FROM messages m
                        WHERE m.conversation_id = c.id
                        ORDER BY m.timestamp DESC
                        LIMIT 1
                    ) as last_message,
                    -- Contador de mensajes no leídos (mensajes entrantes no leídos)
                    (
                        SELECT COUNT(*)
                        FROM messages m
                        WHERE m.conversation_id = c.id
                        AND m.direction = 'in'
                        AND m.status != 'read'
                    ) as unread_count
                FROM conversations c
                JOIN contacts ct ON c.contact_id = ct.id
                WHERE 1=1
                {account_access_filter}
                {account_filter}
                AND EXISTS (
                    SELECT 1
                    FROM messages m
                    WHERE m.conversation_id = c.id
                )
                ORDER BY c.general_last_message_at DESC NULLS LAST
            """

            print("query: ", query)
            print("params: ", params)

            rows = conn.run(query, **params)
            column_names = [col["name"] for col in conn.columns]
            print("resultado: ", rows)
            result = [dict(zip(column_names, row)) for row in rows]
            print("resultado 2: ", result)
            return result

    @staticmethod
    def get_conversation_messages_sync(conversation_id: str, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Obtener todos los mensajes de una conversación"""# select base de datos
        with get_sync_conn() as conn:
            # Primero verificar que el usuario tiene acceso a esta conversación
            #access_query = """
                #SELECT 1 FROM conversations c
                #WHERE c.id = :conversation_id
                #AND c.account_id IN (
                    #SELECT whatsapp_account_id FROM user_whatsapp_accounts WHERE user_id = :user_id
                #)
                #LIMIT 1
            #"""
            #access_rows = conn.run(access_query, conversation_id=conversation_id, user_id=user_id)
            #if not access_rows:
                #return []  # Usuario no tiene acceso

            # Obtener los mensajes
            messages_query = """
                SELECT
                    m.id,
                    m.conversation_id,
                    m.type,
                    m.media_url,
                    m.file_name,
                    m.status,
                    m.is_from_user,
                    m.timestamp,
                    m.template_id,
                    m.estatus,
                    m.wamid,
                    m.direction,
                    m.content,
                    m.error,
                    m.errors,
                    m.updated_at,
                    m.media_url,
                    m.file_name,
                    m.message_text,
                    m.is_forwarded,
                    m.reply_to_message_id,
                    -- Reacciones agregadas como array JSON
                    COALESCE(
                        (
                            SELECT json_agg(
                                json_build_object(
                                    'id', r.id,
                                    'emoji', r.emoji,
                                    'is_from_user', r.is_from_user,
                                    'account_id', r.account_id,
                                    'conversation_id', r.conversation_id,
                                    'created_at', r.created_at,
                                    'updated_at', r.updated_at
                                )
                            )
                            FROM message_reactions r
                            WHERE r.wamid = m.wamid
                        ), '[]'::json
                    ) AS reactions
                FROM messages m
                WHERE m.conversation_id = :conversation_id
                ORDER BY m.timestamp DESC
                LIMIT :limit OFFSET :offset
            """

            otra_opcion = """
                SELECT
                    m.*,
                    COALESCE(json_agg(json_build_object(
                        'emoji', r.emoji,
                        'count', r.count,
                        'reacted_by_user', r.is_from_user
                    )) FILTER (WHERE r.emoji IS NOT NULL), '[]') AS reactions
                FROM messages m
                LEFT JOIN (
                    SELECT
                        message_id,
                        emoji,
                        COUNT(*) AS count,
                        BOOL_OR(is_from_user) AS is_from_user
                    FROM message_reactions
                    GROUP BY message_id, emoji
                ) r ON r.message_id = m.id
                WHERE m.conversation_id = :conversation_id
                ORDER BY m.timestamp DESC
                LIMIT :limit OFFSET :offset;
            """

            rows = conn.run(messages_query,
                          conversation_id=conversation_id,
                          limit=limit,
                          offset=offset)
            column_names = [col["name"] for col in conn.columns]
            #print("resultado: ", rows)
            result = [dict(zip(column_names, row)) for row in rows]
            #print("resultado 2: ", result)
            return result
        
    @staticmethod
    def get_message_sync(message_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Obtener un mensaje de una conversación"""# select base de datos
        with get_sync_conn() as conn:
            # Primero verificar que el usuario tiene acceso a esta conversación
            #access_query = """
                #SELECT 1 FROM conversations c
                #WHERE c.id = :conversation_id
                #AND c.account_id IN (
                    #SELECT whatsapp_account_id FROM user_whatsapp_accounts WHERE user_id = :user_id
                #)
                #LIMIT 1
            #"""
            #access_rows = conn.run(access_query, conversation_id=conversation_id, user_id=user_id)
            #if not access_rows:
                #return []  # Usuario no tiene acceso

            # Obtener los mensajes
            messages_query = """
                SELECT
                    m.id,
                    m.conversation_id,
                    m.type,
                    m.media_url,
                    m.file_name,
                    m.status,
                    m.is_from_user,
                    m.timestamp,
                    m.template_id,
                    m.estatus,
                    m.wamid,
                    m.direction,
                    m.content,
                    m.error,
                    m.errors,
                    m.updated_at,
                    m.media_url,
                    m.file_name,
                    m.message_text,
                    m.is_forwarded,
                    m.reply_to_message_id,
                    -- Reacciones agregadas como array JSON
                    COALESCE(
                        (
                            SELECT json_agg(
                                json_build_object(
                                    'id', r.id,
                                    'emoji', r.emoji,
                                    'is_from_user', r.is_from_user,
                                    'account_id', r.account_id,
                                    'conversation_id', r.conversation_id,
                                    'created_at', r.created_at,
                                    'updated_at', r.updated_at
                                )
                            )
                            FROM message_reactions r
                            WHERE r.wamid = m.wamid
                        ), '[]'::json
                    ) AS reactions
                FROM messages m
                WHERE m.id = :message_id
                ORDER BY m.timestamp DESC
                LIMIT 1"""

            rows = conn.run(messages_query,
                          message_id=message_id)
            column_names = [col["name"] for col in conn.columns]
            #print("resultado: ", rows)
            result = make_json_safe(dict(zip(column_names, rows[0]))) if rows else None
            #print("resultado 2: ", result)
            return result #
        
    @staticmethod
    def set_messages_as_read(message_ids_to_read: List[str]) -> int:
        """Marcar mensajes recibidos como leídos"""

        with get_sync_conn() as conn:
            print("set_messages_as_read")
            

            query = """
                UPDATE messages
                SET status = 'read',
                    updated_at = NOW()
                WHERE id = ANY(:message_ids);
            """
            if message_ids_to_read:
                print("entró, ", len(message_ids_to_read))
                conn.run(query, message_ids=message_ids_to_read)
                return len(message_ids_to_read)
            else:
                print("no entró")
                return 0

    @staticmethod
    def get_conversation_sync(conversation_id: str, user_id: str, is_admin: bool = False) -> Dict[str, Any] | None:
        """Obtener una conversación específica"""# select base de datos
        with get_sync_conn() as conn:
            params = { "conversation_id": conversation_id }

            # Filtro de acceso a cuentas (solo si NO es admin)
            account_access_filter = ""
            if not is_admin:
                account_access_filter = """
                    AND c.account_id IN (
                        SELECT whatsapp_account_id FROM user_whatsapp_accounts WHERE user_id = :user_id
                    )
                """
                params["user_id"] = user_id

            query = f"""
                SELECT
                    c.id,
                    c.contact_id,
                    c.account_id,
                    c.last_user_message_at,
                    c.can_send_regular_message,
                    c.created_at,
                    c.estatus,
                    c.last_message_at,
                    c.general_last_message_at,
                    ct.phone_number,
                    ct.name,
                    ct.opt_in,
                    -- Último mensaje de la conversación
                    (
                        SELECT json_build_object(
                            'id', m.id,
                            'content', m.content,
                            'type', m.type,
                            'timestamp', m.timestamp,
                            'direction', m.direction,
                            'status', m.status,
                            'is_from_user', m.is_from_user,
                            'message_text',
                                CASE
                                    WHEN NULLIF(m.message_text, '') IS NOT NULL THEN m.message_text
                                    WHEN m.type = 'image' THEN '📷 Foto'
                                    WHEN m.type = 'video' THEN '🎥 Video'
                                    WHEN m.type = 'document' THEN '📄 Documento'
                                    WHEN m.type = 'sticker' THEN '😀 Sticker'
                                    ELSE ''
                                END
                        )
                        FROM messages m
                        WHERE m.conversation_id = c.id
                        ORDER BY m.timestamp DESC
                        LIMIT 1
                    ) as last_message,
                    -- Contador de mensajes no leídos (mensajes entrantes no leídos)
                    (
                        SELECT COUNT(*)
                        FROM messages m
                        WHERE m.conversation_id = c.id
                        AND m.direction = 'in'
                        AND m.status != 'read'
                    ) as unread_count
                FROM conversations c
                JOIN contacts ct ON c.contact_id = ct.id
                WHERE c.id = :conversation_id
                {account_access_filter}
                LIMIT 1;
            """

            rows = conn.run(query, **params)
            if rows:
                column_names = [col["name"] for col in conn.columns]
                #print("resultado: ", rows)
                result = dict(zip(column_names, rows[0]))
                result = make_json_safe(result)
                #print("resultado 2: ", result)
                return result
            return None

    @staticmethod
    async def get_conversations(user_id: str, account_id: str = None, is_admin: bool = False) -> List[Dict[str, Any]]:
        """Método asíncrono para obtener conversaciones"""
        return await anyio.to_thread.run_sync(
            ConversationService.get_conversations_sync,
            user_id,
            account_id,
            is_admin
        )

    @staticmethod
    async def get_conversation_messages(conversation_id: str, account_id: str, user_id: str, limit: int = 50, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        """Método asíncrono para obtener mensajes de una conversación"""
        mensajes = await anyio.to_thread.run_sync(
            ConversationService.get_conversation_messages_sync,
            conversation_id,
            user_id,
            limit,
            offset
        )

        # obtener IDs de mensajes entrantes no leídos
        message_ids_to_read = [
            {
                "id": msg["id"],
                "wamid": msg["wamid"]
            }
            for msg in mensajes
            if msg["direction"] == "in" and msg["status"] != "read"
        ]
        print("message_ids_to_read: ", message_ids_to_read)

        message_ids = [m["id"] for m in message_ids_to_read]
        wamids = [m["wamid"] for m in message_ids_to_read]

        try:
            # Enviar estado 'seen' a Meta
            await ConversationService.send_seen_status_to_meta(wamids, account_id=account_id)  # Aquí deberías pasar el account_id correcto

            # Marcar mensajes como leídos en la base de datos
            total_mensajes_vistos = await anyio.to_thread.run_sync(
                ConversationService.set_messages_as_read,
                message_ids
            )
        except Exception as e:
            print("Error al marcar mensajes como leídos:", e)
            total_mensajes_vistos = 0

        return mensajes, total_mensajes_vistos

    @staticmethod
    async def get_conversation(conversation_id: str, user_id: str, is_admin: bool = False) -> Dict[str, Any] | None:
        """Método asíncrono para obtener una conversación específica, Verificar que la conversación existe y el usuario tiene acceso"""
        return await anyio.to_thread.run_sync(
            ConversationService.get_conversation_sync,
            conversation_id,
            user_id,
            is_admin
        )
    
    @staticmethod
    async def create_or_get_conversation(contact_id: str, account_id: str, user_id: str) -> Dict[str, Any]:
        """Crear una nueva conversación o retornar la existente para un contacto específico"""
        # Por simplicidad, este método asume que el usuario tiene permiso para el account_id dado.
        # En producción, deberías verificar permisos aquí.

        def create_or_get():
            with get_sync_conn() as conn:
                # Verificar si ya existe una conversación para este contacto y cuenta
                query = """
                    SELECT id FROM conversations
                    WHERE contact_id = :contact_id AND account_id = :account_id
                    LIMIT 1
                """
                rows = conn.run(query, contact_id=contact_id, account_id=account_id)
                if rows:
                    conversation_id = rows[0][0]
                else:
                    # Crear nueva conversación
                    insert_query = """
                        INSERT INTO conversations (contact_id, account_id, created_at, estatus)
                        VALUES (:contact_id, :account_id, NOW(), 'activo')
                        RETURNING id
                    """
                    new_rows = conn.run(insert_query, contact_id=contact_id, account_id=account_id)
                    conversation_id = new_rows[0][0]


                conversion = ConversationService.get_conversation_sync(conversation_id, user_id, is_admin=True)
                messages = ConversationService.get_conversation_messages_sync(conversation_id, user_id)
                return conversion, messages

        return await anyio.to_thread.run_sync(create_or_get)
    
    async def get_message(self, message_id: str, user_id: str) -> Dict[str, Any] | None:
        """Obtener un mensaje específico, Verificar que el mensaje existe y el usuario tiene acceso a la conversación"""
        return await anyio.to_thread.run_sync(
            ConversationService.get_message_sync,
            message_id,
            user_id
        )
    
    @staticmethod
    async def send_seen_status_to_meta(wamids: List[str], account_id: str):
        """
        Marca como leídos una lista de mensajes de WhatsApp en Meta API.
        """
        if not wamids:
            print("no llegó lista")
            return 0
        
        print("wamids tamaño: ", len(wamids))

        account = await get_data_by_account_id(account_id)

        phone_number_id = account['phone_number_id']
        token = account['access_token']

        #print("phone_number_id: ", phone_number_id)

        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = []

            url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{phone_number_id}/messages"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            }

            for wamid in wamids:
                payload = {
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": wamid
                }

                # Crear la tarea async para cada request
                tasks.append(client.post(url, json=payload, headers=headers))

            # Ejecutar todas las requests concurrentemente
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            print("No. Respuestas meta: ", len(responses))

        # Contar cuántos fueron exitosos
        success_count = 0
        for r in responses:
            print("Meta raw response:", r.text)
            if isinstance(r, Exception):
                print("Error al marcar mensaje:", r)
            elif r.status_code in (200, 201):
                success_count += 1
            else:
                print("Fallo API:", r.status_code, r.text)

        return success_count
    
    @staticmethod
    async def send_reaction_to_meta(
        wamid: str,
        emoji: str,
        to: str,
        account_id: str
    ):
        """
        Envía o quita una reacción a un mensaje de WhatsApp vía Meta API.
        Emoji vacío ("") = quitar reacción.
        """

        if not wamid:
            print("wamid vacío")
            return False
        
        account = await get_data_by_account_id(account_id)

        phone_number_id = account['phone_number_id']
        token = account['access_token']

        #print("phone_number_id: ", phone_number_id)

        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{phone_number_id}/messages"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            }

            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "reaction",
                "reaction": {
                    "message_id": wamid,
                    "emoji": emoji  # "" quita la reacción
                }
            }

            try:
                response = await client.post(url, json=payload, headers=headers)
                print("Meta reaction raw response:", response.text)

                if response.status_code in (200, 201):
                    return True
                else:
                    print("Fallo reacción Meta:", response.status_code, response.text)
                    return False

            except Exception as e:
                print("Error enviando reacción a Meta:", e)
                return False


conversation_service = ConversationService()
