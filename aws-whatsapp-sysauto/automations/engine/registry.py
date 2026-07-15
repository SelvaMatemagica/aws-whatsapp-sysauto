class BaseAction:  # pragma: no cover - fallback used when the app automation modules are unavailable
    action_type = ""


ACTION_REGISTRY: dict[str, BaseAction] = {}
REGISTRY_IMPORT_ERROR: Exception | None = None

try:
    from app.automations.actions.add_tag import AddTagAction
    from app.automations.actions.base import BaseAction
    from app.automations.actions.delay import DelayAction
    from app.automations.actions.notify_internal_users import NotifyInternalUsersAction
    from app.automations.actions.send_text import SendTextAction

    ACTION_REGISTRY = {
        SendTextAction.action_type: SendTextAction(),
        AddTagAction.action_type: AddTagAction(),
        DelayAction.action_type: DelayAction(),
        NotifyInternalUsersAction.action_type: NotifyInternalUsersAction(),
    }
except Exception as exc:  # pragma: no cover - allows the Lambda entrypoint to import in minimal environments
    REGISTRY_IMPORT_ERROR = exc
