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
