from fastapi import FastAPI                                                                             
from src.routes.analyze import router  # se importa el router que ya se creo                                                               

app = FastAPI(
      title="SENTINEL API",
      description="Detección de riesgo digital para menores",
      version="0.1.0"
  )

app.include_router(router, prefix="/api/v1") # registra todas las routas del router en la app pero con el prefijo antes de la direccion de la routa
#entonces la routa base que tenemos se llama asi POST /api/v1/analyze

@app.get("/health")
def health_check():
      return {"status": "ok", "service": "SENTINEL"}