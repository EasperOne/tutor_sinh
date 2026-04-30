"""Validation and enrichment helpers for classify.json files."""
from __future__ import annotations

from collections import Counter
from typing import Any

CHAPTER_CODES = {
    "DT_PT", "DT_TB", "CH_TV", "CH_DV", "DT_BD", "QL_DT",
    "DT_QT", "DT_HP", "UD_DT", "TH", "ST_MT",
}
MUC_DO_VALUES = {"B", "H", "VD"}
COMPETENCY_VALUES = {"recall", "understand", "interpret", "apply", "calculate", "experiment"}
CALCULATION_LOAD_VALUES = {"none", "light", "medium", "heavy"}
BO_GD_FIT_VALUES = {"high", "medium", "low"}


def validate_classifications(
    classifications: list[dict[str, Any]],
    *,
    strict_new_fields: bool = False,
) -> dict[str, list[str]]:
    """Return validation errors/warnings. Legacy files warn on missing new fields."""
    errors: list[str] = []
    warnings: list[str] = []
    counts = Counter(c.get("phan") for c in classifications)

    expected = {"P1": 18, "P2": 16, "P3": 6}
    if len(classifications) != 40:
        errors.append(f"total item count is {len(classifications)}, expected 40")
    for phan, expected_count in expected.items():
        if counts.get(phan, 0) != expected_count:
            errors.append(f"{phan} count is {counts.get(phan, 0)}, expected {expected_count}")

    seen: set[tuple[str, int, str]] = set()
    for idx, item in enumerate(classifications, 1):
        loc = _loc(item, idx)
        phan = item.get("phan")
        stt = item.get("stt")
        y = item.get("y")

        if phan not in expected:
            errors.append(f"{loc}: invalid phan {phan!r}")
        if not isinstance(stt, int):
            errors.append(f"{loc}: stt must be an integer")
        if phan == "P2":
            if y not in {"a", "b", "c", "d"}:
                errors.append(f"{loc}: P2 item must have y in a/b/c/d")
        elif y not in (None, ""):
            errors.append(f"{loc}: non-P2 item must not have y")

        key = (str(phan), int(stt) if isinstance(stt, int) else -1, str(y or ""))
        if key in seen:
            errors.append(f"{loc}: duplicate item key {key}")
        seen.add(key)

        if item.get("chuong") not in CHAPTER_CODES:
            errors.append(f"{loc}: invalid chuong {item.get('chuong')!r}")
        if item.get("muc_do") not in MUC_DO_VALUES:
            errors.append(f"{loc}: invalid muc_do {item.get('muc_do')!r}")

        _validate_new_field(item, "skill", str, loc, errors, warnings, strict_new_fields)
        _validate_enum(item, "competency", COMPETENCY_VALUES, loc, errors, warnings, strict_new_fields)
        _validate_enum(item, "calculation_load", CALCULATION_LOAD_VALUES, loc, errors, warnings, strict_new_fields)
        _validate_enum(item, "bo_gd_fit", BO_GD_FIT_VALUES, loc, errors, warnings, strict_new_fields)

        confidence = item.get("confidence")
        if confidence is None:
            (errors if strict_new_fields else warnings).append(f"{loc}: missing confidence")
        elif not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            errors.append(f"{loc}: confidence must be a number from 0.0 to 1.0")
        elif confidence < 0.7:
            warnings.append(f"{loc}: low confidence {confidence}")

        if item.get("skill") == "unknown":
            warnings.append(f"{loc}: skill is unknown")
        if item.get("bo_gd_fit") == "low":
            warnings.append(f"{loc}: low BoGD fit")
        if item.get("calculation_load") == "heavy":
            warnings.append(f"{loc}: heavy calculation load")

    return {"errors": errors, "warnings": warnings}


def summarize_classification_style(classifications: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "skill_counts": dict(Counter(c.get("skill", "unknown") for c in classifications)),
        "competency_counts": dict(Counter(c.get("competency", "unknown") for c in classifications)),
        "calculation_load_counts": dict(Counter(c.get("calculation_load", "unknown") for c in classifications)),
        "bo_gd_fit_counts": dict(Counter(c.get("bo_gd_fit", "unknown") for c in classifications)),
        "low_confidence_count": sum(1 for c in classifications if float(c.get("confidence") or 1.0) < 0.7),
    }


def _loc(item: dict[str, Any], idx: int) -> str:
    phan = item.get("phan", "?")
    stt = item.get("stt", "?")
    y = item.get("y")
    return f"item {idx} ({phan}.{stt}{'.' + y if y else ''})"


def _validate_new_field(
    item: dict[str, Any],
    field: str,
    typ: type,
    loc: str,
    errors: list[str],
    warnings: list[str],
    strict: bool,
) -> None:
    value = item.get(field)
    if value is None:
        (errors if strict else warnings).append(f"{loc}: missing {field}")
    elif not isinstance(value, typ) or (typ is str and not value.strip()):
        errors.append(f"{loc}: invalid {field}")


def _validate_enum(
    item: dict[str, Any],
    field: str,
    allowed: set[str],
    loc: str,
    errors: list[str],
    warnings: list[str],
    strict: bool,
) -> None:
    value = item.get(field)
    if value is None:
        (errors if strict else warnings).append(f"{loc}: missing {field}")
    elif value not in allowed:
        errors.append(f"{loc}: invalid {field} {value!r}")
