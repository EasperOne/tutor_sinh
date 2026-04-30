# Main Orchestrator Instructions

You are the main orchestration agent for batch classification of biology exams.

## Your task

Classify all unprocessed exams (those with `de.md` but no `classify.json`) using sub-agents.

## Step 1 — Find unprocessed exams

```bash
python -c "
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

## Step 3 — Validate output

After each sub-agent completes, check:

```bash
python -c "
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

## Step 4 — Import to database

After all sub-agents complete:

```bash
python scripts/init_db.py --seed
```

## Step 5 — Run evaluation (if ground truth exists)

```bash
python scripts/eval_harness.py
```

Review the accuracy table. If aggregate accuracy < 0.80, flag for monitor session.

## Constraints

- Do NOT modify `config/rubric.md` or `config/few_shot_classify.md`
- Do NOT evaluate or summarize classification choices — that is the monitor's job
- Do NOT read de.md yourself — sub-agents do that
- Log any FAIL exams to a note for the tutor to review manually
