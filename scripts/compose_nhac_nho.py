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
    Table,
    TableStyle,
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

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 2.5 * cm
RIGHT_MARGIN = 2.0 * cm
TOP_MARGIN = 2.0 * cm
BOTTOM_MARGIN = 2.0 * cm
USABLE_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN

_font_name: str | None = None


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _register_unicode_font() -> str:
    global _font_name
    if _font_name is not None:
        return _font_name

    candidates = [
        ROOT / "config" / "fonts" / "DejaVuSans.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont("UniFont", str(path)))
                _font_name = "UniFont"
                return _font_name
            except Exception:
                continue

    console.print(
        "[yellow]Warning: No Vietnamese font found. PDF may not render diacritics correctly.\n"
        "Download DejaVuSans.ttf and save to config/fonts/DejaVuSans.ttf[/yellow]"
    )
    _font_name = "Helvetica"
    return _font_name


def load_exam_markdown(exam_id: str) -> str:
    md_path = PROCESSED_DIR / exam_id / "de.md"
    if not md_path.exists():
        raise FileNotFoundError(
            f"de.md not found for {exam_id}. Run `tutor form` and import JSON first."
        )
    return md_path.read_text(encoding="utf-8")


def load_classify(exam_id: str) -> dict:
    classify_path = PROCESSED_DIR / exam_id / "classify.json"
    if not classify_path.exists():
        return {}
    with open(classify_path, encoding="utf-8") as f:
        return json.load(f)


def extract_p1_question(markdown: str, stt: int) -> str:
    pattern = (
        rf"(?:Câu|câu)\s+{stt}\s*[.:)]\s*"
        rf"(.+?)"
        rf"(?=(?:Câu|câu)\s+\d+\s*[.:)]|(?:Phần|PHẦN)\s+II|$)"
    )
    match = re.search(pattern, markdown, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return f"[Câu {stt} — không tìm thấy trong de.md]"


def extract_p2_question(markdown: str, stt: int, y_list: list[str] | None) -> str:
    pattern = (
        rf"(?:Câu|câu)\s+{stt}\s*[.:)]\s*"
        rf"(.+?)"
        rf"(?=(?:Câu|câu)\s+\d+\s*[.:)]|(?:Phần|PHẦN)\s+III|$)"
    )
    match = re.search(pattern, markdown, re.DOTALL | re.IGNORECASE)
    if not match:
        return f"[Câu {stt} P2 — không tìm thấy trong de.md]"

    full_text = match.group(1).strip()

    if not y_list:
        return full_text

    lines = full_text.split("\n")
    context_lines: list[str] = []
    y_lines: dict[str, list[str]] = {}
    current_y: str | None = None

    for line in lines:
        y_match = re.match(r"^\s*([abcd])\s*[.):]\s*(.*)", line, re.IGNORECASE)
        if y_match:
            current_y = y_match.group(1).lower()
            y_lines.setdefault(current_y, []).append(line)
        elif current_y:
            y_lines.setdefault(current_y, []).append(line)
        else:
            context_lines.append(line)

    selected = [y for y in ["a", "b", "c", "d"] if y in [yy.lower() for yy in y_list]]
    result_lines = context_lines[:]
    for y in selected:
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


def build_source_label(exam_id: str, phan: str, stt: int, y_list: list[str] | None, muc_do: str = "") -> str:
    if phan == "P2" and y_list:
        y_str = ",".join(sorted(y_list))
        loc = f"{phan}·{stt}-{y_str}"
    else:
        loc = f"{phan}·{stt}"
    if muc_do:
        return f"[{exam_id} · {loc} · {muc_do}]"
    return f"[{exam_id} · {loc}]"


def sanitize_filename(title: str) -> str:
    return re.sub(r"[^\w\-_]", "_", title).strip("_")


def _make_page_footer(font_name: str):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name, 9)
        canvas.setFillColor(colors.grey)
        canvas.drawCentredString(PAGE_WIDTH / 2, 1.2 * cm, f"Trang {doc.page}")
        canvas.restoreState()
    return _draw


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
        muc_do = meta.get("muc_do", "")
        source_label = build_source_label(exam_id, phan, stt, y_list, muc_do)

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
        by_chapter.setdefault(e["chuong"], []).append(e)

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
    chapter_header_style = ParagraphStyle(
        "ChapterHeader",
        fontName=font_name,
        fontSize=12,
        textColor=colors.white,
        leading=16,
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
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
    )

    footer_fn = _make_page_footer(font_name)

    story = []
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(f"Ngày tạo: {date.today().isoformat()}", date_style))

    q_num = 0

    for chapter_code in ordered_chapters:
        qs = by_chapter[chapter_code]
        chapter_name = chapter_names.get(chapter_code, chapter_code)

        header_para = Paragraph(f"<b>{chapter_code} — {chapter_name}</b>", chapter_header_style)
        header_table = Table([[header_para]], colWidths=[USABLE_WIDTH])
        header_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1a3a5c")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(Spacer(1, 8))
        story.append(header_table)
        story.append(Spacer(1, 6))

        for q in qs:
            q_num += 1
            story.append(Paragraph(f"Câu {q_num}.", q_num_style))
            story.append(Paragraph(q["source_label"], source_style))
            safe_text = (
                q["text"]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>")
            )
            story.append(Paragraph(safe_text, question_style))

    doc.build(story, onFirstPage=footer_fn, onLaterPages=footer_fn)

    page_count = doc.page
    console.print(
        f"[green]✓ PDF đã tạo: {output_path} ({q_num} câu hỏi, {page_count} trang)[/green]"
    )
    return output_path
