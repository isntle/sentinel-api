# Auto-calibración segura

El script solo genera una `DatasetVersion` con estado
`calibration_proposed`. Nunca modifica pesos publicados, elimina términos ni
consulta un LLM.

```bash
python scripts/auto_calibrate.py --window-days 90
```

Resultados posibles:

- `insufficient_data`: menos de 50 feedbacks válidos con procedencia.
- `no_adjustments`: hay datos, pero ningún término supera las salvaguardas.
- `proposal_created`: propuesta lista para revisión humana.
- `already_exists`: la misma evidencia y versión ya fueron procesadas.

Antes de aplicar una propuesta, un humano debe revisar en `/admin/review`:

1. diversidad de clientes y concentración máxima;
2. peso anterior y propuesto;
3. tasas balanceadas e intervalo Wilson;
4. benchmark SDK con cero bloqueos falsos y sin caída de recall;
5. red-team adversarial.

No programes el cron para publicar. El cron puede generar propuestas; publicar
siempre es una acción administrativa separada.
