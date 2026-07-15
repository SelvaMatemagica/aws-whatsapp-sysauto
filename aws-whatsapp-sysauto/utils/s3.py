
from ..config import settings
from uuid import uuid4
import mimetypes
from ..services.accounts_service import get_by_phone_id, get_account_id_by_phone_number_id
from typing import Optional
import os
import boto3

BUCKET_NAME = "bucket-selva-whatsapp-correos"

s3 = boto3.client(
    "s3",
    aws_access_key_id="AKIAVPLLWPOTPHV56QNV",
    aws_secret_access_key="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",
    region_name="us-east-2",
    #endpoint_url=f"https://s3.us-east-2.amazonaws.com"
)

 
async def upload_to_s3(file_bytes: bytes, content_type: str, get_name: Optional[str] = None) -> str:
    if get_name:
        name, ext = os.path.splitext(get_name)
    else:
        name = uuid4()
        ext = mimetypes.guess_extension(content_type)
    print("ext: ", ext)
    if not ext:
        if content_type == "audio/ogg":
            ext = ".ogg"
        elif content_type == "image/webp":
            ext = ".webp"
        else:
            raise ValueError("Tipo de archivo no soportado")

    account_id = await get_account_id_by_phone_number_id(settings.PHONE_NUMBER_ID)
    filename = f"whatsapp/{account_id}/{name}{ext}"############################cambiar

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=filename,
        Body=file_bytes,
        ContentType=content_type
    )

    file_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{filename}"
    print("file_url: ", file_url)

    return file_url, f"{name}{ext}"


def upload_to_s3_sync(file_bytes: bytes, content_type: str, get_name: Optional[str] = None) -> str:
    if get_name:
        name, ext = os.path.splitext(get_name)
    else:
        name = uuid4()
        ext = mimetypes.guess_extension(content_type)
    print("content_type: ", content_type)
    print("ext: ", ext)
    if not ext:
        if content_type == "audio/ogg":
            ext = ".ogg"
        elif content_type == "image/webp":
            ext = ".webp"
        elif content_type == "image/jpeg":
            ext = ".jpeg"
        elif content_type == "application/pdf":
            ext = ".pdf"
        else:
            raise ValueError("Tipo de archivo no soportado")

    account_id = get_account_id_by_phone_number_id(settings.PHONE_NUMBER_ID)
    
    filename = f"whatsapp/{account_id}/{name}{ext}"############################cambiar

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=filename,
        Body=file_bytes,
        ContentType=content_type
    )

    file_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{filename}"
    print("file_url: ", file_url)

    return file_url, f"{name}{ext}"