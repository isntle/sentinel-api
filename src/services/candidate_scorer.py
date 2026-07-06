import json
import os
import re
from datetime import datetime
from sqlalchemy.orm import Session
from src.models.db_models import CandidateSighting, HotTerm

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
    if term.isnumeric() or "http" in term_lower or "www" in term_lower:
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

def get_mature_candidates(db: Session, limit: int = 25) -> list[dict]:
    """
    Obtiene los candidatos que ya están listos para ser enviados a Groq.
    Regla de maduración: >= 2 fuentes distintas, o >= 3 apariciones totales.
    Retorna el top N por score.
    """
    sightings = db.query(CandidateSighting).all()
    grouped = {}
    for s in sightings:
        term = s.term.lower().strip()
        if term not in grouped:
            grouped[term] = []
        grouped[term].append(s)
        
    mature_candidates = []
    
    for term, term_sightings in grouped.items():
        if is_hard_filtered(term):
            continue
            
        sources = {s.source for s in term_sightings}
        
        # Regla de maduración
        if len(sources) >= 2 or len(term_sightings) >= 3:
            score = calculate_score(term, term_sightings, db)
            
            best_context = max(term_sightings, key=lambda s: len(s.context or "")).context
            best_source = list(sources)[0]
            
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
    for term, term_sightings in grouped.items():
        if not is_hard_filtered(term):
            sources = {s.source for s in term_sightings}
            if len(sources) >= 2 or len(term_sightings) >= 3:
                eligible += 1
                
    approved = db.query(HotTerm).filter(HotTerm.approved == True).count()
    rejected = db.query(RejectedTerm).count()
    
    return {
        "sightings_totales": total_sightings,
        "candidatos_unicos": len(grouped),
        "candidatos_elegibles": eligible,
        "terminos_aprobados": approved,
        "terminos_rechazados": rejected
    }
