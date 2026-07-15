from pydantic import BaseModel
from typing import Optional, Any, List, Dict, Literal
from datetime import datetime
import hashlib
from fastapi import UploadFile, File, Form
import json

class SendRequestForm:
    def __init__(
        self,
        to: str = Form(...),
        type: str = Form(...),  # text, image, video, file
        body: str = Form(...),
        account_id: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
        message_id: Optional[str] = Form(None),
    ):
        self.to = to
        self.type = type
        self.body = body
        self.account_id = account_id
        self.file = file
        self.message_id = message_id
    

class ParamConfig(BaseModel):
    type: Literal["static", "user", "computed"]
    value: str | None = None
    field: str | None = None
    format: str | None = None
    base: str | None = None
    query: dict | None = None

class TemplateSendRequest(BaseModel):############################
    template_name: str
    language: str = "es_MX"
    to: List[str]
    #components: List[Dict[str, Any]] | None = None
    namespace: str | None = None
    account_id: Optional[str]
    name: Optional[str] = "Desconocido"
    param_config: list[ParamConfig]
    users: Optional[list[Any]] = []
    origin: Optional[str] = ""
    # El frontend puede enviar sender_email o senderEmail; aceptamos ambos
    sender_email: Optional[str] = None
    message_id: Optional[str] = None

class TemplateSendRequestNewUser(BaseModel):############################
    template_name: str
    language: str = "es_MX"
    to: str
    #components: List[Dict[str, Any]] | None = None
    #namespace: str | None = None
    account_id: Optional[str]
    name: Optional[str] = "Desconocido"
    param_config: Optional[list[ParamConfig]] = []
    #users: Optional[list[Any]] = []
    #origin: Optional[str] = ""
    sender_email: Optional[str] = None

class User(BaseModel):
    name: str
    phone: str

class TemplateSendRequestNewUsers(BaseModel):############################
    template_name: str
    language: str = "es_MX"
    #to: List[str]
    #components: List[Dict[str, Any]] | None = None
    #namespace: str | None = None
    account_id: Optional[str]
    #name: Optional[str] = "Desconocido"
    param_config: Optional[list[ParamConfig]] = []
    users: list[User]
    #origin: Optional[str] = ""
    sender_email: Optional[str] = None
    senderEmail: Optional[str] = None

class TemplateSendRequestBotonLiga(BaseModel):
    Nombre: str
    Teléfono: str

class TemplateRequestSetTemplateToButton(BaseModel):
    account_id: str
    template_id: Optional[str] = None
    number: int

class WebhookMessage(BaseModel):
    object: str
    entry: list

class ChatSummary(BaseModel):
    chat_id: str
    contact_number: str
    display_name: Optional[str]
    last_message: Optional[str]
    last_ts: Optional[datetime]
    unread_count: int = 0



######


class TemplateComponentParam(BaseModel):
    type: str
    text: str | None = None
    # for images/files, you might have {"type":"image","image":{"link": "..."}}

class TemplateComponent(BaseModel):
    type: str
    parameters: list[TemplateComponentParam] | None = None

class TemplateRecord(BaseModel):
    id: str | None
    waba_id: str
    name: str
    language: str
    components: list[TemplateComponent] | None = None
    namespace: str | None = None
    raw: dict | None = None


class LoginRequest(BaseModel):
    email: str
    password: str

class UserIn(BaseModel):
    #id: str
    name: str
    email: str
    role: str
    authorized: bool = False
    created_at: Optional[datetime] = None
    estatus: str = 'activo'
    department: Optional[str] = None 
    department_name: Optional[str] = None


class UserOut(UserIn):
    id: str

class UserCreate(BaseModel):
    name: str
    email: str
    password: str

class UserCreateFull(BaseModel):
    name: str
    email: str
    password: str
    phone: str
    department: Optional[str] = None
    role: str = "user"
    authorized: bool = True
    account_id: Optional[str] = None
    is_admin: bool = False
    can_receive_notifications: bool = False

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    authorized: Optional[bool] = None
    estatus: Optional[str] = None
    account_id: Optional[str] = None
    is_admin: Optional[bool] = None
    can_receive_notifications: Optional[bool] = None

class LoginResponse(BaseModel):
    user: UserOut
    token: str

class ReactionRequest(BaseModel):
    message_id: str
    emoji: str
    to: str
    account_id: Optional[str]

#####

class ContactCreate(BaseModel):
    name: str
    area_code: str
    phone_number: str
    account_id: Optional[str]
    tag: Optional[List[str]] = None
    tag_color: Optional[List[str]] = None

class ContactUpdate(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    #area_code: str
    phone_number: Optional[str] = None
    account_id: Optional[str] = None
    tag: Optional[List[str]] = None
    tag_color: Optional[List[str]] = None

class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None
    account_id: str

class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    account_id: str

class ConversationCreate(BaseModel):
    contact_id: str
    account_id: Optional[str]

class UserWhatsAppAccountCreate(BaseModel):
    user_id: str
    is_admin: bool = False
    can_receive_notifications: bool = False

class UserWhatsAppAccountUpdate(BaseModel):
    is_admin: Optional[bool] = None
    can_receive_notifications: Optional[bool] = None

class WhatsAppAccountCreate(BaseModel):
    phone_number: str
    phone_number_id: str
    access_token: str
    waba_id: str
    display_name: Optional[str] = None
    business_id: Optional[str] = None
    app_id: Optional[str] = None
    webhook_verify_token: Optional[str] = None
    is_active: bool = True
    estatus: str = "activo"
    department_id: Optional[str] = None

class WhatsAppAccountUpdate(BaseModel):
    phone_number: Optional[str] = None
    phone_number_id: Optional[str] = None
    access_token: Optional[str] = None
    waba_id: Optional[str] = None
    display_name: Optional[str] = None
    business_id: Optional[str] = None
    app_id: Optional[str] = None
    webhook_verify_token: Optional[str] = None
    is_active: Optional[bool] = None
    estatus: Optional[str] = None

class WhatsAppAccountDepartmentUpdate(BaseModel):
    department_id: Optional[str] = None

class WhatsAppAccountNotificationTemplateUpdate(BaseModel):
    notification_template_id: Optional[str] = None

b = """ class ProfileUpdateRequest(BaseModel):
    account_id: Optional[str]
    display_name: Optional[str] = None
    vertical: Optional[str] = None
    description: Optional[str] = None
    about: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    websites: Optional[List[str]] = None """

class ProfileUpdateForm:
    def __init__(
        self,
        account_id: Optional[str] = Form(None),
        display_name: Optional[str] = Form(None),
        vertical: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        about: Optional[str] = Form(None),
        address: Optional[str] = Form(None),
        email: Optional[str] = Form(None),
        websites: Optional[str] = Form("[]"),  # JSON string
        image: Optional[UploadFile] = File(None),
    ):
        self.account_id = account_id
        self.display_name = display_name
        self.vertical = vertical
        self.description = description
        self.about = about
        self.address = address
        self.email = email
        self.websites = json.loads(websites)  # Parse JSON string
        self.image = image

a=""" class TemplateCreateRequest(BaseModel):
    account_id: Optional[str]
    name: str
    language: str = "es_MX"
    category: str = "UTILITY"
    parameter_format: str = "positional"
    media_type: str = "NONE"
    header: Optional[str] = None
    body: Optional[str] = None
    footer: Optional[str] = None
    components: List[Dict[str, Any]] = [] """

class TemplateCreateForm:
    def __init__(
        self,
        account_id: Optional[str] = Form(None),
        name: str = Form(...),
        language: str = Form("es_MX"),
        category: str = Form("UTILITY"),
        parameter_format: str = Form("positional"),
        media_type: str = Form("NONE"),
        header: Optional[str] = Form(None),
        body: Optional[str] = Form(None),
        footer: Optional[str] = Form(None),
        components: Optional[str] = Form("[]"),  # 👈 string JSON
        media_file: Optional[UploadFile] = File(None),
    ):
        self.account_id = account_id
        self.name = name
        self.language = language
        self.category = category
        self.parameter_format = parameter_format
        self.media_type = media_type
        self.header = header
        self.body = body
        self.footer = footer
        self.components = json.loads(components)  # 👈 parse aquí
        self.media_file = media_file