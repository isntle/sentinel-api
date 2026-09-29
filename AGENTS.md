# Sentinel — instrucciones para agentes

El plan vigente desde 2026-09-26 está en `../sentinel-sdk/docs/plan-2026-09/`. Leer primero README, ESTADO y HANDOFF, después solo el prompt elegido. Los planes de julio/agosto son antecedentes. Código actual y resultados medidos prevalecen sobre narrativa histórica.

- Una tarea por sesión; no subagentes ni maratón sin petición expresa. No iniciar implementación por leer este archivo.
- Consultar `codebase-memory-query "consulta concreta" 1200` antes de reexplorar; usar `project-git-status` para inventario. Si no existen, usar Git/rg acotados.
- Preservar cambios previos. SDK y API son repos independientes. No tocar HCKMX26 ni datasets/material de estudio de la raíz. No indexar secretos, .env, dumps ni ignorados.
- Para tareas >60 segundos, usar script existente y terminal persistente visible; registrar comando/cwd/log/estado, terminar turno y reanudar cuando Luis indique que acabó. Nada de polling o agentes esperando.
- No afirmar pruebas ejecutadas o revisión humana si no ocurrieron. Modelo nuevo en sombra por defecto; cambios de acción necesitan evidencia.
- Al cerrar, actualizar tasks.json, ESTADO.md, HANDOFF.md y CHANGELOG.md del plan. DONE requiere evidencia.
- Commits nuevos: autor y committer Luis Merida <tatomerida21@gmail.com>. Antes de push autorizado verificar `gh auth status` con isntle activo y autores/committers; después verificar asociación GitHub. No atribuir commits a IA ni reescribir remoto sin petición explícita.

Si falta el plan al clonar un repo solo, traer el SDK compañero o el paquete del plan. No inventar estado. Para una herramienta que no lee AGENTS automáticamente, usar el prompt compuesto por `sentinel-sdk/scripts/sentinel_plan.py`.
