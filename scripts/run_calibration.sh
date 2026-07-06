#!/usr/bin/env bash
# run_calibration.sh
# 
# Ejecuta el script de auto-calibración de falsos positivos.
# Puedes añadir este script a tu crontab para que corra cada noche o semana.
# Ejemplo de crontab para correr todos los domingos a las 3 AM:
# 0 3 * * 0 /ruta/absoluta/a/sentinel-api/scripts/run_calibration.sh >> /ruta/absoluta/a/sentinel-api/calibration.log 2>&1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "==============================================="
echo "Ejecutando auto-calibración en: $(date)"
echo "==============================================="

cd "$ROOT_DIR" || exit 1

# Asegúrate de usar el entorno virtual si existe
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

python scripts/auto_calibrate.py

echo "==============================================="
echo "Terminado en: $(date)"
echo "==============================================="
