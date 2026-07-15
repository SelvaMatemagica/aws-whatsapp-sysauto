import json

import anyio
import redis.asyncio as aioredis

from app.automations.actions.base import BaseAction
from app.automations.engine.context import ActionContext, ActionResult
from app.config import settings
from app.db import get_sync_conn
from app.services.accounts_service import get_data_by_account_id
from app.utils.general_utils import generar_cadena


class SendTextAction(BaseAction):
    action_type = "send_text"

    async def execute(self, ctx: ActionContext, config: dict) -> ActionResult:
        body = ctx.render(config.get("body", ""))
        if not body.strip():
            return ActionResult(status="failed", error="send_text: body vacío")

        contact = ctx.event.get("contact") or {}
        phone_number = contact.get("phone_number") or contact.get("wa_id")
        if not phone_number:
            return ActionResult(status="failed", error="send_text: teléfono no disponible")

        content = {
            "to": phone_number.replace("+", ""),
            "type": "text",
            "body": body,
        }

        def insert_and_queue():
            with get_sync_conn() as conn:
                rows = conn.run(
                    """
                    INSERT INTO messages
                        (conversation_id, direction, type, content, status, wamid, is_from_user, updated_at, message_text)
                    VALUES
                        (:conversation_id, 'out', 'text', :content::jsonb, 'queued', :wamid, FALSE, NOW(), :message_text)
                    RETURNING id
                    """,
                    conversation_id=ctx.conversation_id,
                    content=json.dumps(content),
                    wamid=generar_cadena(30),
                    message_text=body,
                )
                message_id = str(rows[0][0])
                conn.run(
                    """
                    UPDATE conversations
                    SET last_message_at = NOW(), general_last_message_at = NOW()
                    WHERE id = :conversation_id
                    """,
                    conversation_id=ctx.conversation_id,
                )
                return message_id

        message_id = await anyio.to_thread.run_sync(insert_and_queue)

        account_data = await get_data_by_account_id(ctx.account_id)
        phone_number_id = account_data.get("phone_number_id") if account_data else None
        if not phone_number_id:
            return ActionResult(status="failed", error="send_text: phone_number_id no encontrado")

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        job = {"message_id": message_id, "conversation_id": ctx.conversation_id}
        await r.rpush(f"queue:{phone_number_id}", json.dumps(job))

        return ActionResult(status="completed", output={"message_id": message_id})
