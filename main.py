from fastapi import FastAPI
from src.database import engine
from src.models import db_models  # Importante para que Base conozca las tablas
from src.routes.analyze import router as analyze_router
from src.routes.messages import router as messages_router

# Esta línea crea las tablas en sentinel.db si no existen
db_models.Base.metadata.create_all(bind=engine)

app = FastAPI(
      title="SENTINEL API",
      description="Detección de riesgo digital para menores",
      version="0.1.0"
  )

# Rutas de Análisis e IA
app.include_router(analyze_router, prefix="/api/v1")

# Rutas de Mensajería y Sincronización
app.include_router(messages_router, prefix="/api/v1/messages")

@app.get("/health")
def health_check():
      return {"status": "ok", "service": "SENTINEL"}
