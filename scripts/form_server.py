"""
Flask form server for manual exam classification.
Single-file app: run via `tutor form`, opens at http://localhost:5000
"""

from __future__ import annotations

import json
import re
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from threading import Timer

import yaml
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template_string, request, send_file, url_for

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "ma_tran_chuan.yaml"
FORM_CONFIG_PATH = ROOT / "config" / "form_config.yaml"
RAW_DIR = ROOT / "question_bank" / "raw"
PROCESSED_DIR = ROOT / "question_bank" / "processed"

load_dotenv(ROOT / ".env")


# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_form_config() -> dict:
    with open(FORM_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Row specification ──────────────────────────────────────────────────────────

def get_row_specs() -> list[dict]:
    rows = []
    for i in range(1, 19):
        rows.append({"phan": "P1", "stt": i, "y": None, "id": f"P1-{i}", "label": f"P1·{i}"})
    for i in range(1, 5):
        for y in ["a", "b", "c", "d"]:
            rows.append({"phan": "P2", "stt": i, "y": y, "id": f"P2-{i}-{y}", "label": f"P2·{i}{y}"})
    for i in range(1, 7):
        rows.append({"phan": "P3", "stt": i, "y": None, "id": f"P3-{i}", "label": f"P3·{i}"})
    return rows  # 40 total


# ── Scoring ────────────────────────────────────────────────────────────────────

def compute_match_score(classifications: list[dict], config: dict) -> float:
    phan_cfg = config["phan"]
    p1 = sum(1 for c in classifications if c["phan"] == "P1")
    p2 = sum(1 for c in classifications if c["phan"] == "P2")
    p3 = sum(1 for c in classifications if c["phan"] == "P3")

    def dev(a: int, e: int) -> float:
        return abs(a - e) / e if e else 0

    section_score = 1 - (
        dev(p1, phan_cfg["P1"]["so_cau"]) +
        dev(p2, phan_cfg["P2"]["so_y"]) +
        dev(p3, phan_cfg["P3"]["so_cau"])
    ) / 3

    exp_muc: dict[str, int] = {}
    for pdata in phan_cfg.values():
        for m, n in pdata.get("muc_do", {}).items():
            exp_muc[m] = exp_muc.get(m, 0) + n

    act_muc: dict[str, int] = {}
    for c in classifications:
        md = c["muc_do"]
        act_muc[md] = act_muc.get(md, 0) + 1

    muc_devs = [dev(act_muc.get(m, 0), e) for m, e in exp_muc.items()]
    muc_score = 1 - sum(muc_devs) / len(muc_devs) if muc_devs else 1.0

    return round(max(0.0, min(1.0, 0.6 * section_score + 0.4 * muc_score)), 3)


# ── classify.json save ─────────────────────────────────────────────────────────

def save_classifications(exam_id: str, classifications: list[dict]) -> float:
    config = load_config()
    match_score = compute_match_score(classifications, config)

    muc_do_counts: dict[str, int] = {}
    for c in classifications:
        md = c["muc_do"]
        muc_do_counts[md] = muc_do_counts.get(md, 0) + 1

    exam_dir = PROCESSED_DIR / exam_id
    exam_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = RAW_DIR / f"{exam_id}.pdf"
    output = {
        "exam_id": exam_id,
        "source_pdf": str(pdf_path.relative_to(ROOT)) if pdf_path.exists() else f"question_bank/raw/{exam_id}.pdf",
        "ma_tran_match_score": match_score,
        "vd_count": muc_do_counts.get("VD", 0),
        "section_counts": {
            "P1": sum(1 for c in classifications if c["phan"] == "P1"),
            "P2_items": sum(1 for c in classifications if c["phan"] == "P2"),
            "P3": sum(1 for c in classifications if c["phan"] == "P3"),
        },
        "muc_do_counts": muc_do_counts,
        "classifications": classifications,
        "screen_pass": match_score >= config["screen"]["list_a_match_min"],
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    (exam_dir / "classify.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return match_score


def strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ── Exam list helpers ──────────────────────────────────────────────────────────

def get_all_exams() -> list[dict]:
    exams = []
    for pdf_path in sorted(RAW_DIR.glob("*.pdf")):
        exam_id = pdf_path.stem
        try:
            import fitz
            doc = fitz.open(str(pdf_path))
            pages = len(doc)
            doc.close()
        except Exception:
            pages = "?"

        classify_path = PROCESSED_DIR / exam_id / "classify.json"
        if classify_path.exists():
            with open(classify_path, encoding="utf-8") as f:
                data = json.load(f)
            count = len(data.get("classifications", []))
            match = data.get("ma_tran_match_score")
            status = "done" if count >= 40 else "partial"
        else:
            count, match, status = 0, None, "notdone"

        exams.append({"exam_id": exam_id, "pages": pages,
                      "status": status, "count": count, "match": match})
    return exams


# ── Markdown rendering ─────────────────────────────────────────────────────────

def render_exam_html(exam_id: str) -> str | None:
    md_path = PROCESSED_DIR / exam_id / "de.md"
    if not md_path.exists():
        return None
    try:
        import markdown as md_lib
        raw = md_path.read_text(encoding="utf-8")
        html = md_lib.markdown(raw, extensions=["tables", "nl2br"])
        return _add_question_anchors(html)
    except ImportError:
        raw = md_path.read_text(encoding="utf-8")
        safe = raw.replace("&", "&amp;").replace("<", "&lt;")
        return f'<pre style="white-space:pre-wrap;font-size:0.9em">{safe}</pre>'


def _add_question_anchors(html: str) -> str:
    """Insert scroll anchors before each 'Câu N' heading."""
    current_section: list[str | None] = [None]

    def detect_section(line: str):
        if re.search(r"Ph[àa]n\s+I[^IV]|PHẦN\s+I[^IV]|trắc nghiệm", line, re.I):
            current_section[0] = "P1"
        elif re.search(r"Ph[àa]n\s+II|PHẦN\s+II|đúng.sai", line, re.I):
            current_section[0] = "P2"
        elif re.search(r"Ph[àa]n\s+III|PHẦN\s+III|trả lời", line, re.I):
            current_section[0] = "P3"

    def inject(m: re.Match) -> str:
        stt = m.group(2)
        sec = current_section[0] or "P1"
        anchor_id = f"q-{sec}-{stt}"
        return f'<a id="{anchor_id}" style="display:block;scroll-margin-top:60px"></a>{m.group(1)}'

    lines = html.split("\n")
    result = []
    for line in lines:
        detect_section(line)
        line = re.sub(r"(Câu\s+(\d+)[\.\:\)]?)", inject, line, count=1)
        result.append(line)
    return "\n".join(result)


# ── Flask app ──────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = "tutor-sinh-form-2025"


@app.route("/")
def index():
    exams = get_all_exams()
    done = sum(1 for e in exams if e["status"] == "done")
    partial = sum(1 for e in exams if e["status"] == "partial")
    return render_template_string(
        INDEX_TEMPLATE, exams=exams, done=done, partial=partial, total=len(exams)
    )


@app.route("/classify/<exam_id>", methods=["GET"])
def classify_form(exam_id: str):
    config = load_config()
    form_config = load_form_config()
    row_specs = get_row_specs()

    existing: dict[str, dict] = {}
    classify_path = PROCESSED_DIR / exam_id / "classify.json"
    if classify_path.exists():
        with open(classify_path, encoding="utf-8") as f:
            data = json.load(f)
        for c in data.get("classifications", []):
            rid = f"{c['phan']}-{c['stt']}"
            if c.get("y"):
                rid += f"-{c['y']}"
            existing[rid] = c

    exam_html = render_exam_html(exam_id)
    has_pdf = (RAW_DIR / f"{exam_id}.pdf").exists()

    return render_template_string(
        CLASSIFY_TEMPLATE,
        exam_id=exam_id,
        chapters=config["chuong"],
        row_specs=row_specs,
        existing=existing,
        exam_html=exam_html,
        has_pdf=has_pdf,
        chapter_keys=form_config.get("chapter_keys", {}),
    )


@app.route("/classify/<exam_id>", methods=["POST"])
def save_classify(exam_id: str):
    row_specs = get_row_specs()
    action = request.form.get("action", "submit")

    classifications = []
    for row in row_specs:
        rid = row["id"]
        chuong = request.form.get(f"chuong_{rid}", "").strip()
        muc_do = request.form.get(f"muc_do_{rid}", "").strip()
        if chuong and muc_do:
            entry: dict = {"phan": row["phan"], "stt": row["stt"],
                           "chuong": chuong, "muc_do": muc_do}
            if row["y"]:
                entry["y"] = row["y"]
            classifications.append(entry)

    if action == "draft":
        exam_dir = PROCESSED_DIR / exam_id
        exam_dir.mkdir(parents=True, exist_ok=True)
        config = load_config()
        partial_data = {
            "exam_id": exam_id,
            "classifications": classifications,
            "ma_tran_match_score": compute_match_score(classifications, config) if classifications else 0,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        (exam_dir / "classify.json").write_text(
            json.dumps(partial_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        flash(f"✓ Draft saved: {len(classifications)}/40 rows", "success")
        return redirect(url_for("classify_form", exam_id=exam_id))

    if len(classifications) < 40:
        flash(f"⚠ Chỉ có {len(classifications)}/40 hàng đã điền. Lưu draft hoặc hoàn thành tất cả.", "warning")
        return redirect(url_for("classify_form", exam_id=exam_id))

    match_score = save_classifications(exam_id, classifications)
    flash(f"✓ {exam_id} đã lưu (match: {match_score:.3f})", "success")
    return redirect(url_for("index"))


@app.route("/review/<exam_id>")
def review(exam_id: str):
    config = load_config()
    classify_path = PROCESSED_DIR / exam_id / "classify.json"
    if not classify_path.exists():
        flash(f"Chưa có classify.json cho {exam_id}", "warning")
        return redirect(url_for("index"))

    with open(classify_path, encoding="utf-8") as f:
        data = json.load(f)

    classifications = data.get("classifications", [])
    match_score = data.get("ma_tran_match_score", 0)
    phan_cfg = config["phan"]

    exp_muc: dict[str, int] = {}
    for pdata in phan_cfg.values():
        for m, n in pdata.get("muc_do", {}).items():
            exp_muc[m] = exp_muc.get(m, 0) + n

    act_muc: dict[str, int] = {}
    for c in classifications:
        md = c["muc_do"]
        act_muc[md] = act_muc.get(md, 0) + 1

    exp_sections = {"P1": phan_cfg["P1"]["so_cau"],
                    "P2": phan_cfg["P2"]["so_y"],
                    "P3": phan_cfg["P3"]["so_cau"]}
    act_sections = {"P1": sum(1 for c in classifications if c["phan"] == "P1"),
                    "P2": sum(1 for c in classifications if c["phan"] == "P2"),
                    "P3": sum(1 for c in classifications if c["phan"] == "P3")}

    # Build chapter × section × muc_do matrix
    chapters = list(config["chuong"].keys())
    sections = ["P1", "P2", "P3"]
    muc_dos = ["B", "H", "VD"]
    matrix: dict = {ch: {p: {m: 0 for m in muc_dos} for p in sections} for ch in chapters}
    for c in classifications:
        ch, p, md = c.get("chuong", ""), c["phan"], c["muc_do"]
        if ch in matrix and p in matrix[ch] and md in matrix[ch][p]:
            matrix[ch][p][md] += 1

    return render_template_string(
        REVIEW_TEMPLATE,
        exam_id=exam_id, data=data, match_score=match_score,
        chapters=config["chuong"], classifications=classifications,
        exp_muc=exp_muc, act_muc=act_muc,
        exp_sections=exp_sections, act_sections=act_sections,
        matrix=matrix, sections=sections, muc_dos=muc_dos,
    )


@app.route("/import/<exam_id>", methods=["POST"])
def import_json_route(exam_id: str):
    raw_text = request.form.get("json_text", "")
    try:
        cleaned = strip_json_fences(raw_text)
        parsed = json.loads(cleaned)
        classifications = parsed.get("classifications", parsed if isinstance(parsed, list) else None)
        if not classifications:
            raise ValueError("Không tìm thấy key 'classifications'")
        match_score = save_classifications(exam_id, classifications)
        flash(f"✓ {exam_id}: {len(classifications)} items, match={match_score:.3f}", "success")
        return redirect(url_for("review", exam_id=exam_id))
    except Exception as e:
        flash(f"✗ Import thất bại: {e}", "danger")
        return redirect(url_for("index"))


@app.route("/pdf/<exam_id>")
def serve_pdf(exam_id: str):
    pdf_path = RAW_DIR / f"{exam_id}.pdf"
    if not pdf_path.exists():
        return "PDF not found", 404
    return send_file(str(pdf_path), mimetype="application/pdf", as_attachment=False)


@app.route("/pdf-data/<exam_id>")
def serve_pdf_data(exam_id: str):
    import base64
    pdf_path = RAW_DIR / f"{exam_id}.pdf"
    if not pdf_path.exists():
        return {"error": "PDF not found"}, 404
    with open(pdf_path, "rb") as f:
        pdf_data = base64.b64encode(f.read()).decode("utf-8")
    return {"data": f"data:application/pdf;base64,{pdf_data}"}


@app.route("/pdf-info/<exam_id>")
def serve_pdf_info(exam_id: str):
    pdf_path = RAW_DIR / f"{exam_id}.pdf"
    if not pdf_path.exists():
        return {"pages": 0}
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        pages = len(doc)
        doc.close()
        return {"pages": pages}
    except Exception:
        return {"pages": 0}


@app.route("/pdf-page/<exam_id>/<int:page>")
def serve_pdf_page(exam_id: str, page: int):
    from flask import Response
    pdf_path = RAW_DIR / f"{exam_id}.pdf"
    if not pdf_path.exists():
        return "PDF not found", 404
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        if page < 0 or page >= len(doc):
            doc.close()
            return "Page out of range", 404
        pix = doc[page].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        doc.close()
        return Response(pix.tobytes("png"), mimetype="image/png")
    except Exception as e:
        return f"Render error: {e}", 500


@app.route("/exam-add", methods=["POST"])
def add_exam():
    exam_id = request.form.get("exam_id", "").strip()
    if not exam_id:
        flash("Exam ID required", "danger")
        return redirect(url_for("index"))
    db_path = ROOT / "tutor_sinh.db"
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT OR IGNORE INTO exams (id) VALUES (?)", (exam_id,))
    conn.commit()
    conn.close()
    flash(f"Added exam: {exam_id}", "success")
    return redirect(url_for("index"))


@app.route("/exam-delete/<exam_id>")
def delete_exam(exam_id: str):
    db_path = ROOT / "tutor_sinh.db"
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM questions WHERE exam_id=?", (exam_id,))
    conn.execute("DELETE FROM exams WHERE id=?", (exam_id,))
    conn.commit()
    conn.close()
    flash(f"Deleted exam: {exam_id}", "success")
    return redirect(url_for("index"))


@app.route("/export-json/<exam_id>")
def export_json(exam_id: str):
    classify_path = PROCESSED_DIR / exam_id / "classify.json"
    if not classify_path.exists():
        return {"error": "No classify.json found"}, 404
    with open(classify_path, encoding="utf-8") as f:
        data = json.load(f)
    return data


def run_server(host: str = "127.0.0.1", port: int = 5000, open_browser: bool = True):
    if open_browser:
        Timer(1.2, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    app.run(host=host, port=port, debug=False, use_reloader=False)


# ── HTML Templates ─────────────────────────────────────────────────────────────

_BS = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
_BSJ = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"

INDEX_TEMPLATE = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>tutor-sinh — Ngân hàng đề</title>
<link href="{_BS}" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4" style="max-width:900px">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h5 class="mb-0">📚 Ngân hàng đề thi</h5>
    <div class="d-flex align-items-center gap-2">
      <button class="btn btn-sm btn-outline-primary" onclick="showAddExam()">+ Thêm đề</button>
      <span class="text-muted small">{{{{ done }}}}/{{{{ total }}}} hoàn thành · {{{{ partial }}}} đang làm</span>
    </div>
  </div>

  {{% with messages = get_flashed_messages(with_categories=true) %}}
  {{% for cat, msg in messages %}}
  <div class="alert alert-{{{{ cat }}}} alert-dismissible py-2">{{{{ msg }}}}
    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
  </div>
  {{% endfor %}}{{% endwith %}}

  <div class="card shadow-sm">
  <table class="table table-hover align-middle mb-0">
    <thead class="table-light"><tr>
      <th>Exam ID</th><th>Trang</th><th>Classify</th><th>Match</th><th>Thao tác</th>
    </tr></thead>
    <tbody>
    {{% for e in exams %}}
    <tr>
      <td class="fw-semibold font-monospace">{{{{ e.exam_id }}}}</td>
      <td class="text-muted">{{{{ e.pages }}}}</td>
      <td>
        {{% if e.status == 'done' %}}<span class="text-success fw-medium">✓ {{{{ e.count }}}}/40</span>
        {{% elif e.status == 'partial' %}}<span class="text-warning fw-medium">⚠ {{{{ e.count }}}}/40</span>
        {{% else %}}<span class="text-danger">✗ chưa làm</span>{{% endif %}}
      </td>
      <td>
        {{% if e.match is not none %}}
        <span class="badge {{% if e.match >= 0.85 %}}bg-success{{% elif e.match >= 0.70 %}}bg-warning text-dark{{% else %}}bg-danger{{% endif %}}">
          {{{{ "%.3f"|format(e.match) }}}}
        </span>
        {{% else %}}—{{% endif %}}
      </td>
      <td class="d-flex gap-1 flex-wrap">
        <a href="/classify/{{{{ e.exam_id }}}}" class="btn btn-sm {{% if e.status == 'done' %}}btn-outline-secondary{{% else %}}btn-primary{{% endif %}}">
          {{% if e.status == 'done' %}}Sửa{{% elif e.status == 'partial' %}}Tiếp tục{{% else %}}Phân loại{{% endif %}}
        </a>
        {{% if e.status != 'notdone' %}}
        <a href="/review/{{{{ e.exam_id }}}}" class="btn btn-sm btn-outline-info">Review</a>
        <button class="btn btn-sm btn-outline-secondary" onclick="showExport('{{{{ e.exam_id }}}}')">Export</button>
        {{% endif %}}
        <button class="btn btn-sm btn-outline-danger" onclick="confirmDelete('{{{{ e.exam_id }}}}')">✕</button>
        <button class="btn btn-sm btn-outline-secondary" onclick="showImport('{{{{ e.exam_id }}}}')">Import JSON</button>
      </td>
    </tr>
    {{% endfor %}}
    {{% if not exams %}}
    <tr><td colspan="5" class="text-center text-muted py-4">
      Chưa có đề nào trong <code>question_bank/raw/</code>
    </td></tr>
    {{% endif %}}
    </tbody>
  </table>
  </div>
</div>

<!-- Add Exam Modal -->
<div class="modal fade" id="addExamModal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header"><h6 class="modal-title">Thêm đề thi mới</h6>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <form method="POST" action="/exam-add">
      <div class="modal-body">
        <div class="mb-2">
          <label class="form-label">Exam ID</label>
          <input type="text" name="exam_id" class="form-control" placeholder="VD: TEST_001" required>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Huỷ</button>
        <button type="submit" class="btn btn-primary btn-sm">Thêm</button>
      </div>
      </form>
    </div>
  </div>
</div>

<!-- Import Modal -->
<div class="modal fade" id="importModal" tabindex="-1">
  <div class="modal-dialog modal-lg">
  <div class="modal-content">
    <div class="modal-header py-2">
      <h6 class="modal-title mb-0">Import JSON — <span id="imp-id" class="font-monospace"></span></h6>
      <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
    </div>
    <form id="imp-form" method="POST">
    <div class="modal-body pb-2">
      <p class="text-muted small mb-2">Dán JSON từ Claude.ai (có thể giữ nguyên code fences).</p>
      <textarea name="json_text" class="form-control font-monospace" rows="10"
                placeholder='{{"classifications": [...]}}' required></textarea>
    </div>
    <div class="modal-footer py-2">
      <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Huỷ</button>
      <button class="btn btn-primary btn-sm">Import & Lưu</button>
    </div>
    </form>
  </div></div>
</div>

<!-- Export JSON Modal -->
<div class="modal fade" id="exportModal" tabindex="-1">
  <div class="modal-dialog modal-lg">
  <div class="modal-content">
    <div class="modal-header py-2">
      <h6 class="modal-title mb-0">Export JSON — <span id="exp-id" class="font-monospace"></span></h6>
      <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
    </div>
    <div class="modal-body pb-2">
      <textarea id="exp-text" class="form-control font-monospace" rows="15" readonly></textarea>
    </div>
    <div class="modal-footer py-2">
      <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Đóng</button>
      <button class="btn btn-primary btn-sm" onclick="document.getElementById('exp-text').select();document.execCommand('copy')">Copy</button>
    </div>
  </div></div>
</div>

<script src="{_BSJ}"></script>
<script>
function showImport(id) {{
  document.getElementById('imp-id').textContent = id;
  document.getElementById('imp-form').action = '/import/' + id;
  new bootstrap.Modal(document.getElementById('importModal')).show();
  setTimeout(() => document.querySelector('#importModal textarea').focus(), 400);
}}
function showAddExam() {{
  new bootstrap.Modal(document.getElementById('addExamModal')).show();
}}
function showExport(id) {{
  document.getElementById('exp-id').textContent = id;
  fetch('/export-json/' + id).then(r => r.json()).then(d => {{
    document.getElementById('exp-text').value = JSON.stringify(d, null, 2);
  }});
  new bootstrap.Modal(document.getElementById('exportModal')).show();
}}
function confirmDelete(id) {{
  if (confirm('Xóa đề ' + id + '? (file gốc giữ nguyên)')) {{
    window.location.href = '/exam-delete/' + id;
  }}
}}
</script>
</body></html>"""

# ── CLASSIFY TEMPLATE ──────────────────────────────────────────────────────────

CLASSIFY_TEMPLATE = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Phân loại {{{{ exam_id }}}} — tutor-sinh</title>
<link href="{_BS}" rel="stylesheet">
<style>
  body {{ margin:0; overflow:hidden; }}
  #layout {{ display:grid; grid-template-columns:55% 45%; height:100vh; }}
  #lp {{ overflow:hidden; border-right:1px solid #dee2e6; background:#fff; }}
  #rp {{ display:flex; flex-direction:column; overflow:hidden; }}
  #rh {{ flex-shrink:0; padding:.4rem .75rem; border-bottom:1px solid #dee2e6; background:#fff; }}
  #rs {{ flex:1; overflow-y:auto; }}
  .sdiv {{ text-align:center; font-size:.75rem; color:#6c757d; padding:5px;
           background:#f8f9fa; border-top:1px solid #dee2e6; border-bottom:1px solid #dee2e6;
           position:sticky; top:0; z-index:5; }}
  .ri {{ display:flex; align-items:center; gap:5px; padding:3px 8px;
         border-left:3px solid transparent; cursor:pointer; outline:none;
         border-bottom:1px solid #f0f0f0; min-height:34px; }}
  .ri:focus, .ri.active {{ border-left-color:#0d6efd; background:#f0f7ff; }}
  .ri.done {{ border-left-color:#198754 !important; }}
  .ri.active.done {{ background:#f0fff4; }}
  .rl {{ width:52px; font-size:.75rem; font-weight:600; color:#6c757d; flex-shrink:0; font-family:monospace; }}
  .ri select {{ flex:1; font-size:.78rem; padding:1px 3px; min-width:0;
                border:1px solid #ced4da; border-radius:3px; background:#fff; }}
  .mg {{ display:flex; gap:2px; flex-shrink:0; }}
  .mg input {{ display:none; }}
  .mg label {{ cursor:pointer; padding:1px 7px; font-size:.72rem; font-weight:600;
               border:1px solid #ced4da; border-radius:3px; user-select:none; }}
  .mg input:checked + .lB {{ background:#cfe2ff; border-color:#0d6efd; color:#0d6efd; }}
  .mg input:checked + .lH {{ background:#d1e7dd; border-color:#198754; color:#198754; }}
  .mg input:checked + .lV {{ background:#f8d7da; border-color:#dc3545; color:#dc3545; }}
  #lp h1,#lp h2,#lp h3 {{ font-size:1rem; font-weight:700; margin-top:1rem; }}
  #lp p {{ margin-bottom:.4rem; }}
  .q-hl {{ background:#fff3cd; border-left:3px solid #ffc107; padding-left:6px; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js"></script>
</head>
<body>
<div id="layout">

<!-- LEFT PANEL -->
<div id="lp" style="padding:0;display:flex;flex-direction:column">
  {{% if exam_html and has_pdf %}}
  <!-- Toggle bar -->
  <div id="toggle-bar" style="display:flex;gap:4px;padding:.3rem .6rem;border-bottom:1px solid #dee2e6;background:#f8f9fa;flex-shrink:0">
    <button id="btn-md"  class="btn btn-xs btn-primary"  style="padding:2px 10px;font-size:.75rem" onclick="showView('md')">Markdown</button>
    <button id="btn-pdf" class="btn btn-xs btn-outline-secondary" style="padding:2px 10px;font-size:.75rem" onclick="showView('pdf')">PDF</button>
  </div>
  <div id="view-md"  style="flex:1;overflow-y:auto;padding:1rem 1.5rem">{{{{ exam_html | safe }}}}</div>
  <div id="view-pdf" style="display:none;flex-direction:column;overflow:hidden">
    {{% include 'pdf_toolbar' ignore missing %}}
    <div style="display:flex;align-items:center;gap:5px;padding:4px 8px;background:#333;color:#fff;font-size:.8rem;flex-shrink:0">
      <button onclick="prevPage()" title="Trang trước (←)" style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 8px;cursor:pointer">&#9664;</button>
      <span id="pdf-page-info" style="min-width:90px;text-align:center">—</span>
      <button onclick="nextPage()" title="Trang sau (→)" style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 8px;cursor:pointer">&#9654;</button>
      <span style="opacity:.35;margin:0 3px">|</span>
      <button onclick="zoomOut()" title="Thu nhỏ" style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 8px;cursor:pointer;font-size:1rem;line-height:1">−</button>
      <span id="pdf-zoom-info" style="min-width:38px;text-align:center">—</span>
      <button onclick="zoomIn()"  title="Phóng to"  style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 8px;cursor:pointer;font-size:1rem;line-height:1">+</button>
      <button onclick="fitWidth()" title="Vừa khung" style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 6px;cursor:pointer;font-size:.8rem">⟺</button>
    </div>
    <div id="pdf-scroll" style="flex:1;overflow:auto;display:flex;justify-content:center;padding:8px;background:#666">
      <canvas id="pdf-canvas" style="box-shadow:0 2px 14px rgba(0,0,0,.6);align-self:flex-start"></canvas>
    </div>
  </div>
  {{% elif exam_html %}}
  <div style="flex:1;overflow-y:auto;padding:1rem 1.5rem">{{{{ exam_html | safe }}}}</div>
  {{% elif has_pdf %}}
  <!-- no markdown — PDF.js canvas viewer fills the whole left panel -->
  <div style="display:flex;flex-direction:column;overflow:hidden;flex:1">
    <div style="display:flex;align-items:center;gap:5px;padding:4px 8px;background:#333;color:#fff;font-size:.8rem;flex-shrink:0">
      <button onclick="prevPage()" style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 8px;cursor:pointer">&#9664;</button>
      <span id="pdf-page-info" style="min-width:90px;text-align:center">—</span>
      <button onclick="nextPage()" style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 8px;cursor:pointer">&#9654;</button>
      <span style="opacity:.35;margin:0 3px">|</span>
      <button onclick="zoomOut()" style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 8px;cursor:pointer;font-size:1rem;line-height:1">−</button>
      <span id="pdf-zoom-info" style="min-width:38px;text-align:center">—</span>
      <button onclick="zoomIn()"  style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 8px;cursor:pointer;font-size:1rem;line-height:1">+</button>
      <button onclick="fitWidth()" style="background:#555;border:1px solid #666;color:#fff;border-radius:3px;padding:1px 6px;cursor:pointer;font-size:.8rem">⟺</button>
    </div>
    <div id="pdf-scroll" style="flex:1;overflow:auto;display:flex;justify-content:center;padding:8px;background:#666">
      <canvas id="pdf-canvas" style="box-shadow:0 2px 14px rgba(0,0,0,.6);align-self:flex-start"></canvas>
    </div>
  </div>
  {{% else %}}
  <div style="padding:1rem" class="alert alert-warning mt-3">
    Không tìm thấy <code>de.md</code> hoặc PDF.<br>
    Chạy <code>tutor gen-prompt {{{{ exam_id }}}}</code> để tạo de.md.
  </div>
  {{% endif %}}
</div>

<!-- RIGHT PANEL -->
<div id="rp">
  <div id="rh">
    <div class="d-flex justify-content-between align-items-center">
      <div>
        <span class="fw-semibold font-monospace">{{{{ exam_id }}}}</span>
        <span class="text-muted ms-2 small" id="prog-txt">0 / 40</span>
      </div>
      <div class="d-flex gap-1">
        <a href="/" class="btn btn-sm btn-outline-secondary">← Danh sách</a>
        <button class="btn btn-sm btn-outline-secondary" onclick="saveDraft()" title="Ctrl+S">💾</button>
        <button class="btn btn-sm btn-primary" onclick="trySubmit()" title="Ctrl+Enter">✓ Nộp</button>
      </div>
    </div>
    <div class="progress mt-1" style="height:3px">
      <div id="prog-bar" class="progress-bar bg-success" style="width:0%;transition:width .2s"></div>
    </div>
    <div class="mt-1" style="font-size:.67rem;color:#6c757d;line-height:1.3">
      <b>b</b>=Biết <b>h</b>=Hiểu <b>v</b>=VD &nbsp;·&nbsp;
      {{% for k,code in chapter_keys.items() %}}<b>{{{{k}}}}</b>={{{{code}}}} {{% endfor %}}
      &nbsp;·&nbsp; ↓↑ Tab/Shift+Tab
    </div>
  </div>

  <div id="rs">
  <form id="clf-form" method="POST" action="/classify/{{{{ exam_id }}}}">
    <input type="hidden" name="action" id="form-action" value="submit">

    {{% macro row(r) %}}
    <div class="ri" id="ri-{{{{r.id}}}}" tabindex="0"
         data-rid="{{{{r.id}}}}" data-phan="{{{{r.phan}}}}" data-stt="{{{{r.stt}}}}"
         onclick="activateByEl(this)">
      <span class="rl">{{{{r.label}}}}</span>
      <select name="chuong_{{{{r.id}}}}" id="ch-{{{{r.id}}}}" tabindex="-1"
              onchange="onChg('{{{{r.id}}}}')">
        <option value="">— Chương —</option>
        {{% for code,info in chapters.items() %}}
        <option value="{{{{code}}}}"
          {{{{ 'selected' if existing.get(r.id, {{}}).get('chuong') == code }}}}>
          {{{{code}}}} — {{{{info.ten}}}}
        </option>
        {{% endfor %}}
      </select>
      <div class="mg">
        {{% for md,cls in [('B','lB'),('H','lH'),('VD','lV')] %}}
        <input type="radio" name="muc_do_{{{{r.id}}}}" id="md-{{{{r.id}}}}-{{{{md}}}}"
               value="{{{{md}}}}" tabindex="-1"
               {{{{ 'checked' if existing.get(r.id, {{}}).get('muc_do') == md }}}}
               onchange="onChg('{{{{r.id}}}}')">
        <label class="{{{{cls}}}}" for="md-{{{{r.id}}}}-{{{{md}}}}">{{{{md}}}}</label>
        {{% endfor %}}
      </div>
    </div>
    {{% endmacro %}}

    <div class="sdiv">── Phần I — Trắc nghiệm (18 câu) ──</div>
    {{% for r in row_specs if r.phan == 'P1' %}}{{{{ row(r) }}}}{{% endfor %}}

    <div class="sdiv">── Phần II — Đúng/Sai (4 câu × 4 ý) ──</div>
    {{% for stt in range(1,5) %}}
    <div style="border-top:2px solid #e9ecef">
    {{% for r in row_specs if r.phan == 'P2' and r.stt == stt %}}{{{{ row(r) }}}}{{% endfor %}}
    </div>
    {{% endfor %}}

    <div class="sdiv">── Phần III — Trả lời ngắn (6 câu) ──</div>
    {{% for r in row_specs if r.phan == 'P3' %}}{{{{ row(r) }}}}{{% endfor %}}

  </form>
  </div>
</div><!-- /rp -->
</div><!-- /layout -->

<script>
const CHAPTER_KEYS = {{{{ chapter_keys | tojson }}}};
const ROW_SPECS = {{{{ row_specs | tojson }}}};
const ROW_IDS = ROW_SPECS.map(r => r.id);
const EXAM_ID = {{{{ exam_id | tojson }}}};
const DRAFT_KEY = 'draft_' + EXAM_ID;
let activeIdx = 0;
let autoSaveTimer = null;

// ── Row activation ────────────────────────────────────────────
function el(rid) {{ return document.getElementById('ri-' + rid); }}
function chEl(rid) {{ return document.getElementById('ch-' + rid); }}
function mdEl(rid, md) {{ return document.getElementById('md-' + rid + '-' + md); }}

function activateRow(idx) {{
  if (idx < 0 || idx >= ROW_IDS.length) return;
  const prev = el(ROW_IDS[activeIdx]);
  if (prev) prev.classList.remove('active');
  activeIdx = idx;
  const curr = el(ROW_IDS[activeIdx]);
  if (curr) {{
    curr.classList.add('active');
    curr.scrollIntoView({{block:'nearest'}});
  }}
  scrollLeftToRow(ROW_SPECS[activeIdx]);
}}

function activateByEl(div) {{
  const rid = div.dataset.rid;
  const idx = ROW_IDS.indexOf(rid);
  if (idx >= 0) activateRow(idx);
}}

function scrollLeftToRow(spec) {{
  const anchorId = 'q-' + spec.phan + '-' + spec.stt;
  const anchor = document.getElementById(anchorId);
  if (anchor) {{
    const lp = document.getElementById('lp');
    lp.scrollTo({{top: anchor.offsetTop - 80, behavior: 'smooth'}});
    // Briefly highlight
    anchor.parentElement && anchor.parentElement.classList.add('q-hl');
    setTimeout(() => anchor.parentElement && anchor.parentElement.classList.remove('q-hl'), 1500);
  }}
}}

// ── Shortcut setters ──────────────────────────────────────────
function setChapter(code) {{
  const rid = ROW_IDS[activeIdx];
  const sel = chEl(rid);
  if (sel) {{ sel.value = code; onChg(rid); }}
}}

function setMucDo(md) {{
  const rid = ROW_IDS[activeIdx];
  const radio = mdEl(rid, md);
  if (radio) {{ radio.checked = true; onChg(rid); }}
}}

// ── onChange & auto-advance ───────────────────────────────────
function onChg(rid) {{
  updateDoneClass(rid);
  updateProgress();
  scheduleAutoSave();
  // Auto-advance when both chapter + muc_do are set
  const sel = chEl(rid);
  const hasCh = sel && sel.value !== '';
  const hasMd = ['B','H','VD'].some(m => mdEl(rid, m)?.checked);
  if (hasCh && hasMd) {{
    const idx = ROW_IDS.indexOf(rid);
    if (idx === activeIdx) setTimeout(() => activateRow(idx + 1), 120);
  }}
}}

function updateDoneClass(rid) {{
  const div = el(rid);
  if (!div) return;
  const sel = chEl(rid);
  const hasCh = sel && sel.value !== '';
  const hasMd = ['B','H','VD'].some(m => mdEl(rid, m)?.checked);
  div.classList.toggle('done', hasCh && hasMd);
}}

// ── Progress ──────────────────────────────────────────────────
function updateProgress() {{
  let done = 0;
  ROW_IDS.forEach(rid => {{
    const sel = chEl(rid);
    const hasCh = sel && sel.value !== '';
    const hasMd = ['B','H','VD'].some(m => mdEl(rid, m)?.checked);
    if (hasCh && hasMd) done++;
  }});
  const pct = Math.round(done / ROW_IDS.length * 100);
  document.getElementById('prog-txt').textContent = done + ' / ' + ROW_IDS.length;
  const bar = document.getElementById('prog-bar');
  bar.style.width = pct + '%';
  bar.className = 'progress-bar ' + (pct === 100 ? 'bg-success' : pct >= 50 ? 'bg-warning' : 'bg-danger');
}}

// ── Draft / localStorage ──────────────────────────────────────
function saveDraft() {{
  const state = {{}};
  ROW_IDS.forEach(rid => {{
    const sel = chEl(rid);
    const md = ['B','H','VD'].find(m => mdEl(rid, m)?.checked) || '';
    state[rid] = {{chuong: sel ? sel.value : '', muc_do: md}};
  }});
  localStorage.setItem(DRAFT_KEY, JSON.stringify(state));
  // Persist via POST
  document.getElementById('form-action').value = 'draft';
  document.getElementById('clf-form').submit();
}}

function restoreDraft() {{
  const saved = localStorage.getItem(DRAFT_KEY);
  if (!saved) return;
  try {{
    const state = JSON.parse(saved);
    ROW_IDS.forEach(rid => {{
      if (!state[rid]) return;
      const {{chuong, muc_do}} = state[rid];
      if (chuong) {{ const sel = chEl(rid); if (sel) sel.value = chuong; }}
      if (muc_do) {{ const r = mdEl(rid, muc_do); if (r) r.checked = true; }}
      updateDoneClass(rid);
    }});
    updateProgress();
  }} catch(e) {{}}
}}

function scheduleAutoSave() {{
  clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => {{
    const state = {{}};
    ROW_IDS.forEach(rid => {{
      const sel = chEl(rid);
      const md = ['B','H','VD'].find(m => mdEl(rid, m)?.checked) || '';
      state[rid] = {{chuong: sel ? sel.value : '', muc_do: md}};
    }});
    localStorage.setItem(DRAFT_KEY, JSON.stringify(state));
  }}, 60000);
}}

// ── Submit ────────────────────────────────────────────────────
function trySubmit() {{
  document.getElementById('form-action').value = 'submit';
  document.getElementById('clf-form').submit();
}}

// ── PDF.js canvas viewer ──────────────────────────────────────
let pdfDoc      = null;
let pdfPage     = 1;      // 1-based (pdfjs convention)
let pdfTotal    = 0;
let pdfScale    = 1.5;
let pdfRendering = false;
let pdfPending  = null;
let inPdfView   = false;

async function initPdfViewer() {{
  if (pdfDoc) return;
  try {{
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js';
    const resp = await fetch('/pdf-data/' + EXAM_ID);
    const json = await resp.json();
    const base64 = json.data.replace('data:application/pdf;base64,', '');
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    pdfDoc = await pdfjsLib.getDocument({{data: bytes}}).promise;
    pdfTotal = pdfDoc.numPages;
    await fitWidth(true);
  }} catch(e) {{ console.error('PDF.js error', e); }}
}}

async function renderPage(n) {{
  if (!pdfDoc || n < 1 || n > pdfTotal) return;
  if (pdfRendering) {{ pdfPending = n; return; }}
  pdfRendering = true;
  pdfPage = n;

  const page     = await pdfDoc.getPage(n);
  const viewport = page.getViewport({{scale: pdfScale}});
  const canvas   = document.getElementById('pdf-canvas');
  canvas.height  = viewport.height;
  canvas.width   = viewport.width;
  await page.render({{canvasContext: canvas.getContext('2d'), viewport}}).promise;

  pdfRendering = false;
  const info = document.getElementById('pdf-page-info');
  if (info) info.textContent = 'Trang ' + n + ' / ' + pdfTotal;
  const zi = document.getElementById('pdf-zoom-info');
  if (zi) zi.textContent = Math.round(pdfScale * 100) + '%';
  document.getElementById('pdf-scroll') && (document.getElementById('pdf-scroll').scrollTop = 0);

  if (pdfPending !== null) {{ const p = pdfPending; pdfPending = null; renderPage(p); }}
}}

function prevPage() {{ renderPage(pdfPage - 1); }}
function nextPage() {{ renderPage(pdfPage + 1); }}
function zoomIn()  {{ pdfScale = Math.min(pdfScale + 0.25, 5.0); renderPage(pdfPage); }}
function zoomOut() {{ pdfScale = Math.max(pdfScale - 0.25, 0.5); renderPage(pdfPage); }}

async function fitWidth(_init) {{
  if (!pdfDoc) return;
  const scroll = document.getElementById('pdf-scroll');
  const availW = scroll ? scroll.clientWidth - 16 : 600;
  const page   = await pdfDoc.getPage(pdfPage || 1);
  const vp     = page.getViewport({{scale: 1.0}});
  pdfScale = availW / vp.width;
  renderPage(pdfPage || 1);
}}

// ── PDF / Markdown toggle ─────────────────────────────────────
function showView(which) {{
  const md     = document.getElementById('view-md');
  const pdf    = document.getElementById('view-pdf');
  const btnMd  = document.getElementById('btn-md');
  const btnPdf = document.getElementById('btn-pdf');
  if (!md || !pdf) return;
  if (which === 'pdf') {{
    md.style.display  = 'none';
    pdf.style.display = 'flex';
    if (btnMd)  btnMd.className  = 'btn btn-xs btn-outline-secondary';
    if (btnPdf) btnPdf.className = 'btn btn-xs btn-primary';
    inPdfView = true;
    initPdfViewer();
  }} else {{
    pdf.style.display = 'none';
    md.style.display  = 'block';
    if (btnMd)  btnMd.className  = 'btn btn-xs btn-primary';
    if (btnPdf) btnPdf.className = 'btn btn-xs btn-outline-secondary';
    inPdfView = false;
  }}
}}

// ── Keyboard ──────────────────────────────────────────────────
document.addEventListener('keydown', e => {{
  if (e.ctrlKey && e.key === 's') {{ e.preventDefault(); saveDraft(); return; }}
  if (e.ctrlKey && e.key === 'Enter') {{ e.preventDefault(); trySubmit(); return; }}

  const inSelect = e.target.tagName === 'SELECT';

  switch(e.key) {{
    case 'Tab':
      e.preventDefault();
      activateRow(e.shiftKey ? activeIdx - 1 : activeIdx + 1);
      break;
    case 'ArrowDown':
      if (!inSelect) {{ e.preventDefault(); if (inPdfView) nextPage(); else activateRow(activeIdx + 1); }}
      break;
    case 'ArrowUp':
      if (!inSelect) {{ e.preventDefault(); if (inPdfView) prevPage(); else activateRow(activeIdx - 1); }}
      break;
    case 'ArrowLeft':
      if (!inSelect && inPdfView) {{ e.preventDefault(); prevPage(); }}
      break;
    case 'ArrowRight':
      if (!inSelect && inPdfView) {{ e.preventDefault(); nextPage(); }}
      break;
    case 'b': if (!inSelect) setMucDo('B'); break;
    case 'h': if (!inSelect) setMucDo('H'); break;
    case 'v': if (!inSelect) setMucDo('VD'); break;
    default:
      if (!inSelect && CHAPTER_KEYS[e.key]) {{
        e.preventDefault();
        setChapter(CHAPTER_KEYS[e.key]);
      }}
  }}
}});

// ── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {{
  ROW_IDS.forEach(updateDoneClass);
  updateProgress();
  activateRow(0);
  // Auto-load PDF.js when there is no markdown panel (pdf-only mode)
  if (!document.getElementById('view-md') && document.getElementById('pdf-canvas')) {{
    inPdfView = true;
    initPdfViewer();
  }}
  // Click on select/radio focuses its row
  document.querySelectorAll('.ri select, .ri input[type=radio]').forEach(inp => {{
    inp.addEventListener('focus', () => {{
      const row = inp.closest('.ri');
      if (row) activateByEl(row);
    }});
  }});
}});
</script>
</body></html>"""

# ── REVIEW TEMPLATE ────────────────────────────────────────────────────────────

REVIEW_TEMPLATE = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Review {{{{ exam_id }}}} — tutor-sinh</title>
<link href="{_BS}" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4" style="max-width:960px">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h5 class="mb-0">Review: <span class="font-monospace">{{{{ exam_id }}}}</span></h5>
    <div class="d-flex gap-2">
      <a href="/classify/{{{{ exam_id }}}}" class="btn btn-sm btn-outline-primary">✏ Sửa</a>
      <a href="/" class="btn btn-sm btn-outline-secondary">← Danh sách</a>
    </div>
  </div>

  {{% with messages = get_flashed_messages(with_categories=true) %}}
  {{% for cat,msg in messages %}}
  <div class="alert alert-{{{{cat}}}} py-2">{{{{msg}}}}</div>
  {{% endfor %}}{{% endwith %}}

  <!-- Match score banner -->
  <div class="card mb-3 shadow-sm">
  <div class="card-body py-2 d-flex align-items-center gap-3">
    <div>
      <div class="text-muted small">match_score</div>
      <div class="fs-4 fw-bold
        {{% if match_score >= 0.85 %}}text-success
        {{% elif match_score >= 0.70 %}}text-warning
        {{% else %}}text-danger{{% endif %}}">
        {{{{ "%.3f"|format(match_score) }}}}
      </div>
    </div>
    <div class="vr"></div>
    <div>
      <div class="text-muted small">Tổng items</div>
      <div class="fs-5">{{{{ classifications|length }}}}/40</div>
    </div>
    <div class="vr"></div>
    <div>
      <div class="text-muted small">screen_pass</div>
      <div class="fs-5">{{{{ '✓' if data.get('screen_pass') else '✗' }}}}</div>
    </div>
    <div class="vr"></div>
    <div>
      <div class="text-muted small">VD count</div>
      <div class="fs-5">{{{{ data.get('vd_count', 0) }}}}</div>
    </div>
  </div>
  </div>

  <!-- Section counts -->
  <div class="card mb-3 shadow-sm">
  <div class="card-header py-2 fw-semibold">Số lượng theo phần</div>
  <table class="table table-sm mb-0">
    <thead class="table-light"><tr><th>Phần</th><th>Thực tế</th><th>Chuẩn</th><th>Δ</th></tr></thead>
    <tbody>
    {{% for p in ['P1','P2','P3'] %}}
    {{% set delta = act_sections[p] - exp_sections[p] %}}
    <tr class="{{% if delta == 0 %}}table-success{{% elif delta|abs <= 1 %}}table-warning{{% else %}}table-danger{{% endif %}}">
      <td class="fw-medium">{{{{p}}}}</td>
      <td>{{{{act_sections[p]}}}}</td>
      <td>{{{{exp_sections[p]}}}}</td>
      <td>{{{{ '+' ~ delta if delta > 0 else delta }}}}</td>
    </tr>
    {{% endfor %}}
    </tbody>
  </table>
  </div>

  <!-- Muc do counts -->
  <div class="card mb-3 shadow-sm">
  <div class="card-header py-2 fw-semibold">Phân bố mức độ</div>
  <table class="table table-sm mb-0">
    <thead class="table-light"><tr><th>Mức độ</th><th>Thực tế</th><th>Chuẩn</th><th>Δ</th></tr></thead>
    <tbody>
    {{% for md in ['B','H','VD'] %}}
    {{% set delta = act_muc.get(md,0) - exp_muc.get(md,0) %}}
    <tr class="{{% if delta == 0 %}}table-success{{% elif delta|abs <= 2 %}}table-warning{{% else %}}table-danger{{% endif %}}">
      <td class="fw-medium">{{{{md}}}}</td>
      <td>{{{{act_muc.get(md,0)}}}}</td>
      <td>{{{{exp_muc.get(md,0)}}}}</td>
      <td>{{{{ '+' ~ delta if delta > 0 else delta }}}}</td>
    </tr>
    {{% endfor %}}
    </tbody>
  </table>
  </div>

  <!-- Chapter × Section matrix -->
  <div class="card shadow-sm">
  <div class="card-header py-2 fw-semibold">Ma trận chương × phần × mức độ</div>
  <div class="table-responsive">
  <table class="table table-sm table-bordered mb-0" style="font-size:.8rem">
    <thead class="table-light">
      <tr>
        <th>Chương</th>
        {{% for p in sections %}}{{% for m in muc_dos %}}<th>{{{{p}}}}-{{{{m}}}}</th>{{% endfor %}}{{% endfor %}}
        <th>Tổng</th>
      </tr>
    </thead>
    <tbody>
    {{% for code,info in chapters.items() %}}
    {{% set row_total = namespace(v=0) %}}
    <tr>
      <td class="fw-medium text-nowrap">{{{{code}}}}</td>
      {{% for p in sections %}}{{% for m in muc_dos %}}
      {{% set cnt = matrix.get(code,{{}}).get(p,{{}}).get(m,0) %}}
      {{% set _ = row_total.__setattr__('v', row_total.v + cnt) %}}
      <td class="{{% if cnt > 0 %}}table-primary{{% endif %}}">{{{{cnt if cnt else ''}}}}</td>
      {{% endfor %}}{{% endfor %}}
      <td class="fw-semibold">{{{{row_total.v if row_total.v else ''}}}}</td>
    </tr>
    {{% endfor %}}
    </tbody>
  </table>
  </div>
  </div>
</div>
<script src="{_BSJ}"></script>
</body></html>"""
