"""
OCR-annotate scanned exam PDFs using Tesseract.

Prerequisites (system packages):
    sudo apt install tesseract-ocr tesseract-ocr-vie

Pipeline per file:
  scanned/<name>.pdf
    → render each page to image (pymupdf, 200 DPI)
    → pytesseract image_to_data (lang=vie, word-level boxes)
    → build invisible-text layer PDF (reportlab)
    → merge text layer onto original pages (pypdf)
    → raw/<name>.pdf
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import fitz  # pymupdf
import pytesseract
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as rl_canvas
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

console = Console()

ROOT = Path(__file__).resolve().parent.parent
SCANNED_DIR = ROOT / "question_bank" / "scanned"
RAW_DIR = ROOT / "question_bank" / "raw"

RENDER_DPI = 400
TESS_LANG = "vie"
TESS_CONFIG = "--psm 6"  # assume uniform block of text; good for exam pages


# ── Tesseract check ────────────────────────────────────────────────────────────

def _check_tesseract():
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract not found. Install it with:\n"
            "  sudo apt install tesseract-ocr tesseract-ocr-vie"
        )
    langs = pytesseract.get_languages()
    if TESS_LANG not in langs:
        raise RuntimeError(
            f"Tesseract language pack '{TESS_LANG}' not installed. Run:\n"
            f"  sudo apt install tesseract-ocr-{TESS_LANG}"
        )


# ── OCR one page image ─────────────────────────────────────────────────────────

def _ocr_image(pil_image: Image.Image) -> dict:
    """Return pytesseract word-level data dict for one page image."""
    return pytesseract.image_to_data(
        pil_image,
        lang=TESS_LANG,
        config=TESS_CONFIG,
        output_type=pytesseract.Output.DICT,
    )


# ── Invisible text layer ───────────────────────────────────────────────────────

def _build_text_layer(ocr_data: dict, page_width_pt: float, page_height_pt: float,
                      img_width_px: int, img_height_px: int) -> bytes:
    """
    Render an invisible text layer PDF page from pytesseract word data.

    Coordinate systems:
      Tesseract  → origin top-left, pixel units  (left, top, width, height)
      ReportLab  → origin bottom-left, point units
    """
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_width_pt, page_height_pt))

    scale_x = page_width_pt / img_width_px
    scale_y = page_height_pt / img_height_px

    n = len(ocr_data["text"])
    for i in range(n):
        word_text = ocr_data["text"][i]
        conf = int(ocr_data["conf"][i])

        # Skip empty words and very low-confidence detections
        if not word_text.strip() or conf < 30:
            continue

        left = ocr_data["left"][i]
        top = ocr_data["top"][i]
        w_px = ocr_data["width"][i]
        h_px = ocr_data["height"][i]

        if w_px <= 0 or h_px <= 0:
            continue

        # Convert to PDF points (flip Y: origin bottom-left)
        x_pt = left * scale_x
        y_pt = page_height_pt - (top + h_px) * scale_y  # baseline at bbox bottom
        w_pt = w_px * scale_x
        h_pt = h_px * scale_y

        font_size = max(h_pt * 0.85, 1.0)
        text_width = c.stringWidth(word_text, "Helvetica", font_size)
        if text_width <= 0:
            continue

        h_scale = w_pt / text_width

        # PDFTextObject.setTextRenderMode(3) = invisible (no fill, no stroke)
        tobj = c.beginText()
        tobj.setTextRenderMode(3)
        tobj.setFont("Helvetica", font_size)
        tobj.setTextTransform(h_scale, 0, 0, 1, x_pt, y_pt)
        tobj.textOut(word_text)
        c.drawText(tobj)

    c.save()
    return buf.getvalue()


# ── Per-page pipeline ──────────────────────────────────────────────────────────

def _process_page(fitz_page: fitz.Page) -> bytes:
    """Render one PDF page, OCR it, return the invisible text layer as PDF bytes."""
    mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
    pix = fitz_page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    rect = fitz_page.rect
    ocr_data = _ocr_image(img)
    return _build_text_layer(ocr_data, rect.width, rect.height, pix.width, pix.height)


def _empty_layer(fitz_page: fitz.Page) -> bytes:
    """Return a blank PDF page matching fitz_page dimensions."""
    rect = fitz_page.rect
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(rect.width, rect.height))
    c.save()
    return buf.getvalue()


# ── Merge text layers onto original ───────────────────────────────────────────

def _merge_text_layers(original_path: Path, text_layer_pages: list[bytes],
                       output_path: Path):
    original_reader = PdfReader(str(original_path))
    writer = PdfWriter()

    for i, orig_page in enumerate(original_reader.pages):
        if i < len(text_layer_pages):
            layer_reader = PdfReader(io.BytesIO(text_layer_pages[i]))
            orig_page.merge_page(layer_reader.pages[0])
        writer.add_page(orig_page)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)


# ── Public interface ───────────────────────────────────────────────────────────

def annotate_pdf(pdf_path: Path, force: bool = False) -> Path | None:
    """
    OCR-annotate a single scanned PDF and write the result to raw/.
    Returns the output path on success, None on failure.
    """
    output_path = RAW_DIR / pdf_path.name

    if output_path.exists() and not force:
        console.print(f"  [dim]Skipping {pdf_path.name} (already in raw/, use --force to redo)[/dim]")
        return output_path

    console.print(f"\n[bold cyan]Annotating {pdf_path.name}[/bold cyan]")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        console.print(f"  [red]Cannot open PDF: {e}[/red]")
        return None

    n_pages = len(doc)
    text_layers: list[bytes] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("  OCR pages", total=n_pages)
        for page_num in range(n_pages):
            try:
                layer = _process_page(doc[page_num])
                text_layers.append(layer)
            except Exception as e:
                console.print(f"  [yellow]Page {page_num + 1} failed: {e} — inserting blank layer[/yellow]")
                text_layers.append(_empty_layer(doc[page_num]))
            progress.advance(task)

    doc.close()

    console.print("  Merging text layers...")
    try:
        _merge_text_layers(pdf_path, text_layers, output_path)
    except Exception as e:
        console.print(f"  [red]Merge failed: {e}[/red]")
        return None

    size_kb = output_path.stat().st_size // 1024
    console.print(f"  [green]✓ Saved → raw/{pdf_path.name} ({size_kb} KB)[/green]")
    return output_path


def run_annotate(pdf_arg: str | None = None, force: bool = False, move: bool = False):
    """
    Annotate one file or all PDFs in question_bank/scanned/.

    Args:
        pdf_arg: filename or path; None means process all scanned PDFs.
        force:   re-annotate even if output already exists in raw/.
        move:    after success, move original to scanned/done/ so it
                 won't appear in future --all runs.
    """
    try:
        _check_tesseract()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if pdf_arg:
        p = Path(pdf_arg)
        if not p.is_absolute() and not p.exists():
            p = SCANNED_DIR / p.name
        targets = [p]
    else:
        targets = sorted(SCANNED_DIR.glob("*.pdf"))

    if not targets:
        console.print("[yellow]No scanned PDFs found in question_bank/scanned/[/yellow]")
        return

    done_dir = SCANNED_DIR / "done"
    succeeded, failed = 0, 0

    for pdf_path in targets:
        if not pdf_path.exists():
            console.print(f"[red]Not found: {pdf_path}[/red]")
            failed += 1
            continue

        result = annotate_pdf(pdf_path, force=force)
        if result:
            succeeded += 1
            if move:
                done_dir.mkdir(exist_ok=True)
                shutil.move(str(pdf_path), done_dir / pdf_path.name)
                console.print(f"  [dim]Moved original to scanned/done/[/dim]")
        else:
            failed += 1

    console.print(
        f"\n[bold]Done:[/bold] {succeeded} annotated"
        + (f", {failed} failed" if failed else "")
    )
