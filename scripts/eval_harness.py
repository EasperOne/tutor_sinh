"""
Pure Python evaluation harness for classification quality.
Zero API calls. Reads classify.json + ground_truth/*.json, outputs metrics.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "question_bank" / "processed"
GROUND_TRUTH_DIR = ROOT / "eval" / "ground_truth"
RESULTS_DIR = ROOT / "eval" / "results"
DB_PATH = ROOT / "tutor_sinh.db"

console = Console()


def load_classify(exam_id: str) -> list[dict]:
    path = PROCESSED_DIR / exam_id / "classify.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("classifications", [])


def load_ground_truth(exam_id: str) -> list[dict] | None:
    path = GROUND_TRUTH_DIR / f"{exam_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _item_key(item: dict) -> tuple:
    return (item["phan"], item["stt"], item.get("y") or "")


def evaluate_exam(exam_id: str) -> dict | None:
    pred = load_classify(exam_id)
    truth = load_ground_truth(exam_id)
    if truth is None:
        console.print(f"  [dim]No ground truth for {exam_id}, skipping[/dim]")
        return None
    if not pred:
        console.print(f"  [yellow]No classify.json for {exam_id}, skipping[/yellow]")
        return None

    pred_map = {_item_key(c): c for c in pred}
    truth_map = {_item_key(c): c for c in truth}

    keys = set(pred_map) | set(truth_map)
    total = len(keys)
    correct = 0
    phan_correct: dict[str, int] = defaultdict(int)
    phan_total: dict[str, int] = defaultdict(int)
    chuong_correct: dict[str, int] = defaultdict(int)
    chuong_total: dict[str, int] = defaultdict(int)
    muc_correct: dict[str, int] = defaultdict(int)
    muc_total: dict[str, int] = defaultdict(int)
    optional_fields = ["skill", "competency", "calculation_load", "bo_gd_fit"]
    optional_correct: dict[str, int] = defaultdict(int)
    optional_total: dict[str, int] = defaultdict(int)
    confidence_buckets = {
        "high": {"total": 0, "errors": 0},
        "low": {"total": 0, "errors": 0},
    }
    confusion: list[dict] = []

    for key in keys:
        p = pred_map.get(key)
        t = truth_map.get(key)
        if p is None or t is None:
            continue
        phan = t["phan"]
        phan_total[phan] += 1
        chuong_total[t["chuong"]] += 1
        muc_total[t["muc_do"]] += 1

        is_core_correct = p["chuong"] == t["chuong"] and p["muc_do"] == t["muc_do"]
        conf = p.get("confidence")
        if isinstance(conf, (int, float)):
            bucket = "high" if conf >= 0.8 else "low" if conf < 0.7 else None
            if bucket:
                confidence_buckets[bucket]["total"] += 1
                if not is_core_correct:
                    confidence_buckets[bucket]["errors"] += 1

        for field in optional_fields:
            if field in t:
                optional_total[field] += 1
                if p.get(field) == t.get(field):
                    optional_correct[field] += 1

        if is_core_correct:
            correct += 1
            phan_correct[phan] += 1
            chuong_correct[t["chuong"]] += 1
            muc_correct[t["muc_do"]] += 1
        else:
            confusion.append({
                "phan": phan, "stt": key[1], "y": key[2],
                "pred_chuong": p["chuong"], "pred_muc_do": p["muc_do"],
                "true_chuong": t["chuong"], "true_muc_do": t["muc_do"],
            })

    acc = correct / total if total else 0.0
    return {
        "exam_id": exam_id,
        "total_items": total,
        "correct": correct,
        "overall_accuracy": round(acc, 4),
        "phan_accuracy": {
            p: round(phan_correct[p] / phan_total[p], 4) if phan_total[p] else 0.0
            for p in phan_total
        },
        "chuong_accuracy": {
            c: round(chuong_correct[c] / chuong_total[c], 4) if chuong_total[c] else 0.0
            for c in chuong_total
        },
        "muc_do_accuracy": {
            m: round(muc_correct[m] / muc_total[m], 4) if muc_total[m] else 0.0
            for m in muc_total
        },
        "optional_accuracy": {
            field: round(optional_correct[field] / optional_total[field], 4)
            for field in optional_total
        },
        "confidence_error_rate": {
            bucket: round(v["errors"] / v["total"], 4) if v["total"] else None
            for bucket, v in confidence_buckets.items()
        },
        "confusion": confusion,
    }


def aggregate_metrics(exam_metrics: list[dict]) -> dict:
    total_items = sum(e["total_items"] for e in exam_metrics)
    total_correct = sum(e["correct"] for e in exam_metrics)
    return {
        "exam_count": len(exam_metrics),
        "total_items": total_items,
        "aggregate_accuracy": round(total_correct / total_items, 4) if total_items else 0.0,
    }


def top_errors(exam_metrics: list[dict], n: int = 20) -> list[dict]:
    counter: dict[tuple, int] = defaultdict(int)
    for em in exam_metrics:
        for c in em["confusion"]:
            key = (c["pred_chuong"], c["pred_muc_do"], c["true_chuong"], c["true_muc_do"])
            counter[key] += 1
    sorted_errors = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    return [
        {"pred_chuong": k[0], "pred_muc_do": k[1],
         "true_chuong": k[2], "true_muc_do": k[3], "count": v}
        for k, v in sorted_errors[:n]
    ]


def run_eval(batch_id: str | None = None, exam_ids: list[str] | None = None):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if batch_id is None:
        batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if exam_ids is None:
        exam_ids = [d.name for d in sorted(PROCESSED_DIR.iterdir()) if d.is_dir()]

    console.print(f"\n[bold cyan]Eval batch {batch_id}[/bold cyan] — {len(exam_ids)} exams")

    exam_metrics = []
    for exam_id in exam_ids:
        result = evaluate_exam(exam_id)
        if result:
            exam_metrics.append(result)
            icon = "[green]✓[/green]" if result["overall_accuracy"] >= 0.85 else "[red]✗[/red]"
            console.print(f"  {icon} {exam_id}: {result['overall_accuracy']:.3f}")

    if not exam_metrics:
        console.print("[yellow]No exams evaluated (no ground truth found).[/yellow]")
        return

    agg = aggregate_metrics(exam_metrics)
    errors = top_errors(exam_metrics)

    metrics_out = {
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "aggregate": agg,
        "per_exam": {e["exam_id"]: e for e in exam_metrics},
    }
    errors_out = {"batch_id": batch_id, "top_errors": errors}

    metrics_path = RESULTS_DIR / f"batch_{batch_id}_metrics.json"
    errors_path = RESULTS_DIR / f"batch_{batch_id}_top_errors.json"
    metrics_path.write_text(json.dumps(metrics_out, ensure_ascii=False, indent=2), encoding="utf-8")
    errors_path.write_text(json.dumps(errors_out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write to DB if available
    if DB_PATH.exists():
        try:
            db = sqlite3.connect(DB_PATH)
            db.execute(
                "INSERT OR REPLACE INTO eval_batches (id, exam_ids_json, metrics_json, top_errors_json) VALUES (?,?,?,?)",
                (batch_id, json.dumps(exam_ids), json.dumps(metrics_out), json.dumps(errors_out)),
            )
            db.commit()
            db.close()
        except Exception as e:
            console.print(f"[yellow]DB write failed: {e}[/yellow]")

    t = Table(title=f"Results — batch {batch_id}")
    t.add_column("Metric"); t.add_column("Value")
    t.add_row("Exams evaluated", str(agg["exam_count"]))
    t.add_row("Total items", str(agg["total_items"]))
    t.add_row("Aggregate accuracy", f"{agg['aggregate_accuracy']:.3f}")
    console.print(t)
    console.print(f"[green]✓ {metrics_path}[/green]")
    console.print(f"[green]✓ {errors_path}[/green]")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id")
    parser.add_argument("--exam-ids", nargs="*")
    args = parser.parse_args()
    run_eval(batch_id=args.batch_id, exam_ids=args.exam_ids)
