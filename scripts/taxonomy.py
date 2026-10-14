"""시나리오 분류 체계: pattern 10종, 기존 category -> pattern 대응, 문항 가중치, 적용 가능 표, 스타일 태그.

이 파일의 표는 배분(build_allocation.py)과 시드 등록(build_seed_registry.py)이 함께 쓴다.
값은 2026-10-11 설계 초안이며, 사람이 확정하기 전까지는 제안값이다.
"""

# ---------------------------------------------------------------- pattern 10종 (추가 지시 배분표 순서)
# draft = 지시서 초안 비율, proposed = 기존 분포·plan 하한을 반영한 조정안 (reports/stage0_design.md 2장)
PATTERNS = {
    "P01_normal":      {"name": "정상 단일턴 (표현 다양화)",   "draft": 0.30, "proposed": 0.28},
    "P02_range_unit":  {"name": "범위·근사·단위·혼합",          "draft": 0.16, "proposed": 0.16},
    "P03_partial":     {"name": "부분 응답·필드 누락",          "draft": 0.10, "proposed": 0.10},
    "P04_reask_fill":  {"name": "재질문 → 보완",                "draft": 0.10, "proposed": 0.08},
    "P05_correction":  {"name": "정정",                         "draft": 0.10, "proposed": 0.09},
    "P06_conflict":    {"name": "충돌",                         "draft": 0.07, "proposed": 0.08},
    "P07_prior_ref":   {"name": "이전 정보 참조",               "draft": 0.05, "proposed": 0.04},
    "P08_unk_refuse":  {"name": "모름·거절·보류",               "draft": 0.06, "proposed": 0.08},
    "P09_oos":         {"name": "OOS",                          "draft": 0.03, "proposed": 0.04},
    "P10_boundary":    {"name": "경계값·범위 초과",             "draft": 0.03, "proposed": 0.05},
    # 2026-10-13 보충(T1): 정규화기 사유 코드·정리 규칙 사례. 10,000 배분표 밖에서 NORM_CASE_QUOTA로 따로 채운다.
    "P11_norm_case":   {"name": "정규화기 규칙·사유 코드 사례",  "draft": 0.0,  "proposed": 0.0},
}

# 다중 턴 pattern: 학습 대상 턴(target_turn) 1개만 샘플로 쓰고 앞 턴은 previous_state로만 넣는다.
MULTI_TURN = {"P04_reask_fill", "P05_correction", "P06_conflict", "P07_prior_ref"}

# pattern별 target_turn에서 예상되는 transition_plan 비율 (plan 균형 추정용 가정값).
# 실제 plan은 생성 후 정규화기 실행 결과로만 정한다. 이 표는 배분 단계의 예측일 뿐이다.
PLAN_MIX = {
    "P01_normal":     {"NEXT": 1.0},
    "P02_range_unit": {"NEXT": 0.7, "ASK_CLARIFICATION": 0.3},
    "P03_partial":    {"ASK_MISSING": 1.0},
    "P04_reask_fill": {"NEXT": 1.0},   # 현재 샘플러의 보완 답은 모두 NEXT (S1 실측)
    "P05_correction": {"ACK_CORRECTION": 1.0},
    "P06_conflict":   {"ASK_CONFLICT": 1.0},
    "P07_prior_ref":  {"NEXT": 1.0},
    "P08_unk_refuse": {"ASK_OR_HOLD": 0.5, "HOLD_OR_SKIP": 0.5},
    "P09_oos":        {"REDIRECT": 1.0},
    "P10_boundary":   {"ASK_CLARIFICATION": 0.7, "NEXT": 0.3},
    "P11_norm_case":  {"NEXT": 0.5, "ASK_MISSING": 0.15, "ASK_CLARIFICATION": 0.15, "ASK_CONFLICT": 0.1, "REDIRECT": 0.1},
}

# P11 칸별 목표(통과 수, 문항 x 정규화기 plan). 하위 유형은 sampler.NORM_CASE_ITEMS. 한 칸에 하위 유형이 여럿이면 고르게 뽑힌다.
# 합계 589. 보충 단계(T1)와 최종 빌드(build_final --upto T1)가 함께 쓴다.
NORM_CASE_QUOTA = {
    ("Q7_1", "ASK_CLARIFICATION"): 25, ("Q7_1", "NEXT"): 25, ("Q7_1", "ASK_MISSING"): 25,
    ("Q7_2", "ASK_CLARIFICATION"): 20, ("Q7_2", "NEXT"): 40, ("Q7_2", "ASK_MISSING"): 20, ("Q7_2", "ASK_CONFLICT"): 40,
    ("Q7", "ASK_MISSING"): 20, ("Q7", "NEXT"): 30, ("Q7", "ASK_CONFLICT"): 30,
    ("Q8_1", "ASK_MISSING"): 12, ("Q8_1", "NEXT"): 30, ("Q9_1", "ASK_MISSING"): 12, ("Q9_1", "NEXT"): 15,
    ("Q10", "ASK_MISSING"): 12,
    ("Q4_1", "ASK_CLARIFICATION"): 15, ("Q4_1", "NEXT"): 12, ("Q5_1", "ASK_CLARIFICATION"): 12, ("Q5_1", "NEXT"): 10,
    ("Q3", "ASK_CLARIFICATION"): 20, ("Q4", "NEXT"): 36, ("Q5", "NEXT"): 30,
    **{(f"Q1.D{n:02d}", "NEXT"): (12 if n in (3, 4, 5) else 4) for n in range(1, 12)},
    **{(f"Q2.D{n:02d}", "REDIRECT"): 6 for n in range(1, 6)},
}
PLANS = ["NEXT", "ASK_MISSING", "ASK_CLARIFICATION", "ASK_CONFLICT", "ACK_CORRECTION",
         "ASK_OR_HOLD", "HOLD_OR_SKIP", "REDIRECT", "COMPLETE"]

# ---------------------------------------------------------------- 기존 category -> pattern
# 기존 219건·Qwen 437건의 category 이름을 10종 pattern에 대응시킨다. 시드 분포 집계용.
# ambiguous_or_uncertain처럼 결과에 따라 갈리는 category는 v1.0 plan으로 다시 나눈다(PLAN_OVERRIDE).
CATEGORY_TO_PATTERN = {
    # 정상 단일턴
    "diagnosis_medication": "P01_normal", "diagnosis_medication_matrix": "P01_normal",
    "family_history": "P01_normal", "family_scope_matrix": "P01_normal",
    "activity_days": "P01_normal", "strength_days": "P01_normal",
    "alcohol_frequency": "P01_normal", "alcohol_amount": "P01_normal",
    "smoking_experience": "P01_normal", "current_smoker_detail": "P01_normal",
    "smoking_details": "P01_normal", "official_option": "P01_normal",
    "non_drinking": "P01_normal", "activity_duration": "P01_normal",
    "former_fractional_quit": "P01_normal", "authored_dialect": "P01_normal",
    "stt_ambiguous": "P01_normal",
    # 범위·근사·단위·혼합
    "hours_only": "P02_range_unit", "hours_minutes": "P02_range_unit",
    "duration_total_minutes": "P02_range_unit", "beverage_unit_matrix": "P02_range_unit",
    "multiple_beverages": "P02_range_unit", "range_same_bin": "P02_range_unit",
    "range_cross_bin": "P02_range_unit", "approximate_frequency": "P02_range_unit",
    # 부분 응답
    "partial_answer": "P03_partial", "missing_unit": "P03_partial",
    # 재질문 -> 보완
    "resolve_conflict": "P04_reask_fill",
    # 정정 / 충돌
    "correction": "P05_correction", "explicit_conflict": "P06_conflict",
    # 모름·거절·보류
    "intent": "P08_unk_refuse", "refusal": "P08_unk_refuse", "skip": "P08_unk_refuse",
    "formal_unknown": "P08_unk_refuse", "ambiguous_or_uncertain": "P08_unk_refuse",
    # OOS
    "ask_purpose": "P09_oos", "off_topic": "P09_oos", "out_of_schema": "P09_oos",
    # 경계값
    "usage_boundary": "P10_boundary", "activity_day_boundary": "P10_boundary",
    "thirty_days_not_daily": "P10_boundary", "openit_policy_boundary": "P10_boundary",
}
# category만으로 정하기 어려운 경우 v1.0 plan을 보고 pattern을 바꾼다.
PLAN_OVERRIDE = {
    ("ambiguous_or_uncertain", "ASK_CLARIFICATION"): "P02_range_unit",
    ("ambiguous_or_uncertain", "ASK_MISSING"): "P03_partial",
    ("intent", "REDIRECT"): "P09_oos",
}

# ---------------------------------------------------------------- 문항 31개 가중치
# 10,000 기준 문항당 최소 150 시나리오를 먼저 주고, 나머지를 가중치 비율로 나눈다.
# 음주(Q7 계열)·흡연(Q4·Q5 계열)은 필드·분기가 많아 높게 둔다. Q1 질환 11개는 예/아니요 2칸이라
# 1.0으로 두면 Q1만 전체의 31%가 되어 0.5로 낮췄다(Q1 23% / Q7 22% / Q4·Q5 19%).
ITEM_MIN_10000 = 150
ITEM_WEIGHTS = {
    **{f"Q1.D{i:02d}": 0.5 for i in range(1, 12)},     # 진단·복약 2칸, 단순 예/아니요
    **{f"Q2.D{i:02d}": 0.5 for i in range(1, 6)},      # 가족력 1칸
    "Q3": 1.0, "Q6": 1.0, "Q6_1": 2.0,                 # Q6_1은 사용 일수 구간 경계가 많음
    "Q4": 1.5, "Q4_1": 4.0, "Q5": 1.5, "Q5_1": 4.0,    # 흡연: 현재/과거, 연수·개비·금연기간
    "Q7": 4.0, "Q7_1": 6.0, "Q7_2": 5.0,               # 음주: 빈도, 5주종 x 양·단위, 최대량
    "Q8_1": 1.5, "Q9_1": 1.5, "Q10": 3.0,              # 활동 일수 (Q10은 END 학습량 때문에 3.0, 2026-10-13)
    "Q8_2": 2.0, "Q9_2": 2.0,                          # 활동 시간 (시간/분 환산)
}
NUMERIC_ITEMS = {"Q4_1", "Q5_1", "Q6_1", "Q7", "Q7_1", "Q7_2", "Q8_1", "Q8_2", "Q9_1", "Q9_2", "Q10"}
MULTI_FIELD_ITEMS = {f"Q1.D{i:02d}" for i in range(1, 12)} | {"Q4_1", "Q5_1", "Q7", "Q7_1", "Q7_2"}


# 이전 정보 참조(P07): 문진표에서 먼저 묻는 문항 중 칸 구조가 같은 문항만 참조 원천으로 둔다(2026-10-11 확정).
# 예: Q9_2 "고강도 할 때랑 똑같이 해요" -> Q8_2 저장 값, Q7_2 "평소랑 같아요" -> Q7_1 저장 값.
# 참조한 값은 LoRA-A 입력의 relevant_state에만 넣는다. 원천이 없는 문항(Q1.D01, Q3 등)에는 P07을 배정하지 않는다.
REF_SOURCE = {
    **{f"Q1.D{i:02d}": f"Q1.D{i - 1:02d}" for i in range(2, 12)},
    **{f"Q2.D{i:02d}": f"Q2.D{i - 1:02d}" for i in range(2, 6)},
    "Q5": "Q4", "Q6": "Q5", "Q5_1": "Q4_1", "Q7_2": "Q7_1",
    "Q9_1": "Q8_1", "Q10": "Q9_1", "Q9_2": "Q8_2",
}


def applicable(pattern, item):
    """pattern x 문항 조합이 현재 스키마·정규화기로 만들 수 있는지(설계 가정).

    - 범위·근사·단위, 경계값: 숫자·구간 칸이 있는 문항만
    - 부분 응답: 칸이 2개 이상인 문항만 (한 칸 문항은 '빠진 칸'이 없음)
    - 이전 정보 참조: REF_SOURCE에 참조 원천이 있는 문항만
    - 나머지: 31개 문항 전부
    """
    if pattern in ("P02_range_unit", "P10_boundary"):
        return item in NUMERIC_ITEMS
    if pattern == "P03_partial":
        return item in MULTI_FIELD_ITEMS
    if pattern == "P07_prior_ref":
        return item in REF_SOURCE
    if pattern == "P11_norm_case":
        return any(i == item for i, _ in NORM_CASE_QUOTA)
    return True


# ---------------------------------------------------------------- 표현 축 (expression_variant 스타일 태그)
# 각 태그 최소 5%, STT 오류형은 10~15% 이하로 제한 (추가 지시).
STYLE_TAGS = {
    "formal_full":     {"name": "존댓말 완결문",                  "share": 0.18},
    "casual_short":    {"name": "짧은 구어 (단답·생략)",           "share": 0.16},
    "banmal":          {"name": "반말",                            "share": 0.08},
    "elderly_verbose": {"name": "장황·부연 (사연·배경 섞임)",      "share": 0.12},
    "hesitant_filler": {"name": "머뭇거림·필러 (음, 그러니까)",    "share": 0.12},
    "hangul_numbers":  {"name": "숫자 한글 표기 (두세 병, 한 갑 반)", "share": 0.14},
    "dialect":         {"name": "사투리",                          "share": 0.08},
    "stt_noise":       {"name": "STT 오류형 (띄어쓰기·동음 오인식)", "share": 0.12},
}
STYLE_MIN_SHARE = 0.05
STT_MAX_SHARE = 0.15
MAX_VARIANTS_PER_CANONICAL = 4      # 지시서 4~5개 중 보수적으로 4. 10,000 / 4 = 최소 2,500 canonical

# START(문진 시작: 인사 + Q1.D01 질문) LoRA-B 전용 레코드 수. 단계 누적 목표 (2026-10-13 사용자 확정: 150~200건)
START_TARGET = {"pilot": 30, "S1": 50, "S2": 100, "S3": 150, "T1": 150, "S4": 200}
