import json
import os
import re
from datetime import datetime
from sqlalchemy.orm import Session
from src.models.db_models import CandidateSighting, HotTerm, RejectedTerm, ScraperRun

# Cargar stopwords
STOPWORDS_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "stopwords_es.json")
try:
    with open(STOPWORDS_FILE, "r", encoding="utf-8") as f:
        STOPWORDS = set(json.load(f))
except Exception:
    STOPWORDS = set()

ANCHOR_TERMS = {
    "cartel", "plaza", "sicario", "levanton", "levantaron", "reclutan", "patron",
    "jefe", "comando", "armado", "armas", "droga", "venta", "punto", "halcon",
    "puntero", "estaca", "cuerno", "cuernos", "troca", "blindada", "topon",
    "enfrentamiento", "chapos", "mayos", "mencho", "cjng", "cds"
}

def is_hard_filtered(term: str) -> bool:
    """Aplica filtros duros a un término. Retorna True si debe ser descartado."""
    term = term.strip()
    term_lower = term.lower()
    
    # 1. Es un número o URL
    if any(character.isdigit() for character in term) or re.search(r"(?:https?://|www\.|\.[a-z]{2,}/)", term_lower):
        return True
    
    # 2. Es una palabra muy común del español
    if term_lower in STOPWORDS:
        return True
        
    # 3. Longitud muy corta
    if len(term) < 3:
        return True
        
    return False

def calculate_score(term: str, sightings: list[CandidateSighting], db: Session) -> int:
    """Calcula el score de un candidato basado en sus apariciones."""
    score = 0
    
    # Frecuencia base
    score += len(sightings)
    
    # Evaluar contexto
    for sighting in sightings:
        context_lower = (sighting.context or "").lower()
        
        # Co-ocurrencia con anclas
        for anchor in ANCHOR_TERMS:
            if anchor in context_lower:
                score += 1
                
    return score

from src.services.data_provenance_service import resolve_canonical_origin, calculate_content_hash

def get_mature_candidates(db: Session, limit: int = 25) -> list[dict]:
    """
    Obtiene los candidatos que ya están listos para ser enviados a Groq.
    Regla de maduración canónica (S08):
    - >=2 apariciones
    - provenientes de >=2 orígenes canónicos distintos (ej. no 2 URLs del mismo sitio)
    - y con >=2 hashes de contenido distintos (evita copias idénticas sindicadas).
    Retorna el top N por score.
    """
    sightings = db.query(CandidateSighting).all()
    known_terms = {
        term for (term,) in db.query(HotTerm.term).all()
    } | {
        term for (term,) in db.query(RejectedTerm.term).all()
    }
    grouped = {}
    for s in sightings:
        term = s.term.lower().strip()
        if term not in grouped:
            grouped[term] = []
        grouped[term].append(s)
        
    mature_candidates = []
    
    for term, term_sightings in grouped.items():
        if is_hard_filtered(term) or term in known_terms:
            continue
            
        canonical_origins = {
            s.canonical_origin or resolve_canonical_origin(s.source)
            for s in term_sightings
        }
        content_hashes = {
            s.content_hash or calculate_content_hash(s.context)
            for s in term_sightings
        }
        
        # Regla de maduración con deduplicación por origen y contenido
        if len(term_sightings) >= 2 and len(canonical_origins) >= 2 and len(content_hashes) >= 2:
            score = calculate_score(term, term_sightings, db)
            
            best_context = max(term_sightings, key=lambda s: len(s.context or "")).context
            best_source = list(canonical_origins)[0]
            
            mature_candidates.append({
                "term": term,
                "source": best_source,
                "context": best_context,
                "score": score
            })
            
    # Ordenar por score descendente
    mature_candidates.sort(key=lambda x: x["score"], reverse=True)
    return mature_candidates[:limit]
    
def get_pipeline_stats(db: Session) -> dict:
    from src.models.db_models import HotTerm, RejectedTerm
    
    total_sightings = db.query(CandidateSighting).count()
    
    sightings = db.query(CandidateSighting).all()
    grouped = {}
    for s in sightings:
        term = s.term.lower().strip()
        if term not in grouped:
            grouped[term] = []
        grouped[term].append(s)
        
    eligible = 0
    known_terms = {
        term for (term,) in db.query(HotTerm.term).all()
    } | {
        term for (term,) in db.query(RejectedTerm.term).all()
    }
    for term, term_sightings in grouped.items():
        if not is_hard_filtered(term) and term not in known_terms:
            canonical_origins = {
                s.canonical_origin or resolve_canonical_origin(s.source)
                for s in term_sightings
            }
            content_hashes = {
                s.content_hash or calculate_content_hash(s.context)
                for s in term_sightings
            }
            if len(term_sightings) >= 2 and len(canonical_origins) >= 2 and len(content_hashes) >= 2:
                eligible += 1
                
    approved = db.query(HotTerm).filter(HotTerm.approved == True).count()
    rejected = db.query(RejectedTerm).count()
    staged = db.query(HotTerm).filter(HotTerm.staged == True).count()
    classified = db.query(HotTerm).count() + rejected
    
    latest_run = (
        db.query(ScraperRun)
        .filter(ScraperRun.status == "success")
        .order_by(ScraperRun.finished_at.desc(), ScraperRun.started_at.desc())
        .first()
    )
    latest_results = {}
    if latest_run and latest_run.results:
        try:
            latest_results = json.loads(latest_run.results)
        except (TypeError, json.JSONDecodeError):
            latest_results = {}

    return {
        "sightings_totales": total_sightings,
        "candidatos_unicos": len(grouped),
        "candidatos_elegibles": eligible,
        "candidatos_clasificados": classified,
        "terminos_staged": staged,
        "terminos_aprobados": approved,
        "terminos_rechazados": rejected,
        "ultima_corrida": {
            "candidatos_entraron": latest_results.get("candidates_found", 0),
            "candidatos_sobrevivieron_prefiltro": latest_results.get("candidates_prefiltered", 0),
            "candidatos_clasificados": latest_results.get("candidates_classified", 0),
            "candidatos_aprobados_ia": latest_results.get("terms_staged", 0),
            "candidatos_omitidos_por_llm": latest_results.get("terms_omitted", 0),
        },
    }
