import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import intervention as iv


def test_low_no_hace_nada():
    p = iv.build_intervention_plan(risk="LOW")
    assert p["recruiter_action"] == iv.RECRUITER_ALLOW
    assert p["protective_actions"] == []


def test_falso_positivo_no_interviene():
    p = iv.build_intervention_plan(risk="MEDIUM", false_positive=True)
    assert p["recruiter_action"] == iv.RECRUITER_ALLOW


def test_medium_vigila_sin_alarmar_al_menor():
    p = iv.build_intervention_plan(risk="MEDIUM")
    assert p["recruiter_action"] == iv.RECRUITER_SOFT_WARN
    assert iv.SHADOW_FLAG in p["protective_actions"]
    # En zona gris NO se alarma al menor todavía.
    assert p["minor_message"] is None


def test_high_no_tipifica_al_agresor_pero_protege_a_la_victima():
    # Principio clave: riesgo alto NO inminente → NO avisar al reclutador (oráculo),
    # proteger al menor en silencio.
    p = iv.build_intervention_plan(risk="HIGH", stage="CAPTACION")
    assert p["recruiter_action"] == iv.RECRUITER_SILENT  # NO es HARD_BLOCK
    assert iv.SHADOW_FLAG in p["protective_actions"]
    assert iv.WARN_MINOR in p["protective_actions"]
    assert p["minor_message"] is not None


def test_instrumentalizacion_es_bloqueo_visible():
    p = iv.build_intervention_plan(risk="CRITICAL", stage="UTILIZACION/INSTRUMENTALIZACION")
    assert p["recruiter_action"] == iv.RECRUITER_HARD_BLOCK
    assert iv.PRESERVE_EVIDENCE in p["protective_actions"]
    assert iv.NOTIFY_GUARDIAN in p["protective_actions"]


def test_red_organizada_bloquea_y_sugiere_denuncia():
    p = iv.build_intervention_plan(risk="HIGH", stage="CAPTACION", network_risk="CRITICAL")
    assert p["recruiter_action"] == iv.RECRUITER_HARD_BLOCK
    assert iv.REPORT_AUTHORITY in p["protective_actions"]


def test_logistica_en_curso_con_critical_es_inminente():
    p = iv.build_intervention_plan(risk="CRITICAL", stage="CAPTACION", logistics_in_progress=True)
    assert p["recruiter_action"] == iv.RECRUITER_HARD_BLOCK
    assert iv.PRESERVE_EVIDENCE in p["protective_actions"]


def test_agresor_por_asimetria_agrega_restringir_contacto():
    p = iv.build_intervention_plan(risk="HIGH", stage="CAPTACION", has_aggressor=True)
    assert iv.RESTRICT_CONTACT in p["protective_actions"]


def test_el_mensaje_al_menor_incluye_recurso_de_ayuda():
    p = iv.build_intervention_plan(risk="HIGH", stage="CAPTACION")
    assert "088" in p["minor_message"] or "Te Protejo" in p["minor_message"]
