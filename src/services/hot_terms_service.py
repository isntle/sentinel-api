import json
import uuid
from datetime import datetime
from groq import Groq
from sqlalchemy.orm import Session
from src.models.db_models import HotTerm, RejectedTerm, DatasetVersion
from src.config.settings import GROQ_API_KEY

def get_approved_terms(db: Session):
    """Devuelve todos los términos aprobados para servir al SDK."""
    return db.query(HotTerm).filter(HotTerm.approved == True).all()

def get_staged_terms(db: Session):
    """Devuelve todos los términos en preparación (aprobados por IA, pendientes de humano)."""
    return db.query(HotTerm).filter(HotTerm.staged == True).all()

def update_term_manual(db: Session, term_id: str, category: str, weight: float):
    term = db.query(HotTerm).filter(HotTerm.id == term_id).first()
    if not term:
        return None
    term.category = category
    term.weight = weight
    db.commit()
    db.refresh(term)
    return term

def approve_term_manual(db: Session, term_id: str):
    term = db.query(HotTerm).filter(HotTerm.id == term_id).first()
    if not term:
        return False
    term.approved = True
    term.staged = False
    db.commit()
    return True

def reject_term_manual(db: Session, term_id: str, reasoning: str = "Rechazado manualmente"):
    term = db.query(HotTerm).filter(HotTerm.id == term_id).first()
    if not term:
        return False
    
    # Crear rejected
    existing_rej = db.query(RejectedTerm).filter(RejectedTerm.term == term.term).first()
    if not existing_rej:
        rejected = RejectedTerm(
            id=str(uuid.uuid4()),
            term=term.term,
            source=term.source,
            reasoning=reasoning,
            rejected_at=int(datetime.now().timestamp()),
        )
        db.add(rejected)
    
    # Borrar de hot_terms
    db.delete(term)
    db.commit()
    return True

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
        existing_rej = db.query(RejectedTerm).filter(RejectedTerm.term == term.lower().strip()).first()
        if not existing_rej:
            rejected = RejectedTerm(
                id=str(uuid.uuid4()),
                term=term.lower().strip(),
                source=source,
                reasoning=result.get("reasoning"),
                rejected_at=int(datetime.now().timestamp()),
            )
            db.add(rejected)
            db.commit()
        return {"approved": False, "reasoning": result.get("reasoning"), "term": term}

    # Aprobado — guardar o actualizar en DB
    existing = db.query(HotTerm).filter(HotTerm.term == term.lower().strip()).first()

    if existing:
        existing.category = result["category"]
        existing.weight = result["weight"]
        existing.variants = ",".join(result.get("variants", []))
        existing.staged = True
        existing.approved = False
        db.commit()
        db.refresh(existing)
        return {"approved": False, "staged": True, "term_id": existing.id, "reasoning": result.get("reasoning")}

    hot_term = HotTerm(
        id=str(uuid.uuid4()),
        term=term.lower().strip(),
        category=result["category"],
        weight=result["weight"],
        variants=",".join(result.get("variants", [])),
        source=source,
        approved=False,
        staged=True,
        created_at=int(datetime.now().timestamp()),
    )
    db.add(hot_term)
    db.commit()
    db.refresh(hot_term)
    return {"approved": False, "staged": True, "term_id": hot_term.id, "reasoning": result.get("reasoning")}

def classify_terms_batch(db: Session, candidates: list[dict]) -> list[dict]:
    """
    Clasifica un lote de términos candidatos usando una sola llamada a Groq.
    """
    if not candidates:
        return []

    client = Groq(api_key=GROQ_API_KEY)
    
    terms_list_str = ""
    for idx, candidate in enumerate(candidates, start=1):
        term = candidate["term"]
        source = candidate.get("source", "desconocida")
        context = candidate.get("context", "no proporcionado")
        terms_list_str += f"{idx}. Término: \"{term}\" | Fuente: {source} | Contexto: {context}\n"

    prompt = f"""
Eres un experto en seguridad infantil y crimen organizado en México.

Analiza el siguiente listado de términos candidatos y determina para cada uno si corresponde a jerga utilizada por depredadores o reclutadores del crimen organizado para comunicarse con menores en plataformas digitales.

Lista de candidatos a clasificar:
{terms_list_str}

Responde estrictamente con un objeto JSON que contenga una propiedad "results" con un arreglo de objetos. Cada objeto en el arreglo debe mapear a un término evaluado con la siguiente estructura:
{{
  "results": [
    {{
      "term": "nombre del término original",
      "is_risk_slang": true | false,
      "category": "reclutamiento" | "grooming" | "normalizacion" | "manipulacion" | "ninguna",
      "weight": <número entero entre 1 y 15, donde 15 es máximo riesgo>,
      "variants": ["variante1", "variante2"],
      "reasoning": "<explicación breve de por qué sí o por qué no>"
    }}
  ]
}}

Si un término no es jerga de riesgo criminal, pon is_risk_slang: false, category: "ninguna", weight: 0.
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    response_content = response.choices[0].message.content
    try:
        data = json.loads(response_content)
        results = data.get("results", [])
    except Exception:
        results = []

    batch_results = []
    results_by_term = {r.get("term", "").lower().strip(): r for r in results}

    for candidate in candidates:
        term_key = candidate["term"].lower().strip()
        result_data = results_by_term.get(term_key)

        if not result_data:
            batch_results.append({
                "term": candidate["term"],
                "approved": False,
                "reasoning": "Omitido por el clasificador batch."
            })
            continue

        if not result_data.get("is_risk_slang"):
            # Guardar en RejectedTerm para no volver a evaluar este término en el futuro
            existing_rejected = db.query(RejectedTerm).filter(RejectedTerm.term == term_key).first()
            if not existing_rejected:
                rejected = RejectedTerm(
                    id=str(uuid.uuid4()),
                    term=term_key,
                    source=candidate.get("source"),
                    reasoning=result_data.get("reasoning"),
                    rejected_at=int(datetime.now().timestamp()),
                )
                db.add(rejected)
                db.commit()
                
            batch_results.append({
                "term": candidate["term"],
                "approved": False,
                "reasoning": result_data.get("reasoning")
            })
            continue

        # Aprobado — guardar o actualizar
        existing = db.query(HotTerm).filter(HotTerm.term == term_key).first()
        variants_str = ",".join(result_data.get("variants", [])) if result_data.get("variants") else ""

        if existing:
            existing.category = result_data.get("category", "pendiente")
            existing.weight = result_data.get("weight", 0)
            existing.variants = variants_str
            existing.staged = True
            existing.approved = False
            db.commit()
            db.refresh(existing)
            batch_results.append({
                "term": candidate["term"],
                "approved": False,
                "staged": True,
                "term_id": existing.id,
                "reasoning": result_data.get("reasoning")
            })
        else:
            hot_term = HotTerm(
                id=str(uuid.uuid4()),
                term=term_key,
                category=result_data.get("category", "pendiente"),
                weight=result_data.get("weight", 0),
                variants=variants_str,
                source=candidate.get("source"),
                approved=False,
                staged=True,
                created_at=int(datetime.now().timestamp()),
            )
            db.add(hot_term)
            db.commit()
            db.refresh(hot_term)
            batch_results.append({
                "term": candidate["term"],
                "approved": False,
                "staged": True,
                "term_id": hot_term.id,
                "reasoning": result_data.get("reasoning")
            })

    return batch_results

def publish_version(db: Session, description: str = None):
    """
    Toma todos los términos staged y los publica, creando una nueva versión del dataset.
    """
    staged_terms = db.query(HotTerm).filter(HotTerm.staged == True).all()
    if not staged_terms:
        return None

    # Publicar
    for t in staged_terms:
        t.approved = True
        t.staged = False
    
    db.commit()

    # Obtener todos los aprobados para el snapshot
    all_approved = db.query(HotTerm).filter(HotTerm.approved == True).all()
    snapshot = [
        {
            "id": t.id,
            "term": t.term,
            "category": t.category,
            "weight": t.weight,
            "variants": t.variants,
            "source": t.source,
            "created_at": t.created_at
        }
        for t in all_approved
    ]

    new_version = DatasetVersion(
        created_at=int(datetime.now().timestamp()),
        description=description or f"Version {datetime.now().isoformat()}",
        terms_snapshot=json.dumps(snapshot)
    )
    db.add(new_version)
    db.commit()
    db.refresh(new_version)
    
    return new_version

def rollback_to_version(db: Session, version_id: int):
    """
    Restaura el dataset a una versión anterior usando su snapshot.
    """
    version = db.query(DatasetVersion).filter(DatasetVersion.version == version_id).first()
    if not version:
        return False
        
    snapshot = json.loads(version.terms_snapshot)
    
    # Eliminar actuales aprobados
    db.query(HotTerm).filter(HotTerm.approved == True).delete()
    
    # Restaurar
    for item in snapshot:
        # Check si existe por id, quiza estaba staged
        existing = db.query(HotTerm).filter(HotTerm.id == item["id"]).first()
        if existing:
            existing.term = item["term"]
            existing.category = item["category"]
            existing.weight = item["weight"]
            existing.variants = item["variants"]
            existing.source = item["source"]
            existing.approved = True
            existing.staged = False
        else:
            t = HotTerm(
                id=item["id"],
                term=item["term"],
                category=item["category"],
                weight=item["weight"],
                variants=item["variants"],
                source=item["source"],
                approved=True,
                staged=False,
                created_at=item["created_at"]
            )
            db.add(t)
            
    db.commit()
    return True
