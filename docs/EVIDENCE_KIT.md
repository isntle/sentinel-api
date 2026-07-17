# Kit de evidencia verificable

## Objetivo y límite probatorio

El kit conserva una instantánea de una sesión `HIGH` o `CRITICAL` y permite
detectar cualquier modificación posterior a su generación mediante SHA-256. No
afirma por sí solo quién escribió los mensajes ni demuestra que la plataforma
cliente no los alteró antes de enviarlos a Sentinel.

**[REVISAR CON ABOGADO]** La admisibilidad, firma electrónica, sellado de tiempo,
identificación de responsables y formato de denuncia dependen de la jurisdicción
y de los procedimientos de la autoridad receptora. SHA-256 aporta integridad,
pero no sustituye una firma digital cualificada ni un sello de tiempo de un
tercero confiable.

## Cuándo se puede generar

- La API debe haber recibido y persistido previamente un análisis cuyo riesgo
  local sea `HIGH` o `CRITICAL`.
- La API key solicitante debe ser la misma que registró el análisis. Una key de
  otro cliente no puede enumerar ni exportar la sesión.
- `POST /api/v1/evidence/{session_id}` crea una instantánea inmutable del análisis
  más reciente que cumpla esas condiciones. Una segunda llamada devuelve el
  mismo kit; no recalcula una evidencia distinta silenciosamente.
- Un análisis posterior de la misma sesión puede producir un kit adicional,
  enlazado a su propio `analysis_record_id`.

## Contenido exacto

La respuesta contiene:

```json
{
  "payload": {
    "schema_version": "1.0",
    "evidence_id": "UUID",
    "analysis_record_id": "UUID",
    "session_id": "identificador seudónimo recibido",
    "generated_at": 1750000000,
    "analysis_recorded_at": 1749999990,
    "messages": [
      {
        "id": "UUID",
        "user_id": "identificador seudónimo",
        "session_id": "identificador seudónimo",
        "content": "texto original",
        "timestamp": 1749999900,
        "source": "text"
      }
    ],
    "engine_result": {
      "score": 80,
      "risk": "CRITICAL",
      "escalate": true,
      "layers": {
        "normalizer": {},
        "v3": {},
        "v4": {},
        "temporal": {},
        "actor": {}
      },
      "velocityFlag": false,
      "velocityWindow": 0,
      "messagesAnalyzed": 1,
      "uniqueCategories": [],
      "ageBand": null,
      "escalationReason": null
    },
    "llm_verdict": {},
    "dataset_versions": {
      "sdk_region_packs": {"MX": "3.x"},
      "api_hot_terms": {"version": 4, "created_at": 1749900000}
    },
    "retention": {
      "explicit_legal_hold": true,
      "normal_automatic_purge_exempt": true
    }
  },
  "integrity": {
    "algorithm": "SHA-256",
    "canonicalization": "json.dumps(sort_keys=True,separators=(',', ':'),ensure_ascii=False)",
    "content_hash": "64 caracteres hexadecimales"
  }
}
```

`engine_result.layers` conserva exactamente lo recibido del SDK: normalización,
V3, V4, progresión temporal y asimetría de actor. `llm_verdict` contiene el
veredicto validado y con piso de confianza aplicado, o el fallback local marcado
con `_llm_unavailable` si ambos proveedores fallaron.

Los mensajes se ordenan por `timestamp` y después por `id`, sin cambiar sus
timestamps originales. `source` distingue texto escrito de una transcripción de
voz cuando el SDK lo reporta.

`dataset_versions` separa las versiones de region packs usadas por el SDK y la
última versión publicada de hot terms que el SDK declaró haber cargado. Los SDK
anteriores pueden reportar `null`; el kit lo conserva como “no reportado” en vez
de inferir una versión que quizá no fue usada.

## Canonicalización y verificación

El hash se calcula únicamente sobre el objeto `payload`; `integrity` queda fuera
porque un hash no puede contenerse a sí mismo. La representación canónica es:

```python
canonical = json.dumps(
    package["payload"],
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
).encode("utf-8")
calculated = hashlib.sha256(canonical).hexdigest()
assert calculated == package["integrity"]["content_hash"]
```

No se debe reordenar `messages`: los arrays conservan orden en JSON y ese orden
forma parte del contenido protegido.

## Uso desde una plataforma cliente

1. Conservar el `session_id` seudónimo asociado al incidente.
2. Solicitar el kit mientras el análisis original siga dentro de sus siete días:

   ```bash
   curl -X POST \
     -H "X-API-Key: $SENTINEL_API_KEY" \
     "https://<host>/api/v1/evidence/<session_id>" \
     -o evidence.json
   ```

3. Recalcular el hash con el procedimiento anterior antes de transferirlo.
4. Registrar internamente quién solicitó, descargó, entregó o copió el archivo.
5. Entregarlo por el canal indicado por Policía Cibernética, 088 o Te Protejo.

**[REVISAR CON ABOGADO]** Definir con asesoría legal si también deben adjuntarse
bitácoras de acceso, declaración del custodio, firma de la plataforma, sello de
tiempo externo, formato PDF, metadatos del dispositivo o una copia forense del
origen. El endpoint no inventa esos elementos.

## Retención y eliminación

Los análisis ordinarios y sus mensajes siguen sujetos a purga automática a los
siete días. La creación explícita del kit constituye un `legal hold`: la
instantánea canónica queda fuera de esa purga para preservar su hash.

Esta excepción no equivale a retención indefinida obligatoria. La eliminación a
petición, el plazo máximo del legal hold, la autorización para levantarlo y el
registro de destrucción requieren una política operativa adicional.

**[REVISAR CON ABOGADO]** Antes de uso con clientes reales, fijar plazo máximo,
base legal, responsables, control de acceso, cifrado de respaldos y proceso de
eliminación segura de evidencia.
