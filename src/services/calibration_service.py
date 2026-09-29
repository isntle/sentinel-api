import hashlib
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.models.db_models import DatasetVersion, Feedback, HotTerm

MIN_GLOBAL_REPORTS = 50
MIN_EFFECTIVE_REPORTS = 15
MIN_DISTINCT_CLIENTS = 3
MAX_REPORTS_PER_CLIENT_TERM = 5
MAX_CLIENT_SHARE = 0.40
MIN_ERROR_REPORTS = 10
MIN_BALANCED_ERROR_RATE = 0.70
MIN_WILSON_LOWER = 0.50


@dataclass(frozen=True)
class CalibrationDecision:
    term_id: str
    previous_weight: float
    proposed_weight: float
    action: str
    evidence: dict


def _wilson_lower(successes: int, total: int, z: float = 1.96) -> float:
    if total == 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + (z * z / total)
    centre = proportion + (z * z / (2 * total))
    margin = z * math.sqrt(
        (proportion * (1 - proportion) / total) + (z * z / (4 * total * total))
    )
    return (centre - margin) / denominator


def _term_ids(feedback: Feedback) -> list[str]:
    if not feedback.term_ids:
        return []
    try:
        parsed = json.loads(feedback.term_ids)
    except (TypeError, json.JSONDecodeError):
        return []
    return [value for value in parsed if isinstance(value, str)] if isinstance(parsed, list) else []


def _snapshot(terms: list[HotTerm], decisions: dict[str, CalibrationDecision]) -> list[dict]:
    return [
        {
            "id": term.id,
            "term": term.term,
            "category": term.category,
            "weight": decisions.get(term.id, None).proposed_weight if term.id in decisions else term.weight,
            "initial_weight": term.initial_weight,
            "variants": term.variants,
            "source": term.source,
            "created_at": term.created_at,
        }
        for term in terms
    ]


def generate_calibration_proposal(
    db: Session,
    window_days: int = 90,
    now: int | None = None,
) -> dict:
    current_time = int(time.time()) if now is None else now
    cutoff = current_time - (window_days * 24 * 60 * 60)
    feedback_rows = (
        db.query(Feedback)
        .filter(
            Feedback.created_at >= cutoff,
            Feedback.api_key_hash.isnot(None),
            Feedback.dataset_version.isnot(None),
            Feedback.term_ids.isnot(None),
        )
        .order_by(Feedback.created_at.asc(), Feedback.id.asc())
        .all()
    )
    usable = [row for row in feedback_rows if _term_ids(row)]
    if len(usable) < MIN_GLOBAL_REPORTS:
        return {
            "status": "insufficient_data",
            "usable_feedback": len(usable),
            "minimum_required": MIN_GLOBAL_REPORTS,
            "proposal_version": None,
        }

    latest_published = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.status == "published")
        .order_by(DatasetVersion.version.desc())
        .first()
    )
    base_version = latest_published.version if latest_published else 0
    run_material = json.dumps(
        {
            "base_version": base_version,
            "feedback_ids": sorted(row.id for row in usable),
            "window_days": window_days,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    run_id = hashlib.sha256(run_material.encode()).hexdigest()
    existing = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.calibration_run_id == run_id)
        .first()
    )
    if existing:
        return {
            "status": "already_exists",
            "usable_feedback": len(usable),
            "proposal_version": existing.version,
            "calibration_run_id": run_id,
        }

    by_term_client: dict[str, dict[str, list[Feedback]]] = defaultdict(lambda: defaultdict(list))
    for row in usable:
        for term_id in set(_term_ids(row)):
            by_term_client[term_id][row.api_key_hash].append(row)

    approved_terms = db.query(HotTerm).filter(HotTerm.approved == True).all()
    terms_by_id = {term.id: term for term in approved_terms}
    decisions: dict[str, CalibrationDecision] = {}
    audit_terms: dict[str, dict] = {}

    for term_id, client_rows in by_term_client.items():
        term = terms_by_id.get(term_id)
        if term is None:
            audit_terms[term_id] = {"decision": "ignored_not_dynamic_approved_term"}
            continue

        capped = {
            client: rows[:MAX_REPORTS_PER_CLIENT_TERM]
            for client, rows in client_rows.items()
        }
        effective = [row for rows in capped.values() for row in rows]
        client_count = len(capped)
        largest_share = max((len(rows) for rows in capped.values()), default=0) / max(len(effective), 1)
        common_evidence = {
            "effective_reports": len(effective),
            "distinct_clients": client_count,
            "largest_client_share": round(largest_share, 4),
        }
        if (
            len(effective) < MIN_EFFECTIVE_REPORTS
            or client_count < MIN_DISTINCT_CLIENTS
            or largest_share > MAX_CLIENT_SHARE
        ):
            audit_terms[term_id] = {**common_evidence, "decision": "ignored_insufficient_diversity"}
            continue

        rates = {}
        counts = {}
        wilson = {}
        for feedback_type in ("false_positive", "false_negative"):
            successes = sum(row.feedback_type == feedback_type for row in effective)
            client_rates = [
                sum(row.feedback_type == feedback_type for row in rows) / len(rows)
                for rows in capped.values()
            ]
            counts[feedback_type] = successes
            rates[feedback_type] = sum(client_rates) / len(client_rates)
            wilson[feedback_type] = _wilson_lower(successes, len(effective))

        action = None
        proposed = term.weight
        if (
            counts["false_positive"] >= MIN_ERROR_REPORTS
            and rates["false_positive"] >= MIN_BALANCED_ERROR_RATE
            and wilson["false_positive"] >= MIN_WILSON_LOWER
        ):
            reduction = min(2.0, term.weight * 0.10)
            floor = max(1.0, (term.initial_weight or term.weight) * 0.50)
            proposed = max(floor, term.weight - reduction)
            action = "reduce_weight"
        elif (
            counts["false_negative"] >= MIN_ERROR_REPORTS
            and rates["false_negative"] >= MIN_BALANCED_ERROR_RATE
            and wilson["false_negative"] >= MIN_WILSON_LOWER
        ):
            proposed = min(15.0, term.weight + min(1.0, term.weight * 0.10))
            action = "increase_weight"

        evidence = {
            **common_evidence,
            "counts": counts,
            "balanced_rates": {key: round(value, 4) for key, value in rates.items()},
            "wilson_lower_95": {key: round(value, 4) for key, value in wilson.items()},
        }
        if action and proposed != term.weight:
            decision = CalibrationDecision(
                term_id=term_id,
                previous_weight=term.weight,
                proposed_weight=round(proposed, 4),
                action=action,
                evidence=evidence,
            )
            decisions[term_id] = decision
            audit_terms[term_id] = {
                **evidence,
                "decision": action,
                "previous_weight": term.weight,
                "proposed_weight": decision.proposed_weight,
            }
        else:
            audit_terms[term_id] = {**evidence, "decision": "keep"}

    if not decisions:
        return {
            "status": "no_adjustments",
            "usable_feedback": len(usable),
            "proposal_version": None,
            "audit": audit_terms,
        }

    proposal = DatasetVersion(
        created_at=current_time,
        description=f"Auto-calibration proposal {run_id[:12]}",
        terms_snapshot=json.dumps(_snapshot(approved_terms, decisions), sort_keys=True),
        status="calibration_proposed",
        base_version=base_version or None,
        calibration_run_id=run_id,
        audit_json=json.dumps(
            {
                "window_days": window_days,
                "usable_feedback": len(usable),
                "terms": audit_terms,
            },
            sort_keys=True,
        ),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return {
        "status": "proposal_created",
        "usable_feedback": len(usable),
        "proposal_version": proposal.version,
        "calibration_run_id": run_id,
        "adjustments": len(decisions),
    }


def apply_calibration_proposal(db: Session, version_id: int) -> str:
    proposal = db.query(DatasetVersion).filter(DatasetVersion.version == version_id).first()
    if proposal is None:
        return "not_found"
    if proposal.status != "calibration_proposed":
        return "not_pending"
    latest_published = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.status == "published")
        .order_by(DatasetVersion.version.desc())
        .first()
    )
    current_base = latest_published.version if latest_published else None
    if proposal.base_version != current_base:
        return "base_version_changed"

    snapshot = json.loads(proposal.terms_snapshot)
    current_terms = {
        term.id: term for term in db.query(HotTerm).filter(HotTerm.approved == True).all()
    }
    if set(current_terms) != {item["id"] for item in snapshot}:
        return "dataset_changed"
    for item in snapshot:
        current_terms[item["id"]].weight = float(item["weight"])

    proposal.status = "published"
    proposal.description = f"Applied {proposal.description}"
    db.commit()
    return "applied"


def reject_calibration_proposal(db: Session, version_id: int) -> str:
    proposal = db.query(DatasetVersion).filter(DatasetVersion.version == version_id).first()
    if proposal is None:
        return "not_found"
    if proposal.status != "calibration_proposed":
        return "not_pending"
    proposal.status = "rejected"
    db.commit()
    return "rejected"
