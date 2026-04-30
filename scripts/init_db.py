"""
Initialize and seed the tutor_sinh SQLite database.

Usage:
  python scripts/init_db.py            # CREATE IF NOT EXISTS (safe to repeat)
  python scripts/init_db.py --reset    # DROP and recreate all tables
  python scripts/init_db.py --seed     # import classify.json + session YAML files
  python scripts/init_db.py --reset --seed
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import yaml
from rich.console import Console

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "tutor_sinh.db"
PROCESSED_DIR = ROOT / "question_bank" / "processed"
SESSIONS_DIR = ROOT / "sessions"

console = Console()

SCHEMA = """
CREATE TABLE IF NOT EXISTS exams (
    id TEXT PRIMARY KEY,
    pdf_path TEXT,
    md_path TEXT,
    md_quality_score REAL,
    classify_status TEXT DEFAULT 'pending',
    ma_tran_match_score REAL,
    screen_pass INTEGER DEFAULT 0,
    vd_count INTEGER DEFAULT 0,
    section_counts_json TEXT,
    muc_do_counts_json TEXT,
    source_type TEXT,
    source_profile_json TEXT,
    style_summary_json TEXT,
    validation_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    phan TEXT NOT NULL,
    stt INTEGER NOT NULL,
    y TEXT,
    chuong TEXT,
    muc_do TEXT,
    skill TEXT,
    competency TEXT,
    calculation_load TEXT,
    bo_gd_fit TEXT,
    confidence REAL,
    classify_notes TEXT,
    question_text TEXT,
    UNIQUE(exam_id, phan, stt, y)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date TEXT NOT NULL,
    exam_id TEXT NOT NULL REFERENCES exams(id),
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wrong_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    phan TEXT NOT NULL,
    stt INTEGER NOT NULL,
    y TEXT,
    sai_ngu INTEGER DEFAULT 0,
    on_tap_status TEXT DEFAULT 'not_yet',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS study_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_json TEXT,
    plan_markdown TEXT,
    progress_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS review_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    question_ids_json TEXT DEFAULT '[]',
    filters_json TEXT DEFAULT '{}',
    pdf_path TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS eval_batches (
    id TEXT PRIMARY KEY,
    exam_ids_json TEXT,
    metrics_json TEXT,
    top_errors_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS guideline_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_batch_id TEXT,
    proposal_markdown TEXT,
    proposed_changes_json TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);
"""

DROP_ALL = """
DROP TABLE IF EXISTS wrong_answers;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS questions;
DROP TABLE IF EXISTS exams;
DROP TABLE IF EXISTS study_plans;
DROP TABLE IF EXISTS review_sets;
DROP TABLE IF EXISTS eval_batches;
DROP TABLE IF EXISTS guideline_proposals;
"""


def init_db(reset: bool = False) -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    if reset:
        console.print("[yellow]Dropping all tables...[/yellow]")
        db.executescript(DROP_ALL)
    db.executescript(SCHEMA)
    _run_migrations(db)
    db.commit()
    console.print(f"[green]✓ Database ready: {DB_PATH}[/green]")
    return db


def _run_migrations(db: sqlite3.Connection):
    for table, column, ddl in (
        ("exams", "source_type", "ALTER TABLE exams ADD COLUMN source_type TEXT"),
        ("exams", "source_profile_json", "ALTER TABLE exams ADD COLUMN source_profile_json TEXT"),
        ("exams", "style_summary_json", "ALTER TABLE exams ADD COLUMN style_summary_json TEXT"),
        ("exams", "validation_json", "ALTER TABLE exams ADD COLUMN validation_json TEXT"),
        ("questions", "skill", "ALTER TABLE questions ADD COLUMN skill TEXT"),
        ("questions", "competency", "ALTER TABLE questions ADD COLUMN competency TEXT"),
        ("questions", "calculation_load", "ALTER TABLE questions ADD COLUMN calculation_load TEXT"),
        ("questions", "bo_gd_fit", "ALTER TABLE questions ADD COLUMN bo_gd_fit TEXT"),
        ("questions", "confidence", "ALTER TABLE questions ADD COLUMN confidence REAL"),
        ("questions", "classify_notes", "ALTER TABLE questions ADD COLUMN classify_notes TEXT"),
        ("sessions", "score", "ALTER TABLE sessions ADD COLUMN score REAL"),
        ("wrong_answers", "reviewed_at", "ALTER TABLE wrong_answers ADD COLUMN reviewed_at TEXT"),
        ("wrong_answers", "review_count", "ALTER TABLE wrong_answers ADD COLUMN review_count INTEGER DEFAULT 0"),
    ):
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            db.execute(ddl)


def seed_exams(db: sqlite3.Connection):
    from scripts.quality_check import check_file
    from scripts.classification_schema import summarize_classification_style, validate_classifications
    from scripts.source_profiles import detect_source_profile

    exam_dirs = sorted(d for d in PROCESSED_DIR.iterdir() if d.is_dir()) if PROCESSED_DIR.exists() else []
    if not exam_dirs:
        console.print("[dim]No processed exams found.[/dim]")
        return

    for exam_dir in exam_dirs:
        exam_id = exam_dir.name
        classify_path = exam_dir / "classify.json"
        md_path = exam_dir / "de.md"
        pdf_path = ROOT / "question_bank" / "raw" / f"{exam_id}.pdf"

        # Quality score
        md_quality = None
        if md_path.exists():
            result = check_file(md_path)
            md_quality = result["score"]

        # Classify data
        classify_status = "pending"
        match_score = vd_count = None
        section_counts = muc_do_counts = None
        source_profile = detect_source_profile(exam_id)
        source_type = source_profile["source_type"]
        style_summary = {}
        validation = {"errors": [], "warnings": []}
        screen_pass = 0
        classifications = []

        if classify_path.exists():
            try:
                with open(classify_path, encoding="utf-8") as f:
                    clf = json.load(f)
                classifications = clf.get("classifications", [])
                source_profile = clf.get("source_profile") or source_profile
                source_type = source_profile.get("source_type", source_type)
                validation = clf.get("validation") or validate_classifications(classifications, strict_new_fields=False)
                style_summary = clf.get("style_summary") or summarize_classification_style(classifications)
                classify_status = "done" if len(classifications) >= 40 else "partial"
                match_score = clf.get("ma_tran_match_score")
                vd_count = clf.get("vd_count")
                section_counts = json.dumps(clf.get("section_counts", {}))
                muc_do_counts = json.dumps(clf.get("muc_do_counts", {}))
                screen_pass = 1 if clf.get("screen_pass") else 0
            except Exception as e:
                console.print(f"  [yellow]⚠ {exam_id}: classify.json parse error: {e}[/yellow]")

        try:
            db.execute(
                """INSERT INTO exams
                   (id, pdf_path, md_path, md_quality_score, classify_status,
                    ma_tran_match_score, screen_pass, vd_count,
                    section_counts_json, muc_do_counts_json,
                    source_type, source_profile_json, style_summary_json, validation_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     pdf_path=excluded.pdf_path,
                     md_path=excluded.md_path,
                     md_quality_score=excluded.md_quality_score,
                     classify_status=excluded.classify_status,
                     ma_tran_match_score=excluded.ma_tran_match_score,
                     screen_pass=excluded.screen_pass,
                     vd_count=excluded.vd_count,
                     section_counts_json=excluded.section_counts_json,
                     muc_do_counts_json=excluded.muc_do_counts_json,
                     source_type=excluded.source_type,
                     source_profile_json=excluded.source_profile_json,
                     style_summary_json=excluded.style_summary_json,
                     validation_json=excluded.validation_json,
                     updated_at=datetime('now')""",
                (exam_id,
                 str(pdf_path.relative_to(ROOT)) if pdf_path.exists() else None,
                 str(md_path.relative_to(ROOT)) if md_path.exists() else None,
                 md_quality, classify_status, match_score, screen_pass,
                 vd_count, section_counts, muc_do_counts,
                 source_type, json.dumps(source_profile, ensure_ascii=False),
                 json.dumps(style_summary, ensure_ascii=False),
                 json.dumps(validation, ensure_ascii=False)),
            )

            if classifications:
                db.execute("DELETE FROM questions WHERE exam_id=?", (exam_id,))
                for c in classifications:
                    db.execute(
                        """INSERT INTO questions
                           (exam_id, phan, stt, y, chuong, muc_do,
                            skill, competency, calculation_load, bo_gd_fit, confidence, classify_notes)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            exam_id, c["phan"], c["stt"], c.get("y"), c.get("chuong"), c.get("muc_do"),
                            c.get("skill"), c.get("competency"), c.get("calculation_load"),
                            c.get("bo_gd_fit"), c.get("confidence"), c.get("notes"),
                        ),
                    )

            db.commit()
            console.print(f"  [green]✓ {exam_id}[/green] ({classify_status}, {len(classifications)} questions)")
        except Exception as e:
            console.print(f"  [red]✗ {exam_id}: {e}[/red]")


def seed_sessions(db: sqlite3.Connection):
    yaml_files = sorted(SESSIONS_DIR.glob("*.yaml")) if SESSIONS_DIR.exists() else []
    # Also check subdirectory session.yaml files
    for subdir in SESSIONS_DIR.iterdir() if SESSIONS_DIR.exists() else []:
        if subdir.is_dir():
            f = subdir / "session.yaml"
            if f.exists():
                yaml_files.append(f)

    if not yaml_files:
        console.print("[dim]No session YAML files found.[/dim]")
        return

    for yaml_path in yaml_files:
        try:
            with open(yaml_path, encoding="utf-8") as f:
                sessions_data = yaml.safe_load(f)
            if not isinstance(sessions_data, list):
                sessions_data = [sessions_data]
        except Exception as e:
            console.print(f"  [yellow]⚠ {yaml_path.name}: {e}[/yellow]")
            continue

        for session_data in sessions_data:
            if not isinstance(session_data, dict):
                continue
            exam_id = session_data.get("exam_id", "")
            session_date = str(session_data.get("date", ""))
            wrong_questions = session_data.get("wrong_questions", [])

            # Check exam exists in DB
            row = db.execute("SELECT id FROM exams WHERE id=?", (exam_id,)).fetchone()
            if not row:
                console.print(f"  [dim]Skipping session for {exam_id} (not in exams table)[/dim]")
                continue

            try:
                existing = db.execute(
                    "SELECT id FROM sessions WHERE session_date=? AND exam_id=?",
                    (session_date, exam_id),
                ).fetchone()
                if existing:
                    db.execute("DELETE FROM wrong_answers WHERE session_id=?", (existing[0],))
                    db.execute("DELETE FROM sessions WHERE id=?", (existing[0],))

                cur = db.execute(
                    "INSERT INTO sessions (session_date, exam_id) VALUES (?,?)",
                    (session_date, exam_id),
                )
                session_id = cur.lastrowid

                for wq in wrong_questions:
                    phan = wq.get("phan", "")
                    stt = wq.get("stt")
                    y = wq.get("y")
                    db.execute(
                        """INSERT INTO wrong_answers (session_id, phan, stt, y)
                           VALUES (?,?,?,?)""",
                        (session_id, phan, stt, y),
                    )
                db.commit()
                console.print(f"  [green]✓ session {session_date}/{exam_id}[/green] ({len(wrong_questions)} wrong)")
            except Exception as e:
                db.rollback()
                console.print(f"  [red]✗ session {session_date}/{exam_id}: {e}[/red]")


def main():
    parser = argparse.ArgumentParser(description="Initialize tutor_sinh database")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables")
    parser.add_argument("--seed", action="store_true", help="Import existing classify.json and session YAMLs")
    args = parser.parse_args()

    db = init_db(reset=args.reset)

    if args.seed:
        console.print("\n[bold]Seeding exams...[/bold]")
        seed_exams(db)
        console.print("\n[bold]Seeding sessions...[/bold]")
        seed_sessions(db)

    db.close()
    console.print("\n[bold green]Done.[/bold green]")


if __name__ == "__main__":
    main()
