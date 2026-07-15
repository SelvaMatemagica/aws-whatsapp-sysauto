import json

import anyio

from app.automations.actions.base import BaseAction
from app.automations.engine.context import ActionContext, ActionResult
from app.db import get_sync_conn


class AddTagAction(BaseAction):
    action_type = "add_tag"

    async def execute(self, ctx: ActionContext, config: dict) -> ActionResult:
        tag = config.get("tag")
        tag_color = config.get("color")
        if not tag:
            return ActionResult(status="failed", error="add_tag: tag requerido")

        def update_tags():
            with get_sync_conn() as conn:
                rows = conn.run(
                    """
                    SELECT tag, tag_color
                    FROM contacts
                    WHERE id = :contact_id AND account_id = :account_id
                    LIMIT 1
                    """,
                    contact_id=ctx.contact_id,
                    account_id=ctx.account_id,
                )
                if not rows:
                    return None

                current_tags = rows[0][0] or []
                current_colors = rows[0][1] or []

                if isinstance(current_tags, str):
                    current_tags = json.loads(current_tags) if current_tags.startswith("[") else [current_tags]
                if isinstance(current_colors, str):
                    current_colors = json.loads(current_colors) if current_colors.startswith("[") else [current_colors]

                if tag not in current_tags:
                    current_tags.append(tag)
                    if tag_color:
                        while len(current_colors) < len(current_tags):
                            current_colors.append(None)
                        current_colors[len(current_tags) - 1] = tag_color

                conn.run(
                    """
                    UPDATE contacts
                    SET tag = :tag, tag_color = :tag_color
                    WHERE id = :contact_id AND account_id = :account_id
                    """,
                    tag=current_tags,
                    tag_color=current_colors if tag_color else rows[0][1],
                    contact_id=ctx.contact_id,
                    account_id=ctx.account_id,
                )
                return current_tags

        updated_tags = await anyio.to_thread.run_sync(update_tags)
        if updated_tags is None:
            return ActionResult(status="failed", error="add_tag: contacto no encontrado")

        return ActionResult(status="completed", output={"tags": updated_tags})
