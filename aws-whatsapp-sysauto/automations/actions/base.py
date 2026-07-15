from abc import ABC, abstractmethod

from app.automations.engine.context import ActionContext, ActionResult


class BaseAction(ABC):
    action_type: str

    @abstractmethod
    async def execute(self, ctx: ActionContext, config: dict) -> ActionResult:
        raise NotImplementedError
