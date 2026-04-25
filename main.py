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
    errors = []
    for err in exc.errors():
        field = " -> ".join(str(loc) for loc in err["loc"] if loc != "body")
        errors.append({
            "field": field or "body",
            "message": err["msg"],
            "invalid_value": err.get("input"),
        })
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "code": "VALIDATION_ERROR",
            "detail": "Los datos enviados son inválidos. Revisa los campos indicados.",
            "errors": errors,
        },
    )

@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={
            "status": "error",
            "code": "CONFLICT",
            "detail": "El recurso que intentas crear ya existe.",
        },
    )

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "code": "INTERNAL_ERROR",
            "detail": "Ocurrió un error interno. Intenta de nuevo más tarde.",
        },
    )

app.include_router(analyze_router, prefix="/api/v1")
app.include_router(messages_router, prefix="/api/v1/messages")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "SENTINEL"}
