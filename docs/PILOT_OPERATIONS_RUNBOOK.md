# Manual Operativo del Piloto (Runbook S21)

Este manual describe los procedimientos de instalación, configuración, verificación de salud, copias de seguridad, purga de datos, rollback de modelos y gestión de emergencias (kill switches) para la operación supervisada de Sentinel en entornos de demostración, staging y piloto B2B.

---

## 1. Requisitos Previos y Entorno

- **Python:** $\ge 3.11$ (con entorno virtual `venv`).
- **Node.js:** $\ge 20.0$ (para SDK TypeScript y herramientas de verificación).
- **Base de Datos:** SQLite 3 (para piloto local/staging) o PostgreSQL $\ge 15$ (para despliegue multi-instancia).
- **Memoria RAM:** Mínimo 1 GB; recomendado 2 GB.
- **Almacenamiento:** Mínimo 5 GB SSD con soporte de snapshots periódicos.

---

## 2. Configuración y Secretos

1. Copiar la plantilla de configuración:
   ```bash
   cp sentinel-api/.env.example sentinel-api/.env
   ```
2. Configurar variables clave en `.env`:
   - `DATABASE_URL`: URI de conexión (por defecto `sqlite:///./sentinel.db`).
   - `ACTOR_HASH_SALT`: Cadena criptográfica aleatoria de 32 bytes para saltear identificadores y aislar tenants.
   - `TELEMETRY_TOKEN_SECRET`: Secreto independiente para firmar tokens efímeros de telemetría.
   - `ARTIFACT_SIGNING_PRIVATE_KEY`: Clave privada Ed25519 en Base64URL para firmar paquetes y complementos.
   - `SENTINEL_SHADOW_ENABLED`: `true` (por defecto) o `false` para desactivar modelos sombra.
   - `SENTINEL_DISABLE_LLM`: `false` (por defecto) o `true` para operar 100% en modo local determinista.

---

## 3. Inicialización y Migraciones Idempotentes

La creación del esquema de base de datos se realiza de forma declarativa e idempotente:
```bash
cd sentinel-api
source venv/bin/activate
python3 -c "from src.database import engine, Base; from src.models import db_models; Base.metadata.create_all(bind=engine)"
```
- **Idempotencia:** Si las tablas ya existen, `create_all()` no altera los datos preexistentes.
- **Semillas Iniciales:** Inyectar claves de API y términos verificados con:
  ```bash
  python3 scripts/seed_initial_data.py
  ```

---

## 4. Verificación de Salud y Endpoints de Monitoreo

Endpoint unificado: `GET /health` (no requiere autenticación).
```bash
curl -s http://127.0.0.1:8000/health | jq .
```
Respuesta esperada:
```json
{
  "status": "ok",
  "service": "SENTINEL",
  "scraper": "ok",
  "oldest_message_age_days": 12
}
```
- Si `scraper == "stale"`: La última recolección exitosa tiene $>48\text{ h}$. Revisar logs del worker de scraping.
- Si `oldest_message_age_days > MESSAGE_RETENTION_DAYS`: Ejecutar el job de purga.

---

## 5. Respaldos, Restauración y Purga (Legal Hold)

### 5.1. Respaldo Diario
```bash
# SQLite
sqlite3 sentinel.db ".backup 'backups/sentinel_$(date +%Y%m%d_%H%M%S).bak'"

# PostgreSQL
pg_dump -Fc -U sentinel_user -d sentinel_db -f "backups/sentinel_$(date +%Y%m%d_%H%M%S).dump"
```

### 5.2. Restauración de Emergencia
```bash
# SQLite
cp backups/sentinel_YYYYMMDD_HHMMSS.bak sentinel.db

# PostgreSQL
pg_restore -c -U sentinel_user -d sentinel_db backups/sentinel_YYYYMMDD_HHMMSS.dump
```

### 5.3. Política de Purga y Retención Legal (Legal Hold)
- **Mensajes Crudos:** Se purgan automáticamente tras 30 días (`MESSAGE_RETENTION_DAYS=30`).
- **Paquetes de Evidencia Seudónima (Legal Hold):** Las conversaciones asociadas a incidentes confirmados (`HIGH` o `CRITICAL`) con veredicto adjudicado o reporte de moderador se conservan en `evidence_packages` de forma seudónima y encriptada por un período de hasta 365 días para cumplimiento de requerimientos legales o auditoría de menores.
- **Comando de purga:**
  ```bash
  python3 -c "from src.services.maintenance_service import purge_expired_messages; purge_expired_messages(retention_days=30)"
  ```

---

## 6. Procedimientos de Emergencia y Kill Switches

### 6.1. Kill Switch de Modelo Sombra (Laya Multilingüe)
Si el modelo sombra experimenta degradación de latencia o consumo excesivo de memoria:
```bash
export SENTINEL_SHADOW_ENABLED=false
# O reiniciar el servicio con SENTINEL_SHADOW_ENABLED=false en .env
```
- **Efecto:** El evaluador en sombra se apaga inmediatamente; las llamadas a la API y el motor principal continúan operando con cero interrupción.

### 6.2. Kill Switch de Proveedores LLM Externos
Si un proveedor externo (Groq/OpenRouter) sufre una interrupción o aumento anómalo de costos:
```bash
export SENTINEL_DISABLE_LLM=true
```
- **Efecto:** El sistema conmuta automáticamente al modo *fail-closed* local (`local_fallback_verdict` y reglas deterministas locales). Ninguna conversación queda sin protección.

### 6.3. Rollback de Términos / Reglas
Si una actualización de hot terms genera falsas alarmas:
```bash
# Inyectar pack anterior o revertir a la semilla base autenticada
curl -X POST http://127.0.0.1:8000/admin/api/rollback-pack -H "X-API-Key: $ADMIN_KEY"
```

---

## 7. Matriz de Alertas, Presupuesto y Límites del Piloto

| Métrica | Umbral de Alerta | Acción Inmediata |
|---|---|---|
| Latencia $p95$ API | $> 250\text{ ms}$ | Revisar timeouts de base de datos; verificar modo sombra |
| Bloqueos Falsos Reportados | $\ge 1$ caso verificado | Des-escalar regla causante a modo observación; notificar a T&S |
| Gasto LLM Acumulado | $> \$25\text{ USD}$ en 1 semana | Activar `SENTINEL_DISABLE_LLM=true`; revisar tasa de escalación |
| Mensajes sin purgar | $> 35\text{ días}$ | Ejecutar job de purga; verificar scheduler cron |

---

## 8. Lista de Pasos para Despliegue de Demo / Staging

1. Clonar repositorios SDK y API en la máquina anfitriona.
2. Configurar variables en `sentinel-api/.env` siguiendo `.env.example`.
3. Ejecutar suite de validación rápida:
   ```bash
   cd sentinel-sdk && python3 scripts/run_fast_checks.py --all
   ```
4. Iniciar el servicio API:
   ```bash
   cd sentinel-api && source venv/bin/activate
   uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
   ```
5. Comprobar salud en `http://127.0.0.1:8000/health`.
6. Abrir bandeja de moderación en `http://127.0.0.1:8000/moderation`.
