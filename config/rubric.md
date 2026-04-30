# CLASSIFICATION RUBRIC — SINH HỌC 2025

## CHAPTER CODES (chuong)
DT_PT  Di truyền cấp phân tử                             Lớp 10
DT_TB  Di truyền cấp tế bào                              Lớp 10
CH_TV  Chuyển hoá vật chất và năng lượng ở thực vật      Lớp 11
CH_DV  Chuyển hoá vật chất và năng lượng ở động vật      Lớp 11
DT_BD  Di truyền và biến dị cấp phân tử và cấp tế bào   Lớp 12+10
QL_DT  Quy luật di truyền                                 Lớp 12
DT_QT  Di truyền quần thể                                 Lớp 12
DT_HP  Di truyền học người và liệu pháp gene             Lớp 12
UD_DT  Ứng dụng di truyền học                            Lớp 12
TH     Tiến hoá                                           Lớp 12
ST_MT  Sinh thái học và môi trường                        Lớp 12

## DIFFICULTY LEVELS (muc_do)
B   Biết     — recall, recognize, name. No reasoning required.
H   Hiểu     — explain, compare, interpret. Requires understanding mechanism.
VD  Vận dụng — calculate, analyze novel situation, apply to new context.

## SECTION TYPES (phan)
P1  Multiple-choice (4 options A/B/C/D)  — 18 questions
P2  True/False (4 sub-items a/b/c/d per question) — 4 questions × 4 items = 16 items
P3  Short answer (numeric result)  — 6 questions

## CLASSIFICATION RULES
- Assign exactly ONE chapter code per question/item
- If a question spans multiple chapters, assign the DOMINANT chapter
- For P2: classify EACH sub-item (a/b/c/d) independently — they may have different muc_do
- For P3: most are VD or H, rarely B
- Boundary H vs VD for Di truyen chapters: if student must calculate a ratio or probability → VD; if student must identify/explain a mechanism → H

## EXTENDED TAGS

skill
- Lowercase snake_case label for the concrete biology skill.
- Must be more specific than chuong.
- Examples: nhan_doi_adn, phien_ma_dich_ma, dot_bien_gen, dot_bien_nst, giam_phan, nguyen_phan, lai_mot_cap_tinh_trang, lai_hai_cap_tinh_trang, hoan_vi_gen, pha_he, xac_suat_di_truyen, di_truyen_quan_the_hardy_weinberg, luoi_thuc_an, chu_trinh_sinh_dia_hoa.
- Use unknown only when no stable label fits.

competency
- recall: identify, name, recognize, remember.
- understand: explain mechanism, compare concepts, infer simple relationship.
- interpret: read graph, table, diagram, pedigree, food web, or result.
- apply: apply concept to new biological situation without substantial calculation.
- calculate: compute ratios, probabilities, map distance, Hardy-Weinberg values, or numeric answers.
- experiment: reason about controls, variables, design, predictions, or conclusions.

calculation_load
- none: no numeric reasoning.
- light: one short computation or obvious ratio.
- medium: multi-step calculation, probability, cross, table counting, or formula use.
- heavy: unusually long math, many cases, old-style genetic probability, or calculation burden above BoGD 2025 style.

bo_gd_fit
- high: consistent with BoGD 2025 style and reasoning burden.
- medium: acceptable practice question but somewhat more calculation-heavy, unusual, or source-specific.
- low: clearly harder, old-style math-heavy, olympiad-like, overly long, ambiguous, or not representative of BoGD-style evaluation.

confidence
- 0.90-1.00: clear label.
- 0.70-0.89: mostly clear.
- 0.50-0.69: plausible but uncertain.
- <0.50: needs human review.

## OUTPUT FORMAT
Return ONLY a JSON object. No prose, no markdown fences.
