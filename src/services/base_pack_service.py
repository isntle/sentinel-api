import json
from functools import lru_cache
from pathlib import Path

BASE_PACK_PATH = (
    Path(__file__).resolve().parents[1]
    / "constants"
    / "sentinel_dataset_v3_base_pack.json"
)


@lru_cache(maxsize=1)
def load_base_pack() -> dict:
    with BASE_PACK_PATH.open(encoding="utf-8") as source:
        payload = json.load(source)
    terms = payload.get("terms")
    if payload.get("pack_id") != "MX" or not isinstance(terms, list):
        raise RuntimeError("Invalid Sentinel MX base pack")
    return payload
