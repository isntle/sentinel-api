import httpx
import re
import uuid
import feedparser
from datetime import datetime
from sqlalchemy.orm import Session
from src.services.hot_terms_service import classify_terms_batch
from src.services.candidate_scorer import get_mature_candidates
from src.models.db_models import HotTerm, RejectedTerm, CandidateSighting
from src.config.settings import YOUTUBE_API_KEY, GENIUS_API_TOKEN

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
    """Verifica si el término ya está en hot_terms o en rejected_terms."""
    clean_term = term.lower().strip()
    is_hot = db.query(HotTerm).filter(HotTerm.term == clean_term).first() is not None
    if is_hot:
        return True
    return db.query(RejectedTerm).filter(RejectedTerm.term == clean_term).first() is not None


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
                        found.append({
                            "term": term, 
                            "source": f"Reddit r/{subreddit}",
                            "context": text[:300]
                        })

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
                    found.append({
                        "term": term, 
                        "source": "Borderland Beat",
                        "context": clean[:300]
                    })

        except Exception:
            continue

    return found


def _scrape_youtube(client: httpx.Client) -> list[dict]:
    """
    Busca comentarios en videos de YouTube sobre noticias de narco o reclutamiento.
    Usa la YouTube Data API v3 con la key configurada.
    """
    if not YOUTUBE_API_KEY:
        return []

    queries = [
        "reclutamiento cartel",
        "narco noticias méxico",
        "corridos bélicos 2026"
    ]
    found = []

    for query in queries[:2]:
        try:
            search_url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "key": YOUTUBE_API_KEY,
                "q": query,
                "part": "snippet",
                "type": "video",
                "maxResults": 5,
                "relevanceLanguage": "es",
                "regionCode": "MX",
                "order": "date"
            }
            response = client.get(search_url, params=params, timeout=10)
            if response.status_code != 200:
                continue

            search_data = response.json()
            items = search_data.get("items", [])

            for item in items:
                video_id = item.get("id", {}).get("videoId")
                if not video_id:
                    continue

                comments_url = "https://www.googleapis.com/youtube/v3/commentThreads"
                comment_params = {
                    "key": YOUTUBE_API_KEY,
                    "videoId": video_id,
                    "part": "snippet",
                    "maxResults": 50,
                    "textFormat": "plainText"
                }
                comments_resp = client.get(comments_url, params=comment_params, timeout=10)
                if comments_resp.status_code != 200:
                    continue

                comments_data = comments_resp.json()
                threads = comments_data.get("items", [])

                for thread in threads:
                    snippet = thread.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                    text = snippet.get("textDisplay", "")
                    if not text or not _is_spanish(text):
                        continue

                    for term in _extract_candidates(text, quoted_only=False):
                        if re.search(r'[/\\.0-9]', term) or len(term) < 3:
                            continue
                        found.append({
                            "term": term,
                            "source": f"YouTube {video_id}",
                            "context": text[:300]
                        })
        except Exception:
            continue

    return found


def _scrape_lyrics(client: httpx.Client) -> list[dict]:
    """
    Busca letras de canciones de artistas populares de corridos bélicos en Genius
    y extrae candidatos (quoted_only=False).
    """
    if not GENIUS_API_TOKEN:
        return []

    artists = ["Peso Pluma", "Luis R Conriquez", "Fuerza Regida"]
    found = []

    headers = {
        "Authorization": f"Bearer {GENIUS_API_TOKEN}",
        "User-Agent": HEADERS["User-Agent"]
    }

    for artist in artists:
        try:
            search_url = "https://api.genius.com/search"
            params = {"q": artist}
            response = client.get(search_url, params=params, headers=headers, timeout=10)
            if response.status_code != 200:
                continue

            data = response.json()
            hits = data.get("response", {}).get("hits", [])

            for hit in hits[:3]:
                song_data = hit.get("result", {})
                song_title = song_data.get("title", "")
                song_url = song_data.get("url")
                if not song_url:
                    continue

                lyrics_resp = client.get(song_url, headers=HEADERS, timeout=10)
                if lyrics_resp.status_code != 200:
                    continue

                html_content = lyrics_resp.text
                
                # Intentar varios selectores comunes de Genius
                lyrics_containers = re.findall(r'<div[^>]*data-lyrics-container="true"[^>]*>(.*?)</div>', html_content, re.DOTALL)
                if not lyrics_containers:
                    lyrics_containers = re.findall(r'<div[^>]*class="[^"]*Lyrics__Container[^"]*"[^>]*>(.*?)</div>', html_content, re.DOTALL)
                if not lyrics_containers:
                    lyrics_containers = re.findall(r'<div[^>]*class="[^"]*lyrics[^"]*"[^>]*>(.*?)</div>', html_content, re.DOTALL)

                if not lyrics_containers:
                    continue

                full_lyrics = ""
                for container in lyrics_containers:
                    clean_text = re.sub(r'<[^>]+>', ' ', container)
                    clean_text = clean_text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                    full_lyrics += clean_text + "\n"

                if not full_lyrics:
                    continue

                for term in _extract_candidates(full_lyrics, quoted_only=False):
                    if re.search(r'[/\\.0-9]', term) or len(term) < 3:
                        continue
                    found.append({
                        "term": term,
                        "source": f"Corrido: {artist} - {song_title}",
                        "context": full_lyrics[:300]
                    })
        except Exception:
            continue

    return found


def _scrape_news_rss(client: httpx.Client) -> list[dict]:
    """
    Parsea feeds RSS de noticias de seguridad y crimen en México.
    Extrae candidatos (quoted_only=True) de títulos y descripciones.
    """
    feeds = {
        "Río Doce": "https://riodoce.mx/feed/",
        "ZETA Tijuana": "https://zetatijuana.com/feed/",
        "Proceso": "https://www.proceso.com.mx/rss/feed.html",
        "La Silla Rota": "https://lasillarota.com/rss/feed.html"
    }
    
    found = []
    
    for name, url in feeds.items():
        try:
            response = client.get(url, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                continue
                
            feed = feedparser.parse(response.text)
            entries = feed.get("entries", [])
            
            for entry in entries[:15]:
                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                text = f"{title} {summary}"
                text = re.sub(r'<[^>]+>', ' ', text)
                
                for term in _extract_candidates(text, quoted_only=True):
                    if re.search(r'[/\\.0-9]', term) or len(term) < 3:
                        continue
                    found.append({
                        "term": term,
                        "source": f"RSS: {name}",
                        "context": text[:300]
                    })
        except Exception:
            continue
            
    return found


def run_scraper(db: Session) -> dict:
    """
    Proceso completo:
    1. Scraping de Reddit, Borderland Beat, YouTube, Corridos y RSS
    2. Deduplicación de candidatos
    3. Filtro de términos ya conocidos
    4. Guardar en CandidateSighting
    5. Clasificación batch con Groq (Top 25 maduros)
    """
    results = {
        "articles_scanned": 0,
        "candidates_found": 0,
        "terms_staged": 0,
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

        # YouTube
        try:
            yt_terms = _scrape_youtube(client)
            all_candidates.extend(yt_terms)
            results["articles_scanned"] += 2
        except Exception as e:
            results["errors"].append(f"YouTube: {str(e)}")

        # Corridos (Genius)
        try:
            lyrics_terms = _scrape_lyrics(client)
            all_candidates.extend(lyrics_terms)
            results["articles_scanned"] += 3
        except Exception as e:
            results["errors"].append(f"Lyrics: {str(e)}")

        # RSS
        try:
            rss_terms = _scrape_news_rss(client)
            all_candidates.extend(rss_terms)
            results["articles_scanned"] += 4
        except Exception as e:
            results["errors"].append(f"RSS: {str(e)}")

    # Deduplicar para esta corrida
    seen = set()
    unique_candidates = []
    for c in all_candidates:
        key = c["term"].lower().strip()
        if key not in seen and not _term_already_known(db, key):
            seen.add(key)
            unique_candidates.append(c)

    results["candidates_found"] = len(unique_candidates)

    # Guardar sightings en BD
    for c in unique_candidates:
        sighting = CandidateSighting(
            id=str(uuid.uuid4()),
            term=c["term"].lower().strip(),
            source=c["source"],
            context=c.get("context", ""),
            seen_at=int(datetime.now().timestamp())
        )
        db.add(sighting)
    db.commit()

    # Obtener el Top 25 maduro y puntuarlo, luego clasificar con Groq
    batch_candidates = get_mature_candidates(db, limit=25)
    if batch_candidates:
        try:
            batch_results = classify_terms_batch(db, batch_candidates)
            for res in batch_results:
                if res.get("staged"):
                    results["terms_staged"] += 1
                else:
                    results["terms_rejected"] += 1
        except Exception as e:
            results["errors"].append(f"Batch classification error: {str(e)}")

    return results
