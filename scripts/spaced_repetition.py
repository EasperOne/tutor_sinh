"""
Priority scoring for review set generation using spaced repetition heuristics.
"""
from __future__ import annotations
from datetime import date, datetime


def _parse_date(d: str | date) -> date:
    if isinstance(d, date):
        return d
    return datetime.fromisoformat(str(d)).date()


def compute_priority(item: dict, today: date) -> int:
    """
    item keys: on_tap_status, last_wrong_date, wrong_count, muc_do, sai_ngu
    Returns int 0–100.
    """
    base = 50

    status = item.get("on_tap_status", "not_yet")
    if status == "redo":
        base += 30
    elif status == "not_yet":
        base += 15
    elif status == "pass":
        base -= 20

    try:
        days_ago = (today - _parse_date(item["last_wrong_date"])).days
    except (KeyError, TypeError, ValueError):
        days_ago = 999
    if days_ago <= 3:
        base += 20
    elif days_ago <= 7:
        base += 10
    elif days_ago <= 14:
        base += 5
    elif days_ago > 30:
        base -= 10

    base += min(int(item.get("wrong_count", 1)) * 5, 20)

    muc_do = item.get("muc_do", "")
    if muc_do == "VD":
        base += 10
    elif muc_do == "H":
        base += 5

    if item.get("sai_ngu"):
        base -= 15

    return max(0, min(100, base))


def compute_priorities(wrong_history: list[dict], today: date | None = None) -> list[dict]:
    """
    Takes a list of wrong-answer history dicts, adds 'priority' field, returns sorted desc.
    """
    if today is None:
        today = date.today()
    result = []
    for item in wrong_history:
        enriched = dict(item)
        enriched["priority"] = compute_priority(item, today)
        result.append(enriched)
    result.sort(key=lambda x: x["priority"], reverse=True)
    return result


def suggest_review_set(
    wrong_history: list[dict],
    today: date | None = None,
    target_count: int = 20,
    min_priority: int = 40,
    chapters: list[str] | None = None,
    muc_do_filter: list[str] | None = None,
) -> list[dict]:
    """
    Filter and rank wrong history, return top target_count items.
    Excludes items that have been marked as 'pass' (already reviewed successfully).
    """
    if today is None:
        today = date.today()

    ranked = compute_priorities(wrong_history, today)

    filtered = []
    for item in ranked:
        # Skip items already marked as pass - they've been reviewed
        if item.get("on_tap_status") == "pass":
            continue
        if item["priority"] < min_priority:
            continue
        if chapters and item.get("chuong") not in chapters:
            continue
        if muc_do_filter and item.get("muc_do") not in muc_do_filter:
            continue
        filtered.append(item)

    return filtered[:target_count]


if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table
    console = Console()

    sample = [
        {"question_id": 1, "exam_id": "de_001", "phan": "P1", "stt": 7, "y": None,
         "chuong": "QL_DT", "muc_do": "VD", "sai_ngu": False,
         "on_tap_status": "redo", "last_wrong_date": "2026-04-25", "wrong_count": 3},
        {"question_id": 2, "exam_id": "de_001", "phan": "P2", "stt": 2, "y": "c",
         "chuong": "DT_HP", "muc_do": "H", "sai_ngu": True,
         "on_tap_status": "not_yet", "last_wrong_date": "2026-04-20", "wrong_count": 2},
        {"question_id": 3, "exam_id": "de_002", "phan": "P3", "stt": 5, "y": None,
         "chuong": "ST_MT", "muc_do": "B", "sai_ngu": False,
         "on_tap_status": "pass", "last_wrong_date": "2026-03-10", "wrong_count": 1},
    ]
    results = suggest_review_set(sample, target_count=10)
    t = Table(title="Review Set")
    t.add_column("Priority"); t.add_column("ID"); t.add_column("Chương"); t.add_column("Status")
    for r in results:
        t.add_row(str(r["priority"]), f"{r['phan']}·{r['stt']}", r["chuong"], r["on_tap_status"])
    console.print(t)
