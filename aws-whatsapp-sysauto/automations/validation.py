from app.automations.engine.registry import ACTION_REGISTRY

VALID_TRIGGER_TYPES = {"message.received"}
VALID_MATCH_TYPES = {"any", "text_equals", "text_contains_any", "message_type"}


class AutomationValidationError(ValueError):
    pass


def validate_trigger_config(trigger_config: dict) -> None:
    if not isinstance(trigger_config, dict):
        raise AutomationValidationError("trigger_config debe ser un objeto JSON")

    match = trigger_config.get("match", {"type": "any"})
    if not isinstance(match, dict):
        raise AutomationValidationError("trigger_config.match debe ser un objeto")

    match_type = match.get("type", "any")
    if match_type not in VALID_MATCH_TYPES:
        raise AutomationValidationError(
            f"trigger_config.match.type inválido: {match_type}. "
            f"Válidos: {', '.join(sorted(VALID_MATCH_TYPES))}"
        )

    if match_type in {"text_equals", "text_contains_any", "message_type"}:
        values = match.get("values")
        if not values or not isinstance(values, list):
            raise AutomationValidationError(
                f"trigger_config.match.values es requerido para type={match_type}"
            )

    conditions = trigger_config.get("conditions", [])
    if conditions and not isinstance(conditions, list):
        raise AutomationValidationError("trigger_config.conditions debe ser una lista")


def validate_actions(actions: list) -> None:
    if not isinstance(actions, list):
        raise AutomationValidationError("actions debe ser una lista")

    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise AutomationValidationError(f"actions[{index}] debe ser un objeto")

        action_type = action.get("type")
        if not action_type:
            raise AutomationValidationError(f"actions[{index}].type es requerido")

        if action_type not in ACTION_REGISTRY:
            raise AutomationValidationError(
                f"actions[{index}].type inválido: {action_type}. "
                f"Válidos: {', '.join(sorted(ACTION_REGISTRY.keys()))}"
            )

        config = action.get("config")
        if config is not None and not isinstance(config, dict):
            raise AutomationValidationError(f"actions[{index}].config debe ser un objeto")


def validate_automation_payload(
    trigger_type: str,
    trigger_config: dict,
    actions: list,
) -> None:
    if trigger_type not in VALID_TRIGGER_TYPES:
        raise AutomationValidationError(
            f"trigger_type inválido: {trigger_type}. "
            f"Válidos: {', '.join(sorted(VALID_TRIGGER_TYPES))}"
        )

    validate_trigger_config(trigger_config or {})
    validate_actions(actions or [])
