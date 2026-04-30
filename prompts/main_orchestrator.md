# Main Orchestrator Instructions

You are the main orchestration agent for batch classification of biology exams.

## Your task

Classify all unprocessed exams (those with `de.md` but no `classify.json`) using sub-agents.

The sub-agent only labels question content. After each sub-agent finishes, you must run deterministic repo tooling to:

- validate counts and extended classification fields
- compute `ma_tran_match_score`
- attach source metadata
- attach style summary and validation metadata
- write the enriched `classify.json`

Do not ask the sub-agent to compute matrix scores, source normalization, or student-performance conclusions.

## Step 1 — Find unprocessed exams

```bash
.venv/bin/python -c "
import json
from pathlib import Path
processed = Path('question_bank/processed')
for d in sorted(processed.iterdir()):
    md = d / 'de.md'
    clf = d / 'classify.json'
    if md.exists() and not clf.exists():
        print(d.name)
"
```

If the list is empty: all exams already classified. Report and stop.

## Step 2 — Classify each exam

For each exam_id from Step 1, use the Task tool (or spawn a sub-agent session) with this exact prompt:

> Read prompts/sub_agent_classify.md and follow it exactly.
> The exam to classify is: **{exam_id}**

Process exams ONE AT A TIME. Do not batch multiple exams in one sub-agent call.

The sub-agent should write a raw JSON object with a `classifications` array to:

```text
question_bank/processed/<exam_id>/classify.json
```

## Step 3 — Validate raw output

After each sub-agent completes, check:

```bash
.venv/bin/python -c "
import json
data = json.load(open('question_bank/processed/{exam_id}/classify.json'))
clf = data.get('classifications', [])
p1 = sum(1 for c in clf if c['phan']=='P1')
p2 = sum(1 for c in clf if c['phan']=='P2')
p3 = sum(1 for c in clf if c['phan']=='P3')
print(f'P1={p1}/18  P2={p2}/16  P3={p3}/6  total={len(clf)}/40')
ok = (p1==18 and p2==16 and p3==6)
print('PASS' if ok else 'FAIL — recheck this exam')
"
```

If FAIL: note the exam_id, continue with next exam. Do NOT retry automatically.

Then run strict schema validation:

```bash
.venv/bin/python -m tutor validate-classify {exam_id} --strict
```

If strict validation fails, log the exam_id and the validation errors. Continue with the next exam. Do NOT edit labels yourself.

## Step 4 — Enrich classify.json

If validation passes, run:

```bash
.venv/bin/python -m tutor import-json {exam_id} --file question_bank/processed/{exam_id}/classify.json
```

This rewrites `classify.json` into the enriched canonical shape:

- `exam_id`
- `source_profile`
- `ma_tran_match_score`
- `vd_count`
- `section_counts`
- `muc_do_counts`
- `style_summary`
- `validation`
- `classifications`
- `screen_pass`
- `processed_at`

The sub-agent must not see or use these computed values during labeling.

## Step 5 — Import to database

After all successful enrichments complete:

```bash
.venv/bin/python scripts/init_db.py --seed
```

## Step 6 — Run evaluation (if ground truth exists)

```bash
.venv/bin/python scripts/eval_harness.py
```

Review the accuracy table. If aggregate accuracy < 0.80, flag for monitor session.

## Constraints

- Do NOT modify `config/rubric.md` or `config/few_shot_classify.md`
- Do NOT evaluate or summarize classification choices — that is the monitor's job
- Do NOT read de.md yourself — sub-agents do that
- Do NOT expose `ma_tran_match_score`, `screen_pass`, source normalization, analytics, or student performance to classification sub-agents
- Do NOT manually add source metadata or style summaries; use `tutor import-json`
- Log any FAIL exams to a note for the tutor to review manually
