from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from src.database import engine, get_db
from sqlalchemy.orm import Session
from src.models import db_models
from src.core.security import require_client_key, require_admin_key
import time
import logging
import math

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sentinel_api")
from src.routes.analyze import router as analyze_router
from src.routes.messages import router as messages_router
from src.routes.messages_crud import router as messages_crud_router
from src.routes.hot_terms import router as hot_terms_router
from src.routes.scraper import router as scraper_router
from src.routes.admin import router as admin_router
from src.routes.feedback import router as feedback_router
from src.routes.network import router as network_router
from src.routes.evidence import router as evidence_router

db_models.Base.metadata.create_all(bind=engine)

# 120 req/min por IP como límite global; el middleware lo aplica a todas las rutas.
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

app = FastAPI(
    title="SENTINEL API",
    description="Detección de riesgo digital para menores",
    version="0.1.0"
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - {response.status_code} - {process_time:.4f}s")
    response.headers["X-Process-Time"] = str(process_time)
    return response

TRANSLATIONS = {
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

def error_response(status_code: int, details):
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "status_code": status_code,
            "details": details,
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    messages = []
    for err in exc.errors():
        field = " -> ".join(str(loc) for loc in err["loc"] if loc != "body")
        field_label = f"El campo '{field}'" if field else "El cuerpo de la solicitud"
        msg = TRANSLATIONS.get(err["msg"], err["msg"])
        messages.append(f"{field_label} {msg}")
    return error_response(422, messages)

@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    return error_response(409, "El recurso que intentas crear ya existe.")

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return error_response(500, "Ocurrió un error interno. Intenta de nuevo más tarde.")

# Client routes (require client key, rate limit 60/minute)
# We can't apply rate limits directly to include_router without slowapi router setup easily,
# but we can apply the security dependency. For slowapi, it is usually applied via decorators on routes.
# To keep it simple as requested by the plan, we will add the dependencies to the routers.
app.include_router(analyze_router, prefix="/api/v1", dependencies=[Depends(require_client_key)])
app.include_router(messages_router, prefix="/api/v1/messages", dependencies=[Depends(require_client_key)])
app.include_router(feedback_router, prefix="/api/v1/feedback", dependencies=[Depends(require_client_key)])
app.include_router(evidence_router, prefix="/api/v1/evidence")
# Admin routes (require admin key)
app.include_router(messages_crud_router, prefix="/api/v1/admin/messages", dependencies=[Depends(require_admin_key)])
app.include_router(scraper_router, prefix="/api/v1/admin/scrape", dependencies=[Depends(require_admin_key)])
app.include_router(admin_router, prefix="/admin", dependencies=[Depends(require_admin_key)])
app.include_router(network_router, prefix="/api/v1/network")

# hot_terms has both GET (client) and POST (admin) so it needs granular protection in the router itself
app.include_router(hot_terms_router, prefix="/api/v1/hot-terms")

# Static files for the Playground
app.mount("/public", StaticFiles(directory="public"), name="public")

@app.get("/playground", include_in_schema=False)
async def serve_playground():
    return FileResponse("public/playground.html")

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    from src.models.db_models import ScraperRun, Message
    last_run = db.query(ScraperRun).filter(ScraperRun.status == "success").order_by(ScraperRun.started_at.desc()).first()
    
    now = int(time.time())
    scraper_status = "ok"
    if not last_run or last_run.finished_at is None or (now - last_run.finished_at > 48 * 3600):
        scraper_status = "stale"
        
    # Check retention policy (max message age)
    oldest_msg = db.query(Message).order_by(Message.timestamp.asc()).first()
    oldest_message_age_days = 0
    if oldest_msg:
        oldest_message_age_days = math.floor((now - oldest_msg.timestamp) / (24 * 3600))
        
    return {
        "status": "ok", 
        "service": "SENTINEL",
        "scraper": scraper_status,
        "oldest_message_age_days": oldest_message_age_days
    }
