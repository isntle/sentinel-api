from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from src.database import engine
from src.models import db_models
from src.routes.analyze import router as analyze_router
from src.routes.messages import router as messages_router

db_models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SENTINEL API",
    description="Detección de riesgo digital para menores",
    version="0.1.0"
)

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    messages = []
    for err in exc.errors():
        field = " -> ".join(str(loc) for loc in err["loc"] if loc != "body")
        field_label = f"El campo '{field}'" if field else "El cuerpo de la solicitud"
        raw_msg = err['msg']
        translations = {
            "Field required": "es obligatorio",
            "String should have at least 1 character": "no puede estar vacío",
            "String should have at most 5000 characters": "no puede superar los 5000 caracteres",
            "Input should be greater than 0": "debe ser mayor a 0",
            "Input should be greater than or equal to 0": "debe ser mayor o igual a 0",
            "Input should be less than or equal to 100": "debe ser menor o igual a 100",
            "Value error, El campo no puede ser solo espacios en blanco": "no puede ser solo espacios en blanco",
            "Input should be a valid integer, unable to parse string as an integer": "debe ser un número entero",
            "Input should be a valid string": "debe ser texto",
            "Input should be a valid boolean": "debe ser verdadero o falso",
            "Input should be a valid list": "debe ser una lista",
            "Input should be a valid number": "debe ser un número",
            "Extra inputs are not permitted": "no es un campo permitido",
            "Value is not a valid enumeration member": "tiene un valor no permitido",
            "Input should be a valid UUID": "debe ser un UUID válido",
            "String should match pattern": "tiene un formato inválido",
            "Input should be a valid integer, got a number with a fractional part": "debe ser un número entero, sin decimales",
        }
        msg = translations.get(raw_msg, raw_msg)
        messages.append(f"{field_label} {msg}")
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "status_code": 422,
            "detail": messages,
        },
    )

@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={
            "status": "error",
            "status_code": 409,
            "detail": "El recurso que intentas crear ya existe.",
        },
    )

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "status_code": 500,
            "detail": "Ocurrió un error interno. Intenta de nuevo más tarde.",
        },
    )

app.include_router(analyze_router, prefix="/api/v1")
app.include_router(messages_router, prefix="/api/v1/messages")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "SENTINEL"}
