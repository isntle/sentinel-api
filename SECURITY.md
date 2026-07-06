# Política de Seguridad de Sentinel

Última actualización: 2026-07-06

Sentinel es una infraestructura de detección de riesgos conversacionales para menores de edad. Operamos bajo el principio de privilegio mínimo y retención mínima de datos.

## 1. Arquitectura de Seguridad
- **SDK On-Device**: El 90% del análisis ocurre localmente en el dispositivo del usuario. Las conversaciones benignas NUNCA salen del dispositivo.
- **API Stateless (Casi)**: La API solo recibe sesiones escaladas (riesgo > LOW). No almacenamos PII (Información Personal Identificable).
- **Cifrado**: Todo el tráfico viaja forzosamente por TLS 1.3 (HTTPS).
- **Credenciales**: Todas las API Keys se almacenan utilizando algoritmos de hash criptográfico unidireccional (SHA-256). No es posible recuperar una llave perdida.

## 2. Retención de Datos
Sentinel no es un archivo histórico. 
- Los mensajes recibidos para escalación cognitiva se retienen por un máximo absoluto de **7 días**.
- Existe un job automático de purga (cron) que elimina físicamente de la base de datos cualquier registro con una antigüedad mayor a la permitida.

## 3. Reporte de Vulnerabilidades
Si encuentras una falla de seguridad, por favor contáctanos en `security@sentinel.dev`. No reveles la vulnerabilidad públicamente hasta que haya sido parcheada.
