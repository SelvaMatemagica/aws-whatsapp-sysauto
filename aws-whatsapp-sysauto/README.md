# Lambda base para este proyecto

Esta carpeta contiene una entrada simple para AWS Lambda.

## Estructura

- handler.py: punto de entrada de Lambda
- requirements.txt: dependencias mínimas para esta capa

## Qué hace por ahora

- GET /health → responde ok
- POST /login → intenta autenticar usando la misma lógica del proyecto

## Uso en AWS

1. Empaqueta esta carpeta junto con el proyecto raíz.
2. Crea una función Lambda con el handler `lambda.handler.lambda_handler`.
3. Configura API Gateway para enrutar `/login` y `/health`.
