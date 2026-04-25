from fastapi import FastAPI
from src.routes.analyze import router as analyze_router
from src.routes.messages import router as messages_router

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
