from fastapi import UploadFile
from ..config import settings
import httpx
import asyncio


async def get_upload_session(app_id: str, access_token: str, image: UploadFile):
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{app_id}/uploads?file_name={image.filename}&file_length={image.size}&file_type={image.content_type}&access_token={access_token}"
    #headers = {"Authorization": f"Bearer {access_token}"}
    print("Uploading profile picture to Meta...")
    print("url: ", url)
    async with httpx.AsyncClient(timeout=60) as client:
        #content = await image.read()
        #files = {"file": (image.filename, content, image.content_type)}
        r = await client.post(url)
        #r = await client.post(url, files=files)
        print("Meta raw response for image upload:", r.text)
        r.raise_for_status()
        response_data = r.json()
        if "id" not in response_data:
            raise Exception(f"Unexpected response from Meta when getting upload session: {response_data}")
        return response_data["id"]
    
    
async def upload_file(session_id: str, access_token: str, image: UploadFile, content: bytes, file_offset: int = 0):
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{session_id}"
    headers = {
        "Authorization": f"OAuth {access_token}", 
        "file_offset": str(file_offset),
        "Content-Type": image.content_type
        }
    print("Uploading file to Meta...")
    print("url: ", url)
    async with httpx.AsyncClient(timeout=60) as client:
        #files = {"file": (image.filename, content, image.content_type)}
        r = await client.post(url, headers=headers, content=content)
        print("Meta raw response for file upload:", r.text)
        r.raise_for_status()
        response_data = r.json()
        if "h" not in response_data:
            raise Exception(f"Unexpected response from Meta when uploading file: {response_data}")
        return response_data["h"]
    
    
async def resume_interrupted_upload(session_id: str, access_token: str):
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{session_id}"
    headers = {"Authorization": f"OAuth {access_token}"}
    print("Resuming interrupted file upload to Meta...")
    print("url: ", url)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers=headers)
        print("Meta raw response for resuming file upload:", r.text)
        r.raise_for_status()
        response_data = r.json()
        if "file_offset" not in response_data:
            raise Exception(f"Unexpected response from Meta when resuming file upload: {response_data}")
        return response_data
    

async def upload_with_retry(app_id, access_token, image: UploadFile, max_retries=5):
    session_id = await get_upload_session(app_id, access_token, image)
    content = await image.read()

    attempt = 0
    offset = 0

    while attempt < max_retries:
        try:
            print(f"Intento {attempt + 1}, offset={offset}")
            return await upload_file(session_id, access_token, image, content, file_offset=offset)

        except Exception as e:
            print(f"Error en intento {attempt + 1}: {e}")

            attempt += 1

            # esperar un poco antes de reintentar
            await asyncio.sleep(2)

            # intentar recuperar offset actual
            try:
                resume_data = await resume_interrupted_upload(session_id, access_token)
                offset = int(resume_data.get("file_offset", 0))
            except Exception as resume_error:
                print(f"No se pudo obtener offset: {resume_error}")
                # si ni siquiera puedes recuperar el offset, reinicias
                offset = 0

    raise Exception("Falló la subida después de múltiples intentos")