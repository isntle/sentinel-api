import json
from groq import Groq
from src.config.settings import GROQ_API_KEY
from src.models.conversation import EscalationRequest

def analyze_conversation(escalation: EscalationRequest):
    categories = escalation.analysis.categories
    triggered_rules = escalation.analysis.triggeredRules
    velocity_flag = escalation.analysis.velocityFlag
    messages = escalation.messages

    conversation_text = "\n".join(f"{msg.user_id}: {msg.content}" for msg in messages)
    velocity_note = (
        "Los mensajes fueron enviados en ráfaga corta (menos de 5 minutos), "
        "lo que sugiere una conversación activa en curso."
        if velocity_flag else ""
    )

    prompt = f"""
Eres un experto en seguridad infantil y protección de menores en México.

Nuestro sistema de detección automática analizó la siguiente conversación
y levantó alertas en estas categorías: {", ".join(categories)}.
Los términos detectados sugieren patrones de: {"; ".join(triggered_rules)}.
{velocity_note}

Analiza los mensajes y determina el nivel de riesgo real para un menor.

RESPONDE SOLO EN JSON con esta estructura exacta:
{{
  "score": <entero 0-100>,
  "risk": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "stage": "NINGUNA" | "CAPTACION" | "INDUCCION/COOPTACION" | "INCUBACION" | "UTILIZACION/INSTRUMENTALIZACION",
  "categories": <lista de categorías de riesgo detectadas>,
  "termsFound": <lista de términos o frases clave encontradas>,
  "ux_recommendation": "NONE" | "SOFT_NUDGE" | "WARNING_OVERLAY" | "SOFT_BLOCK" | "HARD_BLOCK"
}}

Criterios:
- score 0-30 → LOW → NONE o SOFT_NUDGE
- score 31-60 → MEDIUM → WARNING_OVERLAY
- score 61-80 → HIGH → SOFT_BLOCK
- score 81-100 → CRITICAL → HARD_BLOCK

Conversación:
{conversation_text}
"""

    print("GROQ INPUT — categories:", categories)
    print("GROQ INPUT — triggered_rules:", triggered_rules)
    print("GROQ INPUT — velocity_flag:", velocity_flag)
    print("GROQ INPUT — messages:", [(m.user_id, m.content) for m in messages])

    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)
