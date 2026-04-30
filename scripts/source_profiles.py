"""Source metadata helpers for exam normalization."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE_PROFILE_PATH = ROOT / "config" / "source_profiles.yaml"


@lru_cache(maxsize=1)
def load_source_profiles() -> dict[str, dict[str, Any]]:
    with open(SOURCE_PROFILE_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources", {})


def detect_source_profile(exam_id: str) -> dict[str, Any]:
    profiles = load_source_profiles()
    for source_type, profile in profiles.items():
        if source_type == "Unknown":
            continue
        for prefix in profile.get("prefixes", []):
            if exam_id.startswith(prefix):
                return {"source_type": source_type, **profile}
    fallback = profiles.get("Unknown", {})
    return {"source_type": "Unknown", **fallback}
