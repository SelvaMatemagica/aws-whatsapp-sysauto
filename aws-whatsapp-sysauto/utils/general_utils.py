import string
import secrets
from datetime import datetime, date, time
import uuid
import decimal
import json
import re

def generar_cadena(longitud=12):
    caracteres = string.ascii_letters + string.digits + "!@#$%^&*()"
    return ''.join(secrets.choice(caracteres) for _ in range(longitud))

def make_json_safe(value):
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (uuid.UUID)):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: make_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [make_json_safe(v) for v in value]
    return value

def normalizar_telefono_mx(numero: str) -> str:
    """
    Normaliza un número telefónico mexicano al formato 52XXXXXXXXXX
    
    Reglas:
    - Elimina espacios, guiones, paréntesis, etc.
    - Quita el prefijo '1' después de '52' si existe (ej: 521...)
    - Agrega '52' si el número viene sin lada país
    - Devuelve el número en formato 52XXXXXXXXXX
    """

    if not numero:
        return None

    # 1. Quitar todo lo que no sea dígito
    num = re.sub(r'\D', '', numero)

    # 2. Normalizar prefijos
    if num.startswith('521'):
        num = '52' + num[3:]
    elif num.startswith('52'):
        pass
    elif len(num) == 10:
        # número nacional sin lada país
        num = '52' + num
    else:
        # caso no esperado (puedes ajustar según tu lógica)
        return numero

    # 3. Validar longitud final (México = 12 dígitos con país)
    if len(num) != 12:
        return numero

    # 4. Agregar el "+"
    return num

def e164_a_mx_movil(numero: str) -> str:
    """
    Convierte +5255XXXXXXXX a 52155XXXXXXXX
    Si ya viene como +521..., lo deja igual.
    Solo aplica para México (+52)
    """
    if not numero:
        return None

    # Quitar el "+"
    num = numero.replace("+", "")

    # Validar que sea México
    if not num.startswith("52"):
        return num  # no lo modificamos si no es MX

    # Si ya tiene el 1 después de 52, no hacer nada
    if num.startswith("521"):
        return num

    # Insertar '1' después de 52
    return "521" + num[2:]