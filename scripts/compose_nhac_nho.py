"""
Compose a reminder/review PDF from a manually selected list of questions.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)
from rich.console import Console

console = Console()

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "ma_tran_chuan.yaml"
PROCESSED_DIR = ROOT / "question_bank" / "processed"
SESSIONS_DIR = ROOT / "sessions"

CHAPTER_ORDER = [
    "DT_PT", "DT_TB", "CH_TV", "CH_DV", "DT_BD",
    "QL_DT", "DT_QT", "DT_HP", "UD_DT", "TH", "ST_MT",
]


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _register_unicode_font() -> str:
    """Try to register a Vietnamese-capable font; fall back to Helvetica."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("UniFont", path))
                return "UniFont"
            except Exception:
                continue
    return "Helvetica"


def load_exam_markdown(exam_id: str) -> str:
    md_path = PROCESSED_DIR / exam_id / "de.md"
    if not md_path.exists():
        raise FileNotFoundError(f"de.md not found for {exam_id}. Run: tutor classify question_bank/raw/{exam_id}.pdf")
    return md_path.read_text(encoding="utf-8")


def load_classify(exam_id: str) -> dict:
    classify_path = PROCESSED_DIR / exam_id / "classify.json"
    if not classify_path.exists():
        return {}
    with open(classify_path, encoding="utf-8") as f:
        return json.load(f)


def extract_p1_question(markdown: str, stt: int) -> str:
    pattern = rf"(?:Câu|câu)\s+{stt}\s*[.:)](.+?)(?=(?:Câu|câu)\s+\d+\s*[.:)]|$)"
    match = re.search(pattern, markdown, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    pattern2 = rf"\b{stt}\s*[.)]\s*(.+?)(?=\b\d+\s*[.)]\s*[A-ZĐÔĂÂÊIUW]|\Z)"
    match2 = re.search(pattern2, markdown, re.DOTALL)
    if match2:
        return match2.group(1).strip()
    return f"[Câu {stt} — không tìm thấy trong de.md]"


def extract_p2_question(markdown: str, stt: int, y_list: list[str] | None) -> str:
    pattern = rf"(?:Câu|câu)\s+{stt}\s*[.:)](.+?)(?=(?:Câu|câu)\s+\d+\s*[.:)]|(?:Phần|PHẦN)\s+III|$)"
    match = re.search(pattern, markdown, re.DOTALL | re.IGNORECASE)
    if not match:
        return f"[Câu {stt} P2 — không tìm thấy trong de.md]"

    full_text = match.group(1).strip()

    if not y_list:
        return full_text

    lines = full_text.split("\n")
    context_lines = []
    y_lines: dict[str, list[str]] = {}
    current_y = None

    for line in lines:
        y_match = re.match(r"^\s*([abcd])\s*[.):]\s*(.*)", line, re.IGNORECASE)
        if y_match:
            current_y = y_match.group(1).lower()
            y_lines.setdefault(current_y, []).append(line)
        elif current_y:
            y_lines.setdefault(current_y, []).append(line)
        else:
            context_lines.append(line)

    selected_y = [y for y in ["a", "b", "c", "d"] if y in [yy.lower() for yy in y_list]]

    result_lines = context_lines[:]
    for y in selected_y:
        result_lines.extend(y_lines.get(y, [f"  {y}) [không tìm thấy]"]))

    return "\n".join(result_lines).strip()


def extract_p3_question(markdown: str, stt: int) -> str:
    return extract_p1_question(markdown, stt)


def get_question_text(exam_id: str, phan: str, stt: int, y_list: list[str] | None) -> str:
    markdown = load_exam_markdown(exam_id)
    if phan == "P1":
        return extract_p1_question(markdown, stt)
    elif phan == "P2":
        return extract_p2_question(markdown, stt, y_list)
    elif phan == "P3":
        return extract_p3_question(markdown, stt)
    return f"[Unknown phan: {phan}]"


def get_metadata(exam_id: str, phan: str, stt: int, y_list: list[str] | None) -> dict:
    classify_data = load_classify(exam_id)
    for c in classify_data.get("classifications", []):
        if c["phan"] == phan and c["stt"] == stt:
            if phan == "P2" and y_list:
                if c.get("y") and c["y"] in [y.lower() for y in y_list]:
                    return c
                elif not c.get("y"):
                    return c
            else:
                return c
    return {"chuong": "UNKNOWN", "muc_do": "?"}


def build_source_label(exam_id: str, phan: str, stt: int, y_list: list[str] | None) -> str:
    if phan == "P2" and y_list:
        y_str = ",".join(sorted(y_list))
        return f"[{exam_id} · {phan}c{stt}-{y_str}]"
    return f"[{exam_id} · {phan}c{stt}]"


def sanitize_filename(title: str) -> str:
    return re.sub(r"[^\w\-_]", "_", title).strip("_")


def run_compose(compose_json_path: Path, output_path: Path | None = None):
    with open(compose_json_path, encoding="utf-8") as f:
        compose_input = json.load(f)

    title = compose_input.get("title", "Ôn tập")
    questions_raw = compose_input.get("questions", [])

    config = load_config()
    chapter_names = {k: v["ten"] for k, v in config["chuong"].items()}

    enriched: list[dict] = []
    for q in questions_raw:
        exam_id = q["exam_id"]
        phan = q["phan"]
        stt = q["stt"]
        y_list = q.get("y_list")

        try:
            text = get_question_text(exam_id, phan, stt, y_list)
        except FileNotFoundError as e:
            console.print(f"[yellow]Warning: {e}[/yellow]")
            text = str(e)

        meta = get_metadata(exam_id, phan, stt, y_list)
        chuong = meta.get("chuong", "UNKNOWN")
        source_label = build_source_label(exam_id, phan, stt, y_list)

        enriched.append({
            "chuong": chuong,
            "phan": phan,
            "stt": stt,
            "y_list": y_list,
            "exam_id": exam_id,
            "text": text,
            "source_label": source_label,
        })

    by_chapter: dict[str, list[dict]] = {}
    for e in enriched:
        ch = e["chuong"]
        by_chapter.setdefault(ch, []).append(e)

    ordered_chapters = [ch for ch in CHAPTER_ORDER if ch in by_chapter]
    for ch in by_chapter:
        if ch not in ordered_chapters:
            ordered_chapters.append(ch)

    if output_path is None:
        today = date.today().isoformat()
        session_dir = SESSIONS_DIR / today
        session_dir.mkdir(parents=True, exist_ok=True)
        safe_title = sanitize_filename(title)
        output_path = session_dir / f"nhac_nho_{safe_title}.pdf"

    font_name = _register_unicode_font()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=16,
        spaceAfter=6,
    )
    date_style = ParagraphStyle(
        "DateStyle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=16,
    )
    chapter_style = ParagraphStyle(
        "ChapterStyle",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=13,
        spaceBefore=14,
        spaceAfter=6,
        textColor=colors.HexColor("#1a3a5c"),
    )
    source_style = ParagraphStyle(
        "SourceStyle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=8,
        textColor=colors.grey,
        spaceAfter=2,
    )
    question_style = ParagraphStyle(
        "QuestionStyle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=11,
        spaceAfter=10,
        leading=16,
    )
    q_num_style = ParagraphStyle(
        "QNumStyle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=11,
        textColor=colors.HexColor("#333333"),
        spaceAfter=2,
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    story = []
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(f"Ngày tạo: {date.today().isoformat()}", date_style))

    q_num = 0
    total_pages = [0]

    for chapter_code in ordered_chapters:
        qs = by_chapter[chapter_code]
        chapter_name = chapter_names.get(chapter_code, chapter_code)
        story.append(Paragraph(f"{chapter_code} — {chapter_name}", chapter_style))
        story.append(Spacer(1, 4))

        for q in qs:
            q_num += 1
            story.append(Paragraph(f"Câu {q_num}.", q_num_style))
            story.append(Paragraph(q["source_label"], source_style))

            safe_text = q["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            safe_text = safe_text.replace("\n", "<br/>")
            story.append(Paragraph(safe_text, question_style))

    doc.build(story)

    page_count = doc.page
    console.print(
        f"[green]✓ PDF đã tạo: {output_path} ({q_num} câu hỏi, {page_count} trang)[/green]"
    )
    return output_path
