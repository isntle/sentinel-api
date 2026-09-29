# Firma y registro de packs/modelos

Sentinel usa envelopes Ed25519 para autenticar region packs y modelos remotos.
Un hash sin firma solo detectaría corrupción accidental; Ed25519 demuestra que
el artefacto fue emitido por una llave privada controlada por Sentinel.

## Contrato

El servidor serializa el body con JSON canónico (`sort_keys=True`, sin espacios),
firma **esos bytes exactos** y devuelve:

```json
{
  "format": "sentinel.envelope.v1",
  "algorithm": "Ed25519",
  "keyId": "sentinel-artifacts-2026-a",
  "payload": "BASE64URL_DE_LOS_BYTES_JSON",
  "signature": "BASE64URL_DE_LA_FIRMA"
}
```

El payload firmado incluye tipo, ID, versión, fecha de emisión, expiración y el
contenido. El SDK verifica primero la firma y solo después parsea/injecta.

## Configuración de producción

Generar una pareja una sola vez en una terminal segura:

```bash
./venv/bin/python scripts/generate_artifact_signing_key.py
```

- `ARTIFACT_SIGNING_PRIVATE_KEY`: guardar únicamente como secreto de Railway.
- `ARTIFACT_SIGNING_KEY_ID`: ID opaco y versionado de la llave.
- `ARTIFACT_TTL_SECONDS`: 86400 por defecto.
- `SENTINEL_ARTIFACT_PUBLIC_KEY`: distribuir a la configuración del SDK; nunca
  es secreto.

No pegar la llave privada en GitHub Actions, documentación, issues o código.

## Trust store y rotación

El SDK acepta varias llaves públicas simultáneamente por `keyId`. Rotación:

1. Generar nueva pareja.
2. Publicar una versión del SDK/configuración que confíe en llave vieja+nueva.
3. Cambiar la llave privada y `keyId` en Railway.
4. Esperar al menos TTL del artefacto y ventana de actualización de clientes.
5. Retirar la llave pública vieja.

Una llave desconocida, firma inválida, artefacto expirado o versión dinámica
anterior se rechaza sin inyectar términos/modelos.

## Registro de modelos

- `POST /api/v1/models/shadow/stage` valida y guarda un modelo candidato.
- `POST /api/v1/models/shadow/publish/{model_id}` crea una release monotónica.
- `POST /api/v1/models/shadow/rollback/{model_id}` vuelve a un modelo anterior,
  pero crea una release **nueva**; no disminuye el contador.
- `GET /api/v1/models/shadow/current` entrega la release actual firmada.

Separar artefacto de release evita que un rollback administrativo legítimo se
confunda con un replay de red. El historial es append-only.

## Compatibilidad

La API mantiene `data` para SDKs antiguos. Los SDKs nuevos configurados con
`artifactVerification` fallan cerrado por default. `requireSigned: false` solo
existe para migración controlada y no debe usarse en producción.
