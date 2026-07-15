import unicodedata


def _normalize_text(text: str) -> str:
    text = (text or "").lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _get_field_value(event: dict, field: str):
    parts = field.split(".")
    value = event
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def eval_condition(condition: dict, event: dict) -> bool:
    field = condition.get("field", "")
    operator = condition.get("operator", "equals")
    expected = condition.get("value")
    actual = _get_field_value(event, field)

    if operator == "equals":
        return actual == expected
    if operator == "not_equals":
        return actual != expected
    if operator == "contains":
        if actual is None:
            return False
        if isinstance(actual, list):
            return expected in actual
        return str(expected) in str(actual)
    if operator == "not_contains":
        if actual is None:
            return True
        if isinstance(actual, list):
            return expected not in actual
        return str(expected) not in str(actual)
    if operator == "exists":
        return actual is not None and actual != ""
    if operator == "not_exists":
        return actual is None or actual == ""

    return False


def matches_trigger(trigger_config: dict, event: dict) -> bool:
    match = trigger_config.get("match", {"type": "any"})
    text = _normalize_text(event.get("message_text") or "")

    match_type = match.get("type", "any")
    if match_type == "any":
        pass
    elif match_type == "text_equals":
        values = [_normalize_text(v) for v in match.get("values", [])]
        if text not in values:
            return False
    elif match_type == "text_contains_any":
        values = [_normalize_text(v) for v in match.get("values", [])]
        if not any(v in text for v in values):
            return False
    elif match_type == "message_type":
        if event.get("message_type") not in match.get("values", []):
            return False
    else:
        return False

    for condition in trigger_config.get("conditions", []):
        if not eval_condition(condition, event):
            return False

    return True
