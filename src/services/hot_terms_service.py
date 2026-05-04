import json
import uuid
from datetime import datetime
from groq import Groq
from sqlalchemy.orm import Session
from src.models.db_models import HotTerm
from src.config.settings import GROQ_API_KEY

def get_approved_terms(db: Session):
    """Devuelve todos los términos aprobados para servir al SDK."""
    return db.query(HotTerm).filter(HotTerm.approved == True).all()

def suggest_term(db: Session, term: str, source: str = None):
    """Guarda un término candidato sin aprobarlo todavía."""
    existing = db.query(HotTerm).filter(HotTerm.term == term.lower().strip()).first()
    if existing:
        return existing

    hot_term = HotTerm(
        id=str(uuid.uuid4()),
        term=term.lower().strip(),
        category="pendiente",
        weight=0.0,
        variants=None,
        source=source,
        approved=False,
        created_at=int(datetime.now().timestamp()),
    )
    db.add(hot_term)
    db.commit()
    db.refresh(hot_term)
    return hot_term

def classify_and_approve_term(db: Session, term: str, source: str = None):
    """
    Usa Groq para clasificar si el término es jerga de riesgo real.
    Si sí, lo aprueba y lo guarda con categoría y peso.
    """
    client = Groq(api_key=GROQ_API_KEY)

    prompt = f"""
Eres un experto en seguridad infantil y crimen organizado en México.

Analiza el siguiente término y determina si es jerga utilizada por depredadores
o reclutadores del crimen organizado para comunicarse con menores en plataformas digitales.

Término: "{term}"
Fuente: {source or "desconocida"}

Responde SOLO en JSON con esta estructura:
{{
  "is_risk": true | false,
  "category": "reclutamiento" | "grooming" | "normalizacion" | "manipulacion" | "ninguna",
  "weight": <número entre 1 y 15, donde 15 es máximo riesgo>,
  "variants": ["variante1", "variante2"],
  "reasoning": "<una línea explicando por qué sí o por qué no>"
}}

Si no es jerga de riesgo, pon is_risk: false, category: "ninguna", weight: 0.
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)

    if not result.get("is_risk"):
        return {"approved": False, "reasoning": result.get("reasoning"), "term": term}

    # Aprobado — guardar o actualizar en DB
    existing = db.query(HotTerm).filter(HotTerm.term == term.lower().strip()).first()

    if existing:
        existing.category = result["category"]
        existing.weight = result["weight"]
        existing.variants = ",".join(result.get("variants", []))
        existing.approved = True
        db.commit()
        db.refresh(existing)
        return {"approved": True, "term_id": existing.id, "reasoning": result.get("reasoning")}

    hot_term = HotTerm(
        id=str(uuid.uuid4()),
        term=term.lower().strip(),
        category=result["category"],
        weight=result["weight"],
        variants=",".join(result.get("variants", [])),
        source=source,
        approved=True,
        created_at=int(datetime.now().timestamp()),
    )
    db.add(hot_term)
    db.commit()
    db.refresh(hot_term)
    return {"approved": True, "term_id": hot_term.id, "reasoning": result.get("reasoning")}
