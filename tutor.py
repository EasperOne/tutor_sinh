"""
tutor-sinh — CLI entry point.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv(Path(__file__).parent / ".env")

app = typer.Typer(
    name="tutor",
    help="Biology tutor workflow CLI — classify exams, track sessions, compose review PDFs.",
    add_completion=False,
)
console = Console()

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PROCESSED_DIR = ROOT / "question_bank" / "processed"


@app.command()
def form(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind"),
    port: int = typer.Option(5000, "--port", help="Port to listen on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open browser automatically"),
):
    """
    Start the web form server for manual exam classification.
    """
    from scripts.form_server import run_server

    run_server(host=host, port=port, open_browser=not no_browser)


@app.command(name="gen-prompt")
def gen_prompt(
    exam_id: str = typer.Argument(..., help="Exam ID (folder name under question_bank/processed/)"),
):
    """
    Export exam markdown for pasting into Claude.ai Project for classification.

    Prints the de.md content to stdout and copies it to the clipboard if possible.
    """
    exam_dir = PROCESSED_DIR / exam_id
    md_path = exam_dir / "de.md"

    if not md_path.exists():
        console.print(f"[red]de.md not found for {exam_id}.[/red]")
        console.print(f"  Expected: {md_path}")
        raise typer.Exit(1)

    content = md_path.read_text(encoding="utf-8")

    prompt = (
        f"Classify all questions in this exam:\n\n{content}\n\n"
        "Return JSON with key 'classifications' containing an array of classification objects. "
        "Each object must have: phan (P1/P2/P3), stt (int), chuong (code), muc_do (B/H/VD). "
        "For P2 items also include: y (a/b/c/d). "
        "Return ONLY the JSON object. No markdown, no prose."
    )

    copied = False
    try:
        import subprocess
        result = subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=prompt.encode(),
            capture_output=True,
        )
        if result.returncode == 0:
            copied = True
    except FileNotFoundError:
        pass

    if not copied:
        try:
            import subprocess
            result = subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=prompt.encode(),
                capture_output=True,
            )
            if result.returncode == 0:
                copied = True
        except FileNotFoundError:
            pass

    if not copied:
        try:
            import subprocess
            result = subprocess.run(
                ["wl-copy"],
                input=prompt.encode(),
                capture_output=True,
            )
            if result.returncode == 0:
                copied = True
        except FileNotFoundError:
            pass

    console.print(f"\n[bold cyan]── Prompt for {exam_id} ──[/bold cyan]")
    console.print(prompt)
    console.print(f"\n[bold cyan]────────────────────────[/bold cyan]")

    if copied:
        console.print("[green]✓ Đã copy vào clipboard.[/green]")
    else:
        console.print("[yellow]Clipboard không khả dụng — copy thủ công từ output trên.[/yellow]")

    console.print(
        f"\n[dim]Sau khi nhận JSON từ Claude, chạy:[/dim]\n"
        f"  [bold]tutor import-json {exam_id}[/bold]"
    )


@app.command(name="import-json")
def import_json(
    exam_id: str = typer.Argument(..., help="Exam ID (folder name under question_bank/processed/)"),
    file: str = typer.Option(None, "--file", "-f", help="Path to JSON file (default: read from stdin)"),
):
    """
    Save classification JSON from Claude.ai into the processed folder.

    Reads JSON from stdin (or --file) and saves it as classify.json,
    then regenerates ma_tran_de.xlsx.

    Usage:
        tutor import-json de_001                # paste JSON, then Ctrl+D
        tutor import-json de_001 --file out.json
    """
    import json
    from datetime import datetime, timezone

    from scripts.classification_schema import summarize_classification_style, validate_classifications
    from scripts.classify import build_matrix_excel, load_config, compute_screen_score
    from scripts.source_profiles import detect_source_profile

    if file:
        file_path = Path(file)
        if not file_path.exists():
            console.print(f"[red]File not found: {file_path}[/red]")
            raise typer.Exit(1)
        raw = file_path.read_text(encoding="utf-8")
    else:
        console.print("[dim]Paste JSON below, then press Ctrl+D (Linux/Mac) or Ctrl+Z Enter (Windows):[/dim]")
        raw = sys.stdin.read()

    raw = raw.strip()
    if not raw:
        console.print("[red]No input received.[/red]")
        raise typer.Exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON: {e}[/red]")
        raise typer.Exit(1)

    classifications = data.get("classifications")
    if not isinstance(classifications, list):
        console.print("[red]JSON must have a 'classifications' list.[/red]")
        raise typer.Exit(1)

    exam_dir = PROCESSED_DIR / exam_id
    exam_dir.mkdir(parents=True, exist_ok=True)

    config = load_config()
    validation = validate_classifications(classifications, strict_new_fields=False)
    if validation["errors"]:
        console.print("[red]Classification validation failed:[/red]")
        for err in validation["errors"][:10]:
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(1)
    if validation["warnings"]:
        console.print(f"[yellow]Validation warnings:[/yellow] {len(validation['warnings'])}")

    match_score, vd_count, screen_pass = compute_screen_score(classifications, config)

    p1 = len([c for c in classifications if c["phan"] == "P1"])
    p2 = len([c for c in classifications if c["phan"] == "P2"])
    p3 = len([c for c in classifications if c["phan"] == "P3"])

    muc_do_counts: dict[str, int] = {}
    for c in classifications:
        md = c.get("muc_do", "?")
        muc_do_counts[md] = muc_do_counts.get(md, 0) + 1

    output = {
        "exam_id": exam_id,
        "source_pdf": str(ROOT / "question_bank" / "raw" / f"{exam_id}.pdf"),
        "source_profile": detect_source_profile(exam_id),
        "ma_tran_match_score": match_score,
        "vd_count": vd_count,
        "section_counts": {"P1": p1, "P2_items": p2, "P3": p3},
        "muc_do_counts": muc_do_counts,
        "style_summary": summarize_classification_style(classifications),
        "validation": validation,
        "classifications": classifications,
        "screen_pass": screen_pass,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    classify_json_path = exam_dir / "classify.json"
    classify_json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[green]✓ Đã lưu classify.json[/green] (match={match_score:.2f}, vd={vd_count}, pass={screen_pass})")

    try:
        build_matrix_excel(exam_id, classifications, exam_dir, config)
    except Exception as e:
        console.print(f"[yellow]Warning: could not build ma_tran_de.xlsx: {e}[/yellow]")


@app.command(name="validate-classify")
def validate_classify(
    exam_id: str = typer.Argument(..., help="Exam ID under question_bank/processed/"),
    strict: bool = typer.Option(False, "--strict", help="Require all new extended fields"),
):
    """
    Validate classify.json shape, counts, enums, and extended tags.
    """
    import json
    from scripts.classification_schema import validate_classifications

    path = PROCESSED_DIR / exam_id / "classify.json"
    if not path.exists():
        console.print(f"[red]classify.json not found: {path}[/red]")
        raise typer.Exit(1)
    data = json.loads(path.read_text(encoding="utf-8"))
    result = validate_classifications(data.get("classifications", []), strict_new_fields=strict)
    if result["errors"]:
        console.print("[red]Validation failed[/red]")
        for err in result["errors"]:
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(1)
    console.print("[green]✓ classify.json is valid[/green]")
    if result["warnings"]:
        console.print(f"[yellow]{len(result['warnings'])} warning(s):[/yellow]")
        for warning in result["warnings"][:20]:
            console.print(f"  [yellow]- {warning}[/yellow]")


@app.command()
def web(
    host: str = typer.Option(None, "--host", help="Override TUTOR_HOST from .env"),
    port: int = typer.Option(None, "--port", help="Override TUTOR_PORT from .env"),
):
    """
    Start the tutor-sinh v2 web app.
    """
    import os as _os
    from app import create_app, HOST as _HOST, PORT as _PORT

    _host = host or _HOST
    _port = port or _PORT
    flask_app = create_app()
    console.print(f"[bold green]tutor-sinh v2[/bold green] running on http://{_host}:{_port}")
    flask_app.run(host=_host, port=_port, debug=(_host == "127.0.0.1"))


@app.command()
def shortlist():
    """
    Regenerate List A and List B shortlist markdown files.
    """
    from scripts.shortlist import run_shortlist

    run_shortlist()


@app.command()
def push(
    session_folder: str = typer.Argument(..., help="Session folder path or date (e.g. '2025-04-23')"),
):
    """
    Push session wrong-answer data to Google Sheet master tracker.
    """
    from scripts.push_sheet import run_push

    try:
        run_push(session_folder)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]Configuration error:[/red]\n{e}")
        raise typer.Exit(1)


@app.command()
def compose(
    compose_json: str = typer.Argument(..., help="Path to compose_input.json"),
    output: str = typer.Option(None, "--output", help="Output PDF path (default: sessions/<today>/nhac_nho_<title>.pdf)"),
):
    """
    Compose a reminder/review PDF from a selected question list.
    """
    from scripts.compose_nhac_nho import run_compose

    compose_path = Path(compose_json)
    if not compose_path.exists():
        console.print(f"[red]File not found: {compose_path}[/red]")
        raise typer.Exit(1)

    output_path = Path(output) if output else None

    try:
        run_compose(compose_path, output_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command()
def ocr(
    pdf: str = typer.Argument(None, help="Filename in question_bank/scanned/ (omit to process all)"),
    force: bool = typer.Option(False, "--force", help="Re-annotate even if output already exists in raw/"),
    move: bool = typer.Option(False, "--move", help="Move originals to scanned/done/ after success"),
):
    """
    OCR-annotate scanned exam PDFs using Tesseract.

    Reads from question_bank/scanned/, writes annotated PDFs to question_bank/raw/.
    Requires tesseract + vie language pack (sudo apt install tesseract-ocr tesseract-ocr-vie).
    """
    from scripts.ocr_annotate import run_annotate

    run_annotate(pdf_arg=pdf, force=force, move=move)


if __name__ == "__main__":
    app()
