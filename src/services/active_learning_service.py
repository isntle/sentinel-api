import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.models.db_models import ActiveLearningQueueItem

# Constantes de retención y límites de cuota
DEFAULT_RETENTION_DAYS = 30
MAX_ITEMS_PER_FAMILY = 5

def calculate_uncertainty_score(probability: Optional[float]) -> float:
    """
    Calcula la métrica de incertidumbre [0..1] normalizada.
    Máxima incertidumbre (1.0) en p=0.5; mínima (0.0) en p=0.0 o p=1.0.
    """
    if probability is None:
        return 0.0
    p = max(0.0, min(1.0, float(probability)))
    return 1.0 - 2.0 * abs(p - 0.5)

def generate_item_fingerprint(
    api_key_hash: str,
    session_id: str,
    sampling_strategy: str,
    family_id: Optional[str] = None,
) -> str:
    """Genera hash SHA-256 para garantizar idempotencia y evitar reenvíos duplicados."""
    source = f"{api_key_hash}:{session_id}:{sampling_strategy}:{family_id or 'none'}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()

class ActiveLearningService:
    @staticmethod
    def enqueue_item(
        db: Session,
        session_id: str,
        api_key_hash: str,
        primary_verdict: Optional[str],
        shadow_probability: Optional[float] = None,
        family_id: Optional[str] = None,
        features: Optional[List[float]] = None,
        random_inclusion_prob: Optional[float] = None,
        is_feedback: bool = False,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> Dict[str, Any]:
        """
        Encola un ítem en la cola de aprendizaje activo aplicando selección por:
        1. Desacuerdo (primary vs shadow)
        2. Incertidumbre (|p - 0.5| < 0.2)
        3. Muestreo aleatorio de control
        4. Reporte de feedback
        Aplica cuota estricta por familia e idempotencia.
        """
        # Calcular desacuerdo
        primary_risky = primary_verdict in ("MEDIUM", "HIGH", "CRITICAL")
        shadow_risky = (shadow_probability is not None) and (shadow_probability >= 0.5)
        is_disagreement = (shadow_probability is not None) and (primary_risky != shadow_risky)
        
        uncertainty = calculate_uncertainty_score(shadow_probability)
        
        # Determinar estrategia y probabilidad de inclusión para desinsesgamiento
        if is_feedback:
            strategy = "feedback"
            inclusion_prob = 1.0
        elif random_inclusion_prob is not None:
            strategy = "random_baseline"
            inclusion_prob = float(random_inclusion_prob)
        elif is_disagreement:
            strategy = "disagreement"
            inclusion_prob = 0.8  # Probabilidad de selección para desacuerdos
        elif uncertainty >= 0.6:  # p in [0.2, 0.8]
            strategy = "uncertainty"
            inclusion_prob = 0.6
        else:
            strategy = "random_baseline"
            inclusion_prob = 0.1

        # Control de cuota por familia (diversidad)
        if family_id:
            family_count = (
                db.query(ActiveLearningQueueItem)
                .filter(
                    ActiveLearningQueueItem.api_key_hash == api_key_hash,
                    ActiveLearningQueueItem.family_id == family_id,
                )
                .count()
            )
            if family_count >= MAX_ITEMS_PER_FAMILY:
                return {
                    "success": False,
                    "enqueued": False,
                    "reason": f"Family quota exceeded (max {MAX_ITEMS_PER_FAMILY} items per family)",
                    "family_id": family_id,
                }

        # Idempotencia / deduplicación
        fp = generate_item_fingerprint(api_key_hash, session_id, strategy, family_id)
        existing = (
            db.query(ActiveLearningQueueItem)
            .filter(ActiveLearningQueueItem.fingerprint == fp)
            .first()
        )
        if existing:
            return {
                "success": True,
                "enqueued": False,
                "deduplicated": True,
                "item_id": existing.id,
                "status": existing.status,
            }

        now = int(time.time())
        purge_at = now + (retention_days * 86400)

        item = ActiveLearningQueueItem(
            id=str(uuid.uuid4()),
            session_id=session_id,
            api_key_hash=api_key_hash,
            family_id=family_id,
            sampling_strategy=strategy,
            inclusion_probability=inclusion_prob,
            features_json=json.dumps(features) if features is not None else None,
            primary_verdict=primary_verdict,
            shadow_probability=shadow_probability,
            uncertainty_score=uncertainty,
            disagreement=is_disagreement,
            status="pending",
            blind_review=True,
            fingerprint=fp,
            created_at=now,
            retention_purge_at=purge_at,
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        return {
            "success": True,
            "enqueued": True,
            "deduplicated": False,
            "item_id": item.id,
            "sampling_strategy": strategy,
            "inclusion_probability": inclusion_prob,
            "status": item.status,
        }

    @staticmethod
    def get_review_batch(
        db: Session,
        api_key_hash: Optional[str] = None,
        limit: int = 20,
        strategy_filter: Optional[str] = None,
        blind: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Obtiene un lote de ítems pendientes para revisión humana.
        En modo ciego (blind=True), no revela predicciones del modelo ni veredictos previos.
        """
        query = db.query(ActiveLearningQueueItem).filter(
            ActiveLearningQueueItem.status.in_(["pending", "reviewed"])
        )
        if api_key_hash:
            query = query.filter(ActiveLearningQueueItem.api_key_hash == api_key_hash)
        if strategy_filter:
            query = query.filter(ActiveLearningQueueItem.sampling_strategy == strategy_filter)

        items = query.order_by(
            ActiveLearningQueueItem.uncertainty_score.desc().nullslast(),
            ActiveLearningQueueItem.created_at.asc(),
        ).limit(limit).all()

        results = []
        for item in items:
            entry = {
                "item_id": item.id,
                "session_id": item.session_id,
                "family_id": item.family_id,
                "sampling_strategy": item.sampling_strategy,
                "status": item.status,
                "created_at": item.created_at,
            }
            if not blind:
                entry.update({
                    "primary_verdict": item.primary_verdict,
                    "shadow_probability": item.shadow_probability,
                    "uncertainty_score": item.uncertainty_score,
                    "disagreement": item.disagreement,
                    "first_verdict": item.first_verdict,
                })
            results.append(entry)
        return results

    @staticmethod
    def submit_review(
        db: Session,
        item_id: str,
        reviewer_id: str,
        verdict: str,
    ) -> Dict[str, Any]:
        """
        Registra la revisión de un humano seudónimo (rev_XXXX).
        Progresión de estados:
        - Si es 1a revisión -> status='reviewed'
        - Si es 2a revisión y coinciden -> status='adjudicated'
        - Si es 2a revisión y difieren -> se mantiene 'reviewed' esperando arbitraje
        """
        if verdict not in ("BENIGN", "RISK", "INSUFFICIENT_CONTEXT"):
            raise ValueError("Verdict must be BENIGN, RISK, or INSUFFICIENT_CONTEXT")

        item = db.get(ActiveLearningQueueItem, item_id)
        if not item:
            raise KeyError("Active learning queue item not found")

        now = int(time.time())

        if item.first_reviewer_id is None:
            # Primera revisión
            item.first_reviewer_id = reviewer_id
            item.first_verdict = verdict
            item.status = "reviewed"
            item.reviewed_at = now
        elif item.second_reviewer_id is None and item.first_reviewer_id != reviewer_id:
            # Segunda revisión independiente
            item.second_reviewer_id = reviewer_id
            item.second_verdict = verdict
            if item.first_verdict == verdict:
                # Acuerdo unánime
                item.adjudicated_verdict = verdict
                item.adjudicated_by = f"consensus({item.first_reviewer_id},{reviewer_id})"
                item.status = "adjudicated"
            else:
                # Discrepancia -> requiere arbitraje
                item.status = "reviewed"
            item.reviewed_at = now
        else:
            raise ValueError("Reviewer already participated or item fully reviewed")

        db.commit()
        db.refresh(item)
        return {
            "success": True,
            "item_id": item.id,
            "status": item.status,
            "adjudicated_verdict": item.adjudicated_verdict,
        }

    @staticmethod
    def adjudicate_item(
        db: Session,
        item_id: str,
        adjudicator_id: str,
        final_verdict: str,
        mark_eligible: bool = True,
    ) -> Dict[str, Any]:
        """
        Adjudicación arbitral formal.
        Transiciona a 'adjudicated' o 'eligible' para dataset export.
        NUNCA entrena modelos ni aprueba términos de forma automática.
        """
        if final_verdict not in ("BENIGN", "RISK", "INSUFFICIENT_CONTEXT", "REJECTED"):
            raise ValueError("Invalid adjudication verdict")

        item = db.get(ActiveLearningQueueItem, item_id)
        if not item:
            raise KeyError("Active learning queue item not found")

        item.adjudicated_verdict = final_verdict
        item.adjudicated_by = adjudicator_id
        item.status = "eligible" if (mark_eligible and final_verdict != "REJECTED") else ("rejected" if final_verdict == "REJECTED" else "adjudicated")
        item.reviewed_at = int(time.time())

        db.commit()
        db.refresh(item)
        return {
            "success": True,
            "item_id": item.id,
            "status": item.status,
            "final_verdict": item.adjudicated_verdict,
        }

    @staticmethod
    def calculate_debiased_population_estimates(db: Session, api_key_hash: Optional[str] = None) -> Dict[str, Any]:
        """
        Calcula estimaciones poblacionales desinsesgadas mediante Inverse Probability Weighting (IPW)
        sobre los ítems evaluados, evitando calcular métricas ingenuas sobre la cola activa enriquecida.
        """
        query = db.query(ActiveLearningQueueItem).filter(
            ActiveLearningQueueItem.status.in_(["adjudicated", "eligible"])
        )
        if api_key_hash:
            query = query.filter(ActiveLearningQueueItem.api_key_hash == api_key_hash)

        items = query.all()
        if not items:
            return {
                "total_adjudicated": 0,
                "naive_risk_prevalence": 0.0,
                "ipw_debiased_risk_prevalence": 0.0,
                "stratified_counts": {},
            }

        naive_risk_count = sum(1 for item in items if item.adjudicated_verdict == "RISK")
        naive_prevalence = naive_risk_count / len(items)

        # IPW estimator: sum( (y_i / pi_i) ) / sum( (1 / pi_i) )
        weighted_risk = 0.0
        weighted_total = 0.0
        stratified_counts: Dict[str, int] = {}

        for item in items:
            strat = item.sampling_strategy
            stratified_counts[strat] = stratified_counts.get(strat, 0) + 1
            
            pi = max(0.01, item.inclusion_probability)
            weight = 1.0 / pi
            
            is_risk = 1.0 if item.adjudicated_verdict == "RISK" else 0.0
            weighted_risk += is_risk * weight
            weighted_total += weight

        debiased_prevalence = (weighted_risk / weighted_total) if weighted_total > 0 else 0.0

        return {
            "total_adjudicated": len(items),
            "naive_risk_prevalence": round(naive_prevalence, 4),
            "ipw_debiased_risk_prevalence": round(debiased_prevalence, 4),
            "stratified_counts": stratified_counts,
        }
