"""
Generate List A (bám ma trận, evaluated) and List B (lệch ma trận, nhiều VD).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import yaml
from rich.console import Console

console = Console()

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "ma_tran_chuan.yaml"
PROCESSED_DIR = ROOT / "question_bank" / "processed"
SHORTLIST_DIR = ROOT / "question_bank" / "shortlist"
LIST_A_PATH = SHORTLIST_DIR / "A_bam_ma_tran.md"
LIST_B_PATH = SHORTLIST_DIR / "B_kho_lech_ma_tran.md"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_all_processed() -> list[dict]:
    entries = []
    if not PROCESSED_DIR.exists():
        return entries

    for exam_dir in sorted(PROCESSED_DIR.iterdir()):
        if not exam_dir.is_dir() or exam_dir.name.startswith("."):
            continue
        classify_json = exam_dir / "classify.json"
        evaluate_json = exam_dir / "evaluate.json"
        if not classify_json.exists():
            continue
        with open(classify_json, encoding="utf-8") as f:
            classify_data = json.load(f)
        evaluate_data = None
        if evaluate_json.exists():
            with open(evaluate_json, encoding="utf-8") as f:
                evaluate_data = json.load(f)
        entries.append({"classify": classify_data, "evaluate": evaluate_data})

    return entries


def top_chapters(entries: list[dict], config: dict, n: int = 3) -> list[str]:
    vd_by_chapter: Counter = Counter()
    for e in entries:
        for c in e["classify"].get("classifications", []):
            if c["muc_do"] == "VD":
                vd_by_chapter[c["chuong"]] += 1
    chapter_names = {k: v["ten"] for k, v in config["chuong"].items()}
    result = []
    for code, _ in vd_by_chapter.most_common(n):
        result.append(f"{code} ({chapter_names.get(code, code)})")
    return result


def build_list_a(entries: list[dict], config: dict) -> str:
    config_screen = config["screen"]
    threshold = config_screen["list_a_match_min"]

    list_a = [
        e for e in entries
        if e["classify"].get("screen_pass")
        and e["evaluate"] is not None
        and e["classify"].get("ma_tran_match_score", 0) >= threshold
    ]
    list_a.sort(key=lambda e: e["classify"].get("ma_tran_match_score", 0), reverse=True)

    today = date.today().isoformat()
    lines = [
        f"# List A — Đề bám sát ma trận (đã qua Sonnet)",
        f"_Cập nhật: {today}_",
        "",
        "| # | Exam ID | Match | Phân loại tư duy | Chính xác KH | Câu nổi bật | PDF |",
        "|---|---------|-------|------------------|--------------|-------------|-----|",
    ]

    for idx, e in enumerate(list_a, 1):
        cl = e["classify"]
        ev = e["evaluate"]
        exam_id = cl["exam_id"]
        match = cl["ma_tran_match_score"]
        tu_duy = ev.get("phan_loai_tu_duy_score", "—") if ev else "—"
        chinh_xac = ev.get("do_chinh_xac_khoa_hoc", "—") if ev else "—"

        noi_bat_items = ev.get("cau_y_noi_bat", []) if ev else []
        noi_bat_strs = []
        for item in noi_bat_items[:3]:
            if item.get("y"):
                noi_bat_strs.append(f"{item['phan']}c{item['stt']}-{item['y']}")
            else:
                noi_bat_strs.append(f"{item['phan']}c{item['stt']}")
        noi_bat = ", ".join(noi_bat_strs) if noi_bat_strs else "—"

        pdf_link = f"[link](../../question_bank/raw/{exam_id}.pdf)"
        lines.append(f"| {idx} | {exam_id} | {match:.2f} | {tu_duy} | {chinh_xac} | {noi_bat} | {pdf_link} |")

    if list_a:
        hot_chapters = top_chapters(list_a, config)
        lines.extend([
            "",
            "## Chương điểm nóng (tổng hợp)",
            "",
        ])
        for i, ch in enumerate(hot_chapters, 1):
            lines.append(f"{i}. {ch}")
    else:
        lines.extend(["", "_Chưa có đề nào đạt ngưỡng._"])

    return "\n".join(lines) + "\n"


def build_list_b(entries: list[dict], config: dict) -> str:
    list_b_vd_min = config["screen"]["list_b_vd_min"]
    list_a_threshold = config["screen"]["list_a_match_min"]

    list_b = [
        e for e in entries
        if not e["classify"].get("screen_pass")
        or e["classify"].get("ma_tran_match_score", 0) < list_a_threshold
    ]
    list_b = [e for e in list_b if e["classify"].get("vd_count", 0) >= list_b_vd_min]
    list_b.sort(key=lambda e: e["classify"].get("vd_count", 0), reverse=True)

    chapter_names = {k: v["ten"] for k, v in config["chuong"].items()}

    today = date.today().isoformat()
    lines = [
        "# List B — Đề lệch ma trận nhưng nhiều câu VD",
        "_Lưu ý: các đề này không bám sát cấu trúc bộ GD nhưng có thể dùng cho ôn luyện nâng cao_",
        f"_Cập nhật: {today}_",
        "",
        "| # | Exam ID | Match | VD count | Chương chủ đạo | PDF |",
        "|---|---------|-------|----------|----------------|-----|",
    ]

    for idx, e in enumerate(list_b, 1):
        cl = e["classify"]
        exam_id = cl["exam_id"]
        match = cl["ma_tran_match_score"]
        vd_count = cl["vd_count"]

        chapter_counter: Counter = Counter()
        for c in cl.get("classifications", []):
            if c["muc_do"] == "VD":
                chapter_counter[c["chuong"]] += 1
        top_chs = [code for code, _ in chapter_counter.most_common(2)]
        chu_dao = ", ".join(top_chs) if top_chs else "—"

        pdf_link = f"[link](../../question_bank/raw/{exam_id}.pdf)"
        lines.append(f"| {idx} | {exam_id} | {match:.2f} | {vd_count} | {chu_dao} | {pdf_link} |")

    if not list_b:
        lines.extend(["", "_Chưa có đề nào đủ điều kiện._"])

    return "\n".join(lines) + "\n"


def run_shortlist():
    SHORTLIST_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config()
    entries = load_all_processed()

    if not entries:
        console.print("[yellow]No processed exams found.[/yellow]")
        return

    list_a_content = build_list_a(entries, config)
    LIST_A_PATH.write_text(list_a_content, encoding="utf-8")
    console.print(f"[green]Saved {LIST_A_PATH}[/green]")

    list_b_content = build_list_b(entries, config)
    LIST_B_PATH.write_text(list_b_content, encoding="utf-8")
    console.print(f"[green]Saved {LIST_B_PATH}[/green]")

    list_a_count = list_a_content.count("\n| ") - 1  # subtract header
    list_b_count = list_b_content.count("\n| ") - 1
    console.print(f"List A: {max(0, list_a_count)} exams | List B: {max(0, list_b_count)} exams")
