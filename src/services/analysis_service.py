from google import genai
from src.config.settings import GEMINI_API_KEY
from src.models.conversation import ConversationRequest

client = genai.Client(api_key=GEMINI_API_KEY) # pues aqui le dices que pedo al gemini no? o que jasjjasj jalas la apy de config

def analyze_conversation(conversation: ConversationRequest) -> dict: # importante el dict para la documentacion, le dices a python que esta funcion te va a regresar un diccionario
    messages_text = "\n".join(
        f"{msg.sender}: {msg.text}" for msg in conversation.messages
    )
    #gemini no entiende objetos de python  [{"sender": "extraño", "text": "hola niña"}]
    # esto lo transforma a   "extraño: hola niña"
    # y el "\n" .join(...) pone cada mensaje en su linea
    # no le hagas mucho caso pero aqui jalas la conversacion para hacerla en texto plano

    #platform es si es tito o whasa
    # messages es la conversacion en texto plano
    prompt = f"""
Eres SENTINEL, un sistema experto en detección de riesgo digital para menores en México.

Analiza esta conversación de {conversation.platform}:

{messages_text}

Detecta si hay alguno de estos patrones de riesgo:
- Grooming (manipulación sexual)
- Reclutamiento del crimen organizado
- Presión social o bullying
- Contenido riesgoso

Responde en JSON con este formato:
{{
  "riesgo_detectado": true/false,
  "nivel": "alto/medio/bajo/ninguno",
  "tipo": "nombre del patrón o null",
  "resumen": "explicación breve para el tutor",
  "protocolo": "acción recomendada"
}}
"""
    # aqui se cambiara por el dataset que hayan quedado tu y samuel o no se

    response = client.models.generate_content( #mandas el texto a gemini y espera una respuesta
        model="gemini-2.0-flash", # el modelo, corona, tecate etc...
        contents=prompt
    )
    return response.text #solo extrae la respuesta
