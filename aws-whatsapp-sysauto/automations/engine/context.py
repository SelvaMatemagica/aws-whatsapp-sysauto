from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


ActionStatus = Literal["completed", "waiting", "failed"]


@dataclass
class ActionResult:
    status: ActionStatus = "completed"
    wait_until: datetime | None = None
    wait_type: str | None = None
    error: str | None = None
    output: dict | None = None


@dataclass
class ActionContext:
    run_id: str
    account_id: str
    contact_id: str
    conversation_id: str
    event: dict
    variables: dict = field(default_factory=dict)
    automation: dict = field(default_factory=dict)
    current_step_index: int = 0

    def render(self, text: str) -> str:
        contact = self.event.get("contact") or {}
        replacements = {
            "contact.name": contact.get("name") or "",
            "contact.phone_number": contact.get("phone_number") or "",
            "message.text": self.event.get("message_text") or "",
        }
        rendered = text
        for key, value in replacements.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return rendered
