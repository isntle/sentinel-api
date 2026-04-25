from google import genai
from datetime import datetime
from src.config.settings import GEMINI_API_KEY
from src.models.conversation import EscalationRequest
from src.models.analysis import SentinelAnalysisResponse

client = genai.Client(api_key=GEMINI_API_KEY)

def analyze_conversation(escalation: EscalationRequest):
    # 1. Preparar el historial de mensajes para la IA
    history_text = "\n".join(
        f"Usuario[{msg.user_id}] ({datetime.fromtimestamp(msg.timestamp).strftime('%H:%M:%S')}): {msg.content}"
        for msg in escalation.messages
    )

    # 2. Preparar el contexto del análisis previo del SDK
    sdk_context = f"""
    EL SDK DETECTÓ LO SIGUIENTE:
    - Score Local: {escalation.analysis.score}
    - Riesgo Inicial: {escalation.analysis.risk}
    - Categorías Disparadas: {', '.join(escalation.analysis.categories)}
    - Reglas MCR: {', '.join(escalation.analysis.triggeredRules)}
    - Alerta de Velocidad: {'SÍ' if escalation.analysis.velocityFlag else 'NO'}
    """

    # 3. El Prompt Maestro (SENTINEL Core)
    prompt = f"""
Eres SENTINEL, un sistema experto en detección de riesgo digital para menores en México (Grooming y Reclutamiento por Crimen Organizado).

CONTEXTO DE LA SESIÓN:
{sdk_context}

HISTORIAL DE CONVERSACIÓN:
{history_text}

TU MISIÓN:
Analiza la intención real detrás de estos mensajes. El SDK ya detectó palabras clave, pero tú debes entender el contexto, la manipulación y la jerga criminal mexicana (como 'el jale', 'mandados', 'plaza', 'familia', etc.).

RESPONDE ESTRICTAMENTE EN FORMATO JSON:
{{
  "status": "success",
  "data": {{
    "risk_score": <entero 0-100>,
    "risk_level": "LOW/MEDIUM/HIGH/CRITICAL",
    "detected_stage": "SAFE / RECRUITMENT_INITIAL / GROOMING_APPROACH / GROOMING_ISOLATION / GROOMING_SEXUALIZATION / HARASSMENT / MANIPULATION",
    "analysis_summary": "<explicación breve de 2 oraciones>",
    "dataset_matches": <lista de términos detectados>,
    "action_protocol": {{
        "ux_recommendation": "NONE / SOFT_NUDGE / WARNING_OVERLAY / SOFT_BLOCK / HARD_BLOCK",
        "parent_instruction": "<qué debe hacer el tutor>",
        "emergency_contact": "088 (Policía Cibernética) / 911 (Emergencias) / SIPINNA (Protección de Menores) / CONADIC (Línea de la Vida) / NONE"
    }}
  }},
  "metadata": {{
    "session_id": "{escalation.messages[0].session_id if escalation.messages else 'unknown'}",
    "processed_at": "{datetime.now().isoformat()}",
    "engine_version": "v2.0-flash"
  }}
}}
"""

    # 4. Llamada a Gemini
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json" # Esto fuerza a que la respuesta sea JSON puro
        }
    )

    # Devolvemos el JSON parseado para que FastAPI lo entregue como objeto
    import json
    return json.loads(response.text)
