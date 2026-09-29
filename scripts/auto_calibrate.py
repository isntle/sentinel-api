"""Genera una propuesta versionada; nunca modifica pesos publicados."""
import argparse
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import SessionLocal
from src.services.calibration_service import generate_calibration_proposal


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a safe weight calibration proposal")
    parser.add_argument("--window-days", type=int, default=90)
    args = parser.parse_args()
    if args.window_days < 1 or args.window_days > 365:
        parser.error("--window-days must be between 1 and 365")

    with SessionLocal() as db:
        result = generate_calibration_proposal(db, window_days=args.window_days)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
