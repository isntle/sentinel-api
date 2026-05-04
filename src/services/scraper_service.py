import httpx
import feedparser
import re
from sqlalchemy.orm import Session
from src.services.hot_terms_service import classify_and_approve_term
from src.models.db_models import HotTerm

# Fuentes RSS de noticias mexicanas sobre crimen organizado y seguridad
RSS_SOURCES = [
    {
        "url": "https://www.eluniversal.com.mx/rss/estados.xml",
        "name": "El Universal - Estados",
    },
    {
        "url": "https://www.milenio.com/rss/estados",
        "name": "Milenio - Estados",
    },
    {
        "url": "https://www.jornada.com.mx/rss/estados.xml",
        "name": "La Jornada - Estados",
    },
    {
        "url": "https://www.infobae.com/feeds/rss/mexico/",
        "name": "Infobae México",
    },
]

# Palabras que indican que el artículo habla de crimen organizado
CRIME_KEYWORDS = [
    "cartel", "narco", "crimen organizado", "extorsión", "reclutamiento",
    "menor", "adolescente", "joven", "captación", "halcón", "sicario",
    "grooming", "abuso", "acoso", "trata", "explotación"
]

# Stopwords básicas para no clasificar palabras comunes
STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "en", "con", "por", "para", "que", "se", "no", "al", "su", "sus",
    "como", "más", "pero", "fue", "han", "hay", "son", "está", "este",
    "esta", "ese", "esa", "ser", "tiene", "había", "sido", "también",
    "cuando", "sobre", "entre", "after", "from", "this", "that", "the"
}


def _is_crime_related(text: str) -> bool:
    """Verifica si el texto habla de crimen organizado o seguridad infantil."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in CRIME_KEYWORDS)


def _extract_candidate_terms(text: str) -> list[str]:
    """
    Extrae palabras y frases cortas candidatas del texto.
    Busca términos en comillas, negritas, o palabras informales.
    """
    candidates = set()

    # Términos entre comillas (jerga reportada por periodistas)
    quoted = re.findall(r'"([^"]{2,30})"', text)
    candidates.update(quoted)

    # Términos entre comillas simples o especiales
    quoted2 = re.findall(r"'([^']{2,30})'", text)
    candidates.update(quoted2)

    # Palabras que no son stopwords, de 4-15 chars, solo letras/espacios
    words = re.findall(r'\b[a-záéíóúüñ]{4,15}\b', text.lower())
    for word in words:
        if word not in STOPWORDS:
            candidates.add(word)

    return list(candidates)


def _term_already_known(db: Session, term: str) -> bool:
    """Verifica si el término ya está en hot_terms (aprobado o pendiente)."""
    return db.query(HotTerm).filter(
        HotTerm.term == term.lower().strip()
    ).first() is not None


async def run_scraper(db: Session) -> dict:
    """
    Proceso completo de scraping:
    1. Lee fuentes RSS
    2. Filtra artículos relevantes
    3. Extrae términos candidatos
    4. Clasifica con Groq los que no se conocen
    5. Devuelve resumen de resultados
    """
    results = {
        "articles_scanned": 0,
        "candidates_found": 0,
        "terms_approved": 0,
        "terms_rejected": 0,
        "errors": [],
    }

    all_candidates: list[dict] = []

    # 1. Scraping de fuentes RSS
    async with httpx.AsyncClient(timeout=15.0) as client:
        for source in RSS_SOURCES:
            try:
                response = await client.get(source["url"])
                feed = feedparser.parse(response.text)

                for entry in feed.entries[:20]:  # máximo 20 artículos por fuente
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    full_text = f"{title} {summary}"

                    results["articles_scanned"] += 1

                    if not _is_crime_related(full_text):
                        continue

                    terms = _extract_candidate_terms(full_text)
                    for term in terms:
                        if not _term_already_known(db, term):
                            all_candidates.append({
                                "term": term,
                                "source": source["name"],
                            })

            except Exception as e:
                results["errors"].append(f"{source['name']}: {str(e)}")

    # Deduplicar candidatos
    seen = set()
    unique_candidates = []
    for c in all_candidates:
        if c["term"] not in seen:
            seen.add(c["term"])
            unique_candidates.append(c)

    results["candidates_found"] = len(unique_candidates)

    # 2. Clasificar con Groq (máximo 30 por corrida para no exceder rate limits)
    for candidate in unique_candidates[:30]:
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
