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


@app.command()
def classify(
    pdf: str = typer.Argument(None, help="Path to a PDF in question_bank/raw/ (or just the filename)"),
    all: bool = typer.Option(False, "--all", help="Process all unprocessed PDFs in question_bank/raw/"),
    force: bool = typer.Option(False, "--force", help="Reprocess even if classify.json already exists"),
):
    """
    Classify exam questions by chapter and difficulty. Stage 1-3 pipeline.
    """
    from scripts.classify import (
        classify_exam,
        load_config,
        print_summary_table,
        run_classify_all,
    )
    from scripts.classify import RAW_DIR, PROCESSED_DIR

    if all:
        results = run_classify_all(force=force)
        print_summary_table(results)
        return

    if not pdf:
        console.print("[red]Error: provide a PDF path or use --all[/red]")
        raise typer.Exit(1)

    pdf_path = Path(pdf)
    if not pdf_path.is_absolute():
        if (RAW_DIR / pdf_path.name).exists():
            pdf_path = RAW_DIR / pdf_path.name
        elif pdf_path.exists():
            pass
        else:
            pdf_path = RAW_DIR / pdf_path.name

    if not pdf_path.exists():
        console.print(f"[red]PDF not found: {pdf_path}[/red]")
        raise typer.Exit(1)

    result = classify_exam(pdf_path, force=force)
    if result:
        print_summary_table([result])


@app.command()
def evaluate(
    threshold: float = typer.Option(None, "--threshold", help="Minimum match_score to evaluate (default from config)"),
):
    """
    Quality-evaluate screen-passed exams using Sonnet.
    """
    from scripts.evaluate import print_evaluate_summary, run_evaluate

    results = run_evaluate(threshold=threshold)
    print_evaluate_summary(results)

    if not results:
        console.print("[dim]All eligible exams already evaluated. Use --force-classify to reprocess.[/dim]")


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
    OCR-annotate scanned exam PDFs using Google Cloud Vision.

    Reads from question_bank/scanned/, writes annotated PDFs to question_bank/raw/.
    Requires GOOGLE_SERVICE_ACCOUNT_JSON and Cloud Vision API enabled.
    """
    from scripts.ocr_annotate import run_annotate

    run_annotate(pdf_arg=pdf, force=force, move=move)


@app.command(name="eval-accuracy")
def eval_accuracy():
    """
    Compare classify output against eval/ground_truth.xlsx for accuracy metrics.
    """
    from scripts.eval_accuracy import run_eval_accuracy

    run_eval_accuracy()


if __name__ == "__main__":
    app()
