# Auto-calibración segura de pesos con feedback real

Estado: `IMPLEMENTADA EN MODO PROPUESTA — NO AUTO-PUBLICA`  
Fecha: 2026-07-17

## Decisión de esta ronda

La base configurada localmente (`sqlite:///./sentinel.db`) contiene **8** filas
de feedback: 7 `false_positive`, 1 `confirmed`, 0 `false_negative`. Las ocho
incluyen algún término, para un total de 9 observaciones. El campo declarativo
`reported_by` tiene dos valores, pero uno concentra 87.5% y no es una identidad
confiable porque lo envía el propio cliente.

Esto está muy por debajo del mínimo operativo de 50 reportes y no permite
estimar tasas por término, por cliente ni por periodo. El algoritmo y el job sí
quedaron construidos, pero responden `insufficient_data` y no generan ni aplican
ajustes con esta evidencia. Esta medición corresponde a la base local; no
demuestra cuántos registros existen en el Postgres de Railway.

## Prerrequisitos de datos

Prerrequisitos ya implementados para feedback nuevo:

1. `Feedback` debe guardar `api_key_hash`, obtenido de la dependencia de
   autenticación y nunca del body. `reported_by` no puede usarse como cliente.
2. El endpoint acepta IDs editoriales/UUID validados, no términos libres ni
   texto de mensajes. La calibración ignora IDs que no correspondan a un
   `HotTerm` dinámico aprobado.
3. El endpoint deduplica reintentos por una huella canónica autenticada.
4. Se registra la versión del dataset que produjo el veredicto. Un reporte sobre
   un peso viejo no debe mezclarse silenciosamente con la versión actual.
5. Reunir al menos 50 reportes válidos globales y suficiente evidencia por
   término según los umbrales siguientes.

## Unidad de análisis y defensa contra manipulación

El volumen bruto nunca es un voto. Para cada término y ventana móvil de 90 días:

- máximo un reporte por sesión y cliente;
- máximo cinco sesiones con peso estadístico por cliente y término;
- mínimo 15 sesiones deduplicadas;
- mínimo tres API keys de organizaciones distintas;
- ninguna organización puede aportar más del 40% de la evidencia efectiva;
- mínimo 10 falsos positivos para proponer reducción;
- tasa de FP balanceada por cliente ≥70%;
- límite inferior de Wilson al 95% para la tasa de FP ≥50%;
- si existen confirmaciones, al menos dos clientes deben seguir coincidiendo en
  que el término es problemático.

Un cliente que envíe cientos de reportes desde una sola API key queda limitado
a cinco observaciones y no satisface diversidad. El job registra el intento en
su resumen, pero no propone ajuste.

## Regla de ajuste propuesta

Para pesos dinámicos de `HotTerm`:

- FP con todos los umbrales: reducir `min(2 puntos, 10% del peso redondeado)`,
  como máximo una vez por versión publicada.
- Confirmados consistentes: no cambiar; sirven como evidencia contraria.
- Falsos negativos: solo proponer aumento si el término ya estaba presente en
  el veredicto y se cumplen los mismos requisitos de diversidad; aumento máximo
  de 1 punto o 10%, con techo 15.
- Piso absoluto: 1.
- Piso relativo: nunca bajar automáticamente de 50% del peso con el que el
  término entró al dataset.
- Peso cero o eliminación: jamás automático. Se crea una propuesta `staged`
  para decisión humana.

Los términos del pack estático V3 no viven actualmente como filas editables de
`HotTerm`. Para ellos el job solo puede generar una propuesta auditada; cambiar
el JSON requiere una nueva versión del pack, benchmark y release del SDK.

## Versionado, auditoría e idempotencia

Extender el patrón existente de `DatasetVersion`, no crear un historial paralelo:

- `base_version`: versión publicada de partida;
- `status`: `calibration_proposed`, `published` o `rejected`;
- `calibration_run_id`: SHA-256 de versión base + ventana + IDs de feedback
  deduplicados;
- `terms_snapshot`: snapshot completo propuesto;
- `audit_json`: por término, peso anterior/nuevo, conteos efectivos, clientes,
  tasas, intervalo Wilson y razón de exclusión o ajuste.

`calibration_run_id` debe ser único. Ejecutar dos veces contra la misma versión
y los mismos reportes devuelve la propuesta existente y no duplica cambios.

El script es `scripts/auto_calibrate.py`, separado de requests:

1. carga y valida feedback;
2. deduplica y limita contribución por cliente;
3. genera propuestas, nunca modifica la versión publicada;
4. guarda una `DatasetVersion` con estado `calibration_proposed`.

El benchmark y red-team siguen siendo una compuerta humana antes de aplicar,
porque los pesos dinámicos viven en la API y el corpus/runner viven en el repo
SDK. Automatizar esa validación cross-repo sin un artefacto versionado común
crearía una falsa garantía. El dashboard exige confirmar esa revisión.

## Revisión humana futura

El dashboard debe mostrar peso anterior/nuevo, número de clientes, distribución
FP/confirmado/FN, intervalo de confianza y efecto exacto en benchmark. El humano
puede aprobar la versión completa o rechazarla; no debe existir un botón que
publique automáticamente desde el cron.

Uso del script:

```bash
# Solo genera propuesta
python scripts/auto_calibrate.py --window-days 90

# El humano revisa en /admin/review y publica desde el flujo versionado.
```

## Criterio para producir la primera propuesta real

El job empezará a proponer cuando el Postgres que realmente recibe feedback tenga ≥50 reportes
válidos, `api_key_hash` y `dataset_version` estén persistidos, y al menos algunos
términos alcancen tres clientes distintos. Tener 50 filas de un solo cliente no
cumple el criterio.
