# tutor-sinh

Biology tutor workflow CLI for managing weekly exam practice sessions.

## Setup

```bash
# Install dependencies
uv pip install -e .

# Activate environment
source .venv/bin/activate

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

## Google Sheets Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com) → IAM & Admin → Service Accounts
2. Create a service account and download the JSON key
3. Save the key to `config/service_account.json`
4. Create a Google Sheet and share it with the service account email (Editor access)
5. Copy the Sheet ID from the URL and set `GOOGLE_SHEET_ID` in `.env`

Run the one-time sheet setup:
```bash
python scripts/setup_sheet.py
```

## One-Time Exam Bank Setup

Drop your exam PDFs into `question_bank/raw/`, then run:

```bash
# Classify all exams (PDF → markdown → chapter/difficulty labels)
tutor classify --all

# Evaluate screen-passed exams with Sonnet
tutor evaluate

# Generate shortlists
tutor shortlist
```

The shortlists appear in `question_bank/shortlist/`:
- `A_bam_ma_tran.md` — exams matching the Ministry matrix (recommended for exam practice)
- `B_kho_lech_ma_tran.md` — off-matrix exams with many hard questions (for advanced drilling)

## Per-Session Workflow

After grading each session:

1. Create `sessions/YYYY-MM-DD/session.yaml` with the wrong questions:

```yaml
date: 2025-04-23
exam_id: de_001
wrong_questions:
  - {phan: P1, stt: 7}
  - {phan: P2, stt: 2, y: b}
  - {phan: P3, stt: 1}
```

2. Push to Google Sheet:

```bash
tutor push 2025-04-23
```

When ready to make a review sheet:

3. Create `compose_input.json` with questions selected from the Sheet:

```json
{
  "title": "Ôn tập Di truyền - 2025-04-30",
  "questions": [
    {"exam_id": "de_001", "phan": "P1", "stt": 7},
    {"exam_id": "de_001", "phan": "P2", "stt": 3, "y_list": ["a", "b", "c", "d"]},
    {"exam_id": "de_002", "phan": "P3", "stt": 2}
  ]
}
```

4. Generate the review PDF:

```bash
tutor compose compose_input.json
```

## Filling Few-Shot Files

Before running `tutor classify`, add 3–5 real example questions to `config/few_shot_classify.md`.
Before running `tutor evaluate`, add 2–3 exam examples to `config/few_shot_evaluate.md`.

See each file for the required format.

## Accuracy Evaluation

Copy `eval/ground_truth_template.xlsx` to `eval/ground_truth.xlsx` and fill in the correct labels.

```bash
tutor eval-accuracy
```

Report is saved to `eval/accuracy_report.md`.

## Commands

| Command | Description |
|---------|-------------|
| `tutor classify <PDF>` | Classify a single exam |
| `tutor classify --all` | Classify all unprocessed PDFs |
| `tutor evaluate` | Evaluate screen-passed exams |
| `tutor shortlist` | Regenerate List A / List B |
| `tutor push <date>` | Push session data to Google Sheet |
| `tutor compose <json>` | Generate review PDF |
| `tutor eval-accuracy` | Run accuracy evaluation |
