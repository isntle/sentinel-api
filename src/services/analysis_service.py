import json
from groq import Groq
from src.config.settings import GROQ_API_KEY
from src.models.conversation import EscalationRequest

UX_LEVELS = ["NONE", "SOFT_NUDGE", "WARNING_OVERLAY", "SOFT_BLOCK", "HARD_BLOCK"]


def _bump_ux(level: str) -> str:
    idx = UX_LEVELS.index(level) if level in UX_LEVELS else 0
    return UX_LEVELS[min(idx + 1, len(UX_LEVELS) - 1)]


def _fallback_from_sdk(escalation: EscalationRequest, reason: str) -> dict:
    """
    Cierra el circuito cuando la IA no está disponible.
    Construye una respuesta segura usando los datos del SDK (score, capas, velocityFlag).
    """
    score = escalation.score
    v3 = escalation.layers.v3
    v4 = escalation.layers.v4

    has_explicit = bool(v4.explicitSignals)
    has_lexical = bool(v3.categories) or bool(v3.terms)

    if score >= 85 or (has_explicit and score >= 70):
        ux = "HARD_BLOCK"
        stage = "UTILIZACION/INSTRUMENTALIZACION"
        confidence = 0.75
        false_positive = False
        summary = "Lo que está pasando aquí es muy peligroso para ti. Aléjate de esta conversación y cuéntale ahora mismo a un adulto de confianza."
    elif score >= 70:
        ux = "SOFT_BLOCK"
        stage = "INCUBACION"
        confidence = 0.65
        false_positive = False
        summary = "Esta persona te está presionando para algo que puede hacerte daño. Mejor no sigas y busca a alguien de confianza para contarle."
    elif score >= 50:
        ux = "WARNING_OVERLAY"
        stage = "INDUCCION/COOPTACION"
        confidence = 0.55
        false_positive = False
        summary = "Ten cuidado con esta conversación: parece que quieren convencerte de algo riesgoso. Si te sientes incómodo, no respondas y habla con alguien que te cuide."
    elif score >= 30 or has_lexical or has_explicit:
        ux = "SOFT_NUDGE"
        stage = "CAPTACION"
        confidence = 0.45
        false_positive = False
        summary = "Esta persona podría estar ofreciéndote algo que parece bueno, pero puede ser una trampa. Tómate tu tiempo y cuéntaselo a alguien que te cuide."
    else:
        ux = "NONE"
        stage = "NINGUNA"
        confidence = 0.3
        false_positive = True
        summary = "Todo parece estar bien por ahora. Sigue cuidándote y habla con alguien de confianza si algo te incomoda."

    if escalation.velocityFlag and ux != "NONE":
        ux = _bump_ux(ux)

    return {
        "ux_recommendation": ux,
        "stage": stage,
        "confidence": confidence,
        "summary": summary,
        "false_positive": false_positive,
        "fallback": True,
        "fallback_reason": reason,
    }


def analyze_conversation(escalation: EscalationRequest):
    v3 = escalation.layers.v3
    v4 = escalation.layers.v4
    normalizer = escalation.layers.normalizer

    conversation_text = "\n".join(
        f"{msg.user_id}: {msg.content}" for msg in escalation.messages
    )

    velocity_note = (
        "Los mensajes fueron enviados en ráfaga corta (ventana de actividad alta), "
        "lo que indica contacto intensivo y sostenido con el menor."
        if escalation.velocityFlag else ""
    )

    evasion_note = (
        f"El texto presenta transformaciones de evasión ({', '.join(normalizer.transformations)}), "
        "lo que indica intención deliberada de ocultar el contenido."
        if normalizer.transformations else ""
    )

    prompt = f"""
Eres un experto en seguridad infantil y prevención del reclutamiento de menores por parte del crimen organizado en México.

El sistema de detección analizó esta conversación y encontró lo siguiente:

SCORE GLOBAL DE RIESGO: {escalation.score}/100 ({escalation.risk})

CAPA LÉXICA (v3):
- Score: {v3.score}/100
- Categorías detectadas: {", ".join(v3.categories) if v3.categories else "ninguna"}
- Términos clave: {", ".join(v3.terms) if v3.terms else "ninguno"}
- Reglas activadas: {", ".join(v3.triggeredRules) if v3.triggeredRules else "ninguna"}

CAPA DE SEÑALES EXPLÍCITAS (v4):
- Score: {v4.score}/100
- Señales explícitas: {", ".join(v4.explicitSignals) if v4.explicitSignals else "ninguna"}
- Features: {", ".join(v4.features) if v4.features else "ninguna"}
- Reglas activadas: {", ".join(v4.triggeredRules) if v4.triggeredRules else "ninguna"}

CAPA DE NORMALIZACIÓN:
- Score: {normalizer.score}/100
- Features: {", ".join(normalizer.features) if normalizer.features else "ninguna"}
{evasion_note}

{velocity_note}

Categorías únicas del análisis: {", ".join(escalation.uniqueCategories) if escalation.uniqueCategories else "ninguna"}
Mensajes analizados: {escalation.messagesAnalyzed}

CONVERSACIÓN:
{conversation_text}

Tu tarea es determinar si esta conversación corresponde a un proceso de reclutamiento de menores por parte del crimen organizado (narcotráfico, pandillas, grupos delictivos).

Las etapas del proceso son:
- NINGUNA: Sin señales de reclutamiento
- CAPTACION: Primer contacto, oferta de dinero fácil, promesas, halago al menor
- INDUCCION/COOPTACION: Normalización del crimen, presión social, pruebas de lealtad
- INCUBACION: El menor ya tiene tareas asignadas, hay dependencia económica o amenaza
- UTILIZACION/INSTRUMENTALIZACION: El menor está siendo usado activamente (halconeo, distribución, sicariato)

IMPORTANTE: Si las tres capas tienen scores bajos y los términos son ambiguos o de contexto común (música, slang juvenil sin contexto delictivo), marca como false_positive: true.
Si v4 tiene señales explícitas de reclutamiento y v3 confirma terminología delictiva, la confianza sube.

RESPONDE SOLO EN JSON con esta estructura exacta:
{{
  "ux_recommendation": "NONE" | "SOFT_NUDGE" | "WARNING_OVERLAY" | "SOFT_BLOCK" | "HARD_BLOCK",
  "stage": "NINGUNA" | "CAPTACION" | "INDUCCION/COOPTACION" | "INCUBACION" | "UTILIZACION/INSTRUMENTALIZACION",
  "confidence": <número entre 0.0 y 1.0>,
  "summary": "<mensaje corto y claro dirigido directamente al usuario final (puede ser un niño o un adulto). Reglas obligatorias: 1) Habla en segundo persona ('tú'), de forma cálida y cercana. 2) Lenguaje muy simple, frases cortas, palabras comunes — debe entenderlo un niño de 10 años. 3) NO menciones que hubo un análisis ni que un sistema lo revisó. 4) Explica en términos humanos qué está pasando y qué puede hacer la persona (por ejemplo: 'esta persona te está ofreciendo dinero a cambio de algo que puede ser peligroso, mejor cuéntale a alguien de confianza'). 5) Si es false_positive, tranquiliza con un mensaje breve y amable. 6) Máximo 2 oraciones.>",
  "false_positive": <true | false>
}}

Criterios de ux_recommendation:
- NINGUNA + confianza baja → NONE
- CAPTACION → SOFT_NUDGE o WARNING_OVERLAY según confianza
- INDUCCION/COOPTACION → WARNING_OVERLAY o SOFT_BLOCK
- INCUBACION → SOFT_BLOCK
- UTILIZACION/INSTRUMENTALIZACION → HARD_BLOCK
- velocityFlag activo sube un nivel de recomendación
"""

    if not GROQ_API_KEY:
        return _fallback_from_sdk(escalation, "GROQ_API_KEY no configurada")

    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError as exc:
        return _fallback_from_sdk(escalation, f"Respuesta de IA inválida: {exc}")
    except Exception as exc:
        return _fallback_from_sdk(escalation, f"IA no disponible: {exc}")
