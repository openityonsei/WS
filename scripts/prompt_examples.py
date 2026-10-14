"""프롬프트 예시 모음 v2 (2026-10-13). 사람이 읽는 원문은 docs/EXAMPLES.md (scripts/export_docs.py가 이 파일에서 만든다).

역할: 생성 프롬프트에 넣는 좋은 예·나쁜 예 데이터와, 그것을 프롬프트 문자열로 만드는 함수.
- U: 환자 발화 예시. (pattern, subtype, 문항, 말투, 상담원 말, 환자 발화, 앞 대화). 발화 생성 프롬프트에 같은 pattern 예시를 모두 넣는다.
- B: LoRA-B 응답 예시. v2 B 입력(action·reason·known·ask·previous·current·hold·next)과 응답. 응답 생성 프롬프트에 같은 action 예시를 모두 넣는다.
- 예시 값은 학습 정답이 아니다. 정답은 sampler와 정규화기가 정한다. 예시는 말투·구성 참고용이다.
- copied_example 가드(checks.py)가 이 문장들과 거의 같은 생성 결과를 걸러 낸다(all_example_texts).
v1.17(2026-10-12 사용자 승인 예시)을 바탕으로, v2 형식(시작·종료·재질문 대상·이전 값)에 맞게 B 예시를 새로 썼다.
부작용 없음(순수 데이터).
"""
from collections import namedtuple

U = namedtuple("U", "pattern subtype item style q utt ctx", defaults=(None,))
B = namedtuple("B", "action item utt resp next_type next_text reason known ask previous current hold",
               defaults=("NEXT", None, None, "", None, None, None, None))

# 자주 쓰는 질문 문장
_N_DIAB = "당뇨병은 진단받으신 적 있으세요? 약도 드세요?"
_N_HARD = "숨이 많이 찰 정도로 힘든 운동은 일주일에 며칠 하세요?"
_N_HARD_T = "그렇게 운동하시는 날은 하루에 얼마 동안 하세요?"
_N_MOD = "숨이 약간 찰 정도의 운동은 일주일에 며칠 하세요?"
_N_MOD_T = "숨이 약간 찰 정도의 운동을 하시는 날은 하루에 얼마나 하세요?"
_N_STR = "지난 일주일 동안 팔굽혀펴기나 아령 같은 근력 운동은 며칠 하셨어요?"
_N_HEAT = "아이코스나 글로 같은 가열담배는 써 보신 적 있으세요?"
_N_HEAT_1 = "가열담배는 지금도 쓰세요? 몇 년 쓰셨고 하루에 몇 개비 쓰시는지도 알려 주세요."
_N_LIQ = "액상형 전자담배는 써 보신 적 있으세요?"
_N_LIQ_1 = "최근 한 달 동안 액상형 전자담배를 며칠 쓰셨어요?"
_N_HEPB = "B형간염 바이러스 보유자라는 말을 들으신 적 있으세요?"
_N_Q4 = "지금까지 일반담배를 다 합쳐서 다섯 갑(100개비) 넘게 피워 보신 적 있으세요?"
_Q_Q4_1 = "지금도 담배 피우세요? 몇 년 피우셨고 하루에 몇 개비 피우시는지도 알려 주세요."
_Q_Q7 = "술은 평소 얼마나 자주 드세요? 일주일이나 한 달에 몇 번인지로 말씀해 주세요."
_Q_Q7_1 = "술 드시는 날에는 보통 얼마나 드세요?"
_Q_Q7_2 = "지난 1년 동안 가장 많이 드신 날은 얼마나 드셨어요?"
_Q_D01 = "뇌졸중(중풍) 진단을 받으신 적이 있거나 지금 약을 드시고 계세요?"
_Q_D02 = "심근경색이나 협심증은 진단받으신 적 있으세요? 약도 드세요?"
_Q_D03 = "고혈압은 진단받으신 적 있으세요? 지금 약도 드세요?"
_F = "부모님이나 형제자매 중에 {d}을 앓으셨거나 그 병으로 돌아가신 분 계세요?"

# ================================================================ 1. 환자 발화 예시 (pattern별)
UTT_EXAMPLES = [
    # ---------------- P01 정상
    U("P01_normal", "normal", "Q1.D03", "formal_full", _Q_D03, "네, 고혈압 진단은 받았습니다. 약은 매일 아침에 먹고 있어요."),
    U("P01_normal", "normal", "Q1.D03", "casual_short", _Q_D03, "진단받았어요. 약도 먹어요."),
    U("P01_normal", "normal", "Q1.D03", "dialect", _Q_D03, "고혈압 있다 캐서 약 묵고 있어예."),
    U("P01_normal", "normal", "Q1.D07", "hesitant_filler", "우울증은 진단받으신 적 있으세요? 지금 약도 드세요?", "음... 아니요, 그런 진단은 받은 적 없어요. 약도 안 먹고요."),
    U("P01_normal", "normal", "Q1.D07", "banmal", "우울증은 진단받으신 적 있으세요? 지금 약도 드세요?", "없어. 약도 안 먹어."),
    U("P01_normal", "normal", "Q1.D01", "elderly_verbose", _Q_D01, "몇 년 전에 중풍으로 쓰러져서 진단받았어요. 그 뒤로는 약을 안 먹고 지내요."),
    U("P01_normal", "normal", "Q1.D01", "formal_full",
      "안녕하세요. 지금부터 건강검진 문진표를 같이 작성해 볼게요. 먼저, 뇌졸중(중풍) 진단을 받으신 적이 있거나 지금 약을 드시고 계세요?",
      "아니요, 그런 진단은 받은 적 없고 약도 안 먹습니다."),
    U("P01_normal", "normal", "Q1.D09", "stt_noise", "C형간염은 진단받으신 적 있으세요? 약도 드세요?", "C형간염은없어요 약도안먹어요"),
    U("P01_normal", "normal", "Q2.D03", "elderly_verbose", _F.format(d="고혈압"), "우리 어머니가 고혈압으로 오래 고생하셨어요. 약을 평생 드셨지요."),
    U("P01_normal", "normal", "Q2.D03", "casual_short", _F.format(d="고혈압"), "아버지가 고혈압 있으세요."),
    U("P01_normal", "normal", "Q2.D05", "formal_full", "부모님이나 형제자매 중에 암 같은 다른 병을 앓으셨거나 그 병으로 돌아가신 분 계세요?",
      "부모님이나 형제 중에 암 같은 큰 병 앓은 사람은 없습니다."),
    U("P01_normal", "normal", "Q2.D05", "stt_noise", "부모님이나 형제자매 중에 암 같은 다른 병을 앓으셨거나 그 병으로 돌아가신 분 계세요?", "부모님형제중에 암걸린사람 없어요"),
    U("P01_normal", "normal", "Q3", "casual_short", "B형간염 바이러스 보유자이신가요?", "아니요, 보유자 아니에요."),
    U("P01_normal", "normal", "Q3", "hesitant_filler", "B형간염 바이러스 보유자이신가요?", "음, 검사를 안 해 봐서 그건 모르겠어요."),
    U("P01_normal", "normal", "Q4", "banmal", _N_Q4, "응, 그 이상 피웠지."),
    U("P01_normal", "normal", "Q4", "formal_full", _N_Q4, "아니요, 담배는 평생 피운 적이 없습니다."),
    U("P01_normal", "normal", "Q4_1", "hangul_numbers", _Q_Q4_1, "네, 지금도 피워요. 이십 년 됐고 하루에 열 개비 피워요."),
    U("P01_normal", "normal", "Q4_1", "formal_full", _Q_Q4_1, "지금은 끊었습니다. 십 년 피웠고 하루에 스무 개비씩 피웠어요. 끊은 지는 오 년 됐습니다."),
    U("P01_normal", "normal", "Q5", "dialect", _N_HEAT, "그런 거는 써 본 적 없어예."),
    U("P01_normal", "normal", "Q6_1", "casual_short", _N_LIQ_1, "열흘요."),
    U("P01_normal", "normal", "Q7", "casual_short", _Q_Q7, "일주일에 두 번 마셔요."),
    U("P01_normal", "normal", "Q7", "banmal", _Q_Q7, "술 안 마셔. 아예 안 먹어."),
    U("P01_normal", "normal", "Q7", "elderly_verbose", _Q_Q7, "모임이 있을 때나 마시니까, 한 달에 두 번 정도 마시지요."),
    U("P01_normal", "normal", "Q7_1", "casual_short", _Q_Q7_1, "소주 한 병요."),
    U("P01_normal", "normal", "Q7_1", "hesitant_filler", _Q_Q7_1, "음, 맥주로 세 캔? 네, 세 캔 마셔요."),
    U("P01_normal", "normal", "Q7_2", "formal_full", _Q_Q7_2, "가장 많이 마신 날은 소주 세 병이었습니다."),
    U("P01_normal", "normal", "Q8_1", "hangul_numbers", _N_HARD, "사흘 해요."),
    U("P01_normal", "normal", "Q8_2", "elderly_verbose", "그런 운동 하시는 날은 하루에 얼마 동안 하세요?", "등산을 가면 한 번에 두 시간은 걸어요."),
    U("P01_normal", "normal", "Q9_2", "stt_noise", _N_MOD_T, "하루에사십분해요"),
    U("P01_normal", "normal", "Q10", "dialect", _N_STR, "아령은 이틀 했심더."),

    # ---------------- P02 범위·단위
    U("P02_range_unit", "approximate", "Q8_2", "casual_short", "그런 운동 하시는 날은 하루에 얼마 동안 하세요?", "한 삼십 분쯤 해요."),
    U("P02_range_unit", "approximate", "Q4_1", "elderly_verbose", _Q_Q4_1, "한 십 년쯤 피웠나, 지금은 끊은 지 대략 삼 년쯤 됐어요. 하루에 열 개비 피웠고요."),
    U("P02_range_unit", "approximate", "Q7_1", "hesitant_filler", _Q_Q7_1, "음... 소주 한 병 정도?"),
    U("P02_range_unit", "approximate", "Q6_1", "banmal", _N_LIQ_1, "한 스무 날쯤 썼나."),
    U("P02_range_unit", "range", "Q7_1", "casual_short", _Q_Q7_1, "소주 두세 병요."),
    U("P02_range_unit", "range", "Q9_1", "formal_full", _N_MOD, "일주일에 3일에서 4일 정도 합니다."),
    U("P02_range_unit", "range", "Q8_1", "hangul_numbers", _N_HARD, "사오 일 해요."),
    U("P02_range_unit", "range", "Q4_1", "banmal", _Q_Q4_1, "이십 년에서 삼십 년? 그쯤 피웠어. 지금은 안 피워, 끊은 지 칠 년. 하루 일곱 개비."),
    U("P02_range_unit", "range", "Q6_1", "casual_short", _N_LIQ_1, "한 달에 열흘에서 스무 날?"),
    U("P02_range_unit", "range_cross_options", "Q6_1", "dialect", _N_LIQ_1, "한 달에 이틀에서 열이틀까지 들쭉날쭉하지예."),
    U("P02_range_unit", "hours_minutes", "Q8_2", "casual_short", "그런 운동 하시는 날은 하루에 얼마 동안 하세요?", "한 시간 반요."),
    U("P02_range_unit", "hours_minutes", "Q9_2", "hangul_numbers", _N_MOD_T, "한 시간 이십 분 걸어요."),
    U("P02_range_unit", "hours_only", "Q8_2", "banmal", "그런 운동 하시는 날은 하루에 얼마 동안 하세요?", "두 시간씩 해."),
    U("P02_range_unit", "mixed_unit_same_beverage", "Q7_1", "casual_short", _Q_Q7_1, "소주 한 병하고 두 잔 더요."),
    U("P02_range_unit", "mixed_unit_same_beverage", "Q7_2", "elderly_verbose", _Q_Q7_2, "그날은 맥주 두 병 마시고 나서 한 캔 더 했던 것 같아요."),
    U("P02_range_unit", "multi_beverage", "Q7_1", "formal_full", _Q_Q7_1, "소주 한 병에 맥주 두 캔 같이 마십니다."),
    U("P02_range_unit", "multi_beverage", "Q7_2", "stt_noise", _Q_Q7_2, "소주두병이랑 막걸리한병"),
    U("P02_range_unit", "unknown_unit", "Q7_1", "casual_short", _Q_Q7_1, "소주 한 짝요."),
    U("P02_range_unit", "unknown_unit", "Q7_2", "banmal", _Q_Q7_2, "맥주 한 짝 마셨어."),
    U("P02_range_unit", "vague", "Q7", "hesitant_filler", _Q_Q7, "음... 가끔 마셔요."),
    U("P02_range_unit", "vague", "Q10", "elderly_verbose", _N_STR, "그건 그때그때 달라요, 손주 보느라 바쁘면 못 하고."),
    U("P02_range_unit", "vague", "Q8_1", "casual_short", _N_HARD, "종종 해요."),

    # ---------------- P03 부분 응답
    U("P03_partial", "missing_on_medication", "Q1.D04", "casual_short", _N_DIAB, "당뇨 진단받은 적 있어요."),
    U("P03_partial", "missing_on_medication", "Q1.D01", "hesitant_filler", _Q_D01, "음, 그러니까, 중풍이라고 진단받은 적 있어요."),
    U("P03_partial", "missing_on_medication", "Q1.D10", "elderly_verbose", "만성폐쇄성폐질환은 진단받으신 적 있으세요? 지금 약도 드세요?",
      "담배를 오래 피워서 그런지 몇 년 전에 만성폐쇄성폐질환이라고 하더라고요."),
    U("P03_partial", "missing_on_medication", "Q1.D05", "formal_full", "이상지질혈증은 진단받으신 적 있으세요? 지금 약도 드세요?", "이상지질혈증 진단을 받은 적이 있습니다."),
    U("P03_partial", "missing_on_medication", "Q1.D08", "stt_noise", "조기정신증은 진단받으신 적 있으세요? 지금 약도 드세요?", "조기정신증진단은받았어요"),
    U("P03_partial", "missing_on_medication", "Q1.D06", "dialect", "폐결핵은 진단받으신 적 있으세요? 약도 드세요?", "옛날에 폐결핵 걸렸다 카더라고예."),
    U("P03_partial", "missing_unit", "Q7", "casual_short", _Q_Q7, "세 번 마셔요."),
    U("P03_partial", "missing_unit", "Q7", "hangul_numbers", _Q_Q7, "다섯 번 마셔요."),
    U("P03_partial", "missing_unit", "Q7", "dialect", _Q_Q7, "두 번 묵지예."),
    U("P03_partial", "missing_amounts[0].amount", "Q7_1", "casual_short", _Q_Q7_1, "와인 마시는 날은 병으로 마셔요."),
    U("P03_partial", "missing_amounts[0].amount", "Q7_1", "banmal", _Q_Q7_1, "맥주를 캔으로 마셔."),
    U("P03_partial", "missing_amounts[0].amount", "Q7_2", "formal_full", _Q_Q7_2, "가장 많이 마신 날은 소주를 병으로 마셨습니다."),
    U("P03_partial", "missing_amounts[0].unit", "Q7_1", "casual_short", _Q_Q7_1, "소주 셋이요."),
    U("P03_partial", "missing_amounts[0].unit", "Q7_2", "hangul_numbers", _Q_Q7_2, "막걸리 다섯이요."),
    U("P03_partial", "missing_years_since_quit", "Q4_1", "formal_full", _Q_Q4_1, "예전에 피우다 끊었습니다. 십오 년 피웠고 하루에 열 개비 피웠어요."),
    U("P03_partial", "missing_years_since_quit", "Q5_1", "banmal", _N_HEAT_1, "아이코스 쓰다가 끊었어. 삼 년 썼고 하루 열 개비."),
    U("P03_partial", "missing_daily_count", "Q4_1", "casual_short", _Q_Q4_1, "지금도 피워요. 오 년 됐어요."),
    U("P03_partial", "missing_total_years", "Q5_1", "elderly_verbose", _N_HEAT_1, "아들이 사 줘서 지금도 써요. 하루에 열 개비 정도 피우고요."),

    # ---------------- P04 재질문 -> 보완 (q = 상담원 재질문, ctx = 처음 질문과 첫 답)
    U("P04_reask_fill", "fill_missing", "Q1.D05", "casual_short", "이상지질혈증 진단을 받으셨군요. 지금 약도 드세요?", "네, 먹어요.",
      ("이상지질혈증은 진단받으신 적 있으세요? 지금 약도 드세요?", "진단은 받았어요.")),
    U("P04_reask_fill", "fill_missing", "Q4_1", "hangul_numbers", "10년 피우셨군요. 하루에 몇 개비 피우셨고, 끊으신 지는 얼마나 되셨어요?",
      "하루에 열다섯 개비 피웠고, 끊은 지 사 년 됐어요.", (_Q_Q4_1, "지금은 끊었어요. 십 년 피웠어요.")),
    U("P04_reask_fill", "fill_missing", "Q7_1", "banmal", "맥주 드시는군요. 보통 얼마나 드세요?", "세 캔.", (_Q_Q7_1, "맥주요.")),
    U("P04_reask_fill", "fill_missing", "Q7", "hesitant_filler", "네 번이요, 일주일에 네 번인지 한 달에 네 번인지 알려 주시겠어요?",
      "아, 한 달에요. 한 달에 네 번.", (_Q_Q7, "네 번요.")),
    U("P04_reask_fill", "clarify_vague", "Q9_1", "casual_short", "가끔 하시는군요. 일주일에 며칠 하시는지 숫자로 말씀해 주시겠어요?", "이틀요.",
      (_N_MOD, "가끔 해요.")),
    U("P04_reask_fill", "clarify_vague", "Q10", "elderly_verbose", "조금 하셨군요. 지난 일주일 동안 며칠 하셨는지 말씀해 주시겠어요?",
      "생각해 보니까 월요일이랑 목요일, 이틀 했네요.", (_N_STR, "조금 했어요.")),
    U("P04_reask_fill", "clarify_vague", "Q8_2", "formal_full", "그때그때 다르시군요. 보통 하시는 날 하루에 몇 분이나 몇 시간 하세요?",
      "보통 한 시간 합니다.", ("그런 운동 하시는 날은 하루에 얼마 동안 하세요?", "그때그때 달라요.")),
    U("P04_reask_fill", "clarify_vague", "Q6_1", "stt_noise", "가끔 쓰시는군요. 최근 한 달 동안 며칠 쓰셨는지 숫자로 말씀해 주시겠어요?",
      "한달에닷새요", (_N_LIQ_1, "가끔 써요.")),
    U("P04_reask_fill", "fill_missing", "Q1.D02", "dialect", "심근경색이나 협심증 진단은 받으셨군요. 지금 약도 드세요?", "약은 안 묵어예.",
      (_Q_D02, "협심증이라 카데예.")),

    # ---------------- P05 정정 (q = 상담원이 앞 답을 되짚고 다음 질문으로 넘어간 말, ctx = 앞 질문과 첫 답)
    U("P05_correction", "correction", "Q7", "casual_short", "일주일에 세 번 드시는군요. " + _Q_Q7_1, "아 잘못 말했어요, 두 번이에요.",
      (_Q_Q7, "일주일에 세 번 마셔요.")),
    U("P05_correction", "correction", "Q7_1", "casual_short", "카스 여섯 캔 드시는군요. " + _Q_Q7_2, "아 잠깐만요, 여섯 캔이 아니라 다섯 캔이에요.",
      (_Q_Q7_1, "카스 여섯 캔요.")),
    U("P05_correction", "correction", "Q1.D04", "hesitant_filler", "진단받으셨고 약은 안 드시는군요. 이상지질혈증은 진단받으신 적 있으세요? 약도 드세요?",
      "아, 아니다... 정정할게요. 당뇨 약은 먹고 있어요.", (_N_DIAB, "당뇨 진단받았고 약은 안 먹어요.")),
    U("P05_correction", "correction", "Q4_1", "elderly_verbose", "끊으신 지 3년 되셨군요. " + _N_HEAT,
      "아이고, 내가 헷갈렸네. 끊은 지 삼 년이 아니라 오 년이에요.", (_Q_Q4_1, "끊은 지 삼 년 됐어요.")),
    U("P05_correction", "correction", "Q8_1", "banmal", "일주일에 나흘 하시는군요. " + _N_HARD_T, "아니, 잘못 말했다. 힘든 운동은 사흘이야.",
      (_N_HARD, "일주일에 나흘 해요.")),
    U("P05_correction", "correction", "Q2.D02", "formal_full", "아버님께서 협심증이 있으셨군요. " + _F.format(d="고혈압"),
      "제가 착각했습니다. 협심증 있으신 분은 없습니다. 정정할게요.", (_F.format(d="심근경색이나 협심증"), "아버지가 협심증 있으셨어요.")),
    U("P05_correction", "correction", "Q10", "stt_noise", "3일 하셨군요. 이걸로 문진은 다 끝났어요. 수고 많으셨어요.", "아 잘못말했어요 근력운동은 이틀이요",
      (_N_STR, "근력 운동 사흘 했어요.")),
    U("P05_correction", "correction", "Q9_2", "dialect", "하루 1시간 하시는군요. " + _N_STR, "아이다, 그 운동은 사십 분이라예. 잘못 말했어예.",
      (_N_MOD_T, "한 시간 해요.")),
    U("P05_correction", "correction", "Q3", "hesitant_filler", "보유자이시군요. " + _N_Q4, "음, 아니에요, 제가 잘못 말했어요. B형간염 보유자 아니에요.",
      ("B형간염 바이러스 보유자이신가요?", "보유자 맞아요.")),
    U("P05_correction", "correction", "Q4", "casual_short", "다섯 갑 넘게 피우셨군요. " + _Q_Q4_1, "아 잘못 말했어요, 담배는 피운 적 없어요.",
      (_N_Q4, "네, 피웠어요.")),

    # ---------------- P06 충돌 (정정 표현 없이 다른 값)
    U("P06_conflict", "prev_diff", "Q10", "casual_short", "3일 하셨군요. 이걸로 문진은 다 끝났어요. 수고 많으셨어요.",
      "근력 운동은 닷새 했어요.", (_N_STR, "사흘 했어요.")),
    U("P06_conflict", "prev_diff", "Q9_1", "banmal", "일주일에 이틀 하시는군요. " + _N_MOD_T, "그 운동은 엿새 해.", (_N_MOD, "이틀 해요.")),
    U("P06_conflict", "prev_diff", "Q1.D04", "formal_full", "당뇨병 진단을 받으셨군요. 이상지질혈증은 진단받으신 적 있으세요? 약도 드세요?",
      "당뇨병 진단은 받은 적 없습니다.", (_N_DIAB, "진단받았어요.")),
    U("P06_conflict", "prev_diff", "Q2.D03", "elderly_verbose", "그런 분은 안 계시는군요. " + _F.format(d="당뇨병"),
      "그러고 보니 우리 형님이 고혈압 약을 드시지요.", (_F.format(d="고혈압"), "없어요.")),
    U("P06_conflict", "prev_diff", "Q5_1", "stt_noise", "가열담배는 끊으셨고 7년 쓰셨군요. " + _N_LIQ, "가열담배는육년썼어요",
      (_N_HEAT_1, "칠 년 썼어요.")),
    U("P06_conflict", "prev_diff", "Q8_2", "hesitant_filler", "하루에 30분 하시는군요. " + _N_MOD, "음, 그 힘든 운동은요, 하루에 사십 분 해요.",
      ("그런 운동 하시는 날은 하루에 얼마 동안 하세요?", "삼십 분 해요.")),
    U("P06_conflict", "r3_max_below_usual", "Q7_2", "casual_short", _Q_Q7_2, "한 병요.", (_Q_Q7_1, "소주 두 병요.")),
    U("P06_conflict", "r3_max_below_usual", "Q7_2", "hesitant_filler", _Q_Q7_2, "음... 두 캔이었나? 두 캔요.", (_Q_Q7_1, "맥주 네 캔.")),

    # ---------------- P07 앞 답 참조 (q = 이번 문항 질문, ctx = 앞 문항 질문과 답)
    U("P07_prior_ref", "same_as_prior_item", "Q5_1", "casual_short", "가열담배는 지금도 쓰세요? 몇 년, 하루 몇 개비요?", "그것도 아까랑 똑같아요.",
      (_Q_Q4_1, "지금 피우고요, 이십 년 됐고 하루 열 개비요.")),
    U("P07_prior_ref", "same_as_prior_item", "Q9_1", "banmal", _N_MOD, "그것도 똑같이 사흘.", (_N_HARD, "사흘 해요.")),
    U("P07_prior_ref", "same_as_prior_item", "Q9_2", "elderly_verbose", _N_MOD_T, "그것도 아까 말한 거랑 같아요, 한 번 나가면 비슷하게 해요.",
      ("힘든 운동 하시는 날은 하루에 얼마 동안 하세요?", "한 시간 해요.")),
    U("P07_prior_ref", "same_as_prior_item", "Q1.D04", "hesitant_filler", "당뇨병은요? 진단받으셨거나 드시는 약 있으세요?", "음, 그것도 고혈압이랑 같아요.",
      (_Q_D03, "진단받고 약 먹어요.")),
    U("P07_prior_ref", "same_as_prior_item", "Q2.D04", "casual_short", "당뇨병은요? 부모님이나 형제자매 중에 계세요?", "그것도 없어요.",
      (_F.format(d="고혈압"), "없어요.")),
    U("P07_prior_ref", "same_as_prior_item", "Q10", "dialect", _N_STR, "그것도 아까랑 똑같이 했심더.", (_N_MOD, "나흘 해요.")),
    U("P07_prior_ref", "same_as_usual", "Q7_2", "casual_short", _Q_Q7_2, "평소랑 같아요, 그 이상은 안 마셔요.", (_Q_Q7_1, "소주 한 병요.")),
    U("P07_prior_ref", "same_as_usual", "Q7_2", "dialect", _Q_Q7_2, "맨날 그만큼만 묵어예, 똑같아요.", (_Q_Q7_1, "맥주 두 캔요.")),

    # ---------------- P08 모름·거절·보류
    U("P08_unk_refuse", "uncertain", "Q3", "hesitant_filler", "B형간염 바이러스 보유자이신가요?", "음... 그게요, 검사를 해 봤는지 기억이 안 나요."),
    U("P08_unk_refuse", "uncertain", "Q2.D01", "elderly_verbose", _F.format(d="뇌졸중"),
      "부모님 쪽은 그런 얘기를 들은 적이 없어서 잘 모르겠어요."),
    U("P08_unk_refuse", "uncertain", "Q4_1", "banmal", _Q_Q4_1, "몇 년 피웠는지는 모르겠어."),
    U("P08_unk_refuse", "uncertain", "Q8_2", "casual_short", "그런 운동 하시는 날은 하루에 얼마 동안 하세요?", "잘 모르겠어요."),
    U("P08_unk_refuse", "uncertain", "Q7_2", "stt_noise", _Q_Q7_2, "그건기억안나요"),
    U("P08_unk_refuse", "uncertain", "Q1.D11", "formal_full", "암 같은 다른 병으로 진단받으신 적 있으세요? 지금 약도 드세요?", "진단을 받았는지 정확히 모르겠습니다."),
    U("P08_unk_refuse", "refused", "Q4_1", "casual_short", _Q_Q4_1, "그건 말 안 할래요."),
    U("P08_unk_refuse", "refused", "Q1.D07", "formal_full", "우울증은 진단받으신 적 있으세요? 지금 약도 드세요?", "그 부분은 답변드리고 싶지 않습니다."),
    U("P08_unk_refuse", "refused", "Q2.D01", "banmal", _F.format(d="뇌졸중"), "그건 말 안 해."),
    U("P08_unk_refuse", "refused", "Q2.D02", "elderly_verbose", _F.format(d="심근경색이나 협심증"), "집안 얘기는 좀 그래요, 그건 안 할게요."),
    U("P08_unk_refuse", "skip", "Q8_1", "hesitant_filler", _N_HARD, "음... 그건 좀 나중에 말씀드릴게요."),
    U("P08_unk_refuse", "skip", "Q1.D05", "casual_short", "이상지질혈증은 진단받으신 적 있으세요? 지금 약도 드세요?", "그건 이따 다시 얘기할게요."),
    U("P08_unk_refuse", "skip", "Q6_1", "dialect", _N_LIQ_1, "그거는 쪼매 있다가 말할게예."),
    U("P08_unk_refuse", "skip", "Q10", "casual_short", _N_STR, "그건 나중에요."),

    # ---------------- P09 범위 밖
    U("P09_oos", "ask_purpose", "Q7", "casual_short", _Q_Q7, "이건 왜 물어보세요?"),
    U("P09_oos", "ask_purpose", "Q2.D01", "banmal", _F.format(d="뇌졸중"), "가족 병까지 왜 말해야 돼?"),
    U("P09_oos", "ask_purpose", "Q4_1", "elderly_verbose", _Q_Q4_1, "이런 걸 다 적어서 어디에 쓰는 거예요? 보험 회사에 가는 건 아니지요?"),
    U("P09_oos", "ask_purpose", "Q3", "hesitant_filler", "B형간염 바이러스 보유자이신가요?", "음... 이걸 꼭 말해야 하나요?"),
    U("P09_oos", "off_topic", "Q7_1", "casual_short", _Q_Q7_1, "근데 오늘 검진 몇 시에 끝나요?"),
    U("P09_oos", "off_topic", "Q9_1", "banmal", _N_MOD, "아 근데 주차는 어디다 해야 돼?"),
    U("P09_oos", "off_topic", "Q5", "dialect", _N_HEAT, "오늘 날이 억수로 덥네예."),
    U("P09_oos", "off_topic", "Q1.D02", "elderly_verbose", _Q_D02, "아이고, 손주가 오늘 학교 시험이라 마음이 계속 쓰이네요."),
    U("P09_oos", "off_topic", "Q6", "stt_noise", _N_LIQ, "아근데 여기 화장실어디에요"),
    U("P09_oos", "out_of_schema", "Q1.D03", "casual_short", _Q_D03, "저 허리 디스크가 있어요."),
    U("P09_oos", "out_of_schema", "Q8_1", "elderly_verbose", _N_HARD, "무릎이 안 좋아서 계단을 오르면 아파요."),
    U("P09_oos", "out_of_schema", "Q7", "formal_full", _Q_Q7, "저는 위염이 있어서 약을 먹고 있습니다."),
    U("P09_oos", "out_of_schema", "Q2.D04", "banmal", _F.format(d="당뇨병"), "나 비염 있어."),
    U("P09_oos", "out_of_schema", "Q10", "hesitant_filler", _N_STR, "음, 요즘 어깨가 좀 결려서요."),

    # ---------------- P10 경계값
    U("P10_boundary", "edge_in", "Q8_1", "casual_short", _N_HARD, "매일 해요, 일주일 내내요."),
    U("P10_boundary", "edge_in", "Q10", "banmal", _N_STR, "하루도 안 했어."),
    U("P10_boundary", "edge_in", "Q6_1", "hangul_numbers", _N_LIQ_1, "한 달 내내 썼어요, 삼십 일요."),
    U("P10_boundary", "edge_in", "Q9_1", "formal_full", _N_MOD, "일주일에 하루도 하지 않습니다."),
    U("P10_boundary", "large_amount", "Q7_2", "casual_short", _Q_Q7_2, "소주 열 병요."),
    U("P10_boundary", "large_amount", "Q4_1", "elderly_verbose", _Q_Q4_1, "젊을 때는 하루에 세 갑, 육십 개비씩 피웠어요. 사십 년 피우고 지금은 끊은 지 이 년 됐어요."),
    U("P10_boundary", "large_amount", "Q7_1", "dialect", _Q_Q7_1, "막걸리 다섯 병은 묵지예."),
    U("P10_boundary", "out_of_range", "Q8_1", "casual_short", _N_HARD, "일주일에 팔 일 해요."),
    U("P10_boundary", "out_of_range", "Q8_2", "hangul_numbers", "그런 운동 하시는 날은 하루에 얼마 동안 하세요?", "하루에 천오백 분 해요."),
    U("P10_boundary", "out_of_range", "Q6_1", "banmal", _N_LIQ_1, "한 달에 사십 일 썼어."),
    U("P10_boundary", "out_of_range", "Q7", "formal_full", _Q_Q7, "일주일에 열 번 마십니다."),
    U("P10_boundary", "out_of_range", "Q10", "stt_noise", _N_STR, "근력운동 아흐레했어요"),
    # ---------------- P11 정규화기 규칙·사유 코드 사례 (2026-10-13 보충)
    U("P11_norm_case", "other_beverage", "Q7_1", "casual_short", _Q_Q7_1, "담금주 두 잔요."),
    U("P11_norm_case", "abv_beverage", "Q7_1", "hesitant_filler", _Q_Q7_1, "음, 저는 하이볼 세 잔 마셔요."),
    U("P11_norm_case", "beverage_missing", "Q7_1", "banmal", _Q_Q7_1, "한 번 마시면 두 병은 먹지."),
    U("P11_norm_case", "beverage_inherit", "Q7_2", "casual_short", _Q_Q7_2, "제일 많이 마신 날은 네 병이요."),
    U("P11_norm_case", "missing_number", "Q8_1", "formal_full", _N_HARD, "네, 그런 운동은 하고 있습니다."),
    U("P11_norm_case", "invalid_option", "Q4_1", "elderly_verbose", _Q_Q4_1, "피웠다 끊었다 해요. 십 년 됐고, 피울 때는 하루에 열 개비요."),
    U("P11_norm_case", "frequency_word", "Q7", "dialect", _Q_Q7, "술은 매일 묵지예."),
    U("P11_norm_case", "does_not_drink_conflict", "Q7", "hesitant_filler", _Q_Q7, "음, 술은 안 마셔요. 회식 때나 맥주 한 잔 마시고요."),
    U("P11_norm_case", "no_exercise", "Q8_1", "casual_short", _N_HARD, "운동은 아예 안 해요."),
    U("P11_norm_case", "few_smokes", "Q4", "banmal", _N_Q4, "호기심에 한두 대 피워 본 게 다야."),
    U("P11_norm_case", "not_now_but_before", "Q4", "elderly_verbose", _N_Q4, "아니요, 안 피워요. 젊을 때 이십 년 피우다가 끊었지요."),
    U("P11_norm_case", "pre_disease", "Q1.D03", "formal_full", _Q_D03, "검진에서 고혈압 전단계라는 말은 들었습니다. 약은 안 먹고 있어요."),
    U("P11_norm_case", "medication_only", "Q1.D03", "casual_short", _Q_D03, "혈압약 먹고 있어요."),
    U("P11_norm_case", "not_target_family", "Q2.D03", "elderly_verbose", _F.format(d="고혈압"), "우리 할아버지가 고혈압이 있으셨어요."),
]

# 말투(스타일)별 짧은 좋은 예 (발화 프롬프트 공통)
STYLE_EXAMPLES = {
    "formal_full": "진단받은 적은 있습니다. 약은 지금 안 먹고 있어요.",
    "casual_short": "두 병요. / 안 피워요, 끊었어요.",
    "banmal": "일주일에 세 번 마셔.",
    "elderly_verbose": "젊을 때부터 피웠으니까 삼십 년 됐지요. 하루에 열 개비씩 피워요.",
    "hesitant_filler": "음... 그게, 진단은 받았는데 약은 안 먹어요.",
    "hangul_numbers": "삼 년 피웠고, 하루에 열두 개비 피웠어요. 끊은 지는 이 년 됐어요.",
    "dialect": "진단은 안 받았심더. 약도 안 묵어요.",
    "stt_noise": "진단은받았는데 약은안먹어요",
}
OOS_STYLE_EXAMPLE = "근데 요즘 밤에 잠을 통 못 자요."

# 나쁜 발화 예: (나쁜 문장, 고친 문장, 이유). v1 데이터에서 실제로 나온 문장이다.
BAD_UTT = [
    ("부모님이나 형제자매 중에서 암을 포함한 기타 질환을 앓은 분은 없습니다", "부모님이나 형제 중에 암 같은 큰 병 앓은 사람은 없어요", "문진표 말투"),
    ("중강도 신체활동을 하는 날은 하루에 사십분 합니다", "운동하는 날은 사십 분씩 해요", "문진표 낱말"),
    ("피운 기간은 모두 6년", "육 년 피웠어요", "문진표 낱말"),
    ("소주를 20병 마셨습니다. 단위는 병이며, 정확히 20병입니다.", "소주 스무 병 마셨어요", "자기 답을 보증하는 군말"),
    ("일주일에 열 번 마셨어요. 그게 맞는 거 같아요, 좀 이상하긴 한데", "일주일에 열 번 마셔요", "군말(큰 값도 그냥 말함)"),
    ("총 세 년 동안 피웠고 / 다섯 날 정도예요 / 열병 / 열백 개비", "삼 년 동안 피웠고 / 닷새요 / 열 병 / 열 개비", "숫자 말투"),
    ("지금 약도 안 먹고 있어요. 아 그게, 별로 안 먹어요", "음, 지금 약도 안 먹고 있어요", "덧붙인 말이 답과 어긋남"),
    ("날씨 변하는 거 무섭다. / 잠을 잘 못 자는 게 걱정스럽다", "요즘 날씨가 왔다 갔다 해서 정신이 없네요 / 요즘 잠을 통 못 자요", "글로 쓴 혼잣말"),
    ("(정정 대화의 첫 답) 처음에 약 안 먹는다고 했는데 정정할게요", "(첫 답) 약은 안 먹어요", "첫 답에 정정이 들어감"),
    ("(이전 환자 턴) 가족 중에 뇌졸중 걸린 분 있나요?", "(이전 환자 턴) 부모님 중엔 뇌졸중 걸린 분 없어요", "환자가 질문함"),
    ("평생 써본 적 있어요", "네, 써 봤어요", "질문 문장을 따라 함"),
]

# ================================================================ 2. LoRA-B 응답 예시 (action별)
_END = "이걸로 문진은 모두 끝났어요. 답해 주셔서 감사합니다."
B_EXAMPLES = [
    # ---------------- START: 인사 + 문진 안내 + 첫 질문(Q1.D01). 환자 말이 없다.
    B("START", "Q1.D01", None, "안녕하세요. 지금부터 건강검진 문진표를 같이 작성해 볼게요. 먼저, 뇌졸중(중풍) 진단을 받으신 적이 있거나 지금 약을 드시고 계세요?",
      next_text="뇌졸중(중풍) 진단을 받았거나 현재 약물 치료 중이십니까?"),
    B("START", "Q1.D01", None, "안녕하세요, 문진 시작할게요. 편하게 답해 주시면 돼요. 혹시 중풍 진단받으신 적 있으세요? 지금 드시는 약도 있으신가요?",
      next_text="요즘 뇌졸중 진단을 받았거나 약을 먹고 계신가요?"),
    B("START", "Q1.D01", None, "안녕하세요. 건강검진 전에 몇 가지 여쭤볼게요. 처음은 질환이에요. 뇌졸중, 그러니까 중풍으로 진단받으셨거나 약을 드시는 중이세요?",
      next_text="뇌졸중으로 진단을 받으셨거나 약을 드시고 계신가요?"),
    B("START", "Q1.D01", None, "안녕하세요. 오늘 문진은 제가 하나씩 여쭤보면서 같이 채워 갈게요. 먼저 뇌졸중(중풍) 진단을 받으신 적이 있는지, 지금 약을 드시는지 말씀해 주세요.",
      next_text="뇌졸중(중풍): 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까?"),
    B("START", "Q1.D01", None, "안녕하세요, 건강검진 문진을 시작하겠습니다. 질문이 몇 가지 있는데 생각나시는 대로 편하게 답해 주세요. 뇌졸중 진단을 받으셨거나 약을 드시고 계세요?",
      next_text="뇌졸중 진단을 받으셨거나 약을 드시고 계신가요?"),
    B("START", "Q1.D01", None, "안녕하세요. 문진표를 같이 작성해 볼게요. 모르시는 건 모른다고 하셔도 괜찮아요. 먼저, 중풍이라고도 하는 뇌졸중 진단을 받으신 적 있으세요? 약도 드세요?",
      next_text="뇌졸중(중풍) 진단을 받으신 적이 있거나 지금 약을 드시고 계세요?"),
    B("START", "Q1.D01", None, "안녕하세요. 지금부터 건강 상태를 몇 가지 여쭤볼게요. 처음으로, 뇌졸중 진단을 받으셨거나 그 약을 드시는 중이신가요?",
      next_text="혹시 뇌졸중으로 진단받으셨거나 현재 약물 치료 중이신가요?"),
    B("START", "Q1.D01", None, "안녕하세요. 건강검진 문진 도와드릴게요. 앓고 계신 병부터 여쭤볼게요. 뇌졸중(중풍)으로 진단받으신 적이 있거나 지금 약을 드시나요?",
      next_text="뇌졸중(중풍)으로 진단받았거나 약을 드시는 중이세요?"),
    B("START", "Q1.D01", None, "안녕하세요, 문진표 작성 시작해 볼게요. 먼저 뇌졸중이요. 진단받으신 적이 있으시거나 지금 약을 드시고 계신가요?",
      next_text="뇌졸중은 어떠세요? 진단을 받으셨거나 약을 복용 중이신가요?"),
    B("START", "Q1.D01", None, "안녕하세요. 지금부터 질문 드리면 아시는 만큼만 답해 주시면 돼요. 첫 번째로, 뇌졸중(중풍) 진단을 받으셨거나 약을 드시고 계세요?",
      next_text="뇌졸중(중풍) 진단을 받으셨거나 약을 드시고 계신가요?"),
    B("START", "Q1.D01", None, "안녕하세요. 검진 전에 문진표를 함께 작성할게요. 먼저 질환 여쭤볼게요. 뇌졸중 진단을 받으셨는지, 그리고 지금 약을 드시는지 알려 주시겠어요?",
      next_text="다음은 뇌졸중입니다. 진단받은 적이 있으신지, 지금 약을 드시는지 알려 주세요."),
    B("START", "Q1.D01", None, "안녕하세요, 반갑습니다. 문진 시작할게요. 중풍이라고 하는 뇌졸중으로 진단받으신 적 있으세요? 지금 약도 드시고요?",
      next_text="뇌졸중(중풍) 진단을 받으셨거나 약을 드시나요?"),

    # ---------------- NEXT: 짧게 받고 next.text를 묻는다
    B("NEXT", "Q1.D03", "네, 고혈압 진단은 받았습니다. 약은 매일 아침에 먹고 있어요.",
      "고혈압 진단을 받으셨고 약도 드시고 계시는군요. " + _N_DIAB, next_text=_N_DIAB, known="진단 받음, 지금 약 먹음"),
    B("NEXT", "Q1.D03", "진단받았어요. 약도 먹어요.", "진단받으시고 약도 드시는군요. 그럼 당뇨병은 어떠세요? 진단받으셨거나 드시는 약 있으세요?",
      next_text=_N_DIAB, known="진단 받음, 지금 약 먹음"),
    B("NEXT", "Q1.D07", "없어. 약도 안 먹어.", "둘 다 없으시군요. 그럼 조기정신증은 진단받으셨거나 드시는 약 있으세요?",
      next_text="조기정신증은 진단받으신 적 있으세요? 약도 드세요?", known="진단 안 받음, 지금 약 안 먹음"),
    B("NEXT", "Q1.D01", "몇 년 전에 중풍으로 쓰러져서 진단받았어요. 그 뒤로는 약을 안 먹고 지내요.",
      "중풍 진단은 받으셨고 지금 약은 안 드시는군요. " + _Q_D02, next_text=_Q_D02, known="진단 받음, 지금 약 안 먹음"),
    B("NEXT", "Q1.D11", "암이나 그런 큰 병은 없어요. 약도 안 먹어요.",
      "그런 병은 없으시군요. 이제 가족 이야기 여쭤볼게요. " + _F.format(d="뇌졸중"), next_text=_F.format(d="뇌졸중"),
      known="진단 안 받음, 지금 약 안 먹음"),
    B("NEXT", "Q2.D03", "우리 어머니가 고혈압으로 오래 고생하셨어요.",
      "어머님께서 고혈압이 있으셨군요. 당뇨병은 어떠세요? 부모님이나 형제자매 중에 앓으셨거나 그 병으로 돌아가신 분 계세요?",
      next_text=_F.format(d="당뇨병"), known="앓은 분 있음"),
    B("NEXT", "Q2.D05", "부모님형제중에 암걸린사람 없어요", "안 계시는군요. 그럼 B형간염 바이러스 보유자이신지 여쭤볼게요. 보유자라고 들으신 적 있으세요?",
      next_text=_N_HEPB, known="앓은 분 없음"),
    B("NEXT", "Q3", "아니요, 보유자 아니에요.", "보유자는 아니시군요. " + _N_Q4, next_text=_N_Q4, known="보유자 아님"),
    B("NEXT", "Q3", "음, 검사를 안 해 봐서 그건 모르겠어요.", "검사를 안 해 보셔서 모르시는군요. 이제 담배 여쭤볼게요. " + _N_Q4,
      next_text=_N_Q4, known="보유 여부 모름"),
    B("NEXT", "Q4", "응, 그 이상 피웠지.", "다섯 갑 넘게 피워 보셨군요. 지금도 피우세요, 아니면 끊으셨어요?", next_text=_Q_Q4_1,
      known="5갑 넘게 피운 적 있음"),
    B("NEXT", "Q4", "아니요, 담배는 평생 피운 적이 없습니다.", "담배는 안 피우셨군요. 그럼 " + _N_HEAT, next_text=_N_HEAT, known="피운 적 없음"),
    B("NEXT", "Q4_1", "네, 지금도 피워요. 이십 년 됐고 하루에 열 개비 피워요.",
      "지금도 피우시고, 20년 동안 하루 10개비씩 피우셨군요. " + _N_HEAT, next_text=_N_HEAT, known="지금 피움, 피운 기간 20년, 하루 10개비"),
    B("NEXT", "Q4_1", "지금은 끊었습니다. 십 년 피웠고 하루에 스무 개비씩 피웠어요. 끊은 지는 오 년 됐습니다.",
      "10년 동안 하루 20개비씩 피우시다가 끊으신 지 5년 되셨군요. " + _N_HEAT, next_text=_N_HEAT,
      known="끊음, 피운 기간 10년, 하루 20개비, 끊은 지 5년"),
    B("NEXT", "Q5", "그런 거는 써 본 적 없어예.", "가열담배는 안 써 보셨군요. " + _N_LIQ, next_text=_N_LIQ, known="써 본 적 없음"),
    B("NEXT", "Q6", "아니요, 그것도 안 써 봤어요.", "액상형도 안 써 보셨군요. 이제 술 여쭤볼게요. " + _Q_Q7, next_text=_Q_Q7, known="써 본 적 없음"),
    B("NEXT", "Q6_1", "열흘요.", "최근 한 달 동안 10일 쓰셨군요. 이제 술 여쭤볼게요. 평소 술은 얼마나 자주 드세요?", next_text=_Q_Q7,
      known="최근 한 달 10~29일 씀"),
    B("NEXT", "Q6_1", "한 스무 날쯤 썼나.", "한 달에 스무 날쯤 쓰셨군요. " + _Q_Q7, next_text=_Q_Q7, known="최근 한 달 10~29일 씀"),
    B("NEXT", "Q7", "일주일에 두 번 마셔요.", "일주일에 두 번 드시는군요. " + _Q_Q7_1, next_text=_Q_Q7_1, known="술 마심, 일주일에 2번"),
    B("NEXT", "Q7", "술 안 마셔. 아예 안 먹어.", "술은 안 드시는군요. 이제 운동 여쭤볼게요. " + _N_HARD, next_text=_N_HARD, known="지난 1년 술 안 마심"),
    B("NEXT", "Q7", "모임이 있을 때나 마시니까, 한 달에 두 번 정도 마시지요.", "모임 있을 때 한 달에 두 번 정도 드시는군요. " + _Q_Q7_1,
      next_text=_Q_Q7_1, known="술 마심, 한 달에 2번쯤"),
    B("NEXT", "Q7_1", "소주 한 병요.", "술 드시는 날엔 소주 한 병 드시는군요. " + _Q_Q7_2, next_text=_Q_Q7_2, known="소주 1병"),
    B("NEXT", "Q7_1", "음, 맥주로 세 캔? 네, 세 캔 마셔요.", "맥주 세 캔 드시는군요. 지난 1년 중에 가장 많이 드신 날은 얼마나 드셨어요?",
      next_text=_Q_Q7_2, known="맥주 3캔"),
    B("NEXT", "Q7_1", "소주 한 병하고 두 잔 더요.", "소주 한 병에 두 잔 더 드시는군요. " + _Q_Q7_2, next_text=_Q_Q7_2,
      known="소주 1.3병쯤"),
    B("NEXT", "Q7_1", "소주 한 병에 맥주 두 캔 같이 마십니다.", "소주 한 병이랑 맥주 두 캔 드시는군요. 가장 많이 드신 날은 얼마나 드셨어요?",
      next_text=_Q_Q7_2, known="소주 1병, 맥주 2캔"),
    B("NEXT", "Q7_1", "생맥주 오백 두 잔요.", "생맥주 오백으로 두 잔 드시는군요. " + _Q_Q7_2, next_text=_Q_Q7_2, known="맥주 1000cc"),
    B("NEXT", "Q7_2", "가장 많이 마신 날은 소주 세 병이었습니다.", "가장 많이 드신 날은 소주 세 병이었군요. 이제 운동 여쭤볼게요. " + _N_HARD,
      next_text=_N_HARD, known="소주 3병"),
    B("NEXT", "Q7_2", "그날은 맥주 두 병 마시고 나서 한 캔 더 했던 것 같아요.", "가장 많이 드신 날은 맥주 두 병에 한 캔 더 드셨군요. " + _N_HARD,
      next_text=_N_HARD, known="맥주 1355cc쯤"),
    B("NEXT", "Q7_2", "평소랑 같아요, 그 이상은 안 마셔요.", "가장 많이 드신 날도 평소처럼 소주 한 병이었군요. " + _N_HARD, next_text=_N_HARD,
      known="소주 1병"),
    B("NEXT", "Q8_1", "사흘 해요.", "일주일에 3일 하시는군요. " + _N_HARD_T, next_text=_N_HARD_T, known="일주일에 3일"),
    B("NEXT", "Q8_1", "그런 운동은 안 해요.", "힘든 운동은 안 하시는군요. 그럼 " + _N_MOD, next_text=_N_MOD, known="일주일에 0일"),
    B("NEXT", "Q8_1", "사오 일 해요.", "일주일에 사오 일 하시는군요. " + _N_HARD_T, next_text=_N_HARD_T, known="일주일에 4.5일쯤"),
    B("NEXT", "Q8_2", "등산을 가면 한 번에 두 시간은 걸어요.", "하루에 2시간 하시는군요. " + _N_MOD, next_text=_N_MOD, known="하루 2시간"),
    B("NEXT", "Q8_2", "한 시간 반요.", "하루에 1시간 30분 하시는군요. " + _N_MOD, next_text=_N_MOD, known="하루 1시간 30분"),
    B("NEXT", "Q9_1", "일주일에 3일에서 4일 정도 합니다.", "일주일에 3일에서 4일 하시는군요. " + _N_MOD_T, next_text=_N_MOD_T, known="일주일에 3.5일쯤"),
    B("NEXT", "Q9_1", "그것도 똑같이 사흘.", "그것도 일주일에 3일 하시는군요. 그렇게 하시는 날은 하루에 얼마나 하세요?", next_text=_N_MOD_T, known="일주일에 3일"),
    B("NEXT", "Q9_2", "하루에사십분해요", "하루 40분 하시는군요. " + _N_STR, next_text=_N_STR, known="하루 40분"),
    B("NEXT", "Q5_1", "그것도 아까랑 똑같아요.", "가열담배도 지금 쓰시고, 20년 동안 하루 10개비씩이시군요. " + _N_LIQ, next_text=_N_LIQ,
      known="지금 씀, 쓴 기간 20년, 하루 10개비"),
    B("NEXT", "Q1.D05", "네, 먹어요.", "약도 드시는군요. 폐결핵은 진단받으신 적 있으세요? 약도 드세요?",
      next_text="폐결핵은 진단받으신 적 있으세요? 약도 드세요?", known="지금 약 먹음"),
    B("NEXT", "Q7_1", "세 캔.", "맥주 세 캔 드시는군요. " + _Q_Q7_2, next_text=_Q_Q7_2, known="맥주 3캔"),

    # ---------------- NEXT/CORRECT/HOLD/SKIP + END (Q10 다음): 받은 것을 짧게 정리하고 마무리 인사로 끝낸다. 질문하지 않는다.
    B("NEXT", "Q10", "이틀요.", "지난 일주일 동안 근력 운동은 2일 하셨군요. " + _END, next_type="END", known="최근 일주일 2일"),
    B("NEXT", "Q10", "아령은 이틀 했심더.", "아령으로 이틀 하셨군요. 이걸로 문진은 다 끝났어요. 끝까지 답해 주셔서 고맙습니다.", next_type="END",
      known="최근 일주일 2일"),
    B("NEXT", "Q10", "하루도 안 했어.", "지난 일주일 동안은 근력 운동을 안 하셨군요. 오늘 문진은 여기까지예요. 수고 많으셨어요.", next_type="END",
      known="최근 일주일 0일"),
    B("NEXT", "Q10", "생각해 보니까 월요일이랑 목요일, 이틀 했네요.", "월요일이랑 목요일, 이틀 하셨군요. 이제 문진이 모두 끝났어요. 답해 주셔서 감사합니다.",
      next_type="END", known="최근 일주일 2일"),
    B("NEXT", "Q10", "일주일 내내 했어요.", "일주일 내내 하셨군요. 질문은 여기까지예요. 오래 답해 주셔서 고맙습니다.", next_type="END",
      known="최근 일주일 7일"),
    B("NEXT", "Q10", "그것도 아까랑 똑같이 했심더.", "근력 운동도 나흘 하셨군요. 이걸로 문진은 모두 마쳤어요. 수고 많으셨어요.", next_type="END",
      known="최근 일주일 4일"),
    B("CORRECT", "Q10", "아 잘못말했어요 근력운동은 이틀이요", "네, 2일로 고쳐 둘게요. 이걸로 문진은 모두 끝났어요. 답해 주셔서 감사합니다.",
      next_type="END", known="최근 일주일 2일"),
    B("HOLD", "Q10", "글쎄요, 며칠 했는지 기억이 안 나네요.", "기억 안 나시면 괜찮아요, 그 부분은 비워 둘게요. 오늘 문진은 이걸로 끝이에요. 수고 많으셨어요.",
      next_type="END", reason="UNCERTAIN", hold="근력 운동 한 날 수"),
    B("SKIP", "Q10", "그건 나중에요.", "네, 나중에 말씀해 주셔도 괜찮아요. 질문은 여기까지예요. 답해 주셔서 감사합니다.", next_type="END",
      reason="REQUEST_SKIP", hold="근력 운동 한 날 수"),
    B("SKIP", "Q10", "그건 말하기 싫어요.", "네, 말씀 안 하셔도 괜찮아요. 이걸로 문진은 모두 끝났어요. 고맙습니다.", next_type="END",
      reason="REFUSED", hold="근력 운동 한 날 수"),

    # ---------------- CORRECT: 새 값으로 고쳐 두었다고 말하고 next.text를 묻는다(앞 문항을 고쳐도 지금 묻던 질문이 next다)
    B("CORRECT", "Q7", "아 잘못 말했어요, 두 번이에요.", "네, 일주일에 두 번으로 고쳐 둘게요. 그럼 " + _Q_Q7_1, next_text=_Q_Q7_1, known="일주일에 2번"),
    B("CORRECT", "Q7_1", "아 잠깐만요, 여섯 캔이 아니라 다섯 캔이에요.", "네, 카스 다섯 캔으로 고쳐 둘게요. " + _Q_Q7_2, next_text=_Q_Q7_2,
      known="맥주 5캔"),
    B("CORRECT", "Q1.D04", "아, 아니다... 정정할게요. 당뇨 약은 먹고 있어요.",
      "당뇨 약은 드시는 걸로 고쳐 둘게요. 이상지질혈증은 진단받으신 적 있으세요? 약도 드세요?",
      next_text="이상지질혈증은 진단받으신 적 있으세요? 약도 드세요?", known="지금 약 먹음"),
    B("CORRECT", "Q4_1", "아이고, 내가 헷갈렸네. 끊은 지 삼 년이 아니라 오 년이에요.", "끊으신 지 5년으로 고쳐 둘게요. " + _N_HEAT,
      next_text=_N_HEAT, known="끊은 지 5년"),
    B("CORRECT", "Q8_1", "아니, 잘못 말했다. 힘든 운동은 사흘이야.", "일주일에 3일로 고쳐 둘게요. " + _N_HARD_T, next_text=_N_HARD_T,
      known="일주일에 3일"),
    B("CORRECT", "Q2.D02", "제가 착각했습니다. 협심증 있으신 분은 없습니다. 정정할게요.",
      "그런 분은 안 계신 걸로 고쳐 둘게요. 고혈압은 어떠세요? 부모님이나 형제자매 중에 앓으셨거나 그 병으로 돌아가신 분 계세요?",
      next_text=_F.format(d="고혈압"), known="앓은 분 없음"),
    B("CORRECT", "Q9_2", "아이다, 그 운동은 사십 분이라예. 잘못 말했어예.", "하루 40분으로 고쳐 둘게요. " + _N_STR, next_text=_N_STR,
      known="하루 40분"),
    B("CORRECT", "Q3", "음, 아니에요, 제가 잘못 말했어요. B형간염 보유자 아니에요.", "보유자가 아닌 걸로 고쳐 둘게요. 그럼 " + _N_Q4,
      next_text=_N_Q4, known="보유자 아님"),
    B("CORRECT", "Q4", "아 잘못 말했어요, 담배는 피운 적 없어요.", "담배는 안 피우신 걸로 고쳐 둘게요. 그럼 " + _N_HEAT, next_text=_N_HEAT,
      known="피운 적 없음"),
    B("CORRECT", "Q7_2", "아 네 병이에요, 다섯 병 아니고.", "네 병으로 고쳐 둘게요. 이제 운동 여쭤볼게요. " + _N_HARD, next_text=_N_HARD,
      known="소주 4병"),
    B("CORRECT", "Q6", "아니, 잘못 말했어요. 액상형 전자담배는 써 봤어요.", "써 보신 걸로 고쳐 둘게요. " + _N_LIQ_1, next_text=_N_LIQ_1,
      known="써 본 적 있음"),

    # ---------------- REASK: ask에 적힌 것만 다시 묻는다. 받은 값(known)은 짧게 인정해도 된다.
    B("REASK", "Q1.D04", "당뇨 진단받은 적 있어요.", "당뇨병 진단을 받으셨군요. 지금 약도 드세요?", next_type="SAME", next_text=_N_DIAB,
      reason="MISSING", known="진단 받음", ask="지금 당뇨병 약을 먹는지"),
    B("REASK", "Q1.D01", "음, 그러니까, 중풍이라고 진단받은 적 있어요.", "중풍 진단을 받으셨군요. 지금 약도 드시고 계세요?", next_type="SAME",
      next_text=_Q_D01, reason="MISSING", known="진단 받음", ask="지금 뇌졸중(중풍) 약을 먹는지"),
    B("REASK", "Q1.D10", "담배를 오래 피워서 그런지 몇 년 전에 만성폐쇄성폐질환이라고 하더라고요.", "그 진단을 받으셨군요. 지금 그 병으로 드시는 약도 있으세요?",
      next_type="SAME", reason="MISSING", known="진단 받음", ask="지금 만성폐쇄성폐질환 약을 먹는지"),
    B("REASK", "Q7", "세 번 마셔요.", "세 번이요, 일주일에 세 번인지 한 달에 세 번인지 알려 주시겠어요?", next_type="SAME", next_text=_Q_Q7,
      reason="MISSING", known="술 마심, 3번 (기준 기간은 아직 모름)", ask="3번이 일주일에·한 달에·1년에 중 어느 기준인지"),
    B("REASK", "Q7", "두 번 묵지예.", "두 번 드시는군요. 일주일에 두 번인지 한 달에 두 번인지 말씀해 주시겠어요?", next_type="SAME",
      reason="MISSING", known="술 마심, 2번 (기준 기간은 아직 모름)", ask="2번이 일주일에·한 달에·1년에 중 어느 기준인지"),
    B("REASK", "Q7_1", "와인 마시는 날은 병으로 마셔요.", "와인을 병으로 드시는군요. 보통 몇 병 드세요?", next_type="SAME", reason="MISSING",
      known="와인, 단위 병 (양은 아직 모름)", ask="술 마시는 날 평소에 와인을 몇 병 마시는지"),
    B("REASK", "Q7_1", "위스키를 잔 단위로 마십니다", "위스키 드시는군요. 보통 한 번 드실 때 몇 잔 정도 드세요?", next_type="SAME",
      reason="MISSING", known="양주(위스키 등), 단위 잔 (양은 아직 모름)", ask="술 마시는 날 평소에 양주(위스키 등)를 몇 잔 마시는지"),
    B("REASK", "Q7_2", "가장 많이 마신 날은 소주를 병으로 마셨습니다.", "그날은 소주를 병으로 드셨군요. 몇 병 드셨는지 알려 주시겠어요?", next_type="SAME",
      reason="MISSING", known="소주, 단위 병 (양은 아직 모름)", ask="가장 많이 마신 날 소주를 몇 병 마시는지"),
    B("REASK", "Q7_1", "소주 셋이요.", "소주 셋이면, 세 병인지 세 잔인지 알려 주시겠어요?", next_type="SAME", reason="MISSING",
      known="소주 3 (단위는 아직 모름)", ask="소주 3이 병·잔·캔 중 어느 단위인지"),
    B("REASK", "Q4_1", "예전에 피우다 끊었습니다. 십오 년 피웠고 하루에 열 개비 피웠어요.",
      "15년 동안 하루 10개비씩 피우시다가 끊으셨군요. 끊으신 지는 몇 년 되셨어요?", next_type="SAME", reason="MISSING",
      known="끊음, 피운 기간 15년, 하루 10개비", ask="끊은 지 몇 년 됐는지"),
    B("REASK", "Q4_1", "지금도 피워요. 오 년 됐어요.", "지금도 피우시고 5년 되셨군요. 하루에 몇 개비 피우세요?", next_type="SAME", reason="MISSING",
      known="지금 피움, 피운 기간 5년", ask="하루에 몇 개비 피우는지(피웠는지)"),
    B("REASK", "Q5_1", "아들이 사 줘서 지금도 써요. 하루에 열 개비 정도 피우고요.", "지금도 쓰시고 하루 열 개비쯤이시군요. 모두 몇 년 쓰셨어요?",
      next_type="SAME", reason="MISSING", known="지금 씀, 하루 10개비쯤", ask="모두 몇 년 썼는지"),
    B("REASK", "Q8_1", "일주일에 팔 일 해요.", "일주일은 7일이라서요, 일주일에 며칠 하시는지 다시 한번 말씀해 주시겠어요?", next_type="SAME",
      reason="OUT_OF_RANGE", ask="일주일은 7일이니 일주일 중 며칠인지 다시"),
    B("REASK", "Q8_2", "하루에 천오백 분 해요.", "하루가 24시간이라서요, 운동하시는 날 하루에 몇 시간이나 몇 분 하시는지 다시 말씀해 주시겠어요?",
      next_type="SAME", reason="OUT_OF_RANGE", ask="하루는 24시간이니 하루에 몇 시간·몇 분인지 다시"),
    B("REASK", "Q6_1", "한 달에 사십 일 썼어.", "한 달은 길어야 31일이라서요, 최근 한 달 동안 며칠 쓰셨는지 다시 한번 말씀해 주시겠어요?",
      next_type="SAME", reason="OUT_OF_RANGE", ask="한 달은 길어야 31일이니 최근 한 달 중 며칠인지 다시"),
    B("REASK", "Q10", "근력운동 아흐레했어요", "지난 일주일은 7일이라서요, 근력 운동을 며칠 하셨는지 다시 한번 말씀해 주시겠어요?", next_type="SAME",
      reason="OUT_OF_RANGE", ask="일주일은 7일이니 일주일 중 며칠인지 다시"),
    B("REASK", "Q7", "일주일에 열 번 마십니다.", "하루에 여러 번 드시는 날도 있으신 것 같은데요, 술 드신 날을 기준으로 일주일에 며칠 드시는지 말씀해 주시겠어요?",
      next_type="SAME", reason="COUNT_EXCEEDS_DAYS", known="술 마심", ask="술을 마신 날을 기준으로 그 기간에 며칠(몇 번) 마시는지"),
    B("REASK", "Q7", "음... 가끔 마셔요.", "가끔 드시는군요. 일주일이나 한 달에 몇 번 드시는지 숫자로 말씀해 주실 수 있을까요?", next_type="SAME",
      reason="VAGUE_QUANTITY", known="술 마심", ask="일주일이나 한 달에 몇 번인지 숫자로"),
    B("REASK", "Q10", "그건 그때그때 달라요, 손주 보느라 바쁘면 못 하고.", "그때그때 다르시군요. 지난 일주일만 놓고 보면 근력 운동을 며칠 하셨어요?",
      next_type="SAME", reason="VAGUE_QUANTITY", ask="최근 일주일 중 며칠인지 숫자로"),
    B("REASK", "Q8_1", "종종 해요.", "종종 하시는군요. 평소 일주일에 며칠 하시는지 숫자로 말씀해 주시겠어요?", next_type="SAME", reason="VAGUE_QUANTITY",
      ask="일주일에 며칠인지 숫자로"),
    B("REASK", "Q6_1", "한 달에 이틀에서 열이틀까지 들쭉날쭉하지예.", "이틀에서 열이틀까지 차이가 나시는군요. 최근 한 달만 보면 며칠 쓰셨는지 하나로 말씀해 주시겠어요?",
      next_type="SAME", reason="RANGE_SPANS_OPTIONS", ask="최근 한 달 동안 며칠 썼는지 하나의 숫자로"),
    B("REASK", "Q7_1", "소주 한 짝요.", "한 짝이면 양이 꽤 되는데요, 병이나 잔으로 치면 얼마나 드시는지 말씀해 주시겠어요?", next_type="SAME",
      reason="UNKNOWN_UNIT", known="소주 1 (단위는 아직 모름)", ask="소주를 병·잔·캔 같은 단위로 치면 얼마나인지"),
    B("REASK", "Q7_2", "맥주 한 짝 마셨어.", "한 짝이면 들어 있는 양이 달라서요, 병이나 캔으로 몇 개쯤 드셨는지 말씀해 주시겠어요?", next_type="SAME",
      reason="UNKNOWN_UNIT", known="맥주 1 (단위는 아직 모름)", ask="맥주를 병·잔·캔 같은 단위로 치면 얼마나인지"),

    # ---------------- CONFIRM: previous와 current를 짧게 짚고 어느 쪽이 맞는지 묻는다
    B("CONFIRM", "Q10", "근력 운동은 닷새 했어요.", "아까는 사흘 하셨다고 하셨는데요, 5일이 맞을까요?", next_type="SAME", reason="CONFLICT_WITH_PREVIOUS",
      ask="이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지", previous="최근 일주일 3일", current="최근 일주일 5일"),
    B("CONFIRM", "Q9_1", "그 운동은 엿새 해.", "앞에서는 일주일에 이틀이라고 하셨는데요, 6일이 맞으세요?", next_type="SAME", reason="CONFLICT_WITH_PREVIOUS",
      ask="이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지", previous="일주일에 2일", current="일주일에 6일"),
    B("CONFIRM", "Q1.D04", "당뇨병 진단은 받은 적 없습니다.", "앞에서는 당뇨병 진단을 받으셨다고 하셔서요. 진단받으신 적이 없는 게 맞을까요?", next_type="SAME",
      reason="CONFLICT_WITH_PREVIOUS", ask="이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지", previous="진단 받음", current="진단 안 받음"),
    B("CONFIRM", "Q2.D03", "그러고 보니 우리 형님이 고혈압 약을 드시지요.", "아까는 고혈압 있으신 분이 없다고 하셨는데요, 형님께서 고혈압이 있으신 게 맞을까요?",
      next_type="SAME", reason="CONFLICT_WITH_PREVIOUS", ask="이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지",
      previous="앓은 분 없음", current="앓은 분 있음"),
    B("CONFIRM", "Q5_1", "가열담배는육년썼어요", "앞에서는 7년 쓰셨다고 하셨는데요, 6년이 맞을까요?", next_type="SAME", reason="CONFLICT_WITH_PREVIOUS",
      ask="이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지", previous="쓴 기간 7년", current="쓴 기간 6년"),
    B("CONFIRM", "Q8_2", "음, 그 힘든 운동은요, 하루에 사십 분 해요.", "아까는 하루 30분이라고 하셨는데요, 40분이 맞으세요?", next_type="SAME",
      reason="CONFLICT_WITH_PREVIOUS", ask="이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지",
      previous="하루 30분", current="하루 40분"),
    B("CONFIRM", "Q7", "일주일에 다섯 번 마셔요.", "앞에서는 일주일에 두 번이라고 하셨는데요, 다섯 번이 맞을까요?", next_type="SAME",
      reason="CONFLICT_WITH_PREVIOUS", ask="이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지",
      previous="일주일에 2번", current="일주일에 5번"),
    B("CONFIRM", "Q3", "보유자 아니에요.", "아까는 보유자라고 하셨는데요, 보유자가 아닌 게 맞으세요?", next_type="SAME", reason="CONFLICT_WITH_PREVIOUS",
      ask="이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지", previous="보유자임", current="보유자 아님"),
    B("CONFIRM", "Q7_2", "한 병요.", "평소에는 소주 두 병 드신다고 하셨는데, 가장 많이 드신 날이 한 병이면 더 적어서요. 가장 많이 드신 날 양이 맞는지 다시 한번 말씀해 주시겠어요?",
      next_type="SAME", reason="CONFLICT_MAX_BELOW_USUAL", ask="가장 많이 마신 날의 양이 맞는지(평소보다 적게 나옴)",
      previous="평소 소주 2병", current="소주 1병"),
    B("CONFIRM", "Q7_2", "음... 두 캔이었나? 두 캔요.", "평소엔 맥주 네 캔 드신다고 하셨는데 가장 많이 드신 날이 두 캔이면 더 적어서요. 가장 많이 드신 날은 얼마나 드셨는지 한 번 더 말씀해 주시겠어요?",
      next_type="SAME", reason="CONFLICT_MAX_BELOW_USUAL", ask="가장 많이 마신 날의 양이 맞는지(평소보다 적게 나옴)",
      previous="평소 맥주 4캔", current="맥주 2캔"),

    # ---------------- HOLD (모름): 괜찮다고 하고 그 부분은 비워 둔 뒤 next.text를 묻는다. 같은 질문을 다시 묻지 않는다.
    B("HOLD", "Q3", "음... 그게요, 검사를 해 봤는지 기억이 안 나요.", "기억 안 나시면 괜찮아요, 그 부분은 비워 둘게요. 지금까지 담배를 다섯 갑 넘게 피워 보신 적 있으세요?",
      next_text=_N_Q4, reason="UNCERTAIN", hold="B형간염 보유 여부"),
    B("HOLD", "Q2.D01", "부모님 쪽은 그런 얘기를 들은 적이 없어서 잘 모르겠어요.",
      "잘 모르시면 괜찮아요, 비워 둘게요. 심근경색이나 협심증은 어떠세요? 부모님이나 형제자매 중에 앓으셨거나 그 병으로 돌아가신 분 계세요?",
      next_text=_F.format(d="심근경색이나 협심증"), reason="UNCERTAIN", hold="가족 중 뇌졸중(중풍)"),
    B("HOLD", "Q4_1", "몇 년 피웠는지는 모르겠어.", "기억 안 나시면 괜찮아요, 피운 기간은 비워 둘게요. " + _N_HEAT, next_text=_N_HEAT, reason="UNCERTAIN",
      hold="일반담배 중 피운 기간"),
    B("HOLD", "Q8_2", "잘 모르겠어요.", "괜찮아요, 그 부분은 비워 둘게요. " + _N_MOD, next_text=_N_MOD, reason="UNCERTAIN", hold="힘든 운동 하는 시간"),
    B("HOLD", "Q7_2", "그건기억안나요", "기억 안 나시면 괜찮아요. 비워 두고 넘어갈게요. 이제 운동 여쭤볼게요. " + _N_HARD, next_text=_N_HARD,
      reason="UNCERTAIN", hold="가장 많이 마신 날의 양"),
    B("HOLD", "Q1.D11", "진단을 받았는지 정확히 모르겠습니다.", "정확히 모르시면 괜찮아요, 비워 둘게요. 이제 가족 이야기예요. " + _F.format(d="뇌졸중"),
      next_text=_F.format(d="뇌졸중"), reason="UNCERTAIN", hold="암이나 그 밖의 병"),
    B("HOLD", "Q7_1", "뭘 마셨는지는 기억이 안 나고 두 병쯤 마셔요.", "어떤 술인지 기억 안 나시면 괜찮아요, 그 부분은 비워 둘게요. " + _Q_Q7_2,
      next_text=_Q_Q7_2, reason="BEVERAGE_MISSING", hold="평소 마시는 양"),

    # ---------------- SKIP (거절·나중에): 괜찮다고 하고 넘어간 뒤 next.text를 묻는다
    B("SKIP", "Q4_1", "그건 말 안 할래요.", "네, 말씀하기 불편하시면 넘어가도 괜찮아요. " + _N_HEAT, next_text=_N_HEAT, reason="REFUSED", hold="일반담배"),
    B("SKIP", "Q1.D07", "그 부분은 답변드리고 싶지 않습니다.", "네, 괜찮아요. 넘어갈게요. 조기정신증은 진단받으신 적 있으세요? 약도 드세요?",
      next_text="조기정신증은 진단받으신 적 있으세요? 약도 드세요?", reason="REFUSED", hold="우울증"),
    B("SKIP", "Q2.D01", "그건 말 안 해.", "네, 말씀 안 하셔도 괜찮아요. 심근경색이나 협심증은 어떠세요? 부모님이나 형제자매 중에 앓으셨거나 그 병으로 돌아가신 분 계세요?",
      next_text=_F.format(d="심근경색이나 협심증"), reason="REFUSED", hold="가족 중 뇌졸중(중풍)"),
    B("SKIP", "Q8_1", "음... 그건 좀 나중에 말씀드릴게요.", "네, 나중에 말씀해 주셔도 괜찮아요. 그럼 " + _N_MOD, next_text=_N_MOD, reason="REQUEST_SKIP",
      hold="힘든 운동 하는 날 수"),
    B("SKIP", "Q1.D05", "그건 이따 다시 얘기할게요.", "네, 이따 말씀해 주세요. 폐결핵은 진단받으신 적 있으세요? 약도 드세요?",
      next_text="폐결핵은 진단받으신 적 있으세요? 약도 드세요?", reason="REQUEST_SKIP", hold="이상지질혈증"),
    B("SKIP", "Q6_1", "그거는 쪼매 있다가 말할게예.", "네, 나중에 말씀해 주셔도 돼요. 이제 술 여쭤볼게요. " + _Q_Q7, next_text=_Q_Q7,
      reason="REQUEST_SKIP", hold="액상형 전자담배 쓴 날 수"),
    B("SKIP", "Q7", "술 얘기는 좀 안 하고 싶어요.", "네, 괜찮아요. 넘어갈게요. " + _Q_Q7_1, next_text=_Q_Q7_1, reason="REFUSED", hold="술 마시는 횟수"),

    # ---------------- REDIRECT: 환자 말에 한 문장으로 반응하고 next.text(지금 묻던 질문)로 돌아온다
    B("REDIRECT", "Q7", "이건 왜 물어보세요?", "건강검진 문진표에 들어가는 내용이라 여쭤보는 거예요. " + _Q_Q7, next_type="SAME", next_text=_Q_Q7,
      reason="ASK_PURPOSE"),
    B("REDIRECT", "Q2.D01", "가족 병까지 왜 말해야 돼?", "가족 중에 앓은 분이 있으면 검진 때 참고가 돼서 여쭤보는 거예요. " + _F.format(d="뇌졸중"),
      next_type="SAME", next_text=_F.format(d="뇌졸중"), reason="ASK_PURPOSE"),
    B("REDIRECT", "Q4_1", "이런 걸 다 적어서 어디에 쓰는 거예요? 보험 회사에 가는 건 아니지요?",
      "건강검진 문진표를 작성하는 데 쓰는 거예요. " + _Q_Q4_1, next_type="SAME", next_text=_Q_Q4_1, reason="ASK_PURPOSE"),
    B("REDIRECT", "Q3", "음... 이걸 꼭 말해야 하나요?", "문진표에 있는 항목이라 여쭤봤어요. 불편하시면 모른다고 하셔도 돼요. " + _N_HEPB, next_type="SAME",
      next_text=_N_HEPB, reason="ASK_PURPOSE"),
    B("REDIRECT", "Q8_2", "이 질문은 어떤 목적으로 하시는 건가요?", "평소 운동량을 문진표에 적으려고 여쭤보는 거예요. 힘든 운동 하시는 날은 하루에 얼마 동안 하세요?",
      next_type="SAME", next_text="그런 운동 하시는 날은 하루에 얼마 동안 하세요?", reason="ASK_PURPOSE"),
    B("REDIRECT", "Q7_1", "근데 오늘 검진 몇 시에 끝나요?", "끝나는 시간은 접수처에서 안내받으실 수 있어요. 문진부터 마저 할게요. " + _Q_Q7_1, next_type="SAME",
      next_text=_Q_Q7_1, reason="OFF_TOPIC"),
    B("REDIRECT", "Q9_1", "아 근데 주차는 어디다 해야 돼?", "주차가 신경 쓰이시는군요. 그건 이따 안내 데스크에서 확인해 보시고, 이것부터 여쭤볼게요. " + _N_MOD,
      next_type="SAME", next_text=_N_MOD, reason="OFF_TOPIC"),
    B("REDIRECT", "Q5", "오늘 날이 억수로 덥네예.", "오늘 정말 덥네요. 이어서 여쭤볼게요. " + _N_HEAT, next_type="SAME", next_text=_N_HEAT, reason="OFF_TOPIC"),
    B("REDIRECT", "Q1.D02", "아이고, 손주가 오늘 학교 시험이라 마음이 계속 쓰이네요.",
      "손주분 시험이라 신경이 쓰이시겠어요. 그럼 이어서 여쭤볼게요. " + _Q_D02, next_type="SAME", next_text=_Q_D02, reason="OFF_TOPIC"),
    B("REDIRECT", "Q6", "아근데 여기 화장실어디에요", "화장실은 문진 끝나고 안내해 드리는 분께 여쭤봐 주세요. 이것만 먼저 여쭤볼게요. " + _N_LIQ, next_type="SAME",
      next_text=_N_LIQ, reason="OFF_TOPIC"),
    B("REDIRECT", "Q1.D03", "저 허리 디스크가 있어요.", "허리 디스크가 있으시군요. 지금은 고혈압을 여쭤보고 있어요. " + _Q_D03, next_type="SAME",
      next_text=_Q_D03, reason="OUT_OF_SCHEMA"),
    B("REDIRECT", "Q8_1", "무릎이 안 좋아서 계단을 오르면 아파요.", "무릎이 불편하시군요. 그래도 하시는 운동이 있으면 여쭤볼게요. " + _N_HARD,
      next_type="SAME", next_text=_N_HARD, reason="OUT_OF_SCHEMA"),
    B("REDIRECT", "Q7", "저는 위염이 있어서 약을 먹고 있습니다.", "위염 약을 드시고 계시는군요. 그럼 술은 평소 얼마나 자주 드세요?", next_type="SAME",
      next_text=_Q_Q7, reason="OUT_OF_SCHEMA"),
    B("REDIRECT", "Q2.D04", "나 비염 있어.", "비염이 있으시군요. 지금은 가족력을 여쭤보고 있어요. " + _F.format(d="당뇨병"), next_type="SAME",
      next_text=_F.format(d="당뇨병"), reason="OUT_OF_SCHEMA"),
    B("REDIRECT", "Q10", "음, 요즘 어깨가 좀 결려서요.", "어깨가 결리시는군요. " + _N_STR, next_type="SAME", next_text=_N_STR, reason="OUT_OF_SCHEMA"),
    B("REDIRECT", "Q4", "요즘 밤에 잠을 통 못 자요.", "요즘 잠을 잘 못 주무시는군요. 문진부터 마저 할게요. " + _N_Q4, next_type="SAME", next_text=_N_Q4,
      reason="OUT_OF_SCHEMA"),
]

# 나쁜 응답 예: (나쁜 문장, 고친 문장, 이유). v1 데이터와 v1.17 파일럿에서 실제로 나온 문장이다.
BAD_B = [
    ("뇌졸중 진단을 받으셨다고 말씀해 주셨고, 현재는 약을 드시지 않는 상태라고 이해했습니다.", "뇌졸중 진단은 받으셨고 지금 약은 안 드시는군요.", "보고체"),
    ("1년 동안 하루 최대 음주량이 맥주 4병 정도라고 말씀하셨군요. 알겠습니다.", "가장 많이 드신 날은 맥주 4병이었군요.", "환자가 안 한 '정도' + 겹친 확인"),
    ("음주량을 5병으로 수정해 두었습니다. (환자는 5캔)", "카스 5캔으로 고쳐 둘게요.", "단위를 바꿈"),
    ("한 주에 두 병 정도의 와인을 드신다고 (가장 많이 마신 날 질문)", "가장 많이 드신 날은 와인 두 병이었군요.", "기간을 바꿈"),
    ("맥주 한 병 드시는군요. (환자는 '맥주 한 병에 세 캔 더')", "맥주 한 병에 세 캔 더 드시는군요.", "환자가 말한 양 일부를 빠뜨림"),
    ("심근경색이나 협심증 있으신 분이 없다고 고쳐 둘게요. (지금 문항은 뇌졸중)", "뇌졸중 앓은 분이 없는 걸로 고쳐 둘게요.", "다른 문항 이름을 말함(topic을 볼 것)"),
    ("이 부분은 넘어가겠습니다. 다음 질문 드리겠습니다.", "넘어갈게요. 그럼 고혈압은 진단받으신 적 있으세요?", "next.text를 묻지 않음"),
    ("중풍 진단을 받으셨다면 현재 약을 복용하고 계신지 여쭤보고 싶어요.", "중풍 진단을 받으셨군요. 지금 약도 드세요?", "조건문, 묻지 않음"),
    ("약은 드시는 거 맞죠? / 아버지가 그 병 있으셨나요?", "지금 약도 드세요? / 부모님이나 형제자매 중에 앓으신 분 계세요?", "답을 유도하는 질문"),
    ("이는 일주일의 날 수를 초과하는 수치이므로", "일주일은 7일이라서요", "설명조"),
    ("4일이요. 그렇다면…", "4일 하시는군요. 그럼…", "환자 말 복사"),
    ("알겠습니다! 잘 기억해 주셨어요. / 육십 개비 정도 피셨다니요.", "(빼기)", "감탄·칭찬"),
    ("위스키를 잔 단위로 마시시는군요.", "위스키 드시는군요.", "존댓말 오류('마시시는'), 단위 코드를 그대로 읽음"),
    ("가장 많이 마신 음주는 몇 잔 정도였나요?", "가장 많이 드신 날은 얼마나 드셨어요?", "next.text에 없는 단위를 넣음"),
    ("건강검진 문진표 작성 때문에 여쭤보는 거예요. (환자는 주차 이야기를 함)", "주차가 신경 쓰이시는군요. 이것부터 여쭤볼게요.", "환자 말에 반응하지 않음"),
    ("지난 일주일 동안 2일 하셨군요. 기록해 둘게요. (next.type END)", "2일 하셨군요. 이걸로 문진은 모두 끝났어요. 답해 주셔서 감사합니다.", "마무리 인사 없음"),
    ("안녕하세요. 문진을 시작하겠습니다. (START인데 질문 없음)", "안녕하세요. 문진표를 같이 작성해 볼게요. 먼저 뇌졸중 진단을 받으신 적 있으세요?", "첫 질문을 하지 않음"),
    ("아까는 조금 다르게 말씀하신 것 같아서요. (previous가 있는데 말하지 않음)", "아까는 하루 15분이라고 하셨는데요, 16분이 맞을까요?", "이전 값을 말하지 않아 모호함"),
]


# ================================================================ 프롬프트 문자열

def _ctx_line(ctx):
    if not ctx:
        return ""
    return f"(앞 대화: 상담원 \"{ctx[0]}\" -> 환자 \"{ctx[1]}\") "


def utterance_examples_text(pattern):
    """발화 생성 시스템 프롬프트에 붙일 예시: 말투 예시 + 같은 pattern 예시 전부 + 나쁜 예."""
    lines = ["[말투 예시] (값은 이번 메모와 다름, 그대로 쓰지 말 것)"]
    lines += [f"- {k}: {v}" for k, v in STYLE_EXAMPLES.items()]
    lines.append(f"- 질문과 관계없는 말: {OOS_STYLE_EXAMPLE}")
    lines.append("[이번 유형의 좋은 예] (문항·값은 이번 메모와 다름. 말투와 길이만 참고)")
    for e in UTT_EXAMPLES:
        if e.pattern == pattern:
            lines.append(f"- {_ctx_line(e.ctx)}상담원 \"{e.q}\" -> 환자({e.style}) \"{e.utt}\"")
    lines.append("[나쁜 예 -> 고친 예] (이렇게 쓰지 않는다)")
    lines += [f"- X \"{b}\" -> O \"{g}\" ({why})" for b, g, why in BAD_UTT]
    return "\n".join(lines)


def b_example_input(e):
    """예시 하나의 B 입력 요약(프롬프트·문서 표시용). 실제 입력의 주요 키만 보인다."""
    d = {"action": e.action}
    if e.reason:
        d["reason"] = e.reason
    if e.utt:
        d["user_utterance"] = e.utt
    if e.action != "START":
        d["known"] = e.known
    for k in ("ask", "previous", "current", "hold"):
        if getattr(e, k):
            d[k] = getattr(e, k)
    if e.next_type == "END":
        d["next"] = {"type": "END"}
    else:
        d["next"] = {"type": e.next_type, "text": e.next_text or "(질문 문장)"}
    return d


def response_examples_text(action, next_type=None):
    """B 응답 시스템 프롬프트에 붙일 예시: 같은 action 예시 전부(+ 마무리 예시) + 나쁜 예.
    next_type이 END이면 다른 action의 END 예시도 함께 넣어 마무리 말투를 보여 준다."""
    import json
    lines = [f"[{action} 좋은 예] (문항·값·다음 질문은 이번 입력과 다름. 말투와 구성만 참고)"]
    picked = [e for e in B_EXAMPLES if e.action == action]
    if next_type == "END":
        picked += [e for e in B_EXAMPLES if e.next_type == "END" and e.action != action]
    for e in picked:
        lines.append(f"- 입력 {json.dumps(b_example_input(e), ensure_ascii=False)} -> 상담원 \"{e.resp}\"")
    lines.append("[나쁜 예 -> 고친 예] (이렇게 쓰지 않는다)")
    lines += [f"- X \"{b}\" -> O \"{g}\" ({why})" for b, g, why in BAD_B]
    return "\n".join(lines)


def all_example_texts():
    """베끼기 검사용: 발화 예시·응답 예시·말투 예시 문장 전부."""
    out = [e.utt for e in UTT_EXAMPLES] + [e.resp for e in B_EXAMPLES]
    for v in STYLE_EXAMPLES.values():
        out += [x.strip() for x in v.split(" / ")]
    out.append(OOS_STYLE_EXAMPLE)
    return out
