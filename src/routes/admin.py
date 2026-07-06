from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.services.hot_terms_service import (
    get_staged_terms,
    approve_term_manual,
    reject_term_manual,
    update_term_manual
)
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class UpdateTermRequest(BaseModel):
    category: str
    weight: float

@router.get("/review", response_class=HTMLResponse)
def review_dashboard(request: Request):
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sentinel Admin - Revisión de Términos</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 text-gray-800 font-sans p-6">
        <div class="max-w-6xl mx-auto">
            <div class="flex justify-between items-center mb-6">
                <h1 class="text-3xl font-bold text-red-600">Sentinel Admin Review</h1>
                <button onclick="publishVersion()" class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded shadow">
                    Publicar Versión (Aprobar Todos los Listos)
                </button>
            </div>
            
            <div class="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 class="text-xl font-semibold mb-4 border-b pb-2">Estadísticas del Pipeline</h2>
                <div id="stats-container" class="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                    <div class="p-3 bg-gray-50 rounded">Cargando...</div>
                </div>
            </div>

            <div class="bg-white rounded-lg shadow-md p-6">
                <h2 class="text-xl font-semibold mb-4 border-b pb-2">Términos Pendientes de Revisión (Staged)</h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
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
        </div>

        <script>
            // La llave admin llega por query param (?api_key=...) porque el navegador
            // no puede mandar headers custom al navegar. Se reenvía como header en
            // cada fetch del dashboard.
            const ADMIN_KEY = new URLSearchParams(window.location.search).get('api_key') || '';
            const AUTH_HEADERS = { 'X-API-Key': ADMIN_KEY };

            async function loadStats() {
                try {
                    const res = await fetch('/api/v1/hot-terms/pipeline-stats', { headers: AUTH_HEADERS });
                    const json = await res.json();
                    if(json.success) {
                        const s = json.data;
                        document.getElementById('stats-container').innerHTML = `
                            <div class="p-3 bg-gray-50 rounded"><div class="text-2xl font-bold">${s.sightings_totales || 0}</div><div class="text-sm text-gray-500">Sightings Totales</div></div>
                            <div class="p-3 bg-gray-50 rounded"><div class="text-2xl font-bold">${s.candidatos_elegibles || 0}</div><div class="text-sm text-gray-500">Elegibles para Groq</div></div>
                            <div class="p-3 bg-gray-50 rounded"><div class="text-2xl font-bold text-green-600">${s.terminos_aprobados || 0}</div><div class="text-sm text-gray-500">Aprobados Activos</div></div>
                            <div class="p-3 bg-gray-50 rounded"><div class="text-2xl font-bold text-red-500">${s.terminos_rechazados || 0}</div><div class="text-sm text-gray-500">Rechazados</div></div>
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
                            <td class="p-3 font-semibold text-red-600">${t.term}</td>
                            <td class="p-3"><input type="text" id="cat-${t.id}" value="${t.category}" class="border rounded px-2 py-1 w-24 text-sm"></td>
                            <td class="p-3"><input type="number" id="weight-${t.id}" value="${t.weight}" class="border rounded px-2 py-1 w-16 text-sm"></td>
                            <td class="p-3 text-xs text-gray-600 max-w-xs break-words">${t.source || 'N/A'}</td>
                            <td class="p-3 text-xs text-gray-600 max-w-xs break-words italic">"Clasificación Automática de IA"</td>
                            <td class="p-3">
                                <div class="flex space-x-2">
                                    <button onclick="approveTerm('${t.id}')" class="bg-green-500 hover:bg-green-600 text-white text-xs px-2 py-1 rounded">Aprobar</button>
                                    <button onclick="updateTerm('${t.id}')" class="bg-gray-500 hover:bg-gray-600 text-white text-xs px-2 py-1 rounded">Guardar</button>
                                    <button onclick="rejectTerm('${t.id}')" class="bg-red-500 hover:bg-red-600 text-white text-xs px-2 py-1 rounded">Rechazar</button>
                                </div>
                            </td>
                        </tr>
                    `).join('');
                } catch(e) { console.error('Error loading terms', e); }
            }

            async function approveTerm(id) {
                await fetch(`/admin/api/staged/${id}/approve`, { method: 'POST', headers: AUTH_HEADERS });
                document.getElementById(`row-${id}`).remove();
                loadStats();
            }

            async function rejectTerm(id) {
                await fetch(`/admin/api/staged/${id}/reject`, { method: 'POST', headers: AUTH_HEADERS });
                document.getElementById(`row-${id}`).remove();
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
                if(!confirm("¿Estás seguro de publicar todos los términos staged como una nueva versión?")) return;
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

            // Init
            loadStats();
            loadTerms();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

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
                "source": t.source
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
