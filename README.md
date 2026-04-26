# Sentinel API

**Backend de análisis de riesgo digital para menores en México.**

Sentinel API es el núcleo de procesamiento de la infraestructura Sentinel. Recibe escalaciones del SDK cuando el motor local detecta conversaciones en zona gris, orquesta el análisis con IA, persiste el historial de sesiones y expone endpoints de administración para los equipos que integran la solución.

---

## Problema que resuelve

El SDK de Sentinel realiza un análisis local ultrarrápido, pero hay casos donde el contexto completo de una conversación requiere comprensión semántica profunda — especialmente en jerga criminal mexicana que cambia constantemente. La API resuelve ese gap: actúa como el cerebro centralizado que combina el contexto del motor local con un LLM de alta capacidad para dar un veredicto definitivo.

---

## Tecnologías y herramientas

| Herramienta | Uso |
|---|---|
| Python 3.13 | Lenguaje principal |
| FastAPI | Framework web y validación |
| SQLAlchemy | ORM para manejo de base de datos |
| SQLite | Base de datos (prototipo) |
| Pydantic v2 | Validación de modelos y tipado |
| Groq SDK | Cliente para el LLM |
| python-dotenv | Manejo de variables de entorno |
| uvicorn | Servidor ASGI |
| Railway | Deploy en la nube |

---

## Arquitectura

```
SDK (cliente)
     │
     │ POST /api/v1/messages/sync    — registra mensaje, devuelve historial
     │ POST /api/v1/analyze          — análisis profundo con IA
     ▼
Sentinel API (FastAPI)
     │
     ├── src/routes/         — endpoints HTTP
     ├── src/controllers/    — lógica de negocio
     ├── src/services/       — acceso a DB e IA
     ├── src/models/         — modelos Pydantic y SQLAlchemy
     └── src/config/         — configuración y variables de entorno
     │
     ├── SQLite (sentinel.db) — persistencia de usuarios, sesiones y mensajes
     └── Groq API             — análisis contextual con LLaMA 3.3 70B
```

### Base de datos

```
users ──────────────── user_sessions ──────────────── sessions
  │                                                      │
  │                                                      │
  └──────────────────── messages ───────────────────────┘

users:        id (PK), user_id, profile
sessions:     id (PK), created_at, last_activity, purge_at (7 días)
user_sessions: user_id (FK), session_id (FK)
messages:     id (PK), user_id (FK), session_id (FK), content, timestamp
```

Las sesiones se purgan automáticamente a los 7 días para no retener datos de menores indefinidamente.

---

## Instalación y ejecución local

### Requisitos

- Python 3.11+
- Una API key de [Groq](https://console.groq.com)

### Pasos

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd sentinel-api

# 2. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env y agregar tu GROQ_API_KEY

# 5. Levantar el servidor
uvicorn main:app --reload
```

El servidor queda disponible en `http://localhost:8000`.

### Variables de entorno

| Variable | Descripción |
|---|---|
| `GROQ_API_KEY` | API key de Groq Cloud |

---

## Endpoints

Todas las respuestas siguen la estructura:

```json
// Éxito
{ "success": true, "status_code": 200, "data": { ... } }

// Error
{ "success": false, "status_code": 422, "details": ["El campo '...' es obligatorio"] }
```

### Mensajería

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/messages/sync` | Registra un mensaje y devuelve el historial de la sesión |

**Body:**
```json
{
  "message": {
    "user_id": "uuid-del-usuario",
    "session_id": "uuid-de-la-sesion",
    "content": "texto del mensaje",
    "timestamp": 1745600000
  }
}
```

### Análisis con IA

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/analyze` | Análisis contextual profundo con LLaMA 3.3 70B |

**Body:**
```json
{
  "analysis": {
    "score": 85,
    "risk": "HIGH",
    "escalate": true,
    "categories": ["reclutamiento"],
    "termsFound": ["jale", "plaza"],
    "triggeredRules": ["rule_grooming_1"],
    "velocityFlag": false,
    "velocityWindow": 0
  },
  "messages": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "session_id": "uuid",
      "content": "oye te interesa el jale",
      "timestamp": 1745600000
    }
  ]
}
```

**Respuesta:**
```json
{
  "success": true,
  "status_code": 200,
  "data": {
    "score": 85,
    "risk": "HIGH",
    "stage": "CAPTACION",
    "categories": ["reclutamiento"],
    "termsFound": ["jale", "plaza"],
    "ux_recommendation": "SOFT_BLOCK"
  }
}
```

### Administración (CRUD de mensajes)

Para uso exclusivo del equipo de desarrollo. Permite gestionar mensajes sin acceder directamente a la base de datos.

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/admin/messages` | Listar todos los mensajes |
| `GET` | `/api/v1/admin/messages/{id}` | Obtener un mensaje por ID |
| `PATCH` | `/api/v1/admin/messages/{id}` | Editar el contenido de un mensaje |
| `DELETE` | `/api/v1/admin/messages/{id}` | Eliminar un mensaje |

### Health check

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Verificar que la API está activa |

---

## Documentación de IA utilizada

### Groq — LLaMA 3.3 70B Versatile

| Atributo | Detalle |
|---|---|
| Proveedor | Groq Cloud |
| Modelo | `llama-3.3-70b-versatile` |
| Propósito | Análisis contextual profundo de conversaciones en zona gris |
| Cuándo se invoca | Solo cuando el pipeline local del SDK produce un score entre 12 y 19 |
| Qué recibe | Historial de mensajes + output de las 3 capas del SDK (categorías, reglas disparadas, features, flag de velocidad) |
| Qué produce | `score`, `risk`, `stage`, `categories`, `termsFound`, `ux_recommendation` |
| Por qué este modelo | El 70B entiende el contexto conversacional, la ironía y la jerga criminal mexicana coloquial ("jale", "plaza", "mandados"). Un modelo más pequeño generaría más falsos negativos en un dominio donde el costo de equivocarse es alto. |
| Infraestructura | Groq LPU — latencia promedio < 2 segundos para análisis completo |

**La IA nunca recibe mensajes que el motor local clasificó como seguros.** El pipeline de 3 capas (NormalizerLayer → V3Layer → V4Layer) actúa como filtro inteligente — la IA solo interviene cuando hay una sospecha real.

---

## Deploy

La API está desplegada en **Railway** con Python 3.13.

- URL de producción: *(agregar URL pública de Railway)*
- Health check: `GET /health`

---

## Demo

> Integración de prueba con **feed-games** — disponible próximamente.

---

## Integrantes del equipo

| Nombre | Rol |
|---|---|
| Samuel Tlahuel | SDK TypeScript, arquitectura del motor de detección |
| Luis Mérida | API Backend, infraestructura, base de datos |
| *(completar con el resto del equipo)* | |

---

## Licencia

MIT License — Copyright (c) 2026 Samuel Tlahuel

Este proyecto fue desarrollado durante el **Hackathon 404 · Marriott Reforma CDMX · Abril 2026** y se publica como código abierto bajo licencia MIT como condición de participación.

El SDK incluye el archivo [LICENSE](../sentinel-sdk/LICENSE) con el texto completo de la licencia MIT.
