from dotenv import load_dotenv
import os

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GENIUS_API_TOKEN = os.getenv("GENIUS_API_TOKEN")

# Sal para hashear identificadores en las señales de red (privacidad por diseño).
# En producción DEBE venir del entorno; el default solo permite desarrollo local.
ACTOR_HASH_SALT = os.getenv("ACTOR_HASH_SALT", "sentinel-dev-salt-change-in-prod")

# Orígenes web autorizados para usar el SDK directamente desde un navegador.
# Default vacío = ninguna integración cross-origin hasta que el operador la autorice.
CORS_ALLOWED_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
)

# Firma tokens efímeros, limitados al endpoint de telemetría, para sendBeacon.
# Debe ser un secreto independiente y aleatorio en producción.
TELEMETRY_TOKEN_SECRET = os.getenv(
    "TELEMETRY_TOKEN_SECRET", "sentinel-dev-telemetry-token-change-in-prod"
)

# Firma Ed25519 de packs/modelos. La llave privada se configura como base64url
# de 32 bytes o PEM; nunca se guarda en el repositorio. Sin llave, la API sigue
# sirviendo el formato legacy para desarrollo, pero producción debe configurarla.
ARTIFACT_SIGNING_PRIVATE_KEY = os.getenv("ARTIFACT_SIGNING_PRIVATE_KEY")
ARTIFACT_SIGNING_KEY_ID = os.getenv("ARTIFACT_SIGNING_KEY_ID", "sentinel-artifacts-v1")
ARTIFACT_TTL_SECONDS = int(os.getenv("ARTIFACT_TTL_SECONDS", "86400"))
