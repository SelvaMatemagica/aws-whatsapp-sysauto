from app.automations.actions.base import BaseAction
from app.automations.engine.context import ActionContext, ActionResult
from app.models import ParamConfig
from app.routes.templates import render_whatsapp_template, resolve_param
from app.services import accounts_service, templates_service
from app.services.user_whatsapp_accounts_service import get_notification_recipients
from app.db import get_sync_conn
import anyio


class NotifyInternalUsersAction(BaseAction):
    action_type = "notify_internal_users"

    async def execute(self, ctx: ActionContext, config: dict) -> ActionResult:
        account_id = ctx.account_id
        contact = ctx.event.get("contact") or {}
        sender_name = contact.get("name") or "Desconocido"

        notification_users = await get_notification_recipients(account_id)
        if not notification_users:
            return ActionResult(status="completed", output={"notified": 0})

        account = await accounts_service.get_data_by_account_id(account_id)
        if not account:
            return ActionResult(status="failed", error="notify_internal_users: cuenta no encontrada")

        template_id = config.get("template_id") or account.get("notification_template_id")
        if not template_id:
            return ActionResult(status="completed", output={"notified": 0, "reason": "sin plantilla"})

        tpl = await templates_service.get_template_by_id(template_id)
        if not tpl:
            return ActionResult(status="failed", error="notify_internal_users: plantilla no encontrada")

        notified = 0
        for user in notification_users:
            param_config = [{"type": "static", "value": sender_name}]
            parameters = [
                {"type": "text", "text": resolve_param(ParamConfig(**p), user)}
                for p in param_config
            ]
            content = {
                "to": user.get("phone", "").replace("+", ""),
                "type": "template",
                "template_name": tpl.get("name"),
                "language": tpl.get("language"),
                "components": [{"type": "body", "parameters": parameters}],
            }
            message_text = render_whatsapp_template(tpl.get("components", []), content)
            msg_id = await templates_service.queue_template_message(
                user.get("phone", "").replace("+", ""),
                content,
                tpl["id"],
                account,
                user.get("name"),
                message_text,
                tpl.get("header_media_url"),
                None,
                user.get("id"),
            )
            notified += 1

            def _update_send_log(message_id: str) -> None:
                with get_sync_conn() as conn:
                    conn.run(
                        """
                        UPDATE whatsapp_send_logs
                        SET department_name = :dept,
                            user_id = :uid
                        WHERE message_id = :mid
                        """,
                        dept="Notificaciones",
                        uid=user.get("id"),#"96b4edb2-4525-4b7c-9ddf-f009ba208761",
                        mid=message_id,
                    )

            try:
                await anyio.to_thread.run_sync(_update_send_log, msg_id)
            except Exception as exc:
                print(
                    f"[notify_internal_users] warning: no se pudo actualizar whatsapp_send_logs "
                    f"para message {msg_id}: {exc}"
                )

        return ActionResult(status="completed", output={"notified": notified})
