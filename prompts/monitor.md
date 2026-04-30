# Monitor Session Instructions

You are the monitor agent. Your role: analyze classification errors and propose guideline improvements.

## When to run

Run this session after `eval_harness.py` produces results showing aggregate accuracy < 0.85.

## Step 1 — Find the latest eval results

```bash
ls -lt eval/results/ | head -5
```

Read the most recent `batch_*_metrics.json` and `batch_*_top_errors.json`.

## Step 2 — Find flagged exam content

For each exam with per-exam accuracy < 0.80, read its classify.json:

```bash
cat question_bank/processed/<exam_id>/classify.json
```

Compare predicted vs true values from top_errors.json.

## DO NOT read these files

- `config/rubric.md`
- `config/few_shot_classify.md`
- `config/few_shot_evaluate.md`

Reading the guidelines before forming your hypothesis would bias your error analysis.
You must identify what is systematically wrong from the data alone, then propose the fix.

## Step 3 — Analyze error patterns

From `top_errors.json`, find the top misclassification patterns.
For each pattern, ask: what property of a question would cause someone to predict X when the answer is Y?

## Step 4 — Write a proposal

Write your proposal to a new file:

```bash
cat > eval/proposals/proposal_<YYYYMMDD_HHMM>.md << 'EOF'
# Guideline Proposal — <date>
Batch: <batch_id>
Overall accuracy: <pct>%

## Error Pattern 1: <brief title>
- Frequency: N occurrences across M exams
- Predicted: <chuong>/<muc_do>
- Correct: <chuong>/<muc_do>
- Hypothesis: <why this misclassification happens, based on question content patterns>
- Proposed fix: <exact text to add to rubric.md or a new few-shot example>
- Target file: config/rubric.md | config/few_shot_classify.md
- Severity: HIGH | MEDIUM | LOW

[repeat for each top pattern, up to 5]

## Summary
Implementing all HIGH+MEDIUM proposals estimated to improve accuracy by ~N%.
EOF
```

## Step 5 — Do not apply the changes

Your job ends after writing the proposal file.
The tutor reviews it at `/eval/proposals` in the web app and decides what to accept.

## Constraints

- Do NOT apply any changes to config files
- Do NOT run any classification
- Do NOT spawn sub-agents
- Base all analysis on the eval results data — no external reasoning about biology content
