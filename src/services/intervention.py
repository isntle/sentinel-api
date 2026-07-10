"""
Capa de intervención graduada (roadmap 8.1).

El sistema NO debe reducirse a "bloquear o no". Un bloqueo VISIBLE tiene dos
efectos secundarios documentados en la literatura de seguridad infantil:
  1. Es un ORÁCULO: le enseña al reclutador qué mensaje disparó el filtro, y
     itera hasta evadirlo.
  2. Puede ESCALAR el peligro: si el reclutador ya tiene datos del menor, cortarle
     el canal puede provocar represalia o mudanza a un canal sin protección.

Por eso la intervención decopla dos dimensiones:
  - recruiter_action: lo que EXPERIMENTA el agresor (nada / advertencia / bloqueo).
  - protective_actions: lo que protege a la VÍCTIMA (vigilancia silenciosa, aviso
    privado al menor con recursos, notificar tutor, preservar evidencia, etc.).

Regla rectora: proteger a la víctima en silencio primero; solo tipificar/bloquear
de forma visible cuando el peligro es INMINENTE (logística física en curso,
instrumentalización, o red organizada confirmada). La plataforma recibe un PLAN
y aplica su política; Sentinel recomienda.
"""

# Lo que experimenta el agresor.
RECRUITER_ALLOW = "ALLOW"            # el mensaje fluye, sin señal al agresor
RECRUITER_SILENT = "SILENT_OBSERVE"  # fluye, pero la plataforma vigila (sin tipificar)
RECRUITER_SOFT_WARN = "SOFT_WARN"    # fricción suave visible (interstitial, "¿seguro?")
RECRUITER_HARD_BLOCK = "HARD_BLOCK"  # se corta el mensaje/contacto

# Acciones que protegen a la víctima (pueden combinarse).
SHADOW_FLAG = "SHADOW_FLAG"           # marcar para vigilancia sin avisar al agresor
WARN_MINOR = "WARN_MINOR"             # aviso privado y cálido al menor + recursos
NOTIFY_GUARDIAN = "NOTIFY_GUARDIAN"   # avisar al tutor vinculado (si la plataforma lo tiene)
RESTRICT_CONTACT = "RESTRICT_CONTACT" # limitar al emisor (no iniciar chats con menores)
PRESERVE_EVIDENCE = "PRESERVE_EVIDENCE"  # congelar la sesión para denuncia
REPORT_AUTHORITY = "REPORT_AUTHORITY"    # sugerir denuncia (Policía Cibernética / Te Protejo)

# Recurso de ayuda para el mensaje al menor (México).
HELP_RESOURCE = "Si algo te incomoda o te da miedo, cuéntale a un adulto de confianza. También puedes marcar al 088 (Guardia Nacional) o escribir a Te Protejo México."

# Etapas que implican peligro INMINENTE (justifican acción visible/bloqueo).
IMMINENT_STAGES = {"INCUBACION", "UTILIZACION/INSTRUMENTALIZACION"}


def build_intervention_plan(
    risk: str,
    stage: str | None = None,
    network_risk: str | None = None,
    has_aggressor: bool = False,
    logistics_in_progress: bool = False,
    false_positive: bool = False,
) -> dict:
    """
    Mapea las señales al plan de intervención. Devuelve un dict que la plataforma
    aplica o ajusta según su política.

    @param risk verdicto de riesgo (LOW/MEDIUM/HIGH/CRITICAL).
    @param stage etapa de captación del LLM (si escaló).
    @param network_risk riesgo de red del actor (NONE/HIGH/CRITICAL).
    @param has_aggressor el SDK detectó un actor que concentra tácticas.
    @param logistics_in_progress hay logística física dirigida (encuentro/traslado).
    @param false_positive el LLM lo marcó como falso positivo.
    """
    risk = (risk or "LOW").upper()
    stage = (stage or "").upper()
    network_risk = (network_risk or "NONE").upper()

    # Falso positivo confirmado: nada.
    if false_positive and network_risk == "NONE" and not has_aggressor:
        return _plan(RECRUITER_ALLOW, [], None,
                     "Sin señales de riesgo real; interacción normal.")

    # Peligro INMINENTE → acción visible + protección fuerte + evidencia.
    # Red organizada confirmada, instrumentalización, o logística física en curso.
    imminent = (
        network_risk == "CRITICAL"
        or stage in IMMINENT_STAGES
        or (risk == "CRITICAL" and logistics_in_progress)
    )
    if imminent:
        protective = [PRESERVE_EVIDENCE, NOTIFY_GUARDIAN, RESTRICT_CONTACT, WARN_MINOR]
        if network_risk == "CRITICAL":
            protective.append(REPORT_AUTHORITY)
        return _plan(
            RECRUITER_HARD_BLOCK, protective, _minor_message(urgent=True),
            "Peligro inminente (instrumentalización, logística en curso o red organizada): "
            "se corta el contacto, se preserva evidencia y se protege al menor.",
        )

    # Riesgo alto pero no inminente → NO tipificar al agresor (evitar oráculo);
    # proteger a la víctima en silencio y avisarle en privado.
    if risk in ("HIGH", "CRITICAL") or network_risk == "HIGH":
        protective = [SHADOW_FLAG, WARN_MINOR]
        if has_aggressor:
            protective.append(RESTRICT_CONTACT)
        return _plan(
            RECRUITER_SILENT, protective, _minor_message(urgent=False),
            "Riesgo alto sin peligro inmediato: se vigila al emisor sin avisarle "
            "(no darle pistas para evadir) y se avisa al menor en privado.",
        )

    # Zona gris (MEDIUM) → vigilancia silenciosa + fricción suave; aún no se avisa
    # al menor para no alarmar sin certeza.
    if risk == "MEDIUM":
        return _plan(
            RECRUITER_SOFT_WARN, [SHADOW_FLAG], None,
            "Zona gris: fricción suave y vigilancia; se escala a revisión sin "
            "alarmar todavía al menor.",
        )

    # LOW
    return _plan(RECRUITER_ALLOW, [], None, "Sin indicios de riesgo.")


def _minor_message(urgent: bool) -> str:
    if urgent:
        return (
            "Esta persona podría estar tratando de involucrarte en algo peligroso. "
            "No vayas a ningún lado ni compartas tu ubicación. " + HELP_RESOURCE
        )
    return (
        "Notamos algo en esta conversación que podría no ser seguro para ti. "
        "No tienes que responder si algo te incomoda. " + HELP_RESOURCE
    )


def _plan(recruiter_action: str, protective: list[str], minor_message: str | None, rationale: str) -> dict:
    return {
        "recruiter_action": recruiter_action,
        "protective_actions": protective,
        "minor_message": minor_message,
        "rationale": rationale,
    }
