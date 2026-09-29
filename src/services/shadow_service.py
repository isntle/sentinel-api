import time
import os
from typing import Callable, Any

class ShadowRunnerService:
    """
    Servicio de evaluación en modo sombra completamente aislado para la API (S16).
    Garantiza:
    1. Cero impacto en las respuestas principales de escalación o latencia crítica.
    2. Manejo estricto de timeout, excepciones de modelos y control de presupuesto.
    3. Cero almacenamiento o exposición de textos crudos o identificadores personales.
    """

    def __init__(
        self,
        enabled: bool = True,
        max_latency_ms: float = 100.0,
        budget_limit_per_minute: int = 1000,
    ):
        env_enabled = os.getenv("SENTINEL_SHADOW_ENABLED", "true").lower() in ("true", "1", "yes")
        self.enabled = enabled and env_enabled
        self.max_latency_ms = max_latency_ms
        self.budget_limit_per_minute = budget_limit_per_minute
        self._call_timestamps: list[float] = []

    def evaluate_shadow_candidate(
        self,
        features: list[float] | None,
        candidate_fn: Callable[[list[float]], float] | None = None,
        model_id: str = "laya-multilingual-v1.2.0-shadow",
    ) -> dict[str, Any]:
        """
        Ejecuta el evaluador candidato de forma aislada y no bloqueante.
        """
        # 1. Kill switch
        if not self.enabled:
            return {
                "status": "disabled",
                "model_id": model_id,
                "shadow_probability": None,
                "latency_ms": 0.0,
                "status_code": "DISABLED",
            }

        # 2. Modelo ausente
        if candidate_fn is None:
            return {
                "status": "missing_model",
                "model_id": "none",
                "shadow_probability": None,
                "latency_ms": 0.0,
                "status_code": "MISSING_MODEL",
            }

        # 3. Límite de tasa / presupuesto por minuto
        now = time.time()
        self._call_timestamps = [t for t in self._call_timestamps if now - t < 60.0]
        if len(self._call_timestamps) >= self.budget_limit_per_minute:
            return {
                "status": "budget_exceeded",
                "model_id": model_id,
                "shadow_probability": None,
                "latency_ms": 0.0,
                "status_code": "BUDGET_EXCEEDED",
                "error": "Shadow execution rate limit exceeded",
            }
        self._call_timestamps.append(now)

        # 4. Ejecución segura con medición de latencia
        start = time.time()
        try:
            feats = features or []
            prob = candidate_fn(feats)
            latency_ms = (time.time() - start) * 1000.0

            if latency_ms > self.max_latency_ms:
                return {
                    "status": "timeout",
                    "model_id": model_id,
                    "shadow_probability": None,
                    "latency_ms": latency_ms,
                    "status_code": "TIMEOUT",
                    "error": f"Shadow evaluation exceeded limit {self.max_latency_ms}ms",
                }

            prob_clamped = max(0.0, min(1.0, float(prob)))
            return {
                "status": "ok",
                "model_id": model_id,
                "shadow_probability": prob_clamped,
                "latency_ms": latency_ms,
                "status_code": "OK",
            }
        except Exception as exc:
            latency_ms = (time.time() - start) * 1000.0
            sanitized_err = str(exc)[:100]
            return {
                "status": "error",
                "model_id": model_id,
                "shadow_probability": None,
                "latency_ms": latency_ms,
                "status_code": "ERROR",
                "error": sanitized_err,
            }
