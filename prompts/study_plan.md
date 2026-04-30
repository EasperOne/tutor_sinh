# Study Plan Generation Instructions

You are generating a personalized study plan for a Vietnamese biology student preparing for THPTQG 2026.

## Input

You will receive a JSON file exported from the tutor-sinh app. Its structure:

```json
{
  "student_name": "...",
  "exam_date": "2026-06-26",
  "generated_at": "...",
  "sessions_last_30_days": 5,
  "chapter_stats": {
    "DT_BD": {"wrong_count": 8, "pass_rate": 0.3, "avg_muc_do": "VD"},
    "QL_DT": {"wrong_count": 5, "pass_rate": 0.4, "avg_muc_do": "H"},
    "ST_MT": {"wrong_count": 3, "pass_rate": 0.6, "avg_muc_do": "B"}
  },
  "persistent_redo": [
    {"exam_id": "de_001", "phan": "P2", "stt": 2, "y": "c",
     "chuong": "QL_DT", "muc_do": "VD", "wrong_count": 4}
  ],
  "muc_do_breakdown": {"B": 0.82, "H": 0.61, "VD": 0.28},
  "weakest_chapters": ["DT_BD", "QL_DT", "DT_HP"],
  "strongest_chapters": ["DT_PT", "DT_TB", "CH_TV"]
}
```

## Chapter codes reference

DT_PT  Di truyền cấp phân tử (Lớp 10)
DT_TB  Di truyền cấp tế bào (Lớp 10)
CH_TV  Chuyển hoá vật chất và năng lượng ở thực vật (Lớp 11)
CH_DV  Chuyển hoá vật chất và năng lượng ở động vật (Lớp 11)
DT_BD  Di truyền và biến dị cấp phân tử và cấp tế bào (Lớp 12+10)
QL_DT  Quy luật di truyền (Lớp 12)
DT_QT  Di truyền quần thể (Lớp 12)
DT_HP  Di truyền học người và liệu pháp gene (Lớp 12)
UD_DT  Ứng dụng di truyền học (Lớp 12)
TH     Tiến hoá (Lớp 12)
ST_MT  Sinh thái học và môi trường (Lớp 12)

## Output format

Write the study plan in Vietnamese. Use this exact structure:

```markdown
# KẾ HOẠCH ÔN TẬP — [Student Name]
**Ngày thi:** [exam_date] | **Tạo ngày:** [today]

---

## 📊 Tổng quan hiện tại
[2–3 câu nhận xét thẳng thắn về tình trạng hiện tại: điểm mạnh, điểm yếu chính, xu hướng]

---

## 🎯 Ưu tiên ôn tập

| Chương | Số lần sai | Tỷ lệ qua | Ưu tiên | Số buổi đề xuất |
|--------|-----------|-----------|---------|-----------------|
| [highest priority first] | ... | ... | 🔴 Cao / 🟡 Trung / 🟢 Thấp | N buổi |

---

## 📅 Lịch học [N] tuần (tính từ hôm nay đến [2 weeks before exam])

### Tuần 1: [date range]
| Ngày | Nội dung | Mục tiêu | Ghi chú |
|------|----------|----------|---------|
| Thứ 2 | [chapter] — [specific topic] | [measurable goal] | |
...

### Tuần 2: [date range]
[similar]

[continue for all weeks]

---

## ⚠️ Câu hỏi cần redo ngay

[List each persistent_redo item:]
- **[phan]·[stt][y]** ([exam_id]) — [chuong] — [muc_do] — Sai [wrong_count] lần
  → [specific advice for this question type]

---

## 💡 Chiến thuật theo mức độ

**Biết (B) — Tỷ lệ đúng: [B%]%**
[concrete advice — if B% > 80: "nền tảng tốt, duy trì"; if lower: specific recall strategies]

**Hiểu (H) — Tỷ lệ đúng: [H%]%**
[concrete advice for comprehension questions in the weak chapters]

**Vận dụng (VD) — Tỷ lệ đúng: [VD%]%**
[concrete calculation/application strategies for the specific weak chapters]

---

## ✅ Mục tiêu tuần này
- [ ] Hoàn thành [N] bài tập [specific chapter]
- [ ] Ôn lại [specific topic] từ đề [exam_id]
- [ ] Đạt tỷ lệ đúng > [target]% ở [weakest chapter]
```

## Rules

- Keep advice specific and actionable — reference actual chapters and question types from the data
- Do NOT give generic biology study advice
- The 4-week schedule should respect the exam_date (stop 1 week before exam for review)
- If exam_date is < 4 weeks away, compress the schedule
- Flag if sessions_last_30_days < 3 (low practice frequency — address this first)
