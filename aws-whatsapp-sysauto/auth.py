# app/auth.py
from jose import jwt, JWTError

try:
    from fastapi import Depends, HTTPException, status
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
except Exception:  # pragma: no cover - fallback for minimal Lambda environments
    class HTTPException(Exception):
        def __init__(self, status_code: int = 500, detail: str | None = None):
            self.status_code = status_code
            self.detail = detail or ""
            super().__init__(detail)

    class _Status:
        HTTP_401_UNAUTHORIZED = 401
        HTTP_403_FORBIDDEN = 403

    status = _Status()

    def Depends(*args, **kwargs):
        return None

    class HTTPAuthorizationCredentials:  # type: ignore[override]
        pass

    class HTTPBearer:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, *args, **kwargs):
            return None

from app.config import settings
from app.db import get_sync_conn
import anyio
from typing import Union
import logging

security = HTTPBearer()

logger = logging.getLogger(__name__)

class User:
    def __init__(self, id: str):
        self.id = id

class Service:
    def __init__(self, name: str, scopes: list[str]):
        self.name = name
        self.scopes = scopes

async def get_current_user_from_ws(token: str | None):
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"], audience="core-api-whatsapp")
        user_id = payload.get("sub")
        if not user_id:
            return None
        # optionally fetch user from DB to validate status/permissions
        return User(id=user_id)
    except JWTError:
        return None

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Union[User, Service]:
    """Dependency para autenticar usuarios en endpoints HTTP"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"], audience="core-api-whatsapp")

        # ---- USUARIO ----
        if "sub" in payload:
            return User(id=payload["sub"])


        # ---- SERVICIO ----
        if "iss" in payload:
            scopes = payload.get("scope", [])
            return Service(
                name=payload["iss"],
                scopes=scopes
            )
        print("llegó lejos")
        raise HTTPException(status_code=401)
    except JWTError as e:
        print("salió error: ", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

async def verify_account_permission(user_id: str, account_id: str):
    logger.info("verify_account_permission start user_id=%s account_id=%s", user_id, account_id)
    if account_id is None:
        logger.warning("verify_account_permission rejected: account_id is None for user_id=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account_id es requerido"
        )
    
    # Obtener de base de datos si usuario tiene permiso sobre cuenta de whatsapp
    def get_if_user_has_permission():
        with get_sync_conn() as conn:

            q = "SELECT role, authorized, estatus FROM users WHERE id = :user_id LIMIT 1;"
            rows = conn.run(q, user_id=user_id)

            if not rows:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, 
                    detail="Usuario no existe"
                )
            
            role = rows[0][0]
            authorized = rows[0][1]
            estatus = rows[0][2]

            if not authorized or estatus != 'activo':
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, 
                    detail="Usuario no autorizado o inactivo"
                )
            
            if role == "admin":
                print("admin")
                return True    ##################################### Si un admin tiene permiso para todos los números



            q = """
            SELECT 1
            FROM user_whatsapp_accounts uwa
            INNER JOIN users u ON u.id = uwa.user_id
            INNER JOIN whatsapp_accounts wa ON wa.id = uwa.whatsapp_account_id
            WHERE uwa.user_id = :user_id
                AND uwa.whatsapp_account_id = :account_id
                AND u.authorized = TRUE
                AND u.estatus = 'activo'
                AND wa.is_active = TRUE
                AND wa.estatus = 'activo'
            LIMIT 1;
            """
            # For brevity: you should implement conversation lookup/creation.
            rows = conn.run(q, user_id=user_id, account_id=account_id)
            print("user: ", user_id)
            print("account_id: ", account_id)
            print("obtuvo si tiene permiso")
            print("row: ", rows)
            if not rows:
                logger.warning(
                    "verify_account_permission rejected user_id=%s account_id=%s: no account membership found",
                    user_id,
                    account_id,
                )
            return rows[0][0] if rows else None

    has_permission = await anyio.to_thread.run_sync(get_if_user_has_permission)

    if not has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para usar esta cuenta de WhatsApp"
        )


async def verify_user_admin(user_id: str) -> bool:
    
    # Obtener de base de datos si usuario tiene permiso sobre cuenta de whatsapp
    def get_if_user_is_admin():
        with get_sync_conn() as conn:

            q = "SELECT role, authorized, estatus FROM users WHERE id = :user_id LIMIT 1;"
            rows = conn.run(q, user_id=user_id)

            if not rows:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, 
                    detail="Usuario no existe"
                )
            
            role = rows[0][0]
            authorized = rows[0][1]
            estatus = rows[0][2]

            if not authorized or estatus != 'activo':
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, 
                    detail="Usuario no autorizado o inactivo"
                )
            
            if role == "admin":
                print("admin")
                return True
            else:
                return False

    has_permission = await anyio.to_thread.run_sync(get_if_user_is_admin)

    return has_permission


async def verify_account_admin(user_id: str, account_id: str):
    if account_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account_id es requerido"
        )

    def get_if_user_is_account_admin():
        with get_sync_conn() as conn:
            q = "SELECT role, authorized, estatus FROM users WHERE id = :user_id LIMIT 1;"
            rows = conn.run(q, user_id=user_id)

            if not rows:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Usuario no existe"
                )

            role = rows[0][0]
            authorized = rows[0][1]
            estatus = rows[0][2]

            if not authorized or estatus != 'activo':
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Usuario no autorizado o inactivo"
                )

            if role == "admin":
                return True

            q = """
            SELECT uwa.is_admin
            FROM user_whatsapp_accounts uwa
            INNER JOIN users u ON u.id = uwa.user_id
            INNER JOIN whatsapp_accounts wa ON wa.id = uwa.whatsapp_account_id
            WHERE uwa.user_id = :user_id
                AND uwa.whatsapp_account_id = :account_id
                AND uwa.is_admin = TRUE
                AND u.authorized = TRUE
                AND u.estatus = 'activo'
                AND wa.is_active = TRUE
                AND wa.estatus = 'activo'
            LIMIT 1;
            """
            rows = conn.run(q, user_id=user_id, account_id=account_id)
            return bool(rows)

    is_account_admin = await anyio.to_thread.run_sync(get_if_user_is_account_admin)

    if not is_account_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos de administrador sobre esta cuenta de WhatsApp"
        )
