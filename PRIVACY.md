# Política de Privacidad de Sentinel

Última actualización: 2026-07-06

Esta política describe cómo procesamos la información al utilizar Sentinel API y SDK. Está orientada al cumplimiento de la Ley Federal de Protección de Datos Personales en Posesión de los Particulares (LFPDPPP) en México.

## 1. Datos Recopilados por el SDK (On-Device)
El SDK de Sentinel procesa los mensajes del chat en tiempo real dentro del dispositivo del usuario (Navegador/Móvil). 
- **NO** enviamos el contenido de conversaciones seguras o benignas a ningún servidor externo. Todo el análisis base ocurre fuera de línea.

## 2. Datos Procesados por la API
Cuando el motor local detecta un patrón de riesgo sospechoso (Medium, High, Critical), la sesión se "escala" a la API de Sentinel para análisis cognitivo con Inteligencia Artificial.
- **Datos Escaneados**: En este caso de excepción, recibimos el historial inmediato de la conversación, identificadores de sesión anónimos y el contexto del mensaje.
- **Anonimato**: Prohibimos contractualmente el envío de nombres reales, correos, IPs o identificadores que revelen la identidad directa del menor. Solo aceptamos UUIDs ofuscados.

## 3. Retención Temporal
Todo dato escalado a la API tiene una fecha de caducidad inamovible de **7 días**. Una vez cumplido el plazo, el texto de las conversaciones se destruye permanentemente.

## 4. No Monetización de Datos
No vendemos, rentamos, ni compartimos el contenido de las conversaciones con terceros publicitarios. Tampoco utilizamos conversaciones de tus usuarios para entrenar modelos fundacionales públicos.

[REVISAR CON ABOGADO ANTES DE PUBLICAR EN ENTORNO CORPORATIVO]
