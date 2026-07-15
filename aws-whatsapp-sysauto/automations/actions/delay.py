from datetime import datetime, timedelta, timezone

from app.automations.actions.base import BaseAction
from app.automations.engine.context import ActionContext, ActionResult


class DelayAction(BaseAction):
    action_type = "delay"

    async def execute(self, ctx: ActionContext, config: dict) -> ActionResult:
        minutes = config.get("minutes", 0)
        seconds = config.get("seconds", 0)
        total_seconds = int(minutes) * 60 + int(seconds)

        if total_seconds <= 0:
            return ActionResult(status="completed")

        wait_until = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)
        return ActionResult(
            status="waiting",
            wait_until=wait_until,
            wait_type="delay",
            output={"wait_seconds": total_seconds},
        )
