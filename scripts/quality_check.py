"""
Heuristic quality scoring for de.md markdown files. Returns 0.0–1.0.
"""
from __future__ import annotations
from pathlib import Path
import re

_VIET_CHARS = set("àáảãạăắặẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđÀÁẢÃẠĂẮẶẲẴẶÂẤẦẨẪẬÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴĐ")

_Q_PATTERN = re.compile(r'Câu\s+\d+', re.IGNORECASE)
_SECT_PATTERN = re.compile(r'(Ph[àa]n|PHẦN)\s+(I{1,3}|IV)', re.IGNORECASE)
_OPT_PATTERN = re.compile(r'\b[ABCD]\s*[\.\)]\s+\S')


def check_markdown(text: str) -> dict:
    issues: list[str] = []
    details: dict = {}
    score = 0.0

    # 1. Vietnamese character density (0–0.25)
    if len(text) > 0:
        viet_count = sum(1 for c in text if c in _VIET_CHARS)
        viet_ratio = viet_count / len(text)
        details["viet_ratio"] = round(viet_ratio, 3)
        viet_score = min(viet_ratio / 0.05, 1.0) * 0.25
        score += viet_score
        if viet_ratio < 0.02:
            issues.append("Very low Vietnamese character ratio — possible OCR failure or wrong language")
    else:
        issues.append("Empty file")
        return {"score": 0.0, "issues": issues, "details": details}

    # 2. Question structure (0–0.30)
    q_matches = _Q_PATTERN.findall(text)
    q_count = len(q_matches)
    details["question_count"] = q_count
    q_score = min(q_count / 40, 1.0) * 0.30
    score += q_score
    if q_count < 20:
        issues.append(f"Only {q_count} 'Câu N' patterns found (expected ~40)")
    elif q_count > 60:
        issues.append(f"Suspicious: {q_count} 'Câu N' patterns (may be duplicate content)")

    # 3. Section detection (0–0.20)
    sections_found = len(set(_SECT_PATTERN.findall(text)))
    details["sections_found"] = sections_found
    sect_score = min(sections_found / 3, 1.0) * 0.20
    score += sect_score
    if sections_found < 2:
        issues.append("Could not detect Phần I/II/III section headers")

    # 4. Answer option presence (0–0.15)
    opt_count = len(_OPT_PATTERN.findall(text))
    details["option_count"] = opt_count
    opt_score = min(opt_count / 72, 1.0) * 0.15
    score += opt_score
    if opt_count < 30:
        issues.append(f"Only {opt_count} A/B/C/D options found (expected ~72 for P1)")

    # 5. Not garbage (0–0.10)
    garbage = False
    if len(text) < 2000:
        issues.append(f"File too short ({len(text)} chars) — likely incomplete conversion")
        garbage = True
    # Check repetition: any 15-char window repeating > 5 times
    if not garbage:
        for i in range(0, min(len(text) - 15, 500), 20):
            fragment = text[i:i+15].strip()
            if len(fragment) >= 10 and text.count(fragment) > 6:
                issues.append(f"Suspicious repetition detected — possible OCR loop artifact")
                garbage = True
                break
    if not garbage:
        score += 0.10

    details["length"] = len(text)
    return {
        "score": round(min(score, 1.0), 3),
        "issues": issues,
        "details": details,
    }


def check_file(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"score": 0.0, "issues": ["File not found"], "details": {}}
    except Exception as e:
        return {"score": 0.0, "issues": [f"Read error: {e}"], "details": {}}
    return check_markdown(text)


if __name__ == "__main__":
    import sys
    from rich.console import Console
    console = Console()
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not path:
        console.print("[red]Usage: python quality_check.py <de.md path>[/red]")
        sys.exit(1)
    result = check_file(path)
    console.print(f"[bold]Score:[/bold] {result['score']:.3f}")
    for issue in result["issues"]:
        console.print(f"  [yellow]⚠ {issue}[/yellow]")
    console.print(f"[dim]{result['details']}[/dim]")
