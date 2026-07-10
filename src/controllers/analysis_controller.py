from sqlalchemy.orm import Session
from src.models.conversation import EscalationRequest
from src.services.analysis_service import analyze_conversation
from src.services.network_service import record_and_score
from src.services.intervention import build_intervention_plan

def handle_escalation(escalation: EscalationRequest, db: Session | None = None):
    """
    Recibe la escalación del SDK (análisis local + mensajes), delega el análisis
    profundo a la IA, evalúa el riesgo de red del actor cruzando sesiones, y
    construye el plan de intervención graduada.
    """
    # Confiamos en la decisión de escalado del SDK; enviamos el paquete al LLM.
    result = analyze_conversation(escalation)

    # Señales de red (7.5): si el SDK identificó un actor que concentra tácticas,
    # se registra y se cruza con sesiones previas para detectar reclutamiento
    # organizado (un actor → N víctimas). Solo si hay DB y agresor identificado.
    actor = escalation.layers.actor
    aggressor = actor.aggressorSender if actor else None
    network = None
    if db is not None and aggressor:
        aggressor_texts = [m.content for m in escalation.messages if m.user_id == aggressor]
        network = record_and_score(
            db=db,
            aggressor_user_id=aggressor,
            session_id=escalation.messages[0].session_id,
            aggressor_texts=aggressor_texts,
            risk=result.get("stage") or escalation.risk,
            categories=escalation.uniqueCategories,
        )
        result["network"] = network
        # Un actor con reclutamiento sistemático fuerza el bloqueo aunque el
        # veredicto de esta sesión aislada haya sido más suave.
        if network["actor_risk"] == "CRITICAL":
            result["ux_recommendation"] = "HARD_BLOCK"

    # Plan de intervención graduada (8.1): decopla lo que ve el reclutador de las
    # acciones que protegen a la víctima. Combina etapa (LLM), red y asimetría.
    logistics = "logistica_fisica" in (escalation.uniqueCategories or [])
    result["intervention"] = build_intervention_plan(
        risk=escalation.risk,
        stage=result.get("stage"),
        network_risk=network["actor_risk"] if network else None,
        has_aggressor=bool(aggressor),
        logistics_in_progress=logistics,
        false_positive=bool(result.get("false_positive")),
    )

    return result
