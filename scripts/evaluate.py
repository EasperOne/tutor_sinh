"""
Stage: Sonnet evaluate — quality scoring for screen-passed exams.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import yaml
from rich.console import Console
from rich.table import Table

console = Console()

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "ma_tran_chuan.yaml"
FEW_SHOT_PATH = ROOT / "config" / "few_shot_evaluate.md"
PROCESSED_DIR = ROOT / "question_bank" / "processed"

EVALUATOR_ROLE = (
    "You are evaluating a Vietnamese biology exam for a private tutor. "
    "Score phan_loai_tu_duy_score (1–10): how well do the P2 and P3 questions "
    "discriminate between good and excellent students. "
    "Score do_chinh_xac_khoa_hoc (1–10): factual correctness. "
    "Return ONLY JSON with keys: phan_loai_tu_duy_score, do_chinh_xac_khoa_hoc, "
    "cau_y_noi_bat (array of {phan, stt, y?, ly_do}), canh_bao (array of strings), nhan_xet (string)."
)


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_classification_summary(classify_data: dict) -> str:
    lines = [
        f"exam_id: {classify_data['exam_id']}",
        f"match_score: {classify_data['ma_tran_match_score']}",
        f"vd_count: {classify_data['vd_count']}",
        f"section_counts: {classify_data['section_counts']}",
        f"muc_do_counts: {classify_data['muc_do_counts']}",
        "",
        "Classification breakdown:",
    ]
    for c in classify_data["classifications"]:
        if c.get("y"):
            lines.append(f"  {c['phan']} câu {c['stt']} ý {c['y']}: {c['chuong']} {c['muc_do']}")
        else:
            lines.append(f"  {c['phan']} câu {c['stt']}: {c['chuong']} {c['muc_do']}")
    return "\n".join(lines)


def call_sonnet_evaluate(exam_id: str, exam_markdown: str, classify_summary: str) -> dict:
    few_shot_content = FEW_SHOT_PATH.read_text(encoding="utf-8")

    client = anthropic.Anthropic()

    system = [
        {"type": "text", "text": EVALUATOR_ROLE},
        {
            "type": "text",
            "text": few_shot_content,
            "cache_control": {"type": "ephemeral"},
        },
    ]

    user_message = (
        f"Evaluate this exam:\n\n"
        f"CLASSIFICATION SUMMARY:\n{classify_summary}\n\n"
        f"EXAM CONTENT:\n{exam_markdown}\n\n"
        "Return JSON with: phan_loai_tu_duy_score, do_chinh_xac_khoa_hoc, "
        "cau_y_noi_bat, canh_bao, nhan_xet."
    )

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )

            usage = response.usage
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            console.print(
                f"  [dim][Sonnet] {exam_id}: {usage.input_tokens} in / "
                f"{usage.output_tokens} out (cached: {cache_read})[/dim]"
            )
            return json.loads(response.content[0].text)

        except json.JSONDecodeError as e:
            raw_path = PROCESSED_DIR / exam_id / "evaluate_raw_error.txt"
            raw_path.write_text(response.content[0].text, encoding="utf-8")
            console.print(f"  [yellow]JSON parse failed, saved to {raw_path}: {e}[/yellow]")
            raise

        except anthropic.APIError as e:
            if attempt == 0:
                console.print(f"  [yellow]API error ({e}), retrying in 10s...[/yellow]")
                time.sleep(10)
            else:
                raise

    raise RuntimeError("Evaluate API call failed after retries")


def evaluate_exam(exam_id: str) -> dict | None:
    exam_dir = PROCESSED_DIR / exam_id
    classify_json_path = exam_dir / "classify.json"
    evaluate_json_path = exam_dir / "evaluate.json"
    md_path = exam_dir / "de.md"

    if evaluate_json_path.exists():
        console.print(f"[dim]Skipping {exam_id} (evaluate.json already exists)[/dim]")
        with open(evaluate_json_path, encoding="utf-8") as f:
            return json.load(f)

    if not classify_json_path.exists():
        console.print(f"[yellow]Skipping {exam_id}: classify.json not found[/yellow]")
        return None

    if not md_path.exists():
        console.print(f"[yellow]Skipping {exam_id}: de.md not found[/yellow]")
        return None

    with open(classify_json_path, encoding="utf-8") as f:
        classify_data = json.load(f)

    if not classify_data.get("screen_pass"):
        console.print(f"[dim]Skipping {exam_id}: screen_pass=False[/dim]")
        return None

    console.print(f"\n[bold cyan]Evaluating {exam_id}[/bold cyan]")

    exam_markdown = md_path.read_text(encoding="utf-8")
    classify_summary = build_classification_summary(classify_data)

    try:
        result = call_sonnet_evaluate(exam_id, exam_markdown, classify_summary)
    except Exception as e:
        console.print(f"  [red]Evaluate failed for {exam_id}: {e}[/red]")
        return None

    output = {
        "exam_id": exam_id,
        "phan_loai_tu_duy_score": result.get("phan_loai_tu_duy_score"),
        "do_chinh_xac_khoa_hoc": result.get("do_chinh_xac_khoa_hoc"),
        "cau_y_noi_bat": result.get("cau_y_noi_bat", []),
        "canh_bao": result.get("canh_bao", []),
        "nhan_xet": result.get("nhan_xet", ""),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    evaluate_json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"  [green]Saved evaluate.json[/green]")
    return output


def run_evaluate(threshold: float | None = None) -> list[dict]:
    config = load_config()
    if threshold is None:
        threshold = config["screen"]["list_a_match_min"]

    results = []
    exam_dirs = sorted(PROCESSED_DIR.iterdir()) if PROCESSED_DIR.exists() else []

    for exam_dir in exam_dirs:
        if not exam_dir.is_dir() or exam_dir.name.startswith("."):
            continue
        classify_json = exam_dir / "classify.json"
        evaluate_json = exam_dir / "evaluate.json"
        if not classify_json.exists():
            continue
        with open(classify_json, encoding="utf-8") as f:
            c = json.load(f)
        if not c.get("screen_pass") or c.get("ma_tran_match_score", 0) < threshold:
            continue
        if evaluate_json.exists():
            continue
        result = evaluate_exam(exam_dir.name)
        if result:
            results.append(result)

    return results


def print_evaluate_summary(results: list[dict]):
    if not results:
        console.print("[dim]No new evaluations.[/dim]")
        return

    table = Table(title="Evaluate Results", show_header=True)
    table.add_column("Exam ID", style="cyan")
    table.add_column("Tư duy", justify="right")
    table.add_column("Chính xác KH", justify="right")
    table.add_column("Cảnh báo", justify="center")

    for r in results:
        canh_bao = "[red]⚠[/red]" if r.get("canh_bao") else "[green]✓[/green]"
        table.add_row(
            r["exam_id"],
            str(r.get("phan_loai_tu_duy_score", "—")),
            str(r.get("do_chinh_xac_khoa_hoc", "—")),
            canh_bao,
        )

    console.print(table)
