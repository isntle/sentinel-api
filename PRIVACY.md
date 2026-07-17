# Política de Privacidad de Sentinel

Última actualización: 2026-07-17

Esta política describe cómo procesamos la información al utilizar Sentinel API y SDK. Está orientada al cumplimiento de la Ley Federal de Protección de Datos Personales en Posesión de los Particulares (LFPDPPP) en México.

## 1. Datos Recopilados por el SDK (On-Device)
El SDK de Sentinel procesa los mensajes del chat en tiempo real dentro del dispositivo del usuario (Navegador/Móvil). 
- **NO** enviamos el contenido de conversaciones seguras o benignas a ningún servidor externo. Todo el análisis base ocurre fuera de línea.

## 2. Datos Procesados por la API
Cuando el motor local detecta un patrón de riesgo sospechoso (Medium, High, Critical), la sesión se "escala" a la API de Sentinel para análisis cognitivo con Inteligencia Artificial.
- **Datos Escaneados**: En este caso de excepción, recibimos el historial inmediato de la conversación, identificadores de sesión anónimos y el contexto del mensaje.
- **Anonimato**: Prohibimos contractualmente el envío de nombres reales, correos, IPs o identificadores que revelen la identidad directa del menor. Solo aceptamos UUIDs ofuscados.
- **Proveedores cognitivos**: Groq es el proveedor principal. Si falla y el operador configuró una API key de respaldo, la misma conversación saneada puede enviarse a OpenRouter. Ambos caminos pasan por las mismas defensas de delimitación, validación estricta y piso de confianza. Si ninguno responde, Sentinel usa el fallback local.

**[REVISAR CON ABOGADO]** Antes de habilitar OpenRouter con datos reales de menores, revisar y contratar las condiciones de tratamiento, retención, región, subencargados y uso para entrenamiento aplicables al modelo/proveedor seleccionado. La existencia de una variante gratuita no equivale a garantías contractuales de privacidad.

## 3. Retención Temporal
Todo dato escalado a la API tiene una fecha de caducidad de **7 días**. Una vez cumplido el plazo, el texto de las conversaciones y los snapshots temporales de análisis se destruyen permanentemente, salvo la excepción explícita descrita a continuación.

### 3a. Excepción por kit de evidencia solicitado

Una plataforma cliente puede solicitar explícitamente un kit de evidencia para una sesión `HIGH` o `CRITICAL`. Esa acción crea una instantánea canónica con hash SHA-256 y constituye un **legal hold**: el kit queda exento de la purga automática de 7 días para evitar romper su integridad y cadena de custodia.

- La excepción nunca se activa automáticamente; requiere una petición autenticada del mismo cliente que registró el análisis.
- Los datos ordinarios y el registro temporal original siguen purgándose. Solo permanece la instantánea del kit.
- El kit contiene los mensajes y metadatos necesarios para su finalidad legal, por lo que aumenta deliberadamente el tiempo de conservación y debe tener controles de acceso reforzados.
- Sentinel no afirma que un hash sustituya una firma digital, sello de tiempo cualificado o los requisitos probatorios de una autoridad.

**[REVISAR CON ABOGADO]** Antes de ofrecer esta función a clientes reales se debe definir el plazo máximo del legal hold, la base jurídica, el proceso de eliminación a petición, los responsables autorizados y los requisitos de cifrado/registro de acceso aplicables.

## 3b. Señales de Red (Detección de Reclutamiento Organizado)
Para detectar a un mismo actor que contacta a múltiples menores con el mismo guion (patrón de reclutamiento organizado que ninguna sesión aislada revela), la API mantiene "avistamientos de actor" cruzando sesiones. **Privacidad por diseño:**
- **Nunca** se almacena contenido de mensajes ni identificadores en claro.
- Los identificadores de usuario y sesión se guardan solo como hash SHA-256 con una sal secreta del servidor (irreversible).
- El "guion" se guarda como una huella hasheada de su apertura, no como texto.
- Estos avistamientos se purgan automáticamente a los **30 días** (minimización de datos).
- La vista administrativa expone solo agregados hasheados, nunca identidades.

## 4. No Monetización de Datos
No vendemos, rentamos, ni compartimos el contenido de las conversaciones con terceros publicitarios. Tampoco utilizamos conversaciones de tus usuarios para entrenar modelos fundacionales públicos.

[REVISAR CON ABOGADO ANTES DE PUBLICAR EN ENTORNO CORPORATIVO]
