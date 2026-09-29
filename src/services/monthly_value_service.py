import calendar
import html
import json
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.models.db_models import DatasetVersion, TelemetrySnapshot


def month_bounds(year: int, month: int) -> tuple[int, int]:
    if year < 2020 or year > 2100 or month < 1 or month > 12:
        raise ValueError("Invalid report month")
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)
    return int(start.timestamp()), int(end.timestamp())


def _parse_json_object(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_snapshot(raw: str | None) -> list[dict]:
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _dataset_changes(db: Session, start: int, end: int) -> dict:
    versions = (
        db.query(DatasetVersion)
        .filter(
            DatasetVersion.status == "published",
            DatasetVersion.created_at < end,
        )
        .order_by(DatasetVersion.version.asc())
        .all()
    )
    previous_ids: set[str] = set()
    additions: list[dict] = []
    versions_published = 0
    for version in versions:
        snapshot = _parse_snapshot(version.terms_snapshot)
        current_by_id = {
            str(item.get("id")): item
            for item in snapshot
            if item.get("id") is not None
        }
        if start <= version.created_at < end:
            versions_published += 1
            for term_id in sorted(set(current_by_id) - previous_ids):
                item = current_by_id[term_id]
                additions.append(
                    {
                        "id": term_id,
                        "term": item.get("term"),
                        "category": item.get("category"),
                        "dataset_version": version.version,
                    }
                )
        previous_ids = set(current_by_id)
    return {
        "scope": "global_dataset_available_to_all_clients",
        "versions_published": versions_published,
        "new_terms_count": len(additions),
        "new_terms": additions,
    }


def build_monthly_value_report(
    db: Session,
    api_key_hash: str,
    client_name: str,
    year: int,
    month: int,
) -> dict:
    start, end = month_bounds(year, month)
    snapshots = (
        db.query(TelemetrySnapshot)
        .filter(
            TelemetrySnapshot.api_key_hash == api_key_hash,
            TelemetrySnapshot.created_at >= start,
            TelemetrySnapshot.created_at < end,
        )
        .all()
    )
    risk = Counter({"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0})
    recruiter = Counter(
        {"ALLOW": 0, "SILENT_OBSERVE": 0, "SOFT_WARN": 0, "HARD_BLOCK": 0}
    )
    protective = Counter()
    total_analyses = 0
    interventions_observed = 0
    for snapshot in snapshots:
        total_analyses += snapshot.total_analyses
        risk.update(
            {
                "LOW": snapshot.low_count,
                "MEDIUM": snapshot.medium_count,
                "HIGH": snapshot.high_count,
                "CRITICAL": snapshot.critical_count,
            }
        )
        interventions_observed += snapshot.intervention_observed_count or 0
        recruiter.update(
            {
                "ALLOW": snapshot.allow_count or 0,
                "SILENT_OBSERVE": snapshot.silent_observe_count or 0,
                "SOFT_WARN": snapshot.soft_warn_count or 0,
                "HARD_BLOCK": snapshot.hard_block_count or 0,
            }
        )
        protective.update(_parse_json_object(snapshot.protective_action_counts))

    return {
        "client": client_name,
        "period": f"{year:04d}-{month:02d}",
        "timezone": "UTC",
        "analyses": {
            "total": total_analyses,
            "risk_distribution": dict(risk),
        },
        "interventions": {
            "recommended_plans_observed": interventions_observed,
            "recruiter_actions_recommended": dict(recruiter),
            "protective_actions_recommended": dict(sorted(protective.items())),
            "execution_tracking": {
                "available": False,
                "reason": (
                    "Sentinel recommends an intervention plan, but the client platform "
                    "does not yet acknowledge which actions it actually executed."
                ),
            },
        },
        "dataset": _dataset_changes(db, start, end),
        "measurement": {
            "telemetry_opt_in_required": True,
            "snapshots_in_period": len(snapshots),
            "intervention_coverage_percent": round(
                (interventions_observed / total_analyses * 100) if total_analyses else 0,
                2,
            ),
            "caveat": (
                "Counts include only opt-in telemetry and are assigned to the UTC month "
                "when each aggregate snapshot was received; no message text or user IDs are stored."
            ),
        },
    }


def render_monthly_value_html(report: dict) -> str:
    risk = report["analyses"]["risk_distribution"]
    recruiter = report["interventions"]["recruiter_actions_recommended"]
    terms = report["dataset"]["new_terms"]
    term_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['id']))}</td>"
        f"<td>{html.escape(str(item.get('term') or ''))}</td>"
        f"<td>{html.escape(str(item.get('category') or ''))}</td>"
        "</tr>"
        for item in terms
    ) or '<tr><td colspan="3">Sin términos nuevos publicados en el período.</td></tr>'
    month_name = calendar.month_name[int(report["period"].split("-")[1])]
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Sentinel · Reporte mensual {html.escape(report['period'])}</title>
<style>body{{font-family:system-ui;background:#f3f4f6;color:#17202a;margin:0}}main{{max-width:980px;margin:auto;padding:32px}}.card{{background:white;border-radius:12px;padding:20px;margin:16px 0;box-shadow:0 2px 8px #0001}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px}}.metric{{background:#f8fafc;padding:16px;border-radius:8px}}.metric strong{{font-size:1.8rem;display:block}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #e5e7eb;text-align:left}}.note{{color:#5f6b7a;font-size:.9rem}}h1{{color:#b91c1c}}</style></head>
<body><main><h1>Sentinel · Valor mensual</h1><p>{html.escape(report['client'])} · {month_name} {report['period'][:4]} · UTC</p>
<section class="card"><h2>Análisis</h2><div class="grid"><div class="metric"><strong>{report['analyses']['total']}</strong>Total</div>{''.join(f'<div class="metric"><strong>{risk[level]}</strong>{level}</div>' for level in ('LOW','MEDIUM','HIGH','CRITICAL'))}</div></section>
<section class="card"><h2>Planes de intervención recomendados</h2><div class="grid">{''.join(f'<div class="metric"><strong>{recruiter[action]}</strong>{action}</div>' for action in ('ALLOW','SILENT_OBSERVE','SOFT_WARN','HARD_BLOCK'))}</div><p class="note">No se presentan como acciones ejecutadas: la plataforma cliente todavía no confirma a Sentinel cuáles aplicó realmente.</p></section>
<section class="card"><h2>Actualizaciones del dataset</h2><p>{report['dataset']['versions_published']} versión(es), {report['dataset']['new_terms_count']} término(s) nuevo(s).</p><table><thead><tr><th>ID</th><th>Término</th><th>Categoría</th></tr></thead><tbody>{term_rows}</tbody></table></section>
<section class="card note"><strong>Privacidad y cobertura</strong><p>{html.escape(report['measurement']['caveat'])}</p><p>Cobertura de planes recomendados: {report['measurement']['intervention_coverage_percent']}%.</p></section>
</main></body></html>"""
