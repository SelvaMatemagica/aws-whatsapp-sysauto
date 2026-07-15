# app/automations/events/types.py

from enum import StrEnum

class EventType(StrEnum):
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_STATUS_UPDATED = "message.status_updated"
    CONTACT_CREATED = "contact.created"
    TAG_ADDED = "tag.added"
    # Fase 2
    CONVERSATION_IDLE = "conversation.idle"
    SCHEDULE_TICK = "schedule.tick"