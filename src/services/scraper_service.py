import httpx
import re
from sqlalchemy.orm import Session
from src.services.hot_terms_service import classify_and_approve_term
from src.models.db_models import HotTerm

# ─── Configuración de fuentes ────────────────────────────────────────────────

# Subreddits donde aparece jerga criminal mexicana real
REDDIT_SUBREDDITS = [
    "Narco",
    "mexico",
    "tijuana",
    "guadalajara",
    "monterrey",
]

# Términos de búsqueda para filtrar posts relevantes en Reddit
REDDIT_SEARCH_TERMS = [
    "cartel", "reclutamiento", "crimen organizado", "plaza",
    "halcón", "jale", "narco", "sicario", "menor", "captación"
]

# Borderland Beat — blog de periodismo sobre crimen organizado en México
BORDERLAND_BEAT_URLS = [
    "https://www.borderlandbeat.com/",
    "https://www.borderlandbeat.com/search/label/Gulf%20Cartel",
    "https://www.borderlandbeat.com/search/label/CJNG",
    "https://www.borderlandbeat.com/search/label/Sinaloa%20Cartel",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SentinelResearch/1.0; academic security research)"
}

SPANISH_MARKERS = {
    "que", "con", "por", "para", "una", "del", "las", "los", "está",
    "son", "hay", "también", "cuando", "sobre", "entre", "según", "fue",
    "han", "tiene", "había", "sido", "más", "pero", "como", "este",
}

STOPWORDS = {
    # Español
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "en", "con", "por", "para", "que", "se", "no", "al", "su", "sus",
    "como", "más", "pero", "fue", "han", "hay", "son", "está", "este",
    "esta", "ese", "esa", "ser", "tiene", "había", "sido", "también",
    "cuando", "sobre", "entre", "según", "muy", "así", "sin", "les",
    "todo", "todos", "toda", "todas", "otro", "otra", "otros", "otras",
    "gobierno", "federal", "estado", "ciudad", "municipio", "grupo",
    "organización", "miembros", "personas", "hombres", "mujeres",
    "cartel", "mexico", "narco",
    # Inglés
    "the", "and", "for", "are", "was", "with", "has", "been", "they",
    "their", "have", "will", "would", "could", "said", "this", "that",
    "from", "after", "where", "when", "which", "who", "what", "how",
    "not", "but", "his", "her", "him", "its", "our", "your", "all",
    "one", "two", "new", "also", "into", "than", "then", "there",
    "were", "about", "after", "police", "military", "mexican", "federal",
    "local", "state", "members", "group", "against", "during", "according",
    "beat", "borderland", "blog", "posted", "author", "comments", "read",
}


def _is_spanish(text: str) -> bool:
    """Verifica que el texto tenga suficientes palabras en español para procesarlo."""
    words = set(re.findall(r'\b[a-záéíóúüñ]{2,}\b', text.lower()))
    matches = words & SPANISH_MARKERS
    return len(matches) >= 2


def _term_already_known(db: Session, term: str) -> bool:
    """Verifica si el término ya está en hot_terms."""
    return db.query(HotTerm).filter(
        HotTerm.term == term.lower().strip()
    ).first() is not None


def _extract_candidates(text: str, quoted_only: bool = False) -> list[str]:
    """
    Extrae términos candidatos del texto.
    - quoted_only=True: solo extrae lo que está entre comillas (para fuentes en inglés)
    - quoted_only=False: extrae también palabras sueltas en español
    """
    candidates = set()

    # Términos entre comillas — donde periodistas reportan jerga real
    for pattern in [r'"([^"]{2,25})"', r'“([^”]{2,25})”', r"'([^']{2,25})'"]:
        for match in re.findall(pattern, text):
            clean = match.strip().lower()
            if clean and clean not in STOPWORDS and not any(c.isdigit() for c in clean):
                candidates.add(clean)

    if quoted_only:
        return list(candidates)

    # Palabras individuales en español (contienen letras con acento o ñ, o son cortas)
    words = re.findall(r'\b[a-záéíóúüñ]{3,12}\b', text.lower())
    for word in words:
        if word not in STOPWORDS:
            candidates.add(word)

    return list(candidates)


def _scrape_reddit(client: httpx.Client) -> list[dict]:
    """
    Lee posts y comentarios de subreddits relevantes usando
    la API pública de Reddit (sin autenticación).
    """
    found = []

    for subreddit in REDDIT_SUBREDDITS:
        for search_term in REDDIT_SEARCH_TERMS[:3]:  # 3 búsquedas por subreddit
            try:
                url = f"https://www.reddit.com/r/{subreddit}/search.json"
                params = {"q": search_term, "sort": "new", "limit": 10}
                response = client.get(url, params=params, headers=HEADERS, timeout=10)

                if response.status_code != 200:
                    continue

                data = response.json()
                posts = data.get("data", {}).get("children", [])

                for post in posts:
                    post_data = post.get("data", {})
                    title = post_data.get("title", "")
                    body = post_data.get("selftext", "")
                    text = f"{title} {body}"

                    # La búsqueda ya garantiza relevancia — solo filtramos español
                    if not _is_spanish(text):
                        continue

                    # quoted_only=True: solo extraer jerga reportada entre comillas
                    for term in _extract_candidates(text, quoted_only=True):
                        if re.search(r'[/\\.0-9]', term) or len(term) < 3:
                            continue
                        found.append({"term": term, "source": f"Reddit r/{subreddit}"})

            except Exception:
                continue

    return found


def _scrape_borderland_beat(client: httpx.Client) -> list[dict]:
    """
    Extrae términos de los artículos y comentarios de Borderland Beat,
    que cubre crimen organizado en México con lenguaje auténtico.
    """
    found = []

    for url in BORDERLAND_BEAT_URLS:
        try:
            response = client.get(url, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                continue

            # Extraer solo párrafos reales (no JS ni metadata)
            text_blocks = re.findall(r'<p[^>]*>([^<]{30,600})</p>', response.text)

            for block in text_blocks:
                # Saltar bloques que parecen código o metadata
                if any(skip in block for skip in ["function", "var ", "http", "{", "}"]):
                    continue
                clean = block.replace("&amp;", "&").replace("&nbsp;", " ").strip()

                # quoted_only=True porque el sitio está en inglés
                # solo nos interesan los términos en español que aparecen entre comillas
                for term in _extract_candidates(clean, quoted_only=True):
                    found.append({"term": term, "source": "Borderland Beat"})

        except Exception:
            continue

    return found


def run_scraper(db: Session) -> dict:
    """
    Proceso completo:
    1. Scraping de Reddit y Borderland Beat
    2. Deduplicación de candidatos
    3. Filtro de términos ya conocidos
    4. Clasificación con Groq (máx 25 por corrida)
    5. Retorna resumen de resultados
    """
    results = {
        "articles_scanned": 0,
        "candidates_found": 0,
        "terms_approved": 0,
        "terms_rejected": 0,
        "errors": [],
    }

    all_candidates: list[dict] = []

    with httpx.Client() as client:
        # Reddit
        try:
            reddit_terms = _scrape_reddit(client)
            all_candidates.extend(reddit_terms)
            results["articles_scanned"] += len(REDDIT_SUBREDDITS)
        except Exception as e:
            results["errors"].append(f"Reddit: {str(e)}")

        # Borderland Beat
        try:
            bb_terms = _scrape_borderland_beat(client)
            all_candidates.extend(bb_terms)
            results["articles_scanned"] += len(BORDERLAND_BEAT_URLS)
        except Exception as e:
            results["errors"].append(f"Borderland Beat: {str(e)}")

    # Deduplicar
    seen = set()
    unique_candidates = []
    for c in all_candidates:
        key = c["term"].lower().strip()
        if key not in seen and not _term_already_known(db, key):
            seen.add(key)
            unique_candidates.append(c)

    results["candidates_found"] = len(unique_candidates)

    # Clasificar con Groq (máximo 25 por corrida para no agotar rate limits)
    for candidate in unique_candidates[:25]:
        try:
            result = classify_and_approve_term(
                db=db,
                term=candidate["term"],
                source=candidate["source"],
            )
            if result.get("approved"):
                results["terms_approved"] += 1
            else:
                results["terms_rejected"] += 1
        except Exception as e:
            results["errors"].append(f"classify '{candidate['term']}': {str(e)}")

    return results
