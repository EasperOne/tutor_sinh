"""
tutor-sinh v2 — Flask web app (single file)
Run via: python app.py  OR  tutor web
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from functools import wraps
from pathlib import Path

import yaml
from dotenv import load_dotenv
from flask import (
    Flask, abort, g, jsonify, make_response, redirect, render_template,
    request, send_file, session, url_for,
)
from jinja2 import DictLoader

load_dotenv()

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "tutor_sinh.db"
PROCESSED_DIR = ROOT / "question_bank" / "processed"
RAW_DIR = ROOT / "question_bank" / "raw"
SESSIONS_DIR = ROOT / "sessions"
EVAL_DIR = ROOT / "eval"
PROPOSALS_DIR = ROOT / "eval" / "proposals"
CONFIG_DIR = ROOT / "config"

HOST = os.getenv("TUTOR_HOST", "127.0.0.1")
PORT = int(os.getenv("TUTOR_PORT", "5000"))
AUTH_USER = os.getenv("TUTOR_USER", "")
AUTH_PASS = os.getenv("TUTOR_PASS", "")

CHAPTER_NAMES = {
    "DT_PT": "Di truyền cấp phân tử",
    "DT_TB": "Di truyền cấp tế bào",
    "CH_TV": "Chuyển hoá VC&NL ở thực vật",
    "CH_DV": "Chuyển hoá VC&NL ở động vật",
    "DT_BD": "Di truyền & biến dị cấp PT và TB",
    "QL_DT": "Quy luật di truyền",
    "DT_QT": "Di truyền quần thể",
    "DT_HP": "Di truyền học người & liệu pháp gene",
    "UD_DT": "Ứng dụng di truyền học",
    "TH":    "Tiến hoá",
    "ST_MT": "Sinh thái học và môi trường",
}

# ── Database ──────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql: str, params=()) -> list[sqlite3.Row]:
    return get_db().execute(sql, params).fetchall()


def query_one(sql: str, params=()) -> sqlite3.Row | None:
    return get_db().execute(sql, params).fetchone()


def execute(sql: str, params=()) -> sqlite3.Cursor:
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur

# ── Auth ──────────────────────────────────────────────────────────────────────

def check_auth(username: str, password: str) -> bool:
    return username == AUTH_USER and password == AUTH_PASS


def require_auth():
    from flask import Response
    return Response(
        "Authentication required", 401,
        {"WWW-Authenticate": 'Basic realm="tutor-sinh"'}
    )


def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if HOST != "127.0.0.1" and AUTH_USER:
            auth = request.authorization
            if not auth or not check_auth(auth.username, auth.password):
                return require_auth()
        return f(*args, **kwargs)
    return decorated

# ── Template helpers ──────────────────────────────────────────────────────────

def _badge_status(status: str) -> str:
    colors = {"done": "success", "partial": "warning", "pending": "secondary", "error": "danger"}
    return colors.get(status, "secondary")


def _score_color(score: float | None) -> str:
    if score is None:
        return "secondary"
    if score >= 0.85:
        return "success"
    if score >= 0.70:
        return "warning"
    return "danger"


def _fmt_date(d: str | None) -> str:
    if not d:
        return "—"
    try:
        return datetime.fromisoformat(d).strftime("%d/%m/%Y")
    except Exception:
        return str(d)


def _pct(v: float | None, decimals: int = 0) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{decimals}f}%"

# ── Templates ─────────────────────────────────────────────────────────────────

BASE = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}tutor-sinh{% endblock %}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
<style>
body{background:#f8f9fa}
.sidebar{width:220px;min-height:100vh;background:#1a3a5c;position:fixed;top:0;left:0;z-index:100;padding-top:1rem}
.sidebar a{color:#c8d8ea;text-decoration:none;display:block;padding:.5rem 1.25rem;border-radius:.25rem;margin:.1rem .5rem;font-size:.9rem}
.sidebar a:hover,.sidebar a.active{background:#2a5a8c;color:#fff}
.sidebar .brand{color:#fff;font-weight:700;font-size:1.1rem;padding:.5rem 1.25rem 1rem}
.main-content{margin-left:220px;padding:1.5rem}
.kbd{display:inline-block;padding:.1em .4em;font-size:.8em;border:1px solid #aaa;border-radius:3px;background:#f5f5f5;font-family:monospace}
.phan-badge{font-size:.75em;font-weight:600;padding:.15em .4em;border-radius:.2em;background:#e9ecef}
@media(max-width:768px){.sidebar{display:none}.main-content{margin-left:0}}
.table-sm td,.table-sm th{padding:.3rem .5rem;font-size:.875rem}
.chart-bar{height:18px;background:#2a5a8c;border-radius:2px;min-width:2px;display:inline-block;vertical-align:middle}
.wrong-chip{display:inline-block;padding:.1em .35em;border:1px solid #dc3545;border-radius:.25em;font-size:.78em;color:#dc3545;margin:.1em}
.wrong-chip.pass{border-color:#198754;color:#198754}
</style>
</head>
<body>
<nav class="sidebar">
  <div class="brand"><i class="bi bi-mortarboard-fill"></i> tutor-sinh</div>
  <a href="{{ url_for('dashboard') }}" class="{{ 'active' if request.endpoint=='dashboard' }}"><i class="bi bi-speedometer2"></i> Dashboard</a>
  <a href="{{ url_for('exams_list') }}" class="{{ 'active' if request.endpoint in ('exams_list','exam_detail','exam_edit_md') }}"><i class="bi bi-journal-text"></i> Đề thi</a>
  <a href="{{ url_for('sessions_list') }}" class="{{ 'active' if 'session' in (request.endpoint or '') }}"><i class="bi bi-pencil-square"></i> Buổi học</a>
  <a href="{{ url_for('review_queue') }}" class="{{ 'active' if request.endpoint=='review_queue' }}"><i class="bi bi-arrow-repeat"></i> Ôn tập</a>
  <a href="{{ url_for('student_overview') }}" class="{{ 'active' if request.endpoint=='student_overview' }}"><i class="bi bi-person-circle"></i> Học sinh</a>
  <a href="{{ url_for('study_plans_list') }}" class="{{ 'active' if 'study_plan' in (request.endpoint or '') }}"><i class="bi bi-calendar3"></i> Kế hoạch</a>
  <a href="{{ url_for('analytics') }}" class="{{ 'active' if request.endpoint=='analytics' }}"><i class="bi bi-graph-up-arrow"></i> Analytics</a>
  <a href="{{ url_for('eval_results') }}" class="{{ 'active' if 'eval' in (request.endpoint or '') }}"><i class="bi bi-bar-chart-line"></i> Đánh giá</a>
</nav>
<div class="main-content">
{% with msgs = get_flashed_messages(with_categories=true) %}{% if msgs %}
{% for cat, msg in msgs %}<div class="alert alert-{{ cat }} alert-dismissible fade show py-2" role="alert">{{ msg }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>{% endfor %}
{% endif %}{% endwith %}
{% block content %}{% endblock %}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
// Global keyboard shortcuts
document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
  if (e.key === 'g' && !e.ctrlKey && !e.metaKey) {
    if (!window._gPressed) { window._gPressed = true; setTimeout(()=>{window._gPressed=false}, 800); return; }
    window._gPressed = false; return;
  }
  {% block js_shortcuts %}{% endblock %}
});
</script>
{% block extra_js %}{% endblock %}
</body>
</html>"""

DASHBOARD_T = """{% extends "base.html" %}
{% block title %}Dashboard — tutor-sinh{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0"><i class="bi bi-speedometer2"></i> Dashboard</h4>
  <a href="{{ url_for('session_new') }}" class="btn btn-primary btn-sm"><i class="bi bi-plus-lg"></i> Buổi học mới</a>
</div>

<div class="row g-3 mb-4">
  <div class="col-6 col-md-3">
    <div class="card text-center">
      <div class="card-body py-3">
        <div class="fs-2 fw-bold text-primary">{{ stats.exam_count }}</div>
        <div class="text-muted small">Đề thi</div>
      </div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card text-center">
      <div class="card-body py-3">
        <div class="fs-2 fw-bold text-success">{{ stats.session_count }}</div>
        <div class="text-muted small">Buổi học</div>
      </div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card text-center">
      <div class="card-body py-3">
        <div class="fs-2 fw-bold text-warning">{{ stats.wrong_count }}</div>
        <div class="text-muted small">Câu sai (tổng)</div>
      </div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card text-center">
      <div class="card-body py-3">
        <div class="fs-2 fw-bold text-danger">{{ stats.redo_count }}</div>
        <div class="text-muted small">Cần redo</div>
      </div>
    </div>
  </div>
</div>

<div class="row g-3">
  <div class="col-md-6">
    <div class="card">
      <div class="card-header fw-semibold">Buổi học gần đây</div>
      <div class="card-body p-0">
        <table class="table table-sm table-hover mb-0">
          <thead><tr><th>Ngày</th><th>Đề</th><th>Sai</th></tr></thead>
          <tbody>
          {% for s in recent_sessions %}
          <tr>
            <td>{{ s.session_date }}</td>
            <td><a href="{{ url_for('session_review', sid=s.id) }}">{{ s.exam_id }}</a></td>
            <td>{{ s.wrong_count }}</td>
          </tr>
          {% else %}
          <tr><td colspan="3" class="text-muted text-center py-3">Chưa có buổi học</td></tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <div class="col-md-6">
    <div class="card">
      <div class="card-header fw-semibold">Tỷ lệ sai theo chương</div>
      <div class="card-body">
        {% for ch, cnt, tot in chapter_stats %}
        <div class="d-flex align-items-center mb-1">
          <div style="width:130px;font-size:.8rem" class="text-truncate" title="{{ chapter_names.get(ch, ch) }}">{{ ch }}</div>
          <div class="flex-grow-1 mx-2">
            <div class="bg-light rounded" style="height:14px">
              <div class="bg-danger rounded" style="height:14px;width:{{ [[(cnt/tot*100)|int, 0]|max, 100]|min }}%"></div>
            </div>
          </div>
          <div style="width:40px;font-size:.8rem;text-align:right">{{ cnt }}/{{ tot }}</div>
        </div>
        {% else %}
        <div class="text-muted small text-center py-2">Chưa có dữ liệu</div>
        {% endfor %}
      </div>
    </div>
  </div>
</div>
{% endblock %}"""

EXAMS_T = """{% extends "base.html" %}
{% block title %}Đề thi — tutor-sinh{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0"><i class="bi bi-journal-text"></i> Đề thi ({{ exams|length }})</h4>
  <div>
    <span class="kbd">e</span> exam detail &nbsp;
    <span class="kbd">/</span> search
  </div>
</div>
<div class="mb-3 d-flex gap-2 align-items-center">
  <input id="search" type="search" class="form-control form-control-sm" placeholder="Tìm kiếm đề…" style="max-width:300px">
  <button onclick="syncAllExams()" class="btn btn-outline-warning btn-sm" id="sync-all-btn" title="Sync tất cả từ classify.json"><i class="bi bi-arrow-clockwise"></i> Sync All</button>
</div>
<div class="table-responsive">
<table class="table table-sm table-hover" id="exam-table">
  <thead class="table-light">
    <tr>
      <th>Exam ID</th>
      <th>Classify</th>
      <th>Match</th>
      <th>MD Quality</th>
      <th>VD</th>
      <th></th>
    </tr>
  </thead>
  <tbody>
  {% for ex in exams %}
  <tr class="exam-row" data-id="{{ ex.id }}">
    <td><a href="{{ url_for('exam_detail', exam_id=ex.id) }}" class="fw-semibold text-decoration-none">{{ ex.id }}</a></td>
    <td><span class="badge bg-{{ ex.id | status_color(ex.classify_status) }}">{{ ex.classify_status }}</span></td>
    <td>
      {% if ex.ma_tran_match_score %}
      <span class="text-{{ ex.ma_tran_match_score | score_color }}">{{ "%.2f"|format(ex.ma_tran_match_score) }}</span>
      {% else %}—{% endif %}
    </td>
    <td>
      {% if ex.md_quality_score %}
      <span class="text-{{ ex.md_quality_score | score_color }}">{{ "%.2f"|format(ex.md_quality_score) }}</span>
      {% else %}—{% endif %}
    </td>
    <td>{{ ex.vd_count or '—' }}</td>
    <td>
      <a href="{{ url_for('exam_detail', exam_id=ex.id) }}" class="btn btn-outline-primary btn-sm py-0">Xem</a>
      <a href="{{ url_for('exam_delete', exam_id=ex.id) }}" class="btn btn-outline-danger btn-sm py-0" onclick="return confirm('Xóa đề và tất cả các buổi học liên quan?')">✕</a>
    </td>
  </tr>
  {% else %}
  <tr><td colspan="6" class="text-muted text-center py-4">Chưa có đề nào. Chạy <code>python scripts/init_db.py --seed</code></td></tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endblock %}
{% block extra_js %}
<script>
document.getElementById('search').addEventListener('input', function() {
  var q = this.value.toLowerCase();
  document.querySelectorAll('.exam-row').forEach(function(row) {
    row.style.display = row.dataset.id.toLowerCase().includes(q) ? '' : 'none';
  });
});
document.addEventListener('keydown', function(e) {
  if (e.key === '/' && e.target.tagName !== 'INPUT') {
    e.preventDefault();
    document.getElementById('search').focus();
  }
});

function syncAllExams() {
  var btn = document.getElementById('sync-all-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Syncing...';
  fetch('/api/sync-all-exams', {method:'POST'})
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        alert('Sync hoàn tất: ' + d.synced + ' đề synced' + (d.failed > 0 ? ', ' + d.failed + ' failed' : ''));
        location.reload();
      } else {
        alert('Sync thất bại: ' + d.error);
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Sync All';
      }
    })
    .catch(e => {
      alert('Sync thất bại: ' + e);
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Sync All';
    });
}
</script>
{% endblock %}"""

EXAM_DETAIL_T = """{% extends "base.html" %}
{% block title %}{{ exam.id }} — tutor-sinh{% endblock %}
{% block content %}
<nav aria-label="breadcrumb" class="mb-2">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a href="{{ url_for('exams_list') }}">Đề thi</a></li>
    <li class="breadcrumb-item active">{{ exam.id }}</li>
  </ol>
</nav>

<div class="row g-3 mb-3">
  <div class="col-md-8">
    <h5 class="mb-1">{{ exam.id }}</h5>
    <div class="d-flex gap-2 flex-wrap">
      <span class="badge bg-{{ exam.classify_status | status_color_plain }}">{{ exam.classify_status }}</span>
      {% if exam.screen_pass %}<span class="badge bg-success"><i class="bi bi-check2-circle"></i> Screen pass</span>{% endif %}
      {% if exam.ma_tran_match_score %}<span class="text-muted small">Match: {{ "%.3f"|format(exam.ma_tran_match_score) }}</span>{% endif %}
      {% if exam.md_quality_score %}<span class="text-muted small">MD quality: {{ "%.2f"|format(exam.md_quality_score) }}</span>{% endif %}
    </div>
  </div>
  <div class="col-md-4 text-md-end d-flex gap-2 justify-content-md-end align-items-start flex-wrap">
    <button onclick="syncExam()" class="btn btn-outline-warning btn-sm" id="sync-btn" title="Đọc lại từ classify.json"><i class="bi bi-arrow-clockwise"></i> Sync JSON</button>
    <a href="{{ url_for('exam_edit_md', exam_id=exam.id) }}" class="btn btn-outline-secondary btn-sm"><i class="bi bi-pencil"></i> Sửa MD</a>
    <a href="{{ url_for('session_new') }}?exam_id={{ exam.id }}" class="btn btn-primary btn-sm"><i class="bi bi-play-fill"></i> Học đề này</a>
  </div>
</div>

<!-- Viewer toggle -->
<div class="btn-group mb-3" id="toggle-bar">
  <button class="btn btn-primary btn-sm active" id="btn-md" onclick="showView('md')"><i class="bi bi-markdown"></i> Markdown</button>
  <button class="btn btn-outline-primary btn-sm" id="btn-pdf" onclick="showView('pdf')"><i class="bi bi-file-pdf"></i> PDF</button>
</div>

<!-- Markdown view -->
<div id="md-view" class="row g-3">
  <div class="col-lg-7">
    <div class="card">
      <div class="card-header fw-semibold small">Nội dung đề (de.md)</div>
      <div class="card-body p-3" style="max-height:70vh;overflow-y:auto;font-size:.85rem">
        <pre class="mb-0" style="white-space:pre-wrap;word-break:break-word">{{ md_content }}</pre>
      </div>
    </div>
  </div>
  <div class="col-lg-5">
    <div class="card">
      <div class="card-header fw-semibold small">Phân loại câu hỏi</div>
      <div class="card-body p-2">
        {% if questions %}
        <table class="table table-sm mb-0">
          <thead><tr><th>Phần</th><th>STT</th><th>Y</th><th>Chương</th><th>Mức độ</th></tr></thead>
          <tbody>
          {% for q in questions %}
          <tr>
            <td><span class="phan-badge">{{ q.phan }}</span></td>
            <td>{{ q.stt }}</td>
            <td>{{ q.y or '' }}</td>
            <td><span title="{{ chapter_names.get(q.chuong,'') }}" style="cursor:help">{{ q.chuong }}</span></td>
            <td>
              <span class="badge bg-{{ {'B':'info','H':'warning','VD':'danger'}.get(q.muc_do,'secondary') }}">{{ q.muc_do }}</span>
            </td>
          </tr>
          {% endfor %}
          </tbody>
        </table>
        {% else %}
        <div class="text-muted text-center py-3 small">Chưa phân loại. Dùng <code>prompts/sub_agent_classify.md</code></div>
        {% endif %}
      </div>
    </div>
  </div>
</div>

<!-- PDF view -->
<div id="pdf-view" style="display:none">
  <div class="card">
    <div class="card-header d-flex align-items-center gap-2">
      <button class="btn btn-sm btn-outline-secondary" id="pdf-prev" onclick="prevPage()"><i class="bi bi-chevron-left"></i></button>
      <span id="pdf-page-info" class="small">Trang 1 / 1</span>
      <button class="btn btn-sm btn-outline-secondary" id="pdf-next" onclick="nextPage()"><i class="bi bi-chevron-right"></i></button>
      <button class="btn btn-sm btn-outline-secondary ms-2" onclick="zoomOut()"><i class="bi bi-zoom-out"></i></button>
      <button class="btn btn-sm btn-outline-secondary" onclick="zoomIn()"><i class="bi bi-zoom-in"></i></button>
      <button class="btn btn-sm btn-outline-secondary" onclick="fitWidth(false)"><i class="bi bi-arrows-fullscreen"></i></button>
    </div>
    <div class="card-body p-0 text-center" id="pdf-scroll" style="max-height:80vh;overflow-y:auto;background:#555">
      <canvas id="pdf-canvas"></canvas>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js"></script>
<script>
var EXAM_ID = {{ exam.id | tojson }};
var HAS_PDF = {{ has_pdf | tojson }};
var pdfDoc = null, pdfPage = 1, pdfScale = 1.5, pdfRendering = false, pdfPending = null, inPdfView = false;

function showView(which) {
  document.getElementById('md-view').style.display = which === 'md' ? '' : 'none';
  document.getElementById('pdf-view').style.display = which === 'pdf' ? '' : 'none';
  document.getElementById('btn-md').className = 'btn btn-sm ' + (which === 'md' ? 'btn-primary active' : 'btn-outline-primary');
  document.getElementById('btn-pdf').className = 'btn btn-sm ' + (which === 'pdf' ? 'btn-primary active' : 'btn-outline-primary');
  inPdfView = (which === 'pdf');
  if (which === 'pdf' && !pdfDoc) initPdfViewer();
}

function initPdfViewer() {
  if (!HAS_PDF) { alert('PDF không tìm thấy cho đề này.'); return; }
  pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js';
  fetch('/pdf-data/' + EXAM_ID).then(function(resp) { return resp.json(); }).then(function(json) {
    var base64 = json.data.replace('data:application/pdf;base64,', '');
    var binary = atob(base64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return pdfjsLib.getDocument({data: bytes}).promise;
  }).then(function(doc) {
    pdfDoc = doc;
    document.getElementById('pdf-page-info').textContent = 'Trang 1 / ' + doc.numPages;
    fitWidth(true);
  }).catch(function(e) { alert('Không thể tải PDF: ' + e.message); });
}

function renderPage(n) {
  if (!pdfDoc) return;
  if (pdfRendering) { pdfPending = n; return; }
  pdfRendering = true;
  pdfDoc.getPage(n).then(function(page) {
    var vp = page.getViewport({scale: pdfScale});
    var canvas = document.getElementById('pdf-canvas');
    canvas.width = vp.width; canvas.height = vp.height;
    page.render({canvasContext: canvas.getContext('2d'), viewport: vp}).promise.then(function() {
      pdfRendering = false;
      document.getElementById('pdf-page-info').textContent = 'Trang ' + n + ' / ' + pdfDoc.numPages;
      if (pdfPending !== null) { var p = pdfPending; pdfPending = null; renderPage(p); }
    });
  });
}

function prevPage() { if (pdfDoc && pdfPage > 1) { pdfPage--; renderPage(pdfPage); } }
function nextPage() { if (pdfDoc && pdfPage < pdfDoc.numPages) { pdfPage++; renderPage(pdfPage); } }
function zoomIn() { pdfScale = Math.min(pdfScale + 0.25, 4); renderPage(pdfPage); }
function zoomOut() { pdfScale = Math.max(pdfScale - 0.25, 0.5); renderPage(pdfPage); }
function fitWidth(init) {
  if (!pdfDoc) return;
  pdfDoc.getPage(1).then(function(p) {
    var w = document.getElementById('pdf-scroll').clientWidth - 20;
    pdfScale = w / p.getViewport({scale:1}).width;
    renderPage(pdfPage);
  });
}

document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (!inPdfView) return;
  if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); prevPage(); }
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); nextPage(); }
});

function syncExam() {
  var btn = document.getElementById('sync-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  fetch('{{ url_for("api_sync_exam", exam_id=exam.id) }}', {method:'POST'})
    .then(r => r.json())
    .then(d => {
      if (d.ok) { location.reload(); }
      else { alert('Sync thất bại: ' + d.error); btn.disabled = false; btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Sync JSON'; }
    })
    .catch(() => { btn.disabled = false; btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Sync JSON'; });
}
</script>
{% endblock %}"""

EXAM_EDIT_MD_T = """{% extends "base.html" %}
{% block title %}Sửa MD — {{ exam_id }}{% endblock %}
{% block content %}
<nav aria-label="breadcrumb" class="mb-2">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a href="{{ url_for('exams_list') }}">Đề thi</a></li>
    <li class="breadcrumb-item"><a href="{{ url_for('exam_detail', exam_id=exam_id) }}">{{ exam_id }}</a></li>
    <li class="breadcrumb-item active">Sửa MD</li>
  </ol>
</nav>
<h5>Sửa de.md — {{ exam_id }}</h5>
<form method="post">
  <textarea name="content" class="form-control font-monospace" rows="35" style="font-size:.82rem">{{ content }}</textarea>
  <div class="mt-2 d-flex gap-2">
    <button type="submit" class="btn btn-primary btn-sm"><i class="bi bi-save"></i> Lưu</button>
    <a href="{{ url_for('exam_detail', exam_id=exam_id) }}" class="btn btn-outline-secondary btn-sm">Hủy</a>
  </div>
</form>
{% endblock %}
{% block extra_js %}
<script>
document.addEventListener('keydown', function(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault();
    document.querySelector('form').submit();
  }
});
</script>
{% endblock %}"""

SESSIONS_T = """{% extends "base.html" %}
{% block title %}Buổi học — tutor-sinh{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0"><i class="bi bi-pencil-square"></i> Buổi học</h4>
  <a href="{{ url_for('session_new') }}" class="btn btn-primary btn-sm"><i class="bi bi-plus-lg"></i> Buổi mới</a>
</div>
<div class="table-responsive">
<table class="table table-sm table-hover">
  <thead class="table-light">
    <tr><th>Ngày</th><th>Đề</th><th>Số câu sai</th><th></th></tr>
  </thead>
  <tbody>
  {% for s in sessions %}
  <tr>
    <td>{{ s.session_date }}</td>
    <td><a href="{{ url_for('exam_detail', exam_id=s.exam_id) }}">{{ s.exam_id }}</a></td>
    <td>{{ s.wrong_count }}</td>
    <td>
      <a href="{{ url_for('session_review', sid=s.id) }}" class="btn btn-outline-secondary btn-sm py-0">Xem</a>
      <a href="{{ url_for('session_record', sid=s.id) }}" class="btn btn-outline-primary btn-sm py-0">Nhập lại</a>
      <a href="{{ url_for('session_delete', sid=s.id) }}" class="btn btn-outline-danger btn-sm py-0" onclick="return confirm('Xóa buổi học này?')">✕</a>
    </td>
  </tr>
  {% else %}
  <tr><td colspan="4" class="text-center text-muted py-4">Chưa có buổi học nào</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endblock %}"""

SESSION_NEW_T = r"""{% extends "base.html" %}
{% block title %}Buổi học mới — tutor-sinh{% endblock %}
{% block content %}
<h5><i class="bi bi-plus-circle"></i> Tạo buổi học mới</h5>
<div class="card" style="max-width:500px">
  <div class="card-body">
    <form method="post">
      <div class="mb-3">
        <label class="form-label fw-semibold">Đề thi</label>
        <select name="exam_id" class="form-select" required>
          <option value="">— Chọn đề —</option>
          {% for ex in exams %}
          <option value="{{ ex.id }}" {{ 'selected' if ex.id == preselect }}>{{ ex.id }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="mb-3">
        <label class="form-label fw-semibold">Ngày học</label>
        <input type="date" name="session_date" class="form-control" value="{{ today }}" required>
      </div>
      <div class="mb-3">
        <label class="form-label fw-semibold">Ghi chú</label>
        <input type="text" name="notes" class="form-control" placeholder="Tuỳ chọn">
      </div>
      <button type="submit" class="btn btn-primary">Tạo &amp; nhập kết quả</button>
    </form>
  </div>
</div>
{% endblock %}"""

SESSION_RECORD_T = r"""{% extends "base.html" %}
{% block title %}Nhập kết quả — {{ session.exam_id }}{% endblock %}
{% block content %}
<nav aria-label="breadcrumb" class="mb-2">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a href="{{ url_for('sessions_list') }}">Buổi học</a></li>
    <li class="breadcrumb-item active">Nhập kết quả</li>
  </ol>
</nav>
<h5><i class="bi bi-pencil-square"></i> {{ session.exam_id }} — {{ session.session_date }}</h5>
<p class="text-muted small">Chọn những câu sai. Click để toggle. Nhấn <span class="kbd">S</span> để lưu.</p>

<form method="post" id="record-form">
<div class="row g-3 mb-3">
  <!-- Phần 1 -->
  <div class="col-12 col-md-4">
    <div class="card">
      <div class="card-header fw-semibold small">Phần 1 — Trắc nghiệm (18 câu)</div>
      <div class="card-body">
        <div class="d-flex flex-wrap gap-2">
        {% for i in range(1, 19) %}
          {% set key = "P1_" ~ i %}
          <label class="wrong-toggle" data-key="{{ key }}">
            <input type="checkbox" name="wrong" value="P1:{{ i }}" class="d-none"
              {{ 'checked' if key in current_wrong }}>
            <span class="wrong-chip {{ 'pass' if key not in current_wrong else '' }}" id="chip-{{ key }}">
              {{ i }}
            </span>
            <input type="checkbox" name="sai_ngu" value="P1:{{ i }}" class="sai-ngu-check d-none"
              title="Sai ngu (câu dễ làm sai)"
              {{ 'checked' if key in current_sai_ngu }}>
            <span class="sai-ngu-indicator d-none">~</span>
          </label>
        {% endfor %}
        </div>
      </div>
    </div>
  </div>
  <!-- Phần 2 -->
  <div class="col-12 col-md-4">
    <div class="card">
      <div class="card-header fw-semibold small">Phần 2 — Đúng/Sai (4 câu × 4 ý)</div>
      <div class="card-body">
        {% for q in range(1, 5) %}
        <div class="mb-2">
          <div class="small fw-semibold mb-1">Câu {{ q }}</div>
          <div class="d-flex gap-2">
          {% for y in ['a','b','c','d'] %}
            {% set key = "P2_" ~ q ~ "_" ~ y %}
            <label class="wrong-toggle" data-key="{{ key }}">
              <input type="checkbox" name="wrong" value="P2:{{ q }}:{{ y }}" class="d-none"
                {{ 'checked' if key in current_wrong }}>
              <span class="wrong-chip {{ 'pass' if key not in current_wrong else '' }}" id="chip-{{ key }}">
                {{ y }}
              </span>
              <input type="checkbox" name="sai_ngu" value="P2:{{ q }}:{{ y }}" class="sai-ngu-check d-none"
                title="Sai ngu (câu dễ làm sai)"
                {{ 'checked' if key in current_sai_ngu }}>
              <span class="sai-ngu-indicator d-none">~</span>
            </label>
          {% endfor %}
          </div>
        </div>
        {% endfor %}
      </div>
    </div>
  </div>
  <!-- Phần 3 -->
  <div class="col-12 col-md-4">
    <div class="card">
      <div class="card-header fw-semibold small">Phần 3 — Trả lời ngắn (6 câu)</div>
      <div class="card-body">
        <div class="d-flex flex-wrap gap-2">
        {% for i in range(1, 7) %}
          {% set key = "P3_" ~ i %}
          <label class="wrong-toggle" data-key="{{ key }}">
            <input type="checkbox" name="wrong" value="P3:{{ i }}" class="d-none"
              {{ 'checked' if key in current_wrong }}>
            <span class="wrong-chip {{ 'pass' if key not in current_wrong else '' }}" id="chip-{{ key }}">
              {{ i }}
            </span>
            <input type="checkbox" name="sai_ngu" value="P3:{{ i }}" class="sai-ngu-check d-none"
              title="Sai ngu (câu dễ làm sai)"
              {{ 'checked' if key in current_sai_ngu }}>
            <span class="sai-ngu-indicator d-none">~</span>
          </label>
        {% endfor %}
        </div>
      </div>
    </div>
  </div>
</div>

<div class="d-flex gap-2">
  <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> Lưu kết quả</button>
  <a href="{{ url_for('sessions_list') }}" class="btn btn-outline-secondary">Hủy</a>
</div>
</form>

<style>
.wrong-chip { cursor:pointer; user-select:none; }
input:checked + .wrong-chip { background:#dc3545; color:#fff; border-color:#dc3545; }
.sai-ngu-indicator { position:absolute; top:-5px; right:-5px; background:#6c757d; color:#fff; border-radius:50%; width:16px; height:16px; font-size:10px; display:flex; align-items:center; justify-content:center; cursor:pointer; }
.wrong-toggle { position:relative; }
</style>
<script>
document.querySelectorAll('.wrong-toggle').forEach(function(label) {
  var wrongCb = label.querySelector('input[name="wrong"]');
  var saiNguCb = label.querySelector('input[name="sai_ngu"]');
  var chip = label.querySelector('.wrong-chip');
  var indicator = label.querySelector('.sai-ngu-indicator');

  // Show indicator if sai ngu is pre-checked
  if (saiNguCb && saiNguCb.checked) {
    indicator.classList.remove('d-none');
  }

  label.addEventListener('click', function(e) {
    e.preventDefault();

    // If clicking on the chip itself, toggle wrong checkbox
    if (e.target === chip || e.target.classList.contains('wrong-chip')) {
      wrongCb.checked = !wrongCb.checked;
      chip.style.background = wrongCb.checked ? '#dc3545' : '';
      chip.style.color = wrongCb.checked ? '#fff' : '';
      chip.style.borderColor = wrongCb.checked ? '#dc3545' : '';

      // If unchecking wrong, also uncheck sai ngu
      if (!wrongCb.checked) {
        saiNguCb.checked = false;
        indicator.classList.add('d-none');
      }
    }
    // If clicking on sai ngu indicator, toggle sai ngu checkbox
    else if (e.target === indicator || e.target.classList.contains('sai-ngu-indicator')) {
      saiNguCb.checked = !saiNguCb.checked;
      indicator.classList.toggle('d-none', !saiNguCb.checked);

      // If checking sai ngu, also check wrong
      if (saiNguCb.checked && !wrongCb.checked) {
        wrongCb.checked = true;
        chip.style.background = '#dc3545';
        chip.style.color = '#fff';
        chip.style.borderColor = '#dc3545';
      }
    }
  });
});
document.addEventListener('keydown', function(e) {
  if (e.key === 's' || e.key === 'S') {
    if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
      document.getElementById('record-form').submit();
    }
  }
});
</script>
{% endblock %}"""

SESSION_REVIEW_T = r"""{% extends "base.html" %}
{% block title %}Kết quả — {{ session.exam_id }}{% endblock %}
{% block content %}
<nav aria-label="breadcrumb" class="mb-2">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a href="{{ url_for('sessions_list') }}">Buổi học</a></li>
    <li class="breadcrumb-item active">Xem kết quả</li>
  </ol>
</nav>
<h5>{{ session.exam_id }} — {{ session.session_date }}</h5>
<div class="row g-3 mb-3">
  {% for phan, items in wrong_by_phan.items() %}
  <div class="col-md-4">
    <div class="card">
      <div class="card-header fw-semibold small">{{ phan }} — {{ items|length }} câu sai</div>
      <div class="card-body">
        {% for w in items %}
        <div class="d-flex align-items-center justify-content-between mb-1">
          <div>
            <span class="wrong-chip">{{ w.phan }}·{{ w.stt }}{% if w.y %}.{{ w.y }}{% endif %}</span>
            <span class="text-muted small ms-1">{{ w.chuong or '' }}</span>
            {% if w.muc_do %}<span class="badge bg-{{ {'B':'info','H':'warning','VD':'danger'}.get(w.muc_do,'secondary') }} ms-1">{{ w.muc_do }}</span>{% endif %}
            {% if w.sai_ngu %}<span class="badge bg-secondary ms-1" title="Sai ngu">sai ngu</span>{% endif %}
            {% if w.on_tap_status and w.on_tap_status != 'not_yet' %}<span class="badge bg-{{ {'pass':'success','redo':'warning'}.get(w.on_tap_status,'secondary') }} ms-1">{{ {'pass':'pass','redo':'redo'}.get(w.on_tap_status,w.on_tap_status) }}</span>{% endif %}
          </div>
          <form method="post" action="{{ url_for('review_mark', wid=w.id) }}" class="d-flex gap-1">
            <button type="submit" name="status" value="pass" class="btn btn-success btn-sm py-0 px-1" title="Pass">✓</button>
            <button type="submit" name="status" value="redo" class="btn btn-warning btn-sm py-0 px-1" title="Redo">↺</button>
            <button type="submit" name="toggle_sai_ngu" value="1" class="btn btn-secondary btn-sm py-0 px-1" title="Sai ngu">~</button>
          </form>
        </div>
        {% endfor %}
      </div>
    </div>
  </div>
  {% else %}
  <div class="col-12"><div class="alert alert-success">Không có câu sai — Xuất sắc!</div></div>
  {% endfor %}
</div>
<a href="{{ url_for('session_record', sid=session.id) }}" class="btn btn-outline-secondary btn-sm">
  <i class="bi bi-pencil"></i> Sửa lại
</a>
{% endblock %}"""

REVIEW_T = r"""{% extends "base.html" %}
{% block title %}Ôn tập — tutor-sinh{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0"><i class="bi bi-arrow-repeat"></i> Ôn tập spaced repetition</h4>
</div>

<form method="get" class="row g-2 mb-3 align-items-end">
  <div class="col-auto">
    <label class="form-label small">Chương</label>
    <select name="chuong" class="form-select form-select-sm">
      <option value="">Tất cả</option>
      {% for code, name in chapter_names.items() %}
      <option value="{{ code }}" {{ 'selected' if filters.chuong == code }}>{{ code }} — {{ name }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="col-auto">
    <label class="form-label small">Mức độ</label>
    <select name="muc_do" class="form-select form-select-sm">
      <option value="">Tất cả</option>
      <option value="B" {{ 'selected' if filters.muc_do == 'B' }}>B</option>
      <option value="H" {{ 'selected' if filters.muc_do == 'H' }}>H</option>
      <option value="VD" {{ 'selected' if filters.muc_do == 'VD' }}>VD</option>
    </select>
  </div>
  <div class="col-auto">
    <label class="form-label small">Trạng thái</label>
    <select name="status" class="form-select form-select-sm">
      <option value="" {{ 'selected' if filters.status == '' }}>Cần ôn</option>
      <option value="all" {{ 'selected' if filters.status == 'all' }}>Tất cả</option>
      <option value="not_yet" {{ 'selected' if filters.status == 'not_yet' }}>Chưa ôn</option>
      <option value="redo" {{ 'selected' if filters.status == 'redo' }}>Redo</option>
      <option value="pass" {{ 'selected' if filters.status == 'pass' }}>Pass</option>
      <option value="sai_ngu" {{ 'selected' if filters.status == 'sai_ngu' }}>Sai ngu</option>
    </select>
  </div>
  <div class="col-auto">
    <label class="form-label small">Số câu</label>
    <input type="number" name="count" class="form-control form-control-sm" value="{{ filters.count or 20 }}" min="5" max="60" style="width:70px">
  </div>
  <div class="col-auto">
    <button type="submit" class="btn btn-primary btn-sm">Tạo bộ ôn</button>
  </div>
</form>

{% if items %}
<div class="table-responsive">
<table class="table table-sm table-hover">
  <thead class="table-light">
    <tr><th>Priority</th><th>Đề</th><th>Câu</th><th>Chương</th><th>Mức</th><th>Status</th><th>Số lần sai câu này</th><th>Hành động</th></tr>
  </thead>
  <tbody>
  {% for item in items %}
  <tr>
    <td>
      <div class="d-flex align-items-center gap-1">
        <span class="fw-bold">{{ item.priority }}</span>
        <div class="chart-bar" style="width:{{ item.priority }}px"></div>
      </div>
    </td>
    <td class="small">{{ item.exam_id }}</td>
    <td><span class="wrong-chip">{{ item.phan }}·{{ item.stt }}{% if item.y %}.{{ item.y }}{% endif %}</span></td>
    <td><span title="{{ chapter_names.get(item.chuong,'') }}" style="cursor:help">{{ item.chuong }}</span></td>
    <td><span class="badge bg-{{ {'B':'info','H':'warning','VD':'danger'}.get(item.muc_do,'secondary') }}">{{ item.muc_do }}</span></td>
    <td>
      {% if item.on_tap_status == 'redo' %}<span class="badge bg-warning text-dark">redo</span>
      {% elif item.on_tap_status == 'pass' %}<span class="badge bg-success">pass</span>
      {% else %}<span class="badge bg-light text-dark">chưa ôn</span>{% endif %}
      {% if item.sai_ngu %}<span class="badge bg-secondary ms-1">sai ngu</span>{% endif %}
    </td>
    <td>{{ item.wrong_count }}</td>
    <td>
      <form method="post" action="{{ url_for('review_mark', wid=item.wa_id) }}" class="d-flex gap-1">
        <input type="hidden" name="next" value="{{ url_for('review_queue', **filters) }}">
        <button type="submit" name="status" value="pass" class="btn btn-success btn-sm py-0 px-1">✓</button>
        <button type="submit" name="status" value="redo" class="btn btn-warning btn-sm py-0 px-1">↺</button>
        <button type="submit" name="toggle_sai_ngu" value="1" class="btn btn-secondary btn-sm py-0 px-1" title="Sai ngu">~</button>
      </form>
    </td>
  </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<div class="alert alert-info">Không có câu nào cần ôn tập với bộ lọc này.</div>
{% endif %}
{% endblock %}"""

ANALYTICS_T = """{% extends "base.html" %}
{% block title %}Analytics — tutor-sinh{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0"><i class="bi bi-graph-up-arrow"></i> Analytics</h4>
  <button class="btn btn-sm btn-outline-secondary" onclick="loadAll()">
    <i class="bi bi-arrow-clockwise"></i> Refresh
  </button>
</div>

<!-- Section 1: Hero metrics -->
<div class="row g-3 mb-4">
  <div class="col-md-4">
    <div class="card h-100">
      <div class="card-body text-center d-flex flex-column justify-content-center py-4">
        <div class="text-muted small mb-1">Điểm sẵn sàng thi</div>
        <div class="display-4 fw-bold mb-1" id="readiness-score">—</div>
        <span class="badge fs-6" id="readiness-label">...</span>
        <div class="mt-2 small text-muted" id="readiness-error"></div>
        <div class="row g-1 mt-2 text-center" id="readiness-components" style="display:none!important">
          <div class="col-3"><div class="small text-muted">Xu hướng</div><div class="fw-bold" id="rc-trend">—</div></div>
          <div class="col-3"><div class="small text-muted">Bao phủ</div><div class="fw-bold" id="rc-cov">—</div></div>
          <div class="col-3"><div class="small text-muted">Ôn tập</div><div class="fw-bold" id="rc-ret">—</div></div>
          <div class="col-3"><div class="small text-muted">Thời gian</div><div class="fw-bold" id="rc-time">—</div></div>
        </div>
      </div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card h-100">
      <div class="card-body text-center d-flex flex-column justify-content-center py-4">
        <div class="text-muted small mb-1">Dự báo BoGD-equivalent</div>
        <div class="display-4 fw-bold mb-1 text-primary" id="projected-range">—</div>
        <div class="text-muted small" id="projected-ci"></div>
        <div class="text-muted small mt-1" id="projected-warn"></div>
      </div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card h-100">
      <div class="card-body py-3">
        <div class="small fw-semibold mb-2">Phần thi</div>
        <div id="section-stats"><div class="text-muted small">Loading...</div></div>
      </div>
    </div>
  </div>
</div>

<div class="card mb-3">
  <div class="card-header fw-semibold">Chuẩn hóa theo nguồn đề</div>
  <div class="card-body">
    <div class="row g-3 mb-2">
      <div class="col-md-4">
        <div class="small text-muted">Raw recent average</div>
        <div class="fs-3 fw-bold" id="raw-recent-score">—</div>
      </div>
      <div class="col-md-4">
        <div class="small text-muted">BoGD-equivalent</div>
        <div class="fs-3 fw-bold text-primary" id="bogd-score">—</div>
      </div>
      <div class="col-md-4">
        <div class="small text-muted">Confidence</div>
        <div class="fs-5 fw-semibold" id="bogd-confidence">—</div>
        <div class="small text-muted" id="bogd-warning"></div>
      </div>
    </div>
    <div id="source-breakdown"><div class="text-muted small">Loading...</div></div>
  </div>
</div>

<!-- Section 2: Score trend -->
<div class="card mb-3">
  <div class="card-header fw-semibold d-flex justify-content-between align-items-center">
    <span>Xu hướng điểm số</span>
    <span class="text-muted small" id="trend-sessions"></span>
  </div>
  <div class="card-body">
    <div style="position:relative;height:200px"><canvas id="trendChart"></canvas></div>
  </div>
</div>

<!-- Section 3 & 4: Chapter mastery + Difficulty -->
<div class="row g-3 mb-3">
  <div class="col-lg-8">
    <div class="card h-100">
      <div class="card-header fw-semibold">Mức độ thành thạo theo chương</div>
      <div class="card-body">
        <div style="position:relative;height:300px"><canvas id="chapterChart"></canvas></div>
      </div>
    </div>
  </div>
  <div class="col-lg-4">
    <div class="card h-100">
      <div class="card-header fw-semibold">Phân tích mức độ</div>
      <div class="card-body">
        <div class="row g-2 mb-3">
          <div class="col-4 text-center"><canvas id="bChart" width="90" height="90"></canvas><div class="small mt-1 fw-semibold">Biết</div><div class="small text-muted" id="b-rate">—</div></div>
          <div class="col-4 text-center"><canvas id="hChart" width="90" height="90"></canvas><div class="small mt-1 fw-semibold">Hiểu</div><div class="small text-muted" id="h-rate">—</div></div>
          <div class="col-4 text-center"><canvas id="vdChart" width="90" height="90"></canvas><div class="small mt-1 fw-semibold">Vận dụng</div><div class="small text-muted" id="vd-rate">—</div></div>
        </div>
        <div class="alert py-2 mb-0" id="pattern-alert" role="alert" style="font-size:.85rem"></div>
      </div>
    </div>
  </div>
</div>

<!-- Section 5: Retention -->
<div class="card mb-3">
  <div class="card-header fw-semibold">Tỷ lệ ghi nhớ (Retention)</div>
  <div class="card-body">
    <div id="retention-stats"><div class="text-muted small">Loading...</div></div>
  </div>
</div>

<!-- Section 6: Actions -->
<div class="card">
  <div class="card-header fw-semibold">Cài đặt & Hành động</div>
  <div class="card-body">
    <div class="row g-3">
      <div class="col-md-5">
        <div class="small fw-semibold mb-2">Đặt mục tiêu thi</div>
        <form id="profile-form" class="row g-2">
          <div class="col-7">
            <input type="date" id="target-date" class="form-control form-control-sm" placeholder="Ngày thi">
          </div>
          <div class="col-5">
            <input type="number" id="target-score" class="form-control form-control-sm" placeholder="Điểm mục tiêu" min="0" max="10" step="0.25">
          </div>
          <div class="col-12">
            <button type="submit" class="btn btn-primary btn-sm w-100">Lưu mục tiêu</button>
          </div>
        </form>
      </div>
      <div class="col-md-7 d-flex flex-column gap-2 justify-content-end">
        <button class="btn btn-outline-secondary btn-sm" onclick="recalcScores()">
          <i class="bi bi-calculator"></i> Tính lại điểm tất cả buổi học
        </button>
        <a href="/api/analytics/export-summary" class="btn btn-outline-primary btn-sm" download="analytics_export.json">
          <i class="bi bi-download"></i> Xuất dữ liệu JSON (cho AI)
        </a>
        <div class="small text-muted" id="action-status"></div>
      </div>
    </div>
  </div>
</div>

{% endblock %}
{% block extra_js %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script>
var _charts = {};
function _mkChart(id, type, labels, datasets, opts) {
  var ctx = document.getElementById(id);
  if (!ctx) return;
  if (_charts[id]) { _charts[id].destroy(); }
  _charts[id] = new Chart(ctx, {type: type, data: {labels: labels, datasets: datasets},
    options: Object.assign({responsive:true, maintainAspectRatio:false}, opts||{})});
}
function _donut(id, correct_pct, wrong_pct) {
  var ctx = document.getElementById(id);
  if (!ctx) return;
  if (_charts[id]) { _charts[id].destroy(); }
  _charts[id] = new Chart(ctx, {type:'doughnut',
    data:{labels:['Đúng','Sai'],datasets:[{data:[correct_pct,wrong_pct],backgroundColor:['#198754','#dc3545'],borderWidth:0}]},
    options:{responsive:true, maintainAspectRatio:true, aspectRatio:1,
             plugins:{legend:{display:false}}, cutout:'70%'}});
}

function loadReadiness() {
  fetch('/api/analytics/readiness').then(r=>r.json()).then(function(d) {
    if (d.error) {
      document.getElementById('readiness-score').textContent = '—';
      document.getElementById('readiness-label').textContent = d.label||'';
      document.getElementById('readiness-error').textContent = d.error;
      return;
    }
    document.getElementById('readiness-score').textContent = d.readiness_score;
    var lbl = document.getElementById('readiness-label');
    lbl.textContent = d.label;
    lbl.className = 'badge fs-6 bg-' + d.color;
    var rc = document.getElementById('readiness-components');
    rc.style.display = '';
    document.getElementById('rc-trend').textContent = (d.components.trend||0)+'%';
    document.getElementById('rc-cov').textContent = (d.components.coverage||0)+'%';
    document.getElementById('rc-ret').textContent = (d.components.retention||0)+'%';
    document.getElementById('rc-time').textContent = (d.components.time_buffer||0)+'%';
    if (d.target_date) document.getElementById('target-date').value = d.target_date;
    if (d.target_score) document.getElementById('target-score').value = d.target_score;
  }).catch(function(e){document.getElementById('readiness-error').textContent='Error: '+e;});
}

function loadProjected() {
  fetch('/api/analytics/bogd-projection?n=6').then(r=>r.json()).then(function(d) {
    if (!d.bogd_equivalent_score && d.bogd_equivalent_score!==0) {
      document.getElementById('projected-range').textContent = '—';
      return;
    }
    document.getElementById('projected-range').textContent = d.bogd_equivalent_score.toFixed(1) + 'đ';
    document.getElementById('projected-ci').textContent = 'Raw gần đây: ' + d.raw_recent_avg.toFixed(1) + 'đ';
    if (d.warnings && d.warnings.length) {
      document.getElementById('projected-warn').textContent = d.warnings[0];
    }
  }).catch(console.error);
}

function loadSourceNormalization() {
  fetch('/api/analytics/bogd-projection?n=6').then(r=>r.json()).then(function(d) {
    document.getElementById('raw-recent-score').textContent = d.raw_recent_avg || d.raw_recent_avg===0 ? d.raw_recent_avg.toFixed(2)+'đ' : '—';
    document.getElementById('bogd-score').textContent = d.bogd_equivalent_score || d.bogd_equivalent_score===0 ? d.bogd_equivalent_score.toFixed(2)+'đ' : '—';
    document.getElementById('bogd-confidence').textContent = d.confidence || '—';
    document.getElementById('bogd-warning').textContent = d.warnings && d.warnings.length ? d.warnings[0] : '';
  }).catch(console.error);
  fetch('/api/analytics/source-breakdown?n=12').then(r=>r.json()).then(function(rows) {
    if (!rows || !rows.length) {
      document.getElementById('source-breakdown').innerHTML = '<div class="text-muted small">Chưa có dữ liệu</div>';
      return;
    }
    var html = '<div class="table-responsive"><table class="table table-sm mb-0">'
      +'<thead><tr><th>Nguồn</th><th>Buổi</th><th>Raw avg</th><th>BoGD eq.</th><th>Reliability</th></tr></thead><tbody>';
    rows.forEach(function(r) {
      html += '<tr><td><b>'+r.source_type+'</b>'+(r.official_anchor?' <span class="badge bg-success">anchor</span>':'')+'</td>'
        +'<td>'+r.sessions+'</td><td>'+r.raw_avg.toFixed(2)+'</td><td>'+r.bogd_equivalent_avg.toFixed(2)+'</td>'
        +'<td>'+r.reliability+'</td></tr>';
    });
    html += '</tbody></table></div>';
    document.getElementById('source-breakdown').innerHTML = html;
  }).catch(console.error);
}

function loadTrend() {
  fetch('/api/analytics/score-trend?n=8').then(r=>r.json()).then(function(d) {
    if (!d || !d.length) return;
    document.getElementById('trend-sessions').textContent = d.length + ' buổi gần nhất';
    var labels = d.map(function(x){return x.date;});
    var data = d.map(function(x){return x.score;});
    var datasets = [{label:'Điểm',data:data,borderColor:'#0d6efd',backgroundColor:'rgba(13,110,253,0.08)',fill:true,tension:0.3,pointRadius:4}];
    fetch('/api/student-profile').then(r=>r.json()).then(function(p){
      if (p.target_score) {
        datasets.push({label:'Mục tiêu',data:labels.map(function(){return p.target_score;}),borderColor:'#dc3545',borderDash:[6,4],pointRadius:0,fill:false});
      }
    }).catch(function(){}).finally(function(){
      _mkChart('trendChart','line',labels,datasets,{scales:{y:{min:0,max:10,ticks:{stepSize:1}}},plugins:{legend:{position:'bottom'}}});
    });
  }).catch(console.error);
}

function loadChapterMastery() {
  fetch('/api/analytics/chapter-mastery?n=5').then(r=>r.json()).then(function(d) {
    if (!d||!d.length) return;
    var labels = d.map(function(x){return x.chapter;});
    var gap = d.map(function(x){return Math.round(x.knowledge_gap_rate*100);});
    var careless = d.map(function(x){return Math.round(x.careless_rate*100);});
    var ok = d.map(function(x){return Math.max(0,100-Math.round(x.error_rate*100));});
    var arrows = d.map(function(x){return x.trend==='improving'?' ↑':x.trend==='declining'?' ↓':'';});
    var fullLabels = d.map(function(x,i){return x.chapter+arrows[i];});
    _mkChart('chapterChart','bar',fullLabels,[
      {label:'Lỗ hổng kiến thức',data:gap,backgroundColor:'#dc3545'},
      {label:'Sai ngu',data:careless,backgroundColor:'#ffc107'},
      {label:'Đúng',data:ok,backgroundColor:'#198754'},
    ],{indexAxis:'y',scales:{x:{stacked:true,max:100,ticks:{callback:function(v){return v+'%';}}},y:{stacked:true}},plugins:{legend:{position:'bottom'},tooltip:{callbacks:{label:function(ctx){return ctx.dataset.label+': '+ctx.raw+'%';}}}}});
  }).catch(console.error);
}

function loadDifficulty() {
  fetch('/api/analytics/difficulty-profile?n=5').then(r=>r.json()).then(function(d) {
    var rates = d.rates || {};
    ['B','H','VD'].forEach(function(m,i) {
      var id = ['b','h','vd'][i];
      var info = rates[m] || {};
      var err = Math.round((info.error_rate||0)*100);
      var ok = 100-err;
      _donut(id+'Chart', ok, err);
      document.getElementById(id+'-rate').textContent = 'Sai: '+err+'%';
    });
    var pa = document.getElementById('pattern-alert');
    pa.className = 'alert py-2 mb-0 alert-'+(d.pattern_color==='success'?'success':d.pattern_color==='danger'?'danger':'warning');
    pa.textContent = d.pattern_label || d.pattern;
  }).catch(console.error);
}

function loadSection() {
  fetch('/api/analytics/section-profile?n=5').then(r=>r.json()).then(function(d) {
    if (!d.P1) return;
    var p1 = d.P1, p2 = d.P2, p3 = d.P3;
    var html = '<table class="table table-sm mb-0">'
      +'<thead><tr><th>Phần</th><th>Đúng</th><th>Sai TB/buổi</th><th>Ghi chú</th></tr></thead><tbody>'
      +'<tr><td><b>P1</b></td><td>'+(p1.accuracy*100).toFixed(0)+'%</td><td>'+p1.avg_wrong_per_session+'</td><td>Trắc nghiệm</td></tr>'
      +'<tr><td><b>P2</b></td><td>'+(p2.full_correct_rate*100).toFixed(0)+'% đủ 4ý</td><td>'+((p2.partial||0)+' câu phần</td><td>Đúng/Sai</td></tr>').replace('phần','phần'+' | '+(p2.fully_wrong||0)+' câu 0ý</td><td>Đúng/Sai</td></tr>')
      +'<tr><td><b>P3</b></td><td>'+(p3.accuracy*100).toFixed(0)+'%</td><td>'+p3.avg_wrong_per_session+'</td><td>Trả lời ngắn</td></tr>'
      +'</tbody></table>';
    document.getElementById('section-stats').innerHTML = html;
  }).catch(function(){document.getElementById('section-stats').textContent='';});
}

function loadRetention() {
  fetch('/api/analytics/retention').then(r=>r.json()).then(function(d) {
    var total = d.total_reviewed||0;
    var rate = Math.round((d.retention_rate||0)*100);
    var barW = rate;
    var html = '<div class="row g-3 align-items-center">'
      +'<div class="col-md-6">'
      +'<div class="d-flex gap-3 mb-2">'
      +'<div class="text-center"><div class="fs-4 fw-bold text-success">'+d.passed+'</div><div class="small text-muted">Pass</div></div>'
      +'<div class="text-center"><div class="fs-4 fw-bold text-warning">'+d.redo+'</div><div class="small text-muted">Redo</div></div>'
      +'<div class="text-center"><div class="fs-4 fw-bold text-secondary">'+d.sai_ngu+'</div><div class="small text-muted">Sai ngu</div></div>'
      +'<div class="text-center"><div class="fs-4 fw-bold">'+total+'</div><div class="small text-muted">Tổng ôn</div></div>'
      +'</div>'
      +'<div class="progress mb-1" style="height:20px">'
      +'<div class="progress-bar bg-success" style="width:'+barW+'%">'+rate+'%</div>'
      +'</div><div class="small text-muted">Tỷ lệ ghi nhớ: '+(total>0?rate+'%':'chưa có dữ liệu')+'</div>'
      +'</div>';
    if (d.struggling_questions && d.struggling_questions.length) {
      html += '<div class="col-md-6"><div class="small fw-semibold mb-1">Câu cần ôn lại ngay:</div><div class="d-flex flex-wrap gap-1">';
      d.struggling_questions.slice(0,10).forEach(function(q) {
        var label = q.phan+'\xB7'+q.stt+(q.y?'.'+q.y:'');
        html += '<span class="wrong-chip" title="'+q.exam_id+' — '+(q.chuong||'')+'">'+label+'</span>';
      });
      html += '</div></div>';
    }
    html += '</div>';
    document.getElementById('retention-stats').innerHTML = html;
  }).catch(function(){document.getElementById('retention-stats').textContent='Chưa có dữ liệu.';});
}

function loadSection() {
  fetch('/api/analytics/section-profile?n=5').then(r=>r.json()).then(function(d) {
    if (!d || !d.P1) { document.getElementById('section-stats').innerHTML='<div class="text-muted small">Chưa có dữ liệu</div>'; return; }
    var p1=d.P1, p2=d.P2, p3=d.P3;
    document.getElementById('section-stats').innerHTML =
      '<table class="table table-sm mb-0 small">'
      +'<tbody>'
      +'<tr><th>P1</th><td>Đúng: '+(p1.accuracy*100).toFixed(0)+'%</td><td>Sai TB: '+p1.avg_wrong_per_session+'/buổi</td></tr>'
      +'<tr><th>P2</th><td>Đủ 4ý: '+(p2.full_correct_rate*100).toFixed(0)+'%</td><td>Thiếu ý: '+(p2.partial_rate*100).toFixed(0)+'%</td></tr>'
      +'<tr><th>P3</th><td>Đúng: '+(p3.accuracy*100).toFixed(0)+'%</td><td>Sai TB: '+p3.avg_wrong_per_session+'/buổi</td></tr>'
      +'</tbody></table>';
  }).catch(function(){});
}

document.getElementById('profile-form').addEventListener('submit', function(e) {
  e.preventDefault();
  fetch('/api/student-profile', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      target_exam_date: document.getElementById('target-date').value,
      target_score: parseFloat(document.getElementById('target-score').value)||null
    })
  }).then(r=>r.json()).then(function(){
    document.getElementById('action-status').textContent = '✓ Đã lưu mục tiêu';
    loadAll();
  }).catch(console.error);
});

function recalcScores() {
  document.getElementById('action-status').textContent = 'Đang tính lại...';
  fetch('/api/admin/recalculate-scores', {method:'POST'})
    .then(r=>r.json()).then(function(d) {
      document.getElementById('action-status').textContent = '✓ Đã tính lại '+d.updated+' buổi học';
      loadTrend();
    }).catch(console.error);
}

function loadAll() {
  loadReadiness();
  loadProjected();
  loadSourceNormalization();
  loadTrend();
  loadChapterMastery();
  loadDifficulty();
  loadSection();
  loadRetention();
}

loadAll();
</script>
{% endblock %}"""

STUDENT_T = r"""{% extends "base.html" %}
{% block title %}Học sinh — tutor-sinh{% endblock %}
{% block content %}
<h4 class="mb-3"><i class="bi bi-person-circle"></i> Tổng quan học sinh</h4>

<div class="row g-3 mb-4">
  <div class="col-md-3 col-6">
    <div class="card text-center"><div class="card-body py-3">
      <div class="fs-3 fw-bold text-primary">{{ stats.sessions_30d }}</div>
      <div class="text-muted small">Buổi / 30 ngày</div>
    </div></div>
  </div>
  <div class="col-md-3 col-6">
    <div class="card text-center"><div class="card-body py-3">
      <div class="fs-3 fw-bold {{ 'text-success' if stats.pass_rate > 0.7 else 'text-warning' }}">{{ (stats.pass_rate * 100)|int }}%</div>
      <div class="text-muted small">Tỷ lệ đúng</div>
    </div></div>
  </div>
  <div class="col-md-3 col-6">
    <div class="card text-center"><div class="card-body py-3">
      <div class="fs-3 fw-bold text-danger">{{ stats.total_wrong }}</div>
      <div class="text-muted small">Tổng câu sai</div>
    </div></div>
  </div>
  <div class="col-md-3 col-6">
    <div class="card text-center"><div class="card-body py-3">
      <div class="fs-3 fw-bold text-warning">{{ stats.redo_pending }}</div>
      <div class="text-muted small">Chờ redo</div>
    </div></div>
  </div>
</div>

<div class="row g-3">
  <div class="col-md-6">
    <div class="card">
      <div class="card-header fw-semibold">Sai theo chương</div>
      <div class="card-body">
        {% for ch, wrong, total in chapter_breakdown %}
        <div class="d-flex align-items-center mb-2">
          <div style="width:80px;font-size:.8rem;font-weight:600">{{ ch }}</div>
          <div class="flex-grow-1 mx-2">
            <div class="progress" style="height:14px">
              <div class="progress-bar bg-danger" style="width:{{ (wrong/total*100)|int if total else 0 }}%"></div>
            </div>
          </div>
          <div style="width:60px;font-size:.8rem;text-align:right">{{ wrong }}/{{ total }}</div>
        </div>
        {% else %}<div class="text-muted small text-center py-2">Chưa có dữ liệu</div>{% endfor %}
      </div>
    </div>
  </div>
  <div class="col-md-6">
    <div class="card">
      <div class="card-header fw-semibold">Sai theo mức độ</div>
      <div class="card-body">
        {% for muc, wrong, total in muc_do_breakdown %}
        <div class="d-flex align-items-center mb-2">
          <div style="width:40px;font-size:.9rem;font-weight:600">
            <span class="badge bg-{{ {'B':'info','H':'warning','VD':'danger'}.get(muc,'secondary') }}">{{ muc }}</span>
          </div>
          <div class="flex-grow-1 mx-2">
            <div class="progress" style="height:14px">
              <div class="progress-bar bg-{{ {'B':'info','H':'warning','VD':'danger'}.get(muc,'secondary') }}"
                   style="width:{{ (wrong/total*100)|int if total else 0 }}%"></div>
            </div>
          </div>
          <div style="width:80px;font-size:.8rem;text-align:right">{{ wrong }}/{{ total }} ({{ (wrong/total*100)|int if total else 0 }}%)</div>
        </div>
        {% else %}<div class="text-muted small text-center py-2">Chưa có dữ liệu</div>{% endfor %}
      </div>
    </div>
  </div>
</div>
{% endblock %}"""

STUDY_PLANS_T = r"""{% extends "base.html" %}
{% block title %}Kế hoạch — tutor-sinh{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0"><i class="bi bi-calendar3"></i> Kế hoạch ôn tập</h4>
  <button class="btn btn-primary btn-sm" data-bs-toggle="modal" data-bs-target="#genModal">
    <i class="bi bi-magic"></i> Tạo kế hoạch
  </button>
</div>

{% if plans %}
<div class="list-group">
{% for p in plans %}
<a href="{{ url_for('study_plan_detail', pid=p.id) }}" class="list-group-item list-group-item-action">
  <div class="d-flex justify-content-between">
    <div class="fw-semibold">{{ p.title }}</div>
    <small class="text-muted">{{ p.created_at[:10] }}</small>
  </div>
</a>
{% endfor %}
</div>
{% else %}
<div class="alert alert-info">
  Chưa có kế hoạch. Nhấn "Tạo kế hoạch" để tạo prompt cho Claude và paste kết quả vào.
</div>
{% endif %}

<!-- Generate modal -->
<div class="modal fade" id="genModal" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title">Tạo prompt kế hoạch ôn tập</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <form method="post" action="{{ url_for('generate_plan_prompt') }}">
      <div class="modal-body">
        <div class="row g-2">
          <div class="col-md-6">
            <label class="form-label small">Tên học sinh</label>
            <input type="text" name="student_name" class="form-control form-control-sm" value="Học sinh">
          </div>
          <div class="col-md-6">
            <label class="form-label small">Ngày thi</label>
            <input type="date" name="exam_date" class="form-control form-control-sm" value="2026-06-26">
          </div>
        </div>
        <div class="mt-3">
          <label class="form-label small">Kết quả kế hoạch (paste từ Claude vào đây — tùy chọn)</label>
          <textarea name="plan_markdown" class="form-control font-monospace" rows="6" placeholder="Để trống để chỉ xem prompt..."></textarea>
        </div>
        <div class="mt-2">
          <label class="form-label small">Tiêu đề kế hoạch</label>
          <input type="text" name="title" class="form-control form-control-sm" placeholder="Kế hoạch tháng 5/2026">
        </div>
      </div>
      <div class="modal-footer">
        <button type="submit" name="action" value="prompt" class="btn btn-outline-primary btn-sm">Xem prompt</button>
        <button type="submit" name="action" value="save" class="btn btn-primary btn-sm">Lưu kế hoạch</button>
      </div>
      </form>
    </div>
  </div>
</div>
{% endblock %}"""

STUDY_PLAN_DETAIL_T = r"""{% extends "base.html" %}
{% block title %}{{ plan.title }} — tutor-sinh{% endblock %}
{% block content %}
<nav aria-label="breadcrumb" class="mb-2">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a href="{{ url_for('study_plans_list') }}">Kế hoạch</a></li>
    <li class="breadcrumb-item active">{{ plan.title }}</li>
  </ol>
</nav>
<div class="d-flex justify-content-between mb-3">
  <h5>{{ plan.title }}</h5>
  <small class="text-muted">{{ plan.created_at[:10] }}</small>
</div>
{% if plan.plan_markdown %}
<div class="card">
  <div class="card-body">
    <div id="plan-content">{{ plan.plan_markdown | markdown_safe }}</div>
  </div>
</div>
{% else %}
<div class="alert alert-info">Kế hoạch chưa có nội dung. Quay lại và paste kết quả từ Claude.</div>
{% endif %}
{% if plan.source_json %}
<details class="mt-3">
  <summary class="small text-muted">Dữ liệu nguồn (JSON)</summary>
  <pre class="mt-2 p-3 bg-light rounded small">{{ plan.source_json }}</pre>
</details>
{% endif %}
{% endblock %}"""

PLAN_PROMPT_T = r"""{% extends "base.html" %}
{% block title %}Prompt kế hoạch — tutor-sinh{% endblock %}
{% block content %}
<h5><i class="bi bi-magic"></i> Prompt kế hoạch ôn tập</h5>
<p class="text-muted small">Copy prompt bên dưới, mở Claude, paste vào và nhận kết quả. Sau đó quay lại và lưu kết quả.</p>
<div class="d-flex gap-2 mb-2">
  <button class="btn btn-outline-primary btn-sm" onclick="copyPrompt()"><i class="bi bi-clipboard"></i> Copy prompt</button>
  <a href="{{ url_for('study_plans_list') }}" class="btn btn-outline-secondary btn-sm">Quay lại</a>
</div>
<div class="card">
  <div class="card-body p-0">
    <pre id="prompt-text" class="p-3 mb-0" style="white-space:pre-wrap;font-size:.82rem;max-height:75vh;overflow-y:auto">{{ prompt_text }}</pre>
  </div>
</div>
<script>
function copyPrompt() {
  navigator.clipboard.writeText(document.getElementById('prompt-text').textContent)
    .then(function() { alert('Đã copy!'); });
}
</script>
{% endblock %}"""

EVAL_T = r"""{% extends "base.html" %}
{% block title %}Đánh giá — tutor-sinh{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0"><i class="bi bi-bar-chart-line"></i> Kết quả đánh giá phân loại</h4>
  <a href="{{ url_for('eval_proposals') }}" class="btn btn-outline-secondary btn-sm">
    <i class="bi bi-lightbulb"></i> Proposals ({{ proposal_count }})
  </a>
</div>

{% if batches %}
{% for batch in batches %}
<div class="card mb-3">
  <div class="card-header d-flex justify-content-between">
    <span class="fw-semibold">Batch {{ batch.id }}</span>
    <small class="text-muted">{{ batch.created_at[:16] }}</small>
  </div>
  <div class="card-body">
    {% set metrics = batch.metrics %}
    {% if metrics %}
    <div class="row g-3 mb-3">
      <div class="col-auto">
        <div class="text-muted small">Aggregate accuracy</div>
        <div class="fs-4 fw-bold text-{{ 'success' if metrics.aggregate_accuracy >= 0.85 else 'warning' if metrics.aggregate_accuracy >= 0.70 else 'danger' }}">
          {{ "%.1f"|format(metrics.aggregate_accuracy * 100) }}%
        </div>
      </div>
      {% if metrics.phan_accuracy %}
      {% for p, acc in metrics.phan_accuracy.items() %}
      <div class="col-auto">
        <div class="text-muted small">{{ p }}</div>
        <div class="fw-bold">{{ "%.1f"|format(acc * 100) }}%</div>
      </div>
      {% endfor %}
      {% endif %}
    </div>
    {% if metrics.top_errors %}
    <div class="small fw-semibold mb-1">Top lỗi phân loại</div>
    <table class="table table-sm">
      <thead><tr><th>Đề</th><th>Câu</th><th>Dự đoán</th><th>Đúng</th><th>Field</th></tr></thead>
      <tbody>
      {% for err in metrics.top_errors[:10] %}
      <tr>
        <td class="small">{{ err.exam_id }}</td>
        <td>{{ err.phan }}·{{ err.stt }}{% if err.y %}.{{ err.y }}{% endif %}</td>
        <td class="text-danger">{{ err.predicted }}</td>
        <td class="text-success">{{ err.true }}</td>
        <td class="text-muted small">{{ err.field }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
    {% endif %}
    {% else %}
    <div class="text-muted small">Không có metrics</div>
    {% endif %}
  </div>
</div>
{% endfor %}
{% else %}
<div class="alert alert-info">
  Chưa có kết quả. Chạy <code>python scripts/eval_harness.py</code> để đánh giá.
</div>
{% endif %}
{% endblock %}"""

PROPOSALS_T = r"""{% extends "base.html" %}
{% block title %}Proposals — tutor-sinh{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0"><i class="bi bi-lightbulb"></i> Guideline Proposals</h4>
  <a href="{{ url_for('eval_results') }}" class="btn btn-outline-secondary btn-sm">← Đánh giá</a>
</div>
{% if proposals %}
{% for p in proposals %}
<div class="card mb-3">
  <div class="card-header d-flex justify-content-between align-items-center">
    <div>
      <span class="badge bg-{{ 'warning' if p.status == 'pending' else 'success' if p.status == 'accepted' else 'secondary' }}">{{ p.status }}</span>
      <span class="ms-2 small text-muted">{{ p.created_at[:16] }}</span>
      {% if p.source_batch_id %}<span class="ms-2 small text-muted">Batch: {{ p.source_batch_id }}</span>{% endif %}
    </div>
    {% if p.status == 'pending' %}
    <div class="d-flex gap-1">
      <form method="post" action="{{ url_for('proposal_resolve', pid=p.id) }}" class="d-inline">
        <button name="action" value="accept" class="btn btn-success btn-sm py-0">Chấp nhận</button>
      </form>
      <form method="post" action="{{ url_for('proposal_resolve', pid=p.id) }}" class="d-inline">
        <button name="action" value="reject" class="btn btn-outline-danger btn-sm py-0">Từ chối</button>
      </form>
    </div>
    {% endif %}
  </div>
  <div class="card-body">
    <pre class="mb-0" style="white-space:pre-wrap;font-size:.82rem;max-height:400px;overflow-y:auto">{{ p.proposal_markdown }}</pre>
  </div>
</div>
{% endfor %}
{% else %}
<div class="alert alert-info">
  Chưa có proposal. Monitor agent tạo file trong <code>eval/proposals/</code>, sau đó import vào DB.
</div>
{% endif %}
{% endblock %}"""

TEMPLATES = {
    "base.html": BASE,
    "dashboard.html": DASHBOARD_T,
    "exams.html": EXAMS_T,
    "exam_detail.html": EXAM_DETAIL_T,
    "exam_edit_md.html": EXAM_EDIT_MD_T,
    "sessions.html": SESSIONS_T,
    "session_new.html": SESSION_NEW_T,
    "session_record.html": SESSION_RECORD_T,
    "session_review.html": SESSION_REVIEW_T,
    "review.html": REVIEW_T,
    "student.html": STUDENT_T,
    "study_plans.html": STUDY_PLANS_T,
    "study_plan_detail.html": STUDY_PLAN_DETAIL_T,
    "plan_prompt.html": PLAN_PROMPT_T,
    "eval.html": EVAL_T,
    "proposals.html": PROPOSALS_T,
    "analytics.html": ANALYTICS_T,
}

# ── Migrations ────────────────────────────────────────────────────────────────

def _run_migrations(db_path: Path) -> None:
    """Idempotent schema migrations — safe to run on every startup."""
    import sqlite3 as _sq
    conn = _sq.connect(db_path)
    # Drop is_correct (replaced by session-level scoring)
    try:
        conn.execute("ALTER TABLE wrong_answers DROP COLUMN is_correct")
        conn.commit()
    except Exception:
        pass
    # Add review-tracking columns
    for stmt in (
        "ALTER TABLE wrong_answers ADD COLUMN reviewed_at TEXT",
        "ALTER TABLE wrong_answers ADD COLUMN review_count INTEGER DEFAULT 0",
        "ALTER TABLE sessions ADD COLUMN score REAL",
        "ALTER TABLE exams ADD COLUMN source_type TEXT",
        "ALTER TABLE exams ADD COLUMN source_profile_json TEXT",
        "ALTER TABLE exams ADD COLUMN style_summary_json TEXT",
        "ALTER TABLE exams ADD COLUMN validation_json TEXT",
        "ALTER TABLE questions ADD COLUMN skill TEXT",
        "ALTER TABLE questions ADD COLUMN competency TEXT",
        "ALTER TABLE questions ADD COLUMN calculation_load TEXT",
        "ALTER TABLE questions ADD COLUMN bo_gd_fit TEXT",
        "ALTER TABLE questions ADD COLUMN confidence REAL",
        "ALTER TABLE questions ADD COLUMN classify_notes TEXT",
    ):
        try:
            conn.execute(stmt)
            conn.commit()
        except Exception:
            pass
    # Student profile table
    conn.execute("""CREATE TABLE IF NOT EXISTS student_profile (
        id INTEGER PRIMARY KEY,
        target_exam_date TEXT,
        target_score REAL,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    conn.close()


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", os.urandom(24).hex())
    app.jinja_loader = DictLoader(TEMPLATES)
    app.teardown_appcontext(close_db)

    # Auto-initialize schema (safe — CREATE IF NOT EXISTS)
    from scripts.init_db import init_db as _init_db
    _init_db(reset=False).close()

    # Idempotent migrations
    _run_migrations(DB_PATH)

    # Jinja filters
    import markdown as _markdown

    @app.template_filter("status_color_plain")
    def status_color_plain(status):
        return _badge_status(status)

    @app.template_filter("status_color")
    def status_color_filter(exam_id, status):
        return _badge_status(status)

    @app.template_filter("score_color")
    def score_color_filter(score):
        return _score_color(score)

    @app.template_filter("markdown_safe")
    def markdown_safe_filter(text):
        from markupsafe import Markup
        return Markup(_markdown.markdown(text or "", extensions=["tables", "nl2br"]))

    @app.context_processor
    def inject_globals():
        return {"chapter_names": CHAPTER_NAMES, "today": date.today().isoformat()}

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.route("/")
    @auth_required
    def dashboard():
        stats = {
            "exam_count": (query_one("SELECT COUNT(*) FROM exams") or [0])[0],
            "session_count": (query_one("SELECT COUNT(DISTINCT session_date) FROM sessions") or [0])[0],
            "wrong_count": (query_one("SELECT COUNT(*) FROM wrong_answers") or [0])[0],
            "redo_count": (query_one("SELECT COUNT(*) FROM wrong_answers WHERE on_tap_status='redo'") or [0])[0],
        }
        recent_sessions = query("""
            SELECT s.id, s.session_date, s.exam_id,
                   COUNT(wa.id) as wrong_count
            FROM sessions s
            LEFT JOIN wrong_answers wa ON wa.session_id = s.id
            GROUP BY s.id ORDER BY s.session_date DESC LIMIT 10
        """)
        chapter_stats = query("""
            SELECT q.chuong, COUNT(wa.id) as wrong, COUNT(DISTINCT q.id) as total
            FROM questions q
            LEFT JOIN wrong_answers wa ON wa.session_id IN (SELECT id FROM sessions)
              AND wa.phan = q.phan AND wa.stt = q.stt AND (wa.y = q.y OR (wa.y IS NULL AND q.y IS NULL))
            WHERE q.chuong IS NOT NULL
            GROUP BY q.chuong HAVING wrong > 0
            ORDER BY wrong DESC LIMIT 10
        """)
        return render_template("dashboard.html", stats=stats,
                               recent_sessions=recent_sessions,
                               chapter_stats=chapter_stats)

    @app.route("/exams")
    @auth_required
    def exams_list():
        exams = query("SELECT * FROM exams ORDER BY id")
        return render_template("exams.html", exams=exams)

    @app.route("/exams/<exam_id>")
    @auth_required
    def exam_detail(exam_id):
        exam = query_one("SELECT * FROM exams WHERE id=?", (exam_id,))
        if not exam:
            abort(404)
        questions = query("SELECT * FROM questions WHERE exam_id=? ORDER BY phan, stt, y", (exam_id,))
        md_path = ROOT / (exam["md_path"] or f"question_bank/processed/{exam_id}/de.md")
        md_content = ""
        if md_path.exists():
            md_content = md_path.read_text(encoding="utf-8")
        pdf_path = ROOT / "question_bank" / "raw" / f"{exam_id}.pdf"
        return render_template("exam_detail.html", exam=exam, questions=questions,
                               md_content=md_content, has_pdf=pdf_path.exists())

    @app.route("/exams/<exam_id>/delete")
    @auth_required
    def exam_delete(exam_id):
        import json
        exam = query_one("SELECT * FROM exams WHERE id=?", (exam_id,))
        if not exam:
            abort(404)
        session_ids = [r["id"] for r in query("SELECT id FROM sessions WHERE exam_id=?", (exam_id,))]
        for sid in session_ids:
            execute("DELETE FROM wrong_answers WHERE session_id=?", (sid,))
        execute("DELETE FROM sessions WHERE exam_id=?", (exam_id,))
        execute("DELETE FROM questions WHERE exam_id=?", (exam_id,))
        execute("DELETE FROM exams WHERE id=?", (exam_id,))
        for batch in query("SELECT id, exam_ids_json FROM eval_batches"):
            try:
                exam_ids = json.loads(batch["exam_ids_json"] or "[]")
                if exam_id in exam_ids:
                    exam_ids = [e for e in exam_ids if e != exam_id]
                    execute("UPDATE eval_batches SET exam_ids_json=? WHERE id=?",
                            (json.dumps(exam_ids), batch["id"]))
            except Exception:
                pass
        for rs in query("SELECT id, pdf_path FROM review_sets"):
            if rs["pdf_path"] and exam_id in rs["pdf_path"]:
                execute("DELETE FROM review_sets WHERE id=?", (rs["id"],))
        from flask import flash
        flash(f"Đã xóa đề {exam_id} và {len(session_ids)} buổi học", "success")
        return redirect(url_for("exams_list"))

    @app.route("/exams/<exam_id>/edit-md", methods=["GET", "POST"])
    @auth_required
    def exam_edit_md(exam_id):
        exam = query_one("SELECT * FROM exams WHERE id=?", (exam_id,))
        if not exam:
            abort(404)
        md_path = ROOT / "question_bank" / "processed" / exam_id / "de.md"
        if request.method == "POST":
            content = request.form.get("content", "")
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(content, encoding="utf-8")
            from scripts.quality_check import check_file
            score = check_file(md_path)["score"]
            execute("UPDATE exams SET md_quality_score=?, updated_at=datetime('now') WHERE id=?",
                    (score, exam_id))
            return redirect(url_for("exam_detail", exam_id=exam_id))
        content = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        return render_template("exam_edit_md.html", exam_id=exam_id, content=content)

    @app.route("/pdf/<exam_id>")
    @auth_required
    def serve_pdf(exam_id):
        path = RAW_DIR / f"{exam_id}.pdf"
        if not path.exists():
            abort(404)
        return send_file(path, mimetype="application/pdf")

    @app.route("/pdf-data/<exam_id>")
    @auth_required
    def serve_pdf_data(exam_id):
        import base64
        path = RAW_DIR / f"{exam_id}.pdf"
        if not path.exists():
            return jsonify({"error": "PDF not found"}), 404
        with open(path, "rb") as f:
            pdf_data = base64.b64encode(f.read()).decode("utf-8")
        return jsonify({"data": f"data:application/pdf;base64,{pdf_data}"})

    # ── Sessions ──────────────────────────────────────────────────────────────

    @app.route("/sessions")
    @auth_required
    def sessions_list():
        sessions = query("""
            SELECT s.*, COUNT(wa.id) as wrong_count
            FROM sessions s
            LEFT JOIN wrong_answers wa ON wa.session_id = s.id
            GROUP BY s.id ORDER BY s.session_date DESC
        """)
        return render_template("sessions.html", sessions=sessions)

    @app.route("/session/new", methods=["GET", "POST"])
    @auth_required
    def session_new():
        if request.method == "POST":
            exam_id = request.form["exam_id"]
            session_date = request.form["session_date"]
            notes = request.form.get("notes", "")
            cur = execute(
                "INSERT INTO sessions (session_date, exam_id, notes) VALUES (?,?,?)",
                (session_date, exam_id, notes)
            )
            return redirect(url_for("session_record", sid=cur.lastrowid))
        exams = query("SELECT id FROM exams ORDER BY id")
        preselect = request.args.get("exam_id", "")
        return render_template("session_new.html", exams=exams, preselect=preselect,
                               today=date.today().isoformat())

    @app.route("/session/<int:sid>/record", methods=["GET", "POST"])
    @auth_required
    def session_record(sid):
        sess = query_one("SELECT * FROM sessions WHERE id=?", (sid,))
        if not sess:
            abort(404)
        if request.method == "POST":
            execute("DELETE FROM wrong_answers WHERE session_id=?", (sid,))
            wrong_list = []
            sai_ngu_list = set(request.form.getlist("sai_ngu"))

            for val in request.form.getlist("wrong"):
                parts = val.split(":")
                phan, stt = parts[0], int(parts[1])
                y = parts[2] if len(parts) > 2 else None
                sai_ngu = 1 if val in sai_ngu_list else 0
                execute(
                    "INSERT INTO wrong_answers (session_id, phan, stt, y, sai_ngu) VALUES (?,?,?,?,?)",
                    (sid, phan, stt, y, sai_ngu)
                )
                wrong_list.append(val)
            from scripts.analytics import session_score
            score = session_score(sid, get_db())
            execute("UPDATE sessions SET score=? WHERE id=?", (score, sid))
            # Also save YAML
            _save_session_yaml(sess)
            return redirect(url_for("session_review", sid=sid))
        existing = query("SELECT phan, stt, y, sai_ngu FROM wrong_answers WHERE session_id=?", (sid,))
        current_wrong = set()
        current_sai_ngu = set()
        for w in existing:
            key = None
            if w["y"]:
                key = f"P2_{w['stt']}_{w['y']}"
            elif w["phan"] == "P1":
                key = f"P1_{w['stt']}"
            else:
                key = f"P3_{w['stt']}"
            current_wrong.add(key)
            if w["sai_ngu"]:
                current_sai_ngu.add(key)
        return render_template("session_record.html", session=sess, current_wrong=current_wrong, current_sai_ngu=current_sai_ngu)

    @app.route("/session/<int:sid>/review")
    @auth_required
    def session_review(sid):
        sess = query_one("SELECT * FROM sessions WHERE id=?", (sid,))
        if not sess:
            abort(404)
        wrong_rows = query("""
            SELECT wa.id, wa.phan, wa.stt, wa.y, wa.on_tap_status, wa.sai_ngu, q.chuong, q.muc_do
            FROM wrong_answers wa
            LEFT JOIN questions q ON q.exam_id=? AND q.phan=wa.phan AND q.stt=wa.stt
              AND (q.y=wa.y OR (q.y IS NULL AND wa.y IS NULL))
            WHERE wa.session_id=?
            ORDER BY wa.phan, wa.stt, wa.y
        """, (sess["exam_id"], sid))
        wrong_by_phan: dict = {}
        for w in wrong_rows:
            p = w["phan"]
            wrong_by_phan.setdefault(p, []).append(w)
        return render_template("session_review.html", session=sess, wrong_by_phan=wrong_by_phan)

    @app.route("/session/<int:sid>/delete")
    @auth_required
    def session_delete(sid):
        sess = query_one("SELECT * FROM sessions WHERE id=?", (sid,))
        if not sess:
            abort(404)
        execute("DELETE FROM wrong_answers WHERE session_id=?", (sid,))
        execute("DELETE FROM sessions WHERE id=?", (sid,))
        from flask import flash
        flash(f"Đã xóa buổi học {sess['exam_id']} ({sess['session_date']})", "success")
        return redirect(url_for("sessions_list"))

    # ── Review / spaced repetition ────────────────────────────────────────────

    @app.route("/review")
    @auth_required
    def review_queue():
        from scripts.spaced_repetition import suggest_review_set, compute_priorities
        chuong_filter = request.args.get("chuong") or None
        muc_do_filter = request.args.get("muc_do") or None
        status_filter = request.args.get("status") or ""
        count = int(request.args.get("count", 20))
        filters = {"chuong": chuong_filter or "", "muc_do": muc_do_filter or "", "status": status_filter, "count": count}

        rows = query("""
            SELECT wa.id as wa_id, wa.phan, wa.stt, wa.y, wa.on_tap_status, wa.sai_ngu,
                   s.session_date as last_wrong_date, s.exam_id,
                   q.chuong, q.muc_do,
                   COUNT(wa2.id) as wrong_count
            FROM wrong_answers wa
            JOIN sessions s ON s.id = wa.session_id
            LEFT JOIN questions q ON q.exam_id = s.exam_id AND q.phan = wa.phan
              AND q.stt = wa.stt AND (q.y = wa.y OR (q.y IS NULL AND wa.y IS NULL))
            LEFT JOIN sessions s2 ON s2.exam_id = s.exam_id
            LEFT JOIN wrong_answers wa2 ON wa2.session_id = s2.id
              AND wa2.phan = wa.phan AND wa2.stt = wa.stt
              AND (wa2.y = wa.y OR (wa2.y IS NULL AND wa.y IS NULL))
            GROUP BY s.exam_id, wa.phan, wa.stt, wa.y
            ORDER BY s.session_date DESC
        """)
        wrong_history = [dict(r) for r in rows]
        
        if status_filter == "all":
            items = compute_priorities(wrong_history, date.today())
        elif status_filter in ("not_yet", "redo", "pass"):
            items = [dict(item, priority=compute_priorities([item], date.today())[0]["priority"])
                     for item in wrong_history if item.get("on_tap_status") == status_filter]
            items.sort(key=lambda x: x["priority"], reverse=True)
        elif status_filter == "sai_ngu":
            items = [dict(item, priority=compute_priorities([item], date.today())[0]["priority"])
                     for item in wrong_history if item.get("sai_ngu")]
            items.sort(key=lambda x: x["priority"], reverse=True)
        else:
            items = suggest_review_set(
                wrong_history,
                today=date.today(),
                target_count=count,
                chapters=[chuong_filter] if chuong_filter else None,
                muc_do_filter=[muc_do_filter] if muc_do_filter else None,
            )
        return render_template("review.html", items=items, filters=filters)

    @app.route("/review/<int:wid>/mark", methods=["POST"])
    @auth_required
    def review_mark(wid):
        from flask import flash
        if request.form.get("toggle_sai_ngu"):
            row = query_one("SELECT sai_ngu FROM wrong_answers WHERE id=?", (wid,))
            if not row:
                abort(404)
            sai_ngu = 0 if row["sai_ngu"] else 1
            execute("UPDATE wrong_answers SET sai_ngu=? WHERE id=?", (sai_ngu, wid))
            flash(f"Đã cập nhật sai ngu: {'có' if sai_ngu else 'không'}", "success")
        else:
            status = request.form.get("status", "not_yet")
            if status not in {"not_yet", "redo", "pass"}:
                status = "not_yet"
            execute(
                """UPDATE wrong_answers
                   SET on_tap_status=?, reviewed_at=datetime('now'),
                       review_count=COALESCE(review_count,0)+1
                   WHERE id=?""",
                (status, wid)
            )
            status_labels = {"pass": "Pass", "redo": "Redo", "not_yet": "Chưa ôn"}
            flash(f"Đã cập nhật trạng thái: {status_labels.get(status, status)}", "success")
        next_url = request.form.get("next") or request.referrer or url_for("review_queue")
        return redirect(next_url)

    # ── Analytics API (v2) ──────────────────────────────────────────────────────

    def _analytics_conn():
        """Open a fresh read connection to the DB for analytics functions."""
        import sqlite3 as _sq
        c = _sq.connect(DB_PATH)
        c.row_factory = _sq.Row
        return c

    @app.route("/api/analytics/score-trend")
    @auth_required
    def api_score_trend():
        from scripts.analytics import score_trend as _st
        n = int(request.args.get("n", 8))
        conn = _analytics_conn()
        result = _st(conn, n)
        conn.close()
        return jsonify(result)

    @app.route("/api/analytics/chapter-mastery")
    @auth_required
    def api_chapter_mastery():
        from scripts.analytics import chapter_mastery as _cm
        n = int(request.args.get("n", 5))
        conn = _analytics_conn()
        result = _cm(conn, n)
        conn.close()
        return jsonify(result)

    @app.route("/api/analytics/difficulty-profile")
    @auth_required
    def api_difficulty_profile():
        from scripts.analytics import difficulty_profile as _dp
        n = int(request.args.get("n", 5))
        conn = _analytics_conn()
        result = _dp(conn, n)
        conn.close()
        return jsonify(result)

    @app.route("/api/analytics/section-profile")
    @auth_required
    def api_section_profile():
        from scripts.analytics import section_profile as _sp
        n = int(request.args.get("n", 5))
        conn = _analytics_conn()
        result = _sp(conn, n)
        conn.close()
        return jsonify(result)

    @app.route("/api/analytics/retention")
    @auth_required
    def api_retention():
        from scripts.analytics import retention_rate as _rr
        chapter = request.args.get("chapter") or None
        conn = _analytics_conn()
        result = _rr(conn, chapter)
        conn.close()
        return jsonify(result)

    @app.route("/api/analytics/projected-score")
    @auth_required
    def api_projected_score():
        from scripts.analytics import projected_score as _ps
        n = int(request.args.get("n", 3))
        conn = _analytics_conn()
        result = _ps(conn, n)
        conn.close()
        return jsonify(result)

    @app.route("/api/analytics/bogd-projection")
    @auth_required
    def api_bogd_projection():
        from scripts.analytics import bogd_equivalent_projection as _bp
        n = int(request.args.get("n", 6))
        conn = _analytics_conn()
        result = _bp(conn, n)
        conn.close()
        return jsonify(result)

    @app.route("/api/analytics/source-breakdown")
    @auth_required
    def api_source_breakdown():
        from scripts.analytics import source_breakdown as _sb
        n = int(request.args.get("n", 12))
        conn = _analytics_conn()
        result = _sb(conn, n)
        conn.close()
        return jsonify(result)

    @app.route("/api/analytics/readiness")
    @auth_required
    def api_readiness():
        from scripts.analytics import readiness_score as _rs
        conn = _analytics_conn()
        result = _rs(conn)
        conn.close()
        return jsonify(result)

    @app.route("/api/analytics/export-summary")
    @auth_required
    def api_export_summary():
        from scripts.analytics import export_summary as _es
        conn = _analytics_conn()
        result = _es(conn)
        conn.close()
        resp = make_response(json.dumps(result, ensure_ascii=False, indent=2))
        resp.headers["Content-Type"] = "application/json"
        resp.headers["Content-Disposition"] = "attachment; filename=analytics_export.json"
        return resp

    @app.route("/api/student-profile", methods=["GET", "POST"])
    @auth_required
    def api_student_profile():
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            exam_date = data.get("target_exam_date")
            score = data.get("target_score")
            existing = query_one("SELECT id FROM student_profile ORDER BY id DESC LIMIT 1")
            if existing:
                execute(
                    "UPDATE student_profile SET target_exam_date=?, target_score=? WHERE id=?",
                    (exam_date, score, existing["id"]),
                )
            else:
                execute(
                    "INSERT INTO student_profile (target_exam_date, target_score) VALUES (?,?)",
                    (exam_date, score),
                )
            return jsonify({"ok": True})
        row = query_one("SELECT * FROM student_profile ORDER BY id DESC LIMIT 1")
        if not row:
            return jsonify({})
        return jsonify({"target_exam_date": row["target_exam_date"], "target_score": row["target_score"]})

    @app.route("/api/admin/recalculate-scores", methods=["POST"])
    @auth_required
    def api_recalculate_scores():
        from scripts.analytics import recalculate_all_scores as _ras
        conn = _analytics_conn()
        updated = _ras(conn)
        conn.close()
        return jsonify({"ok": True, "updated": updated})

    @app.route("/api/sync-exam/<exam_id>", methods=["POST"])
    @auth_required
    def api_sync_exam(exam_id: str):
        import json as _json
        from scripts.classification_schema import summarize_classification_style as _style_summary, validate_classifications as _validate_classifications
        from scripts.quality_check import check_file as _qcheck
        from scripts.source_profiles import detect_source_profile as _detect_source_profile

        processed_dir = ROOT / "question_bank" / "processed"
        raw_dir = ROOT / "question_bank" / "raw"
        exam_dir = processed_dir / exam_id
        classify_path = exam_dir / "classify.json"
        md_path = exam_dir / "de.md"
        pdf_path = raw_dir / f"{exam_id}.pdf"

        if not classify_path.exists():
            return jsonify({"ok": False, "error": "classify.json not found"}), 404

        try:
            with open(classify_path, encoding="utf-8") as f:
                clf = _json.load(f)
        except Exception as e:
            return jsonify({"ok": False, "error": f"JSON parse error: {e}"}), 400

        classifications = clf.get("classifications", [])
        source_profile = clf.get("source_profile") or _detect_source_profile(exam_id)
        source_type = source_profile.get("source_type", "Unknown")
        validation = clf.get("validation") or _validate_classifications(classifications, strict_new_fields=False)
        style_summary = clf.get("style_summary") or _style_summary(classifications)
        classify_status = "done" if len(classifications) >= 40 else "partial"
        match_score = clf.get("ma_tran_match_score")
        vd_count = clf.get("vd_count")
        section_counts = _json.dumps(clf.get("section_counts", {}))
        muc_do_counts = _json.dumps(clf.get("muc_do_counts", {}))
        screen_pass = 1 if clf.get("screen_pass") else 0

        md_quality = None
        if md_path.exists():
            md_quality = _qcheck(md_path)["score"]

        execute(
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
             source_type, _json.dumps(source_profile, ensure_ascii=False),
             _json.dumps(style_summary, ensure_ascii=False),
             _json.dumps(validation, ensure_ascii=False)),
        )
        if classifications:
            execute("DELETE FROM questions WHERE exam_id=?", (exam_id,))
            for c in classifications:
                execute(
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

        return jsonify({"ok": True, "questions": len(classifications), "status": classify_status})

    @app.route("/api/sync-all-exams", methods=["POST"])
    @auth_required
    def api_sync_all_exams():
        import json as _json
        from scripts.classification_schema import summarize_classification_style as _style_summary, validate_classifications as _validate_classifications
        from scripts.quality_check import check_file as _qcheck
        from scripts.source_profiles import detect_source_profile as _detect_source_profile

        processed_dir = ROOT / "question_bank" / "processed"
        raw_dir = ROOT / "question_bank" / "raw"

        if not processed_dir.exists():
            return jsonify({"ok": False, "error": "processed directory not found"}), 404

        results = {"synced": 0, "failed": 0, "errors": []}

        for exam_dir in processed_dir.iterdir():
            if not exam_dir.is_dir():
                continue

            exam_id = exam_dir.name
            classify_path = exam_dir / "classify.json"
            md_path = exam_dir / "de.md"
            pdf_path = raw_dir / f"{exam_id}.pdf"

            if not classify_path.exists():
                continue

            try:
                with open(classify_path, encoding="utf-8") as f:
                    clf = _json.load(f)

                classifications = clf.get("classifications", [])
                source_profile = clf.get("source_profile") or _detect_source_profile(exam_id)
                source_type = source_profile.get("source_type", "Unknown")
                validation = clf.get("validation") or _validate_classifications(classifications, strict_new_fields=False)
                style_summary = clf.get("style_summary") or _style_summary(classifications)
                classify_status = "done" if len(classifications) >= 40 else "partial"
                match_score = clf.get("ma_tran_match_score")
                vd_count = clf.get("vd_count")
                section_counts = _json.dumps(clf.get("section_counts", {}))
                muc_do_counts = _json.dumps(clf.get("muc_do_counts", {}))
                screen_pass = 1 if clf.get("screen_pass") else 0

                md_quality = None
                if md_path.exists():
                    md_quality = _qcheck(md_path)["score"]

                execute(
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
                     source_type, _json.dumps(source_profile, ensure_ascii=False),
                     _json.dumps(style_summary, ensure_ascii=False),
                     _json.dumps(validation, ensure_ascii=False)),
                )
                if classifications:
                    execute("DELETE FROM questions WHERE exam_id=?", (exam_id,))
                    for c in classifications:
                        execute(
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

                results["synced"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"{exam_id}: {str(e)}")

        return jsonify({"ok": True, **results})

    # ── Student overview ──────────────────────────────────────────────────────

    @app.route("/student")
    @auth_required
    def student_overview():
        from datetime import timedelta
        thirty_ago = (date.today() - timedelta(days=30)).isoformat()
        sessions_30d = (query_one(
            "SELECT COUNT(DISTINCT session_date) FROM sessions WHERE session_date >= ?", (thirty_ago,)
        ) or [0])[0]
        total_wrong = (query_one("SELECT COUNT(*) FROM wrong_answers") or [0])[0]
        redo_pending = (query_one(
            "SELECT COUNT(*) FROM wrong_answers WHERE on_tap_status='redo'"
        ) or [0])[0]
        total_q = (query_one("""
            SELECT COUNT(DISTINCT q.id) FROM questions q
            JOIN sessions s ON s.exam_id = q.exam_id
        """) or [0])[0]
        pass_rate = max(0.0, 1 - (total_wrong / total_q)) if total_q else 0.0
        stats = {
            "sessions_30d": sessions_30d,
            "total_wrong": total_wrong,
            "redo_pending": redo_pending,
            "pass_rate": pass_rate,
        }
        chapter_breakdown = query("""
            SELECT q.chuong,
                   COUNT(wa.id) as wrong,
                   COUNT(DISTINCT q.id) as total
            FROM questions q
            LEFT JOIN wrong_answers wa ON wa.phan = q.phan AND wa.stt = q.stt
              AND (wa.y = q.y OR (wa.y IS NULL AND q.y IS NULL))
            WHERE q.chuong IS NOT NULL
            GROUP BY q.chuong ORDER BY wrong DESC
        """)
        muc_do_breakdown = query("""
            SELECT q.muc_do,
                   COUNT(wa.id) as wrong,
                   COUNT(DISTINCT q.id) as total
            FROM questions q
            LEFT JOIN wrong_answers wa ON wa.phan = q.phan AND wa.stt = q.stt
              AND (wa.y = q.y OR (wa.y IS NULL AND q.y IS NULL))
            WHERE q.muc_do IS NOT NULL
            GROUP BY q.muc_do ORDER BY q.muc_do
        """)
        return render_template("student.html", stats=stats,
                               chapter_breakdown=chapter_breakdown,
                               muc_do_breakdown=muc_do_breakdown)

    # ── Analytics ────────────────────────────────────────────────────────────

    @app.route("/analytics")
    @auth_required
    def analytics():
        return render_template("analytics.html")

    # ── Study plans ───────────────────────────────────────────────────────────

    @app.route("/study-plans")
    @auth_required
    def study_plans_list():
        plans = query("SELECT * FROM study_plans ORDER BY created_at DESC")
        return render_template("study_plans.html", plans=plans)

    @app.route("/study-plans/<int:pid>")
    @auth_required
    def study_plan_detail(pid):
        plan = query_one("SELECT * FROM study_plans WHERE id=?", (pid,))
        if not plan:
            abort(404)
        return render_template("study_plan_detail.html", plan=plan)

    @app.route("/study-plans/generate-prompt", methods=["POST"])
    @auth_required
    def generate_plan_prompt():
        student_name = request.form.get("student_name", "Học sinh")
        exam_date = request.form.get("exam_date", "2026-06-26")
        plan_markdown = request.form.get("plan_markdown", "").strip()
        title = request.form.get("title", "").strip() or f"Kế hoạch {date.today().isoformat()}"
        action = request.form.get("action", "prompt")

        source_data = _build_plan_source_data(student_name, exam_date)

        if action == "save" and plan_markdown:
            execute(
                "INSERT INTO study_plans (title, source_json, plan_markdown) VALUES (?,?,?)",
                (title, json.dumps(source_data, ensure_ascii=False), plan_markdown)
            )
            return redirect(url_for("study_plans_list"))

        prompt_instructions = (ROOT / "prompts" / "study_plan.md").read_text(encoding="utf-8")
        prompt_text = (
            prompt_instructions
            + "\n\n## Student data\n\n"
            + "```json\n"
            + json.dumps(source_data, ensure_ascii=False, indent=2)
            + "\n```"
        )
        return render_template("plan_prompt.html", prompt_text=prompt_text)

    # ── Eval ──────────────────────────────────────────────────────────────────

    @app.route("/eval")
    @auth_required
    def eval_results():
        proposal_count = (query_one("SELECT COUNT(*) FROM guideline_proposals WHERE status='pending'") or [0])[0]
        batch_rows = query("SELECT * FROM eval_batches ORDER BY created_at DESC LIMIT 10")
        batches = []
        for b in batch_rows:
            metrics = json.loads(b["metrics_json"] or "{}")
            top_errors = json.loads(b["top_errors_json"] or "[]")
            metrics["top_errors"] = top_errors
            batches.append({"id": b["id"], "created_at": b["created_at"], "metrics": metrics})
        return render_template("eval.html", batches=batches, proposal_count=proposal_count)

    @app.route("/eval/proposals")
    @auth_required
    def eval_proposals():
        proposals = query("SELECT * FROM guideline_proposals ORDER BY created_at DESC")
        return render_template("proposals.html", proposals=proposals)

    @app.route("/eval/proposals/<int:pid>/resolve", methods=["POST"])
    @auth_required
    def proposal_resolve(pid):
        action = request.form.get("action", "reject")
        status = "accepted" if action == "accept" else "rejected"
        execute(
            "UPDATE guideline_proposals SET status=?, resolved_at=datetime('now') WHERE id=?",
            (status, pid)
        )
        return redirect(url_for("eval_proposals"))

    @app.route("/eval/import-proposals", methods=["POST"])
    @auth_required
    def import_proposals():
        imported = 0
        if PROPOSALS_DIR.exists():
            for f in sorted(PROPOSALS_DIR.glob("proposal_*.md")):
                text = f.read_text(encoding="utf-8")
                existing = query_one(
                    "SELECT id FROM guideline_proposals WHERE proposal_markdown=?", (text,)
                )
                if not existing:
                    execute(
                        "INSERT INTO guideline_proposals (proposal_markdown) VALUES (?)", (text,)
                    )
                    imported += 1
        from flask import flash
        flash(f"Imported {imported} proposal(s).", "success")
        return redirect(url_for("eval_proposals"))

    return app


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_session_yaml(sess):
    """Write/append session to sessions/<date>.yaml"""
    session_date = sess["session_date"]
    yaml_path = SESSIONS_DIR / f"{session_date}.yaml"
    SESSIONS_DIR.mkdir(exist_ok=True)

    import sqlite3 as _sqlite3
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    wrongs = db.execute(
        "SELECT phan, stt, y FROM wrong_answers WHERE session_id=? ORDER BY phan, stt, y",
        (sess["id"],)
    ).fetchall()
    db.close()

    wrong_list = []
    for w in wrongs:
        item = {"phan": w["phan"], "stt": w["stt"]}
        if w["y"]:
            item["y"] = w["y"]
        wrong_list.append(item)

    entry = {
        "date": session_date,
        "exam_id": sess["exam_id"],
        "wrong_questions": wrong_list,
    }

    existing = []
    if yaml_path.exists():
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing = data
            elif data:
                existing = [data]
        except Exception:
            pass

    existing = [e for e in existing if not (
        e.get("exam_id") == sess["exam_id"] and str(e.get("date")) == session_date
    )]
    existing.append(entry)
    yaml_path.write_text(yaml.dump(existing, allow_unicode=True, default_flow_style=False,
                                   sort_keys=False), encoding="utf-8")


def _build_plan_source_data(student_name: str, exam_date: str) -> dict:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    from datetime import timedelta
    thirty_ago = (date.today() - timedelta(days=30)).isoformat()
    sessions_30d = db.execute(
        "SELECT COUNT(DISTINCT session_date) FROM sessions WHERE session_date >= ?", (thirty_ago,)
    ).fetchone()[0]

    chapter_rows = db.execute("""
        SELECT q.chuong,
               COUNT(wa.id) as wrong_count,
               COUNT(DISTINCT q.id) as total
        FROM questions q
        LEFT JOIN wrong_answers wa ON wa.phan = q.phan AND wa.stt = q.stt
          AND (wa.y = q.y OR (wa.y IS NULL AND q.y IS NULL))
        WHERE q.chuong IS NOT NULL
        GROUP BY q.chuong
    """).fetchall()

    chapter_stats = {}
    for r in chapter_rows:
        total = r["total"] or 1
        wrong = r["wrong_count"] or 0
        pass_rate = round(1 - wrong / total, 2)
        chapter_stats[r["chuong"]] = {
            "wrong_count": wrong,
            "pass_rate": pass_rate,
        }

    muc_rows = db.execute("""
        SELECT q.muc_do,
               COUNT(wa.id) as wrong,
               COUNT(DISTINCT q.id) as total
        FROM questions q
        LEFT JOIN wrong_answers wa ON wa.phan = q.phan AND wa.stt = q.stt
          AND (wa.y = q.y OR (wa.y IS NULL AND q.y IS NULL))
        WHERE q.muc_do IS NOT NULL
        GROUP BY q.muc_do
    """).fetchall()
    muc_do_breakdown = {
        r["muc_do"]: round(1 - (r["wrong"] or 0) / (r["total"] or 1), 2)
        for r in muc_rows
    }

    redo_rows = db.execute("""
        SELECT wa.phan, wa.stt, wa.y, s.exam_id, q.chuong, q.muc_do,
               COUNT(wa2.id) as wrong_count
        FROM wrong_answers wa
        JOIN sessions s ON s.id = wa.session_id
        LEFT JOIN questions q ON q.exam_id = s.exam_id AND q.phan = wa.phan
          AND q.stt = wa.stt AND (q.y = wa.y OR (q.y IS NULL AND wa.y IS NULL))
        LEFT JOIN wrong_answers wa2 ON wa2.phan = wa.phan AND wa2.stt = wa.stt
          AND (wa2.y = wa.y OR (wa2.y IS NULL AND wa.y IS NULL))
        WHERE wa.on_tap_status = 'redo'
        GROUP BY wa.phan, wa.stt, wa.y
        ORDER BY wrong_count DESC LIMIT 10
    """).fetchall()

    persistent_redo = []
    for r in redo_rows:
        item = {
            "exam_id": r["exam_id"],
            "phan": r["phan"],
            "stt": r["stt"],
            "chuong": r["chuong"],
            "muc_do": r["muc_do"],
            "wrong_count": r["wrong_count"],
        }
        if r["y"]:
            item["y"] = r["y"]
        persistent_redo.append(item)

    db.close()

    sorted_ch = sorted(chapter_stats.items(), key=lambda x: x[1]["pass_rate"])
    weakest = [c for c, _ in sorted_ch[:3]]
    strongest = [c for c, _ in sorted_ch[-3:]]

    return {
        "student_name": student_name,
        "exam_date": exam_date,
        "generated_at": datetime.now().isoformat(),
        "sessions_last_30_days": sessions_30d,
        "chapter_stats": chapter_stats,
        "persistent_redo": persistent_redo,
        "muc_do_breakdown": muc_do_breakdown,
        "weakest_chapters": weakest,
        "strongest_chapters": strongest,
    }


if __name__ == "__main__":
    app = create_app()
    app.run(host=HOST, port=PORT, debug=(HOST == "127.0.0.1"))
