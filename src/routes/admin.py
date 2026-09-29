from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.models.db_models import CandidateSighting, DatasetVersion
from src.services.calibration_service import (
    apply_calibration_proposal,
    reject_calibration_proposal,
)
from src.services.hot_terms_service import (
    get_staged_terms,
    approve_term_manual,
    reject_term_manual,
    update_term_manual
)
from pydantic import BaseModel
from typing import Optional
import json

router = APIRouter()

class UpdateTermRequest(BaseModel):
    category: str
    weight: float


class ApplyCalibrationRequest(BaseModel):
    benchmark_confirmed: bool

@router.get("/review", response_class=HTMLResponse)
def review_dashboard(request: Request):
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta name="referrer" content="no-referrer">
        <title>Sentinel Admin - Revisión de Términos</title>
        <style>
            :root { color-scheme: light; font-family: system-ui, sans-serif; }
            body { margin: 0; background: #f3f4f6; color: #1f2937; }
            .wrap { max-width: 1150px; margin: auto; padding: 24px; }
            .top { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
            .card { background: white; border-radius: 10px; padding: 20px; margin: 20px 0; box-shadow: 0 2px 8px #0001; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(145px,1fr)); gap: 12px; }
            .metric { background: #f9fafb; padding: 12px; border-radius: 8px; text-align: center; }
            .metric strong { display: block; font-size: 1.5rem; }
            h1 { color: #dc2626; } h2 { border-bottom: 1px solid #e5e7eb; padding-bottom: 10px; }
            table { border-collapse: collapse; width: 100%; min-width: 850px; }
            th, td { border-bottom: 1px solid #e5e7eb; padding: 10px; text-align: left; vertical-align: top; }
            th { background: #f9fafb; } .scroll { overflow-x: auto; }
            input { max-width: 110px; padding: 5px; border: 1px solid #d1d5db; border-radius: 5px; }
            button { border: 0; border-radius: 6px; padding: 7px 10px; color: white; cursor: pointer; margin: 2px; }
            .blue { background: #2563eb; } .green { background: #16a34a; }
            .red { background: #dc2626; } .gray { background: #6b7280; }
            .muted { color: #6b7280; font-size: .85rem; } pre { white-space: pre-wrap; background: #f9fafb; padding: 10px; }
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="top">
                <h1>Sentinel Admin Review</h1>
                <button onclick="publishVersion()" class="blue">
                    Publicar Versión (Aprobar Todos los Listos)
                </button>
            </div>
            
            <div class="card">
                <h2>Estadísticas del Pipeline</h2>
                <div id="stats-container" class="grid">
                    <div class="metric">Cargando...</div>
                </div>
            </div>

            <div class="card">
                <h2>Términos Pendientes de Revisión (Staged)</h2>
                <div class="scroll">
                    <table>
                        <thead>
                            <tr class="bg-gray-100">
                                <th class="p-3 border-b">Término</th>
                                <th class="p-3 border-b">Categoría</th>
                                <th class="p-3 border-b">Peso</th>
                                <th class="p-3 border-b">Fuente / Contexto</th>
                                <th class="p-3 border-b">Justificación (IA)</th>
                                <th class="p-3 border-b">Acciones</th>
                            </tr>
                        </thead>
                        <tbody id="terms-tbody">
                            <tr><td colspan="6" class="p-4 text-center text-gray-500">Cargando términos...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="card">
                <h2>Propuestas de calibración</h2>
                <div id="calibration-container">Cargando...</div>
            </div>
        </div>

        <script>
            // El navegador conserva HTTP Basic para los fetch del mismo origen.
            // La llave nunca se copia a JavaScript, la URL ni los logs de acceso.
            const AUTH_HEADERS = {};
            const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
            })[char]);

            async function loadStats() {
                try {
                    const res = await fetch('/api/v1/hot-terms/pipeline-stats', { headers: AUTH_HEADERS });
                    const json = await res.json();
                    if(json.success) {
                        const s = json.data;
                        const r = s.ultima_corrida || {};
                        document.getElementById('stats-container').innerHTML = `
                            <div class="metric"><strong>${r.candidatos_entraron || 0}</strong><span class="muted">Entraron (última corrida)</span></div>
                            <div class="metric"><strong>${r.candidatos_sobrevivieron_prefiltro || 0}</strong><span class="muted">Sobrevivieron gratis</span></div>
                            <div class="metric"><strong>${r.candidatos_clasificados || 0}</strong><span class="muted">Clasificados por Groq</span></div>
                            <div class="metric"><strong>${r.candidatos_aprobados_ia || 0}</strong><span class="muted">Aprobados por IA</span></div>
                        `;
                    }
                } catch(e) { console.error('Error loading stats', e); }
            }

            async function loadTerms() {
                try {
                    const res = await fetch('/admin/api/staged', { headers: AUTH_HEADERS });
                    const json = await res.json();
                    const tbody = document.getElementById('terms-tbody');
                    if(json.data.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="6" class="p-4 text-center text-gray-500">No hay términos staged.</td></tr>';
                        return;
                    }
                    tbody.innerHTML = json.data.map(t => `
                        <tr class="border-b hover:bg-gray-50" id="row-${t.id}">
                            <td class="p-3 font-semibold text-red-600">${escapeHtml(t.term)}</td>
                            <td class="p-3"><input type="text" id="cat-${t.id}" value="${escapeHtml(t.category)}" class="border rounded px-2 py-1 w-24 text-sm"></td>
                            <td class="p-3"><input type="number" id="weight-${t.id}" value="${t.weight}" class="border rounded px-2 py-1 w-16 text-sm"></td>
                            <td class="p-3 text-xs text-gray-600 max-w-xs break-words"><strong>${escapeHtml(t.source || 'N/A')}</strong><br>${escapeHtml(t.context || 'Sin contexto guardado')}</td>
                            <td class="p-3 text-xs text-gray-600 max-w-xs break-words italic">${t.reviewed ? 'Revisado; listo para publicar' : 'Pendiente de revisión humana'}</td>
                            <td class="p-3">
                                <div class="flex space-x-2">
                                    <button onclick="approveTerm('${t.id}')" class="green">Marcar revisado</button>
                                    <button onclick="updateTerm('${t.id}')" class="gray">Guardar</button>
                                    <button onclick="rejectTerm('${t.id}')" class="red">Rechazar</button>
                                </div>
                            </td>
                        </tr>
                    `).join('');
                } catch(e) { console.error('Error loading terms', e); }
            }

            async function approveTerm(id) {
                await fetch(`/admin/api/staged/${id}/approve`, { method: 'POST', headers: AUTH_HEADERS });
                loadTerms();
                loadStats();
            }

            async function rejectTerm(id) {
                await fetch(`/admin/api/staged/${id}/reject`, { method: 'POST', headers: AUTH_HEADERS });
                await loadTerms();
                loadStats();
            }

            async function updateTerm(id) {
                const cat = document.getElementById(`cat-${id}`).value;
                const weight = parseFloat(document.getElementById(`weight-${id}`).value);
                const res = await fetch(`/admin/api/staged/${id}`, {
                    method: 'PATCH',
                    headers: {'Content-Type': 'application/json', ...AUTH_HEADERS},
                    body: JSON.stringify({ category: cat, weight: weight })
                });
                if(res.ok) {
                    alert("Término actualizado");
                }
            }

            async function publishVersion() {
                if(!confirm("¿Publicar únicamente los términos revisados como una nueva versión?")) return;
                const res = await fetch('/api/v1/hot-terms/publish', { method: 'POST', headers: AUTH_HEADERS });
                const json = await res.json();
                if(res.ok) {
                    alert("Versión publicada: " + json.data.version);
                    loadTerms();
                    loadStats();
                } else {
                    alert("Error: " + (json.message || "No se pudo publicar"));
                }
            }

            async function loadCalibrations() {
                const res = await fetch('/admin/api/calibration-proposals', { headers: AUTH_HEADERS });
                const json = await res.json();
                const container = document.getElementById('calibration-container');
                if(!json.data.length) {
                    container.innerHTML = '<p class="text-gray-500">No hay propuestas pendientes.</p>';
                    return;
                }
                container.innerHTML = json.data.map(p => `
                    <div class="border rounded p-3">
                        <div><strong>Versión propuesta ${p.version}</strong> · base ${p.base_version || 'vacía'} · ${p.adjustments} ajuste(s)</div>
                        <pre class="text-xs bg-gray-50 p-2 my-2 overflow-x-auto">${escapeHtml(JSON.stringify(p.audit, null, 2))}</pre>
                        <button onclick="applyCalibration(${p.version})" class="green">Aplicar (benchmark confirmado)</button>
                        <button onclick="rejectCalibration(${p.version})" class="red">Rechazar</button>
                    </div>
                `).join('');
            }

            async function applyCalibration(version) {
                if(!confirm('Confirma que ejecutaste benchmark y red-team sobre esta propuesta.')) return;
                const res = await fetch(`/admin/api/calibration-proposals/${version}/apply`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', ...AUTH_HEADERS},
                    body: JSON.stringify({benchmark_confirmed: true})
                });
                if(!res.ok) alert('No se pudo aplicar: ' + await res.text());
                loadCalibrations();
            }

            async function rejectCalibration(version) {
                await fetch(`/admin/api/calibration-proposals/${version}/reject`, {method: 'POST', headers: AUTH_HEADERS});
                loadCalibrations();
            }

            // Init
            loadStats();
            loadTerms();
            loadCalibrations();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(
        content=html_content,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
        },
    )

@router.get("/api/staged")
def api_get_staged_terms(db: Session = Depends(get_db)):
    terms = get_staged_terms(db)
    return JSONResponse(content={
        "success": True,
        "data": [
            {
                "id": t.id,
                "term": t.term,
                "category": t.category,
                "weight": t.weight,
                "source": t.source,
                "reviewed": bool(t.reviewed),
                "context": (
                    db.query(CandidateSighting.context)
                    .filter(CandidateSighting.term == t.term)
                    .order_by(CandidateSighting.seen_at.desc())
                    .scalar()
                ),
            } for t in terms
        ]
    })

@router.post("/api/staged/{term_id}/approve")
def api_approve_staged(term_id: str, db: Session = Depends(get_db)):
    success = approve_term_manual(db, term_id)
    if not success:
        raise HTTPException(status_code=404, detail="Term not found")
    return {"success": True}

@router.post("/api/staged/{term_id}/reject")
def api_reject_staged(term_id: str, db: Session = Depends(get_db)):
    success = reject_term_manual(db, term_id)
    if not success:
        raise HTTPException(status_code=404, detail="Term not found")
    return {"success": True}

@router.patch("/api/staged/{term_id}")
def api_update_staged(term_id: str, body: UpdateTermRequest, db: Session = Depends(get_db)):
    term = update_term_manual(db, term_id, body.category, body.weight)
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    return {"success": True}


@router.get("/api/calibration-proposals")
def api_calibration_proposals(db: Session = Depends(get_db)):
    proposals = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.status == "calibration_proposed")
        .order_by(DatasetVersion.version.desc())
        .all()
    )
    data = []
    for proposal in proposals:
        audit = json.loads(proposal.audit_json or "{}")
        adjustments = sum(
            item.get("decision") in {"reduce_weight", "increase_weight"}
            for item in audit.get("terms", {}).values()
        )
        data.append({
            "version": proposal.version,
            "base_version": proposal.base_version,
            "created_at": proposal.created_at,
            "adjustments": adjustments,
            "audit": audit,
        })
    return {"success": True, "data": data}


@router.post("/api/calibration-proposals/{version_id}/apply")
def api_apply_calibration(
    version_id: int,
    body: ApplyCalibrationRequest,
    db: Session = Depends(get_db),
):
    if not body.benchmark_confirmed:
        raise HTTPException(status_code=400, detail="Benchmark confirmation required")
    result = apply_calibration_proposal(db, version_id)
    if result != "applied":
        status_code = 404 if result == "not_found" else 409
        raise HTTPException(status_code=status_code, detail=result)
    return {"success": True, "status": result}


@router.post("/api/calibration-proposals/{version_id}/reject")
def api_reject_calibration(version_id: int, db: Session = Depends(get_db)):
    result = reject_calibration_proposal(db, version_id)
    if result != "rejected":
        status_code = 404 if result == "not_found" else 409
        raise HTTPException(status_code=status_code, detail=result)
    return {"success": True, "status": result}


# ─── Endpoints de Procedencia y Permisos de Datos (S08) ──────────────────────

from src.models.db_models import DataSource
from src.services.data_provenance_service import (
    ensure_canonical_data_sources,
    register_data_source,
    review_data_source,
    export_dataset_by_usage,
)


class RegisterDataSourceRequest(BaseModel):
    id: str
    name: str
    canonical_origin: str
    source_type: str
    license_or_permission_ref: str
    allowed_uses: list[str]
    permission_status: Optional[str] = "quarantine"
    reviewer: Optional[str] = None


class ReviewDataSourceRequest(BaseModel):
    permission_status: str
    reviewer: str
    allowed_uses: Optional[list[str]] = None


@router.get("/api/sources")
def api_list_data_sources(db: Session = Depends(get_db)):
    """Lista todas las fuentes de datos registradas con sus permisos y derechos de uso."""
    ensure_canonical_data_sources(db)
    sources = db.query(DataSource).order_by(DataSource.created_at.asc()).all()
    return {
        "success": True,
        "data": [
            {
                "id": s.id,
                "name": s.name,
                "canonical_origin": s.canonical_origin,
                "source_type": s.source_type,
                "permission_status": s.permission_status,
                "allowed_uses": s.allowed_uses.split(","),
                "license_ref": s.license_or_permission_ref,
                "created_at": s.created_at,
                "reviewed_by": s.reviewed_by,
                "reviewed_at": s.reviewed_at,
            }
            for s in sources
        ],
    }


@router.post("/api/sources")
def api_register_data_source(
    body: RegisterDataSourceRequest,
    db: Session = Depends(get_db),
):
    """Registra una nueva fuente con estatus 'quarantine' por defecto."""
    try:
        source = register_data_source(
            db=db,
            source_id=body.id,
            name=body.name,
            canonical_origin=body.canonical_origin,
            source_type=body.source_type,
            license_ref=body.license_or_permission_ref,
            allowed_uses=body.allowed_uses,
            permission_status=body.permission_status or "quarantine",
            reviewer=body.reviewer,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"success": True, "data": {"id": source.id, "permission_status": source.permission_status}}


@router.post("/api/sources/{source_id}/review")
def api_review_data_source(
    source_id: str,
    body: ReviewDataSourceRequest,
    db: Session = Depends(get_db),
):
    """Aprobación o revocación humana obligatoria de una fuente de datos."""
    try:
        source = review_data_source(
            db=db,
            source_id=source_id,
            permission_status=body.permission_status,
            reviewer=body.reviewer,
            allowed_uses=body.allowed_uses,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    return {"success": True, "data": {"id": source.id, "permission_status": source.permission_status}}


@router.get("/api/dataset/export")
def api_export_dataset(
    target_use: str = Query(..., description="Uso objetivo: discovery | training | evaluation | redistribution"),
    category: Optional[str] = Query(None, description="Filtro opcional por categoría"),
    db: Session = Depends(get_db),
):
    """
    Exporta datos filtrados estrictamente por permisos del origen canónico.
    Bloquea datos sin trazabilidad, en cuarentena o revocados de exports de entrenamiento.
    """
    try:
        manifest = export_dataset_by_usage(db=db, target_use=target_use, category=category)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"success": True, "data": manifest}
