from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

AutomationStatus = Literal["draft", "active", "paused", "archived"]


class AutomationAction(BaseModel):
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class AutomationCreate(BaseModel):
    account_id: str
    name: str
    description: Optional[str] = None
    priority: int = 100
    trigger_type: str = "message.received"
    trigger_config: dict[str, Any] = Field(default_factory=lambda: {"match": {"type": "any"}})
    actions: list[AutomationAction] = Field(default_factory=list)
    graph: Optional[dict[str, Any]] = None
    stop_on_human_reply: bool = True
    status: AutomationStatus = "draft"


class AutomationUpdate(BaseModel):
    account_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[dict[str, Any]] = None
    actions: Optional[list[AutomationAction]] = None
    graph: Optional[dict[str, Any]] = None
    stop_on_human_reply: Optional[bool] = None
    status: Optional[AutomationStatus] = None


class AutomationOut(BaseModel):
    id: str
    account_id: str
    name: str
    description: Optional[str] = None
    status: AutomationStatus
    priority: int
    trigger_type: str
    trigger_config: dict[str, Any]
    actions: list[dict[str, Any]]
    graph: Optional[dict[str, Any]] = None
    current_version: int
    stop_on_human_reply: bool
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConversationAutomationUpdate(BaseModel):
    account_id: str
    paused: bool
