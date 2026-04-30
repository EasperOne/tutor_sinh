"""
Analytics module for tutor-sinh.

All public functions accept a sqlite3.Connection and return JSON-serializable
dicts or lists. Queries use parameterized statements only.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml

from scripts.source_profiles import detect_source_profile

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "ma_tran_chuan.yaml"

_CHAPTER_NAMES = {
    "DT_PT": "Di truyền cấp phân tử",
    "DT_TB": "Di truyền cấp tế bào",
    "CH_TV": "Chuyển hoá VC&NL ở thực vật",
    "CH_DV": "Chuyển hoá VC&NL ở động vật",
    "DT_BD": "Di truyền & biến dị cấp PT và TB",
    "QL_DT": "Quy luật di truyền",
    "DT_QT": "Di truyền quần thể",
    "DT_HP": "Di truyền học người & liệu pháp gene",
    "UD_DT": "Ứng dụng di truyền học",
    "TH":    "Tiến hoá",
    "ST_MT": "Sinh thái học và môi trường",
}

# Per Sinh 2025: correct sub-item count → score for that P2 question
_P2_SCORE = {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0}


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _linear_slope(values: list[float]) -> float:
    """Least-squares slope for y = f(index), no external deps."""
    n = len(values)
    if n < 2:
        return 0.0
    sx = n * (n - 1) / 2
    sy = sum(values)
    sxy = sum(i * v for i, v in enumerate(values))
    sx2 = n * (n - 1) * (2 * n - 1) / 6
    denom = n * sx2 - sx ** 2
    return (n * sxy - sx * sy) / denom if denom else 0.0


def _last_n_session_ids(conn: sqlite3.Connection, n: int) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM sessions ORDER BY session_date DESC, id DESC LIMIT ?", (n,)
    ).fetchall()
    return [r[0] for r in rows]


# ── Tier 1: Score & Trend ─────────────────────────────────────────────────────

def session_score(session_id: int, conn: sqlite3.Connection) -> float:
    """
    Calculate session score per Sinh 2025 rules.

    P1: 18 questions × 0.25đ each (max 4.5đ)
    P3:  6 questions × 0.25đ each (max 1.5đ)
    P2:  4 questions, scored by correct sub-item count:
         0→0đ  1→0.1đ  2→0.25đ  3→0.5đ  4→1.0đ  (max 4.0đ)
    Total max: 10đ
    """
    wrong_p1 = conn.execute(
        "SELECT COUNT(*) FROM wrong_answers WHERE session_id=? AND phan='P1'",
        (session_id,),
    ).fetchone()[0]
    wrong_p3 = conn.execute(
        "SELECT COUNT(*) FROM wrong_answers WHERE session_id=? AND phan='P3'",
        (session_id,),
    ).fetchone()[0]

    p2_rows = conn.execute(
        "SELECT stt, COUNT(*) FROM wrong_answers WHERE session_id=? AND phan='P2' GROUP BY stt",
        (session_id,),
    ).fetchall()
    wrong_by_stt = {r[0]: r[1] for r in p2_rows}

    p2_score = sum(_P2_SCORE.get(4 - wrong_by_stt.get(stt, 0), 0.0) for stt in range(1, 5))
    total = (18 - wrong_p1) * 0.25 + (6 - wrong_p3) * 0.25 + p2_score
    return round(min(total, 10.0), 2)


def recalculate_all_scores(conn: sqlite3.Connection) -> int:
    """Backfill score column for every session. Returns count of sessions updated."""
    ids = [r[0] for r in conn.execute("SELECT id FROM sessions").fetchall()]
    for sid in ids:
        conn.execute("UPDATE sessions SET score=? WHERE id=?", (session_score(sid, conn), sid))
    conn.commit()
    return len(ids)


def score_trend(conn: sqlite3.Connection, last_n: int = 8) -> list[dict]:
    """
    Return last N sessions with computed scores in chronological order.
    Recalculates score on-the-fly if session.score is NULL.
    """
    rows = conn.execute(
        "SELECT id, session_date, exam_id, score FROM sessions "
        "ORDER BY session_date DESC, id DESC LIMIT ?",
        (last_n,),
    ).fetchall()
    result = []
    for r in reversed(rows):
        score = r[3] if r[3] is not None else session_score(r[0], conn)
        result.append({"session_id": r[0], "date": r[1], "exam_id": r[2], "score": round(score, 2)})
    return result


def _source_profile_for_exam(conn: sqlite3.Connection, exam_id: str) -> dict:
    row = conn.execute(
        "SELECT source_type, source_profile_json FROM exams WHERE id=?", (exam_id,)
    ).fetchone()
    if row and row[1]:
        try:
            import json
            profile = json.loads(row[1])
            if "source_type" not in profile:
                profile["source_type"] = row[0] or detect_source_profile(exam_id)["source_type"]
            return profile
        except Exception:
            pass
    return detect_source_profile(exam_id)


def _style_adjustment(conn: sqlite3.Connection, exam_id: str) -> float:
    rows = conn.execute(
        "SELECT bo_gd_fit, calculation_load FROM questions WHERE exam_id=?", (exam_id,)
    ).fetchall()
    if not rows:
        return 0.0
    low_fit = sum(1 for r in rows if r[0] == "low")
    heavy = sum(1 for r in rows if r[1] == "heavy")
    medium_fit = sum(1 for r in rows if r[0] == "medium")
    n = max(len(rows), 1)
    # Harder-than-official item style depresses raw practice scores.
    return min(0.6, (low_fit / n) * 0.5 + (heavy / n) * 0.4 + (medium_fit / n) * 0.15)


# ── Tier 2: Diagnostic ────────────────────────────────────────────────────────

def chapter_mastery(conn: sqlite3.Connection, last_n_sessions: int = 5) -> list[dict]:
    """
    Per chapter across last N sessions:
      encountered, wrong, knowledge_wrong (not sai_ngu), careless,
      error_rate, knowledge_gap_rate, careless_rate, trend.
    Sorted by knowledge_gap_rate descending.
    """
    ids = _last_n_session_ids(conn, last_n_sessions)
    if not ids:
        return []
    ph = ",".join("?" * len(ids))

    enc_rows = conn.execute(f"""
        SELECT q.chuong, COUNT(DISTINCT q.id) as enc
        FROM questions q
        JOIN sessions s ON s.exam_id = q.exam_id
        WHERE s.id IN ({ph}) AND q.chuong IS NOT NULL
        GROUP BY q.chuong
    """, ids).fetchall()
    encountered = {r[0]: r[1] for r in enc_rows}

    wrong_rows = conn.execute(f"""
        SELECT q.chuong,
               COUNT(wa.id) as wrong,
               SUM(CASE WHEN COALESCE(wa.sai_ngu,0)=0 THEN 1 ELSE 0 END) as kw
        FROM wrong_answers wa
        JOIN sessions s ON s.id = wa.session_id
        JOIN questions q ON q.exam_id = s.exam_id AND q.phan = wa.phan AND q.stt = wa.stt
          AND (q.y = wa.y OR (q.y IS NULL AND wa.y IS NULL))
        WHERE wa.session_id IN ({ph}) AND q.chuong IS NOT NULL
        GROUP BY q.chuong
    """, ids).fetchall()
    wrongs = {r[0]: (r[1], r[2]) for r in wrong_rows}

    # Trend: split sessions into older half vs newer half
    half = max(1, len(ids) // 2)
    newer_ids, older_ids = ids[:half], ids[half:]

    def _rates(sids: list[int]) -> dict[str, float]:
        if not sids:
            return {}
        p = ",".join("?" * len(sids))
        rows = conn.execute(f"""
            SELECT q.chuong,
                   COUNT(DISTINCT q.id) as enc,
                   COUNT(wa.id) as wrong
            FROM questions q
            JOIN sessions s ON s.exam_id = q.exam_id AND s.id IN ({p})
            LEFT JOIN wrong_answers wa ON wa.session_id = s.id AND wa.phan = q.phan
              AND wa.stt = q.stt AND (wa.y = q.y OR (wa.y IS NULL AND q.y IS NULL))
            WHERE q.chuong IS NOT NULL
            GROUP BY q.chuong
        """, sids).fetchall()
        return {r[0]: (r[2] / r[1] if r[1] else 0.0) for r in rows}

    newer_rates = _rates(newer_ids)
    older_rates = _rates(older_ids)

    result = []
    for ch, enc in encountered.items():
        wrong, kw = wrongs.get(ch, (0, 0))
        careless = wrong - kw
        denom = max(enc, 1)
        old_r = older_rates.get(ch, 0.0)
        new_r = newer_rates.get(ch, 0.0)
        if old_r - new_r > 0.1:
            trend = "improving"
        elif new_r - old_r > 0.1:
            trend = "declining"
        else:
            trend = "stable"
        result.append({
            "chapter": ch,
            "chapter_name": _CHAPTER_NAMES.get(ch, ch),
            "encountered": enc,
            "wrong": wrong,
            "knowledge_wrong": kw,
            "careless": careless,
            "error_rate": round(wrong / denom, 3),
            "knowledge_gap_rate": round(kw / denom, 3),
            "careless_rate": round(careless / denom, 3),
            "trend": trend,
        })
    result.sort(key=lambda x: x["knowledge_gap_rate"], reverse=True)
    return result


def difficulty_profile(conn: sqlite3.Connection, last_n_sessions: int = 5) -> dict:
    """
    Error rates per difficulty level (B / H / VD) across last N sessions.
    pattern: foundation_weak | understanding_weak | application_weak | balanced
    """
    ids = _last_n_session_ids(conn, last_n_sessions)
    if not ids:
        return {"rates": {}, "pattern": "balanced", "sessions_used": 0}
    ph = ",".join("?" * len(ids))

    rows = conn.execute(f"""
        SELECT q.muc_do,
               COUNT(DISTINCT q.id) as enc,
               COUNT(wa.id) as wrong
        FROM questions q
        JOIN sessions s ON s.exam_id = q.exam_id AND s.id IN ({ph})
        LEFT JOIN wrong_answers wa ON wa.session_id = s.id AND wa.phan = q.phan
          AND wa.stt = q.stt AND (wa.y = q.y OR (wa.y IS NULL AND q.y IS NULL))
        WHERE q.muc_do IS NOT NULL
        GROUP BY q.muc_do
    """, ids).fetchall()

    rates: dict[str, dict] = {}
    for r in rows:
        enc = max(r[1], 1)
        wrong = r[2]
        rates[r[0]] = {
            "encountered": r[1],
            "wrong": wrong,
            "error_rate": round(wrong / enc, 3),
            "accuracy_rate": round(1 - wrong / enc, 3),
        }

    b_rate = rates.get("B", {}).get("error_rate", 0.0)
    h_rate = rates.get("H", {}).get("error_rate", 0.0)
    vd_rate = rates.get("VD", {}).get("error_rate", 0.0)

    if b_rate > 0.4:
        pattern = "foundation_weak"
    elif h_rate > 0.4:
        pattern = "understanding_weak"
    elif vd_rate > 0.5:
        pattern = "application_weak"
    else:
        pattern = "balanced"

    pattern_labels = {
        "foundation_weak": ("Nền tảng yếu — cần ôn lý thuyết cơ bản", "danger"),
        "understanding_weak": ("Hiểu biết chưa sâu — ôn cơ chế & giải thích", "warning"),
        "application_weak": ("Vận dụng yếu — luyện bài tập tính toán", "warning"),
        "balanced": ("Phân bố đều — tập trung vào chương yếu nhất", "success"),
    }
    label, color = pattern_labels[pattern]
    return {
        "rates": rates,
        "pattern": pattern,
        "pattern_label": label,
        "pattern_color": color,
        "sessions_used": len(ids),
    }


def section_profile(conn: sqlite3.Connection, last_n_sessions: int = 5) -> dict:
    """
    Per-section performance stats across last N sessions.
    P1/P3: accuracy, avg wrong per session.
    P2: full_correct_rate (0 wrong), partial_rate (1-3 wrong), zero_rate (4 wrong).
    """
    ids = _last_n_session_ids(conn, last_n_sessions)
    n = len(ids)
    if not n:
        return {}
    ph = ",".join("?" * len(ids))

    # P1 and P3
    phan_rows = conn.execute(f"""
        SELECT phan, COUNT(*) as total_wrong
        FROM wrong_answers WHERE session_id IN ({ph}) AND phan IN ('P1','P3')
        GROUP BY phan
    """, ids).fetchall()
    wrong_map = {r[0]: r[1] for r in phan_rows}

    total_p1 = 18 * n
    total_p3 = 6 * n
    wrong_p1 = wrong_map.get("P1", 0)
    wrong_p3 = wrong_map.get("P3", 0)

    # P2 per-question breakdown
    p2_rows = conn.execute(f"""
        SELECT session_id, stt, COUNT(*) as wrong_cnt
        FROM wrong_answers WHERE session_id IN ({ph}) AND phan='P2'
        GROUP BY session_id, stt
    """, ids).fetchall()

    full_correct = fully_wrong = partial = 0
    for sid in ids:
        for stt in range(1, 5):
            wrong_cnt = next((r[2] for r in p2_rows if r[0] == sid and r[1] == stt), 0)
            if wrong_cnt == 0:
                full_correct += 1
            elif wrong_cnt == 4:
                fully_wrong += 1
            else:
                partial += 1
    total_p2_qs = 4 * n

    return {
        "P1": {
            "total": total_p1,
            "wrong": wrong_p1,
            "accuracy": round(1 - wrong_p1 / total_p1, 3) if total_p1 else 0,
            "avg_wrong_per_session": round(wrong_p1 / n, 1),
        },
        "P2": {
            "total_questions": total_p2_qs,
            "full_correct": full_correct,
            "partial": partial,
            "fully_wrong": fully_wrong,
            "full_correct_rate": round(full_correct / total_p2_qs, 3) if total_p2_qs else 0,
            "partial_rate": round(partial / total_p2_qs, 3) if total_p2_qs else 0,
            "zero_rate": round(fully_wrong / total_p2_qs, 3) if total_p2_qs else 0,
        },
        "P3": {
            "total": total_p3,
            "wrong": wrong_p3,
            "accuracy": round(1 - wrong_p3 / total_p3, 3) if total_p3 else 0,
            "avg_wrong_per_session": round(wrong_p3 / n, 1),
        },
        "sessions_used": n,
    }


def retention_rate(conn: sqlite3.Connection, chapter: Optional[str] = None) -> dict:
    """
    Among questions that have been reviewed (on_tap_status in pass/redo):
      retention_rate = pass / (pass + redo)
    Optionally filter by chapter.
    """
    base_params: list = []
    chapter_join = ""
    chapter_filter = ""
    if chapter:
        chapter_join = """
            JOIN sessions s ON s.id = wa.session_id
            JOIN questions q ON q.exam_id = s.exam_id AND q.phan = wa.phan
              AND q.stt = wa.stt AND (q.y = wa.y OR (q.y IS NULL AND wa.y IS NULL))
        """
        chapter_filter = "AND q.chuong = ?"
        base_params.append(chapter)

    sql = f"""
        SELECT on_tap_status, COUNT(*) as cnt
        FROM wrong_answers wa
        {chapter_join}
        WHERE wa.on_tap_status IN ('pass','redo')
        {chapter_filter}
        GROUP BY wa.on_tap_status
    """
    rows = conn.execute(sql, base_params).fetchall()
    counts = {r[0]: r[1] for r in rows}

    passed = counts.get("pass", 0)
    redo = counts.get("redo", 0)
    careless = conn.execute(
        "SELECT COUNT(*) FROM wrong_answers WHERE COALESCE(sai_ngu,0)=1"
    ).fetchone()[0]
    total_reviewed = passed + redo
    rate = round(passed / (passed + redo), 3) if (passed + redo) else 0.0

    # Struggling questions (status=redo)
    redo_rows = conn.execute("""
        SELECT wa.id, wa.phan, wa.stt, wa.y,
               s.exam_id, q.chuong, q.muc_do
        FROM wrong_answers wa
        JOIN sessions s ON s.id = wa.session_id
        LEFT JOIN questions q ON q.exam_id = s.exam_id AND q.phan = wa.phan
          AND q.stt = wa.stt AND (q.y = wa.y OR (q.y IS NULL AND wa.y IS NULL))
        WHERE wa.on_tap_status = 'redo'
        ORDER BY s.session_date DESC LIMIT 20
    """).fetchall()
    struggling = [
        {"wa_id": r[0], "phan": r[1], "stt": r[2], "y": r[3],
         "exam_id": r[4], "chuong": r[5], "muc_do": r[6]}
        for r in redo_rows
    ]

    return {
        "total_reviewed": total_reviewed,
        "passed": passed,
        "redo": redo,
        "sai_ngu": careless,
        "retention_rate": rate,
        "struggling_questions": struggling,
    }


# ── Tier 3: Predictive ────────────────────────────────────────────────────────

def projected_score(conn: sqlite3.Connection, last_n_sessions: int = 3) -> dict:
    """
    Project exam score by applying observed per-(phan, muc_do) error rates
    to the counts defined in ma_tran_chuan.yaml.

    Returns projected_score, confidence_low, confidence_high,
    data_confidence (0-1), based_on_sessions, warnings.
    """
    ids = _last_n_session_ids(conn, last_n_sessions)
    warnings: list[str] = []
    if not ids:
        return {"projected_score": None, "warnings": ["No session data available"]}

    ph = ",".join("?" * len(ids))

    # Per (phan, muc_do): encountered and wrong
    rows = conn.execute(f"""
        SELECT q.phan, q.muc_do,
               COUNT(DISTINCT q.id) as enc,
               COUNT(wa.id) as wrong
        FROM questions q
        JOIN sessions s ON s.exam_id = q.exam_id AND s.id IN ({ph})
        LEFT JOIN wrong_answers wa ON wa.session_id = s.id AND wa.phan = q.phan
          AND wa.stt = q.stt AND (wa.y = q.y OR (wa.y IS NULL AND q.y IS NULL))
        WHERE q.phan IS NOT NULL AND q.muc_do IS NOT NULL
        GROUP BY q.phan, q.muc_do
    """, ids).fetchall()

    # error_rates[(phan, muc_do)] = error_rate
    error_rates: dict[tuple, float] = {}
    for r in rows:
        enc = max(r[2], 1)
        error_rates[(r[0], r[1])] = r[3] / enc

    # Global fallback rates by muc_do
    global_rows = conn.execute(f"""
        SELECT q.muc_do,
               COUNT(DISTINCT q.id) as enc,
               COUNT(wa.id) as wrong
        FROM questions q
        JOIN sessions s ON s.exam_id = q.exam_id AND s.id IN ({ph})
        LEFT JOIN wrong_answers wa ON wa.session_id = s.id AND wa.phan = q.phan
          AND wa.stt = q.stt AND (wa.y = q.y OR (wa.y IS NULL AND q.y IS NULL))
        WHERE q.muc_do IS NOT NULL
        GROUP BY q.muc_do
    """, ids).fetchall()
    global_md_rates = {r[0]: r[2] / max(r[1], 1) for r in global_rows}

    try:
        cfg = _load_config()
    except FileNotFoundError:
        return {"projected_score": None, "warnings": ["ma_tran_chuan.yaml not found"]}

    phan_cfg = cfg.get("phan", {})

    # P1 and P3: each correct question = 0.25đ
    projected = 0.0
    confidence_weights: list[float] = []

    for phan in ("P1", "P3"):
        pcfg = phan_cfg.get(phan, {})
        muc_do_counts = pcfg.get("muc_do", {})
        for md, count in muc_do_counts.items():
            key = (phan, md)
            if key in error_rates:
                rate = error_rates[key]
                w = 1.0
            else:
                rate = global_md_rates.get(md, 0.5)
                w = 0.5
                warnings.append(f"No data for {phan}·{md}, using global fallback")
            projected += count * (1 - rate) * 0.25
            confidence_weights.extend([w] * count)

    # P2: approximate each sub-item as 0.25đ (linear approximation)
    p2_cfg = phan_cfg.get("P2", {})
    for md, count in p2_cfg.get("muc_do", {}).items():
        key = ("P2", md)
        if key in error_rates:
            rate = error_rates[key]
            w = 1.0
        else:
            rate = global_md_rates.get(md, 0.5)
            w = 0.5
            warnings.append(f"No data for P2·{md}, using global fallback")
        projected += count * (1 - rate) * 0.25
        confidence_weights.extend([w] * count)

    projected = round(min(projected, 10.0), 2)
    data_confidence = round(sum(confidence_weights) / len(confidence_weights), 2) if confidence_weights else 0.0

    # Confidence interval from score variance
    trend_data = score_trend(conn, last_n_sessions)
    scores = [d["score"] for d in trend_data]
    if len(scores) >= 2:
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std = variance ** 0.5
        ci_low = round(max(0, projected - std), 2)
        ci_high = round(min(10, projected + std), 2)
    else:
        ci_low = round(max(0, projected - 1.0), 2)
        ci_high = round(min(10, projected + 1.0), 2)

    if len(ids) < 3:
        warnings.append(f"Only {len(ids)} session(s) — projection confidence is low")

    return {
        "projected_score": projected,
        "confidence_low": ci_low,
        "confidence_high": ci_high,
        "data_confidence": data_confidence,
        "based_on_sessions": len(ids),
        "warnings": warnings,
    }


def source_breakdown(conn: sqlite3.Connection, last_n_sessions: int = 12) -> list[dict]:
    rows = conn.execute(
        "SELECT id, session_date, exam_id, score FROM sessions ORDER BY session_date DESC, id DESC LIMIT ?",
        (last_n_sessions,),
    ).fetchall()
    grouped: dict[str, dict] = {}
    for r in rows:
        sid, _, exam_id, stored_score = r
        raw_score = stored_score if stored_score is not None else session_score(sid, conn)
        profile = _source_profile_for_exam(conn, exam_id)
        source_type = profile.get("source_type", "Unknown")
        bias = abs(float(profile.get("expected_bias_points", 0.0) or 0.0))
        normalized = min(10.0, raw_score + bias + _style_adjustment(conn, exam_id))
        bucket = grouped.setdefault(source_type, {
            "source_type": source_type,
            "sessions": 0,
            "raw_total": 0.0,
            "normalized_total": 0.0,
            "reliability": profile.get("reliability", "low"),
            "reliability_weight": profile.get("reliability_weight", 0.35),
            "official_anchor": bool(profile.get("official_anchor")),
        })
        bucket["sessions"] += 1
        bucket["raw_total"] += raw_score
        bucket["normalized_total"] += normalized

    result = []
    for item in grouped.values():
        n = max(item["sessions"], 1)
        result.append({
            **{k: v for k, v in item.items() if not k.endswith("_total")},
            "raw_avg": round(item["raw_total"] / n, 2),
            "bogd_equivalent_avg": round(item["normalized_total"] / n, 2),
        })
    result.sort(key=lambda x: (not x["official_anchor"], -x["sessions"], x["source_type"]))
    return result


def bogd_equivalent_projection(conn: sqlite3.Connection, last_n_sessions: int = 6) -> dict:
    rows = conn.execute(
        "SELECT id, session_date, exam_id, score FROM sessions ORDER BY session_date DESC, id DESC LIMIT ?",
        (last_n_sessions,),
    ).fetchall()
    if not rows:
        return {"raw_recent_avg": None, "bogd_equivalent_score": None, "warnings": ["No session data available"]}

    weighted_total = raw_total = weight_total = 0.0
    official_count = 0
    low_reliability_count = 0
    source_counts: dict[str, int] = {}

    for age, r in enumerate(rows):
        sid, _, exam_id, stored_score = r
        raw_score = stored_score if stored_score is not None else session_score(sid, conn)
        profile = _source_profile_for_exam(conn, exam_id)
        source_type = profile.get("source_type", "Unknown")
        source_counts[source_type] = source_counts.get(source_type, 0) + 1
        if profile.get("official_anchor"):
            official_count += 1
        if float(profile.get("reliability_weight", 0.35) or 0.35) < 0.5:
            low_reliability_count += 1

        bias = abs(float(profile.get("expected_bias_points", 0.0) or 0.0))
        normalized = min(10.0, raw_score + bias + _style_adjustment(conn, exam_id))
        recency_weight = max(0.35, 1.0 - age * 0.08)
        reliability_weight = float(profile.get("reliability_weight", 0.35) or 0.35)
        weight = recency_weight * reliability_weight
        weighted_total += normalized * weight
        raw_total += raw_score
        weight_total += weight

    score = round(weighted_total / weight_total, 2) if weight_total else None
    raw_avg = round(raw_total / len(rows), 2)
    confidence = "high" if official_count >= 2 else "medium" if official_count >= 1 and low_reliability_count <= len(rows) // 2 else "low"
    warnings: list[str] = []
    if official_count == 0:
        warnings.append("No recent BoGD anchor test; normalized score uses source priors.")
    if low_reliability_count > len(rows) // 2:
        warnings.append("Recent sessions are mostly low-reliability hard sources.")

    return {
        "raw_recent_avg": raw_avg,
        "bogd_equivalent_score": score,
        "confidence": confidence,
        "based_on_sessions": len(rows),
        "official_anchor_sessions": official_count,
        "source_mix": source_counts,
        "warnings": warnings,
    }


def readiness_score(conn: sqlite3.Connection) -> dict:
    """
    Composite readiness score 0-100:
      40% trend (linear regression slope on last 5 scores)
      30% chapter coverage (chapters with ≥3 questions / 11)
      20% retention (pass rate)
      10% time buffer (estimated sessions left / questions not yet reviewed)

    Reads target_exam_date from student_profile table.
    """
    profile = conn.execute(
        "SELECT target_exam_date, target_score FROM student_profile ORDER BY id DESC LIMIT 1"
    ).fetchone()
    target_date_str = profile[0] if profile else None
    target_score = profile[1] if profile else None

    if not target_date_str:
        return {
            "readiness_score": None,
            "label": "Chưa đặt mục tiêu",
            "color": "secondary",
            "error": "Hãy đặt ngày thi mục tiêu trong phần Actions bên dưới.",
            "components": {},
        }

    try:
        target_date = date.fromisoformat(target_date_str)
    except ValueError:
        return {"readiness_score": None, "error": "Ngày thi không hợp lệ"}

    days_left = (target_date - date.today()).days

    # 1. Trend (40%): linear slope of last 5 scores, scaled to 0-1
    trend_data = score_trend(conn, last_n=5)
    scores = [d["score"] for d in trend_data]
    if len(scores) >= 2:
        slope = _linear_slope(scores)
        trend_component = min(1.0, max(0.0, 0.5 + slope / 0.6))
    else:
        trend_component = 0.5

    # 2. Coverage (30%): chapters with ≥3 encountered / 11
    cov_rows = conn.execute("""
        SELECT q.chuong, COUNT(DISTINCT q.id) as enc
        FROM questions q
        JOIN sessions s ON s.exam_id = q.exam_id
        WHERE q.chuong IS NOT NULL
        GROUP BY q.chuong HAVING enc >= 3
    """).fetchall()
    chapters_covered = len(cov_rows)
    coverage_component = min(1.0, chapters_covered / 11)

    # 3. Retention (20%): pass / (pass + redo)
    ret = retention_rate(conn)
    retention_component = ret["retention_rate"] if (ret["passed"] + ret["redo"]) > 0 else 0.5

    # 4. Time buffer (10%): estimated sessions / outstanding not-yet count
    not_yet = conn.execute(
        "SELECT COUNT(*) FROM wrong_answers WHERE on_tap_status != 'pass'"
    ).fetchone()[0]
    sessions_per_week = 3
    est_sessions_left = max(0, days_left) * sessions_per_week / 7
    time_component = min(1.0, est_sessions_left / max(not_yet, 1)) if not_yet else 1.0

    raw = (
        0.40 * trend_component
        + 0.30 * coverage_component
        + 0.20 * retention_component
        + 0.10 * time_component
    )
    score = round(raw * 100)

    if score >= 70:
        label, color = "Tốt", "success"
    elif score >= 45:
        label, color = "Cần cố gắng", "warning"
    else:
        label, color = "Nguy hiểm", "danger"

    return {
        "readiness_score": score,
        "label": label,
        "color": color,
        "days_until_exam": days_left,
        "target_date": target_date_str,
        "target_score": target_score,
        "components": {
            "trend": round(trend_component * 100),
            "coverage": round(coverage_component * 100),
            "retention": round(retention_component * 100),
            "time_buffer": round(time_component * 100),
        },
    }


def export_summary(conn: sqlite3.Connection) -> dict:
    """Combine all analytics into one JSON blob for AI study plan generation."""
    return {
        "generated_at": datetime.now().isoformat(),
        "score_trend": score_trend(conn, 8),
        "chapter_mastery": chapter_mastery(conn, 5),
        "difficulty_profile": difficulty_profile(conn, 5),
        "section_profile": section_profile(conn, 5),
        "retention": retention_rate(conn),
        "projected_score": projected_score(conn, 3),
        "bogd_equivalent_projection": bogd_equivalent_projection(conn, 6),
        "source_breakdown": source_breakdown(conn, 12),
        "readiness": readiness_score(conn),
    }
