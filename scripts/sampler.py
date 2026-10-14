"""canonical_scenario 샘플러: (문항, pattern, 번호) -> 고유 정답 시나리오 (데이터셋 v2, 2026-10-13 수정본).

v2 변경: 정정(P05)·충돌(P06 prev_diff)의 앞 상담원 턴은 '되짚기 + 다음 문항 질문'(파이프라인이 질문을 붙임),
충돌 r1(술 안 마심 + 음주량) 제외, 범위 밖 소재 확장, 문진표 밖 건강 이야기 요약(note).

원칙
- 정답(LoRA-A target)을 먼저 확정한다. 자연어 발화는 나중에 이 정답에 맞춰 생성한다.
- 값 축(주종·수량·단위·기간·범위·경계)과 구조 축(턴 수, 정정·충돌·참조 종류)을 고정 시드 난수로 뽑는다.
- normalization_result·transition_plan은 손으로 쓰지 않는다. 뽑은 정답을 정규화기(v1.0)에 실제로 돌려서
  나온 plan이 그 pattern에서 허용한 plan이 아니면 그 정답은 버리고 다른 하위 유형으로 다시 뽑는다.
- 발화 생성용 설명(spec)은 사람이 읽는 한국어 지시문이다. 각 fact에는 근거 키(k1, k2...)를 붙여서,
  생성 모델이 발화 안의 근거 구간을 키별로 돌려주게 한다.

출력(build_canonical): dict
  canonical_id, question_id, pattern_type, subtype, source(seed_derived/new_sampled), seed_id,
  prior_turns(이전 턴 설명), previous(정규화기 previous 형식), stored_state(사람이 읽는 저장 값),
  relevant_state(LoRA-A 입력용), target(정답 facts/intents/relations/unmapped_facts, 근거 없음),
  spec(생성 지시), expected(정규화기 결과, 근거 없음)
"""
import datetime
import hashlib
import random
import sqlite3

from common import CATALOG, DEFAULT_TODAY, NORMALIZER_ROOT, normalize, run_turn
from taxonomy import REF_SOURCE

TODAY = datetime.date.fromisoformat(DEFAULT_TODAY)
ALLOWED_PLANS = {
    "P01_normal": {"NEXT"},
    "P02_range_unit": {"NEXT", "ASK_CLARIFICATION"},
    "P03_partial": {"ASK_MISSING"},
    "P04_reask_fill": {"NEXT", "ASK_MISSING", "ASK_CLARIFICATION"},
    "P05_correction": {"ACK_CORRECTION"},
    "P06_conflict": {"ASK_CONFLICT"},
    "P07_prior_ref": {"NEXT"},
    "P08_unk_refuse": {"ASK_OR_HOLD", "HOLD_OR_SKIP"},
    "P09_oos": {"REDIRECT"},
    "P10_boundary": {"NEXT", "ASK_CLARIFICATION"},
    "P11_norm_case": {"NEXT", "ASK_MISSING", "ASK_CLARIFICATION", "ASK_CONFLICT", "REDIRECT"},
}
GROUPS = ("facts", "intents", "relations", "unmapped_facts")


def _subjects():
    db = NORMALIZER_ROOT / "dataset" / "db" / "questionnaire_reference.sqlite3"
    with sqlite3.connect(db) as conn:
        return {i: (s or "") for i, s in conn.execute(
            "SELECT item_id, subject_label FROM question_items WHERE version_id='national_health_2026_v1'")}


SUBJECT = _subjects()
TOBACCO = {"Q4": "일반담배(궐련)", "Q5": "궐련형 전자담배(가열담배)", "Q6": "액상형 전자담배",
           "Q4_1": "일반담배(궐련)", "Q5_1": "궐련형 전자담배(가열담배)", "Q6_1": "액상형 전자담배"}
STICK = {"Q4_1": "개비", "Q5_1": "개비(스틱)"}
# 2026-10-12 v1.17: 생성 메모의 활동 이름을 사람들이 실제로 하는 말로 바꿨다. '고강도 신체활동' 같은 문진표 낱말을 메모에
# 쓰면 발화가 그대로 따라 했다(u_form_words 가드 대상). 정답 값·칸에는 영향이 없다(메모 문구만).
ACTIVITY = {"Q8_1": "숨이 많이 찰 정도로 힘든 운동", "Q8_2": "숨이 많이 찰 정도로 힘든 운동",
            "Q9_1": "숨이 약간 찰 정도의 운동", "Q9_2": "숨이 약간 찰 정도의 운동", "Q10": "근력 운동"}
# 메모에 쓰는 질환 이름. DB의 subject_label('기타(암포함)', '심근경색/협심증')은 말로 옮기기 어색해서 메모용 이름을 따로 둔다.
SUBJECT_SAY = {"Q1.D02": "심근경색이나 협심증", "Q2.D02": "심근경색이나 협심증",
               "Q1.D11": "암이나 그 밖의 큰 병", "Q2.D05": "암이나 그 밖의 큰 병"}


def subj(item):
    """생성 메모용 질환 이름 (SUBJECT_SAY에 없으면 DB 이름)."""
    return SUBJECT_SAY.get(item) or SUBJECT[item]
BEVERAGES = {  # 생성에 쓰는 원래 술 이름 -> (자주 쓰는 단위 후보)
    "소주": ["병", "잔"], "참이슬": ["병"], "처음처럼": ["병"], "맥주": ["캔", "병", "잔", "cc"],
    "생맥주": ["잔", "cc"], "카스": ["병", "캔"], "막걸리": ["병", "잔"], "와인": ["잔", "병"],
    "레드와인": ["잔"], "양주": ["잔"], "위스키": ["잔"],
}
AMOUNT_POOL = {"병": [0.5, 1, 1.5, 2, 3, 4], "잔": [1, 2, 3, 4, 5, 7, 10], "캔": [1, 2, 3, 4, 6],
               "cc": [300, 500, 1000, 1500, 2000]}
REASON = "STORED"   # relevant_state 사유: 정정·충돌 여부를 미리 알려주지 않도록 중립 이름만 쓴다


# ================================================================ 기본 도구

def F(item, field, value, precision="exact", status="ANSWERED", say=""):
    """정답 fact 하나. say는 생성 모델에게 줄 한국어 설명(근거 키는 build 단계에서 붙인다)."""
    return {"item_id": item, "field": field, "value": value, "precision": precision,
            "semantic_status": status, "_say": say}


def labels(facts=(), intents=(), relations=(), unmapped=()):
    return {"facts": list(facts), "intents": list(intents), "relations": list(relations),
            "unmapped_facts": list(unmapped)}


def strip_say(lab):
    """생성 설명(_say)을 뺀 정규화기 입력용 복사본."""
    return {g: [{k: v for k, v in e.items() if not k.startswith("_")} for e in lab[g]] for g in GROUPS}


def n_ko(x):
    """설명문에 쓰는 숫자 표기 (0.5 -> 0.5, 2.0 -> 2)."""
    return str(int(x)) if float(x).is_integer() else str(x)


def approx_say(precision):
    return {"approximate": " (어림 표현으로: '쯤', '정도', '대략' 등)",
            "range": " (범위로 말함)"}.get(precision, "")


FIELD_KO = {"on_medication": "현재 약을 먹는지 안 먹는지", "total_years": "피운 기간(몇 년)",
            "daily_count": "하루에 피우는 양(개비 수)", "years_since_quit": "끊은 지 얼마나 됐는지",
            "unit": "기간 단위(일주일에/한 달에/1년에)", "amount": "마시는 양(숫자)", "beverage": "술 종류"}


def silent_ko(item, field):
    """말하지 않을 칸의 사람이 읽는 설명. 필드 이름(on_medication 등)을 생성 모델에 그대로 보이지 않는다."""
    name = field.split(".")[-1]
    if item in ("Q7_1", "Q7_2") and name == "unit":
        return "단위(병·잔·캔 등)"
    return FIELD_KO.get(name, name)


# ================================================================ 문항별 값 축 (정상 답)

def normal_facts(item, rng, precision="exact"):
    """정상 답(전 칸 응답) facts. precision='approximate'면 숫자 칸 하나를 어림 표현으로 만든다."""
    if item.startswith("Q1."):
        d = rng.random() < 0.6
        m = d and rng.random() < 0.6
        return [F(item, "diagnosed", d, say=f"{subj(item)} 진단을 받은 적이 {'있다' if d else '없다'}"),
                F(item, "on_medication", m,
                  say=f"현재 {subj(item)} 약을 {'먹고 있다' if m else '먹지 않는다'}")]
    if item.startswith("Q2."):
        v = rng.random() < 0.5
        who = rng.choice(["어머니", "아버지", "형제자매 중 한 명", "부모님 중 한 분"])
        return [F(item, "family_history", v,
                  say=(f"{who}가 앓은 병: {subj(item)} (부모·형제자매만 언급)" if v
                       else f"부모님이나 형제자매 중에 {subj(item)} 앓은 사람은 없다"))]
    if item == "Q3":
        v = rng.choice(["yes", "no", "unknown"])
        say = {"yes": "B형간염 바이러스 보유자라고 들었다", "no": "B형간염 보유자가 아니다",
               "unknown": "B형간염 보유자인지 검사해 본 적이 없어 모른다"}[v]
        return [F(item, "answer", v, say=say)]
    if item in ("Q4", "Q5", "Q6"):
        v = rng.random() < 0.5
        return [F(item, "answer", v, say=f"평생 {TOBACCO[item]}를 {'피우거나 써 본 적이 있다' if v else '피우거나 써 본 적이 전혀 없다'}")]
    if item in ("Q4_1", "Q5_1"):
        cur = rng.random() < 0.5
        years = rng.choice([1, 2, 3, 5, 8, 10, 12, 15, 20, 25, 30])
        count = rng.choice([1, 2, 3, 5, 7, 10, 12, 15, 20, 25])
        fs = [F(item, "status", "current" if cur else "former",
                say=f"{TOBACCO[item]}를 {'지금도 피운다' if cur else '예전에 피웠지만 지금은 끊었다'}"),
              F(item, "total_years", years, say=f"{years}년 동안 피웠다")]
        fs.append(F(item, "daily_count", count, say=f"하루 평균 {count}{STICK[item]}"))
        if not cur:
            q = rng.choice([0.5, 1, 2, 3, 5, 7, 10])
            fs.append(F(item, "years_since_quit", q, say=f"끊은 지 {n_ko(q)}년 (0.5년이면 '반년'이라고 말해도 됨)"))
        if precision == "approximate":
            fs[2]["precision"] = "approximate"
            fs[2]["_say"] += approx_say("approximate")
        return fs
    if item == "Q6_1":
        d = rng.choice([1, 2, 4, 6, 8, 12, 15, 20, 25])
        f = F(item, "usage_days", d, say=f"최근 한 달 동안 액상형 전자담배를 쓴 날이 {d}일")
        if precision == "approximate":
            f["precision"] = "approximate"
            f["_say"] += approx_say("approximate")
        return [f]
    if item == "Q7":
        if rng.random() < 0.2:
            return [F(item, "does_not_drink", True, say="지난 1년 동안 술을 전혀 마시지 않았다")]
        unit = rng.choice(["week", "week", "month", "year"])
        freq = {"week": [1, 2, 3, 4, 5], "month": [1, 2, 3, 4, 6, 8], "year": [2, 3, 5, 6, 10]}[unit]
        n = rng.choice(freq)
        word = {"week": "일주일에", "month": "한 달에", "year": "1년에"}[unit]
        f = F(item, "frequency", n, say=f"술은 {word} {n}번 정도 마신다" if precision == "approximate"
              else f"술은 {word} {n}번 마신다")
        if precision == "approximate":
            f["precision"] = "approximate"
        return [F(item, "does_not_drink", False, say="술을 마신다"), f,
                F(item, "unit", unit, say=f"기간 단위는 '{word}'")]
    if item in ("Q7_1", "Q7_2"):
        return amount_facts(item, rng, k=1, precision=precision)
    if item in ("Q8_1", "Q9_1", "Q10"):
        d = rng.choice([1, 2, 3, 4, 5, 6])
        f = F(item, "answer", d, say=f"일주일 중 {ACTIVITY[item]}를 하는 날이 {d}일")
        if precision == "approximate":
            f["precision"] = "approximate"
            f["_say"] += approx_say("approximate")
        return [f]
    if item in ("Q8_2", "Q9_2"):
        m = rng.choice([10, 15, 20, 30, 40, 45, 50, 60, 90, 120])
        f = F(item, "minutes", m, say=f"{ACTIVITY[item]}를 하는 날 하루에 {m}분 (60분 이상이면 '1시간' 같은 표현 금지, 분으로만)")
        if precision == "approximate":
            f["precision"] = "approximate"
            f["_say"] += approx_say("approximate")
        return [f]
    raise ValueError(item)


def amount_facts(item, rng, k=1, precision="exact", beverages=None):
    """Q7_1·Q7_2 음주량: 술 k종 x (술 이름, 양, 단위). 원래 술 이름·단위를 그대로 원시 값으로 둔다."""
    when = "평소 술 마시는 날 하루에" if item == "Q7_1" else "지난 1년 중 가장 많이 마신 날 하루에"
    names = beverages or rng.sample(sorted(BEVERAGES), k)
    fs = []
    for i, name in enumerate(names):
        unit = rng.choice(BEVERAGES[name])
        amt = rng.choice(AMOUNT_POOL[unit])
        p = precision if i == 0 else "exact"
        fs += [F(item, f"amounts[{i}].beverage", name, say=f"술 종류: {name}"),
               F(item, f"amounts[{i}].amount", amt, precision=p,
                 say=f"{when} {name} {n_ko(amt)}{unit}{approx_say(p)}"),
               F(item, f"amounts[{i}].unit", unit, say=f"단위: {unit}")]
    return fs


# ================================================================ pattern별 하위 유형

def pat_normal(item, rng):
    return {"subtype": "normal", "target": labels(normal_facts(item, rng))}


def pat_range_unit(item, rng):
    """범위·근사·단위·혼합. 일부 하위 유형은 ASK_CLARIFICATION(구간 3칸 걸침, 막연한 양, 모르는 단위)."""
    options = ["approximate", "range"]
    if item in ("Q7_1", "Q7_2"):
        options += ["multi_beverage", "mixed_unit_same_beverage", "unknown_unit"]
    if item in ("Q8_2", "Q9_2"):
        options += ["hours_minutes", "hours_only"]
    if item == "Q6_1":
        options += ["range_cross_options"]
    if item in ("Q7", "Q8_1", "Q9_1", "Q10"):   # 흡연 개비 수의 '여러 번'은 레이블 규약이 불분명해 제외(파일럿 1차)
        options += ["vague"]
    sub = rng.choice(options)
    if sub == "approximate":
        return {"subtype": sub, "target": labels(normal_facts(item, rng, precision="approximate"))}
    if sub == "range":
        fs = normal_facts(item, rng)
        num = [f for f in fs if isinstance(f["value"], (int, float)) and not isinstance(f["value"], bool)
               and f["field"] not in ("years_since_quit",)]
        if not num:
            return None
        f = rng.choice(num)
        lo = f["value"]
        hi = lo + (rng.choice([1, 2]) if lo < 10 else rng.choice([5, 10]) if lo < 100 else lo // 2)
        if item in ("Q8_1", "Q9_1", "Q10") and hi > 7:
            lo, hi = 5, 6
        f["value"], f["precision"] = f"{n_ko(lo)}~{n_ko(hi)}", "range"
        f["_say"] = f["_say"].replace(n_ko(f["_say"] and lo), f"{n_ko(lo)}~{n_ko(hi)}", 1) + " (범위로 말함)"
        return {"subtype": sub, "target": labels(fs)}
    if sub == "multi_beverage":
        return {"subtype": sub, "target": labels(amount_facts(item, rng, k=2))}
    if sub == "mixed_unit_same_beverage":
        name = rng.choice(["소주", "맥주"])
        when = "평소 술 마시는 날 하루에" if item == "Q7_1" else "가장 많이 마신 날 하루에"
        u1, u2 = ("병", "잔") if name == "소주" else ("병", "캔")
        a1, a2 = rng.choice([1, 2]), rng.choice([1, 2, 3])
        fs = [F(item, "amounts[0].beverage", name, say=f"술 종류: {name}"),
              F(item, "amounts[0].amount", a1, say=f"{when} {name} {a1}{u1}에"),
              F(item, "amounts[0].unit", u1, say=f"단위: {u1}"),
              F(item, "amounts[1].beverage", name, say=f"같은 {name}"),
              F(item, "amounts[1].amount", a2, say=f"{name} {a2}{u2}를 더 마신다"),
              F(item, "amounts[1].unit", u2, say=f"단위: {u2}")]
        return {"subtype": sub, "target": labels(fs)}
    if sub == "unknown_unit":
        name = rng.choice(["맥주", "소주"])
        fs = [F(item, "amounts[0].beverage", name, say=f"술 종류: {name}"),
              F(item, "amounts[0].amount", 1, say=f"{name} 한 짝 (상자 단위)"),
              F(item, "amounts[0].unit", "짝", say="단위: 짝")]
        return {"subtype": sub, "target": labels(fs)}
    if sub == "hours_minutes":
        h, m = rng.choice([1, 2]), rng.choice([10, 15, 20, 30, 40])
        # 시간·분을 따로 메모하면 '1시간 정도, 그중 10분'처럼 나눠 말하는 오류가 많아 한 메모로 준다.
        return {"subtype": sub, "target": labels([
            F(item, "hours", h, say=f"{ACTIVITY[item]}를 하는 날 하루에 모두 {h}시간 {m}분 ('{h}시간 {m}분'을 한 덩어리로 말함)"),
            F(item, "minutes", m, say=f"(앞 메모의 {m}분)")])}
    if sub == "hours_only":
        h = rng.choice([1, 2, 3])
        return {"subtype": sub, "target": labels([F(item, "hours", h, say=f"{ACTIVITY[item]}를 하는 날 하루 {h}시간")])}
    if sub == "range_cross_options":
        lo, hi = rng.choice([(1, 15), (2, 12), (5, 20)])
        return {"subtype": sub, "target": labels([F(item, "usage_days", f"{lo}~{hi}", precision="range",
                                                       say=f"최근 한 달 동안 액상형 전자담배를 쓴 날이 {lo}일에서 {hi}일 사이 (범위로 말함)")])}
    if sub == "vague":
        field = {"Q7": "frequency", "Q4_1": "daily_count", "Q5_1": "daily_count"}.get(item, "answer")
        word = rng.choice(["가끔", "종종", "여러 번", "그때그때 다르게"])
        fs = [F(item, field, word, precision="approximate", say=f"숫자 없이 '{word}'처럼 막연하게 말함")]
        if item == "Q7":
            fs = [F(item, "does_not_drink", False, say="술을 마신다")] + fs
        if item in ("Q4_1", "Q5_1"):
            fs = [F(item, "status", "current", say=f"{TOBACCO[item]}를 지금 피운다"),
                  F(item, "total_years", rng.choice([3, 5, 10]), say="피운 기간 (숫자로)")] + fs
            fs[1]["_say"] = f"{fs[1]['value']}년 동안 피웠다"
        return {"subtype": sub, "target": labels(fs)}
    return None


def pat_partial(item, rng):
    """부분 응답: 칸 하나 이상을 말하지 않음(MISSING, value null)."""
    fs = normal_facts(item, rng)
    if item.startswith("Q1."):
        fs[0].update(value=True, _say=f"{subj(item)} 진단을 받은 적이 있다")
        drop = [1]
    elif item == "Q7":
        fs = normal_facts(item, rng)
        while len(fs) < 3:
            fs = normal_facts(item, rng)
        drop = [2]
        fs[1]["_say"] = f"술은 {n_ko(fs[1]['value'])}번 마신다 (일주일에/한 달에 같은 기간은 말하지 않음)"
    elif item in ("Q7_1", "Q7_2"):
        drop = [rng.choice([1, 2])]
    elif item in ("Q4_1", "Q5_1"):
        drop = [rng.choice(range(1, len(fs)))]
    else:
        return None
    for i in drop:
        fs[i].update(value=None, precision="unspecified", semantic_status="MISSING",
                     _say=f"{silent_ko(item, fs[i]['field'])}는 말하지 않는다 (있다/없다·숫자 모두 언급 금지)")
    if item in ("Q7_1", "Q7_2") and drop == [2]:
        fs[1]["_say"] = f"{fs[0]['value']} {n_ko(fs[1]['value'])} (단위 없이 숫자만)"
    if item in ("Q7_1", "Q7_2") and drop == [1]:
        fs[2]["_say"] = f"{fs[0]['value']}를 {fs[2]['value']} 단위로 마신다고만 하고 양은 말하지 않음"
    return {"subtype": f"missing_{fs[drop[0]]['field']}", "target": labels(fs)}


def pat_unknown_refuse(item, rng):
    # ASK_OR_HOLD(모름)와 HOLD_OR_SKIP(거절·보류)이 각각 plan 하한 3%를 넘도록 모름을 절반으로 둔다.
    sub = rng.choices(["uncertain", "refused", "skip"], weights=[2, 1, 1])[0]
    if sub == "uncertain":
        fields = [f["field"] for f in normal_facts(item, random.Random(0)) if f["field"] != "does_not_drink"]
        if item.startswith("Q1."):
            fields = ["diagnosed", "on_medication"]
        fs = [F(item, fd, None, "unspecified", "UNCERTAIN", say="잘 모른다/기억이 안 난다고 말함")
              for fd in fields[:1 if item in ("Q7_1", "Q7_2", "Q4_1", "Q5_1", "Q7") else 2]]
        return {"subtype": sub, "target": labels(fs)}
    intent = {"refused": "REFUSED", "skip": "REQUEST_SKIP"}[sub]
    say = {"REFUSED": "이 질문에는 답하고 싶지 않다고 말함", "REQUEST_SKIP": "이 질문은 나중에 답하겠다고 말함"}[intent]
    return {"subtype": sub, "target": labels(intents=[{"item_id": item, "intent": intent, "_say": say}])}


# 범위 밖 이야기 소재 (2026-10-13 v2: 소재를 구체적으로 정해 줘서 B가 그 말에 맞게 반응하는 예를 늘린다)
PURPOSE_SAY = ["이 질문을 왜 하는지 되묻는다", "이런 걸 꼭 말해야 하는지 묻는다", "이 내용을 어디에 쓰는지 묻는다",
               "가족 이야기나 술·담배 이야기까지 왜 필요한지 묻는다", "이 질문이 검진이랑 무슨 상관인지 묻는다"]
OFF_TOPICS = ["오늘 날씨(덥다·춥다·비가 온다)", "주차를 어디에 해야 하는지", "검진이 몇 시에 끝나는지", "화장실이 어디인지",
              "대기 시간이 길다는 불평", "출근길 지하철이 붐볐던 일", "손주·자녀 이야기", "점심을 뭘 먹을지",
              "어제 본 드라마", "검진 끝나고 바로 회사에 가야 한다는 것", "휴대폰 배터리가 없다는 것", "버스를 잘못 탔던 일"]
OOS_HEALTH = ["고양이 알레르기", "요즘 잠을 잘 못 잠", "무릎이 가끔 아픔", "커피를 하루 세 잔 마심", "허리 디스크",
              "비염", "위염 약을 먹음", "어깨가 결림", "눈이 침침함", "두통이 자주 있음", "소화가 잘 안 됨", "변비가 있음",
              "손발이 저림", "피부가 가려움", "치과 치료 중", "건강기능식품(비타민)을 먹음", "다이어트 중", "귀에서 소리가 남"]


def pat_oos(item, rng):
    sub = rng.choice(["ask_purpose", "off_topic", "out_of_schema"])
    if sub == "ask_purpose":
        return {"subtype": sub, "target": labels(intents=[{"item_id": item, "intent": "ASK_PURPOSE",
                                                           "_say": rng.choice(PURPOSE_SAY) + " (답은 하지 않음)"}])}
    if sub == "off_topic":
        topic = rng.choice(OFF_TOPICS)
        return {"subtype": sub, "target": labels(intents=[{"item_id": item, "intent": "OFF_TOPIC",
                                                           "_say": f"문진과 상관없는 이야기를 함: {topic}"}])}
    topic = rng.choice(OOS_HEALTH)
    return {"subtype": sub, "note": topic,
            "target": labels(unmapped=[{"scope": "OUT_OF_SCHEMA", "_say": f"질문과 상관없이 '{topic}'라는 내 건강 이야기를 꺼냄"}])}


BOUNDARY = {
    "Q8_1": ("answer", [7], [8, 10]), "Q9_1": ("answer", [7], [8, 9]), "Q10": ("answer", [7, 0], [8, 14]),
    "Q8_2": ("minutes", [1, 300], [1500, 2000]), "Q9_2": ("minutes", [1, 240], [1500, 1800]),
    "Q6_1": ("usage_days", [30, 31, 29], [32, 40]),
    "Q4_1": ("daily_count", [40, 60], []), "Q5_1": ("daily_count", [40], []),
}


def pat_boundary(item, rng):
    """경계값(범위 끝, NEXT) 또는 범위 밖(ASK_CLARIFICATION). Q7은 주 8회 같은 R2 초과."""
    if item == "Q7":
        inside = rng.random() < 0.3
        unit = rng.choice(["week", "month"])
        n = (7 if unit == "week" else 30) if inside else (rng.choice([8, 10]) if unit == "week" else rng.choice([32, 40]))
        word = {"week": "일주일에", "month": "한 달에"}[unit]
        return {"subtype": "edge_in" if inside else "out_of_range", "target": labels([
            F(item, "does_not_drink", False, say="술을 마신다"),
            F(item, "frequency", n, say=f"술은 {word} {n}번 마신다"),
            F(item, "unit", unit, say=f"기간 단위는 '{word}'")])}
    if item in ("Q7_1", "Q7_2"):
        name = rng.choice(["소주", "맥주"])
        amt = rng.choice([10, 15, 20]) if name == "소주" else rng.choice([10, 12])
        return {"subtype": "large_amount", "target": labels([
            F(item, "amounts[0].beverage", name, say=f"술 종류: {name}"),
            F(item, "amounts[0].amount", amt, say=f"{name} {amt}병 (아주 많은 양)"),
            F(item, "amounts[0].unit", "병", say="단위: 병")])}
    if item not in BOUNDARY:
        return None
    field, ins, outs = BOUNDARY[item]
    inside = not outs or rng.random() < 0.3
    v = rng.choice(ins if inside else outs)
    say = {"answer": f"일주일 중 {ACTIVITY.get(item, '')}를 하는 날이 {v}일",
           "minutes": f"{ACTIVITY.get(item, '')}를 하는 날 하루에 {v}분 (분으로만 말함)",
           "usage_days": f"최근 한 달 동안 액상형 전자담배를 쓴 날이 {v}일",
           "daily_count": f"하루 평균 {v}{STICK.get(item, '개비')}"}[field]
    fs = [F(item, field, v, say=say)]
    if item in ("Q4_1", "Q5_1"):
        fs = [F(item, "status", "current", say=f"{TOBACCO[item]}를 지금 피운다"),
              F(item, "total_years", rng.choice([10, 20, 30]), say="피운 기간 (년, 숫자로)")] + fs
        fs[1]["_say"] = f"{fs[1]['value']}년 동안 피웠다"
    return {"subtype": "edge_in" if inside else "out_of_range", "target": labels(fs)}


# ---------------------------------------------------------------- 다중 턴 pattern

def _stored(prior_labels, previous=None):
    """이전 턴 정답 -> (정규화기 previous, 사람이 읽는 저장 값). 확정(CONFIRMED) 행만 남긴다."""
    previous = dict(previous or {})
    res = normalize(strip_say(prior_labels), CATALOG, previous, today=TODAY)
    for r in res.records:
        if r.resolution_status == "CONFIRMED":
            previous[(r.field_id, r.repeat_key)] = r.value
    return previous


def state_key(field_id, repeat_key):
    item, field = field_id.rsplit(".", 1)
    return f"{item}/{repeat_key + '.' if repeat_key else ''}{field}"


def relevant(previous, items, reason=REASON):
    """LoRA-A 입력용 relevant_state: 지정한 문항의 저장 값만. 최근 N턴 전체를 넣지 않는다."""
    out = {}
    for (fid, key), v in sorted(previous.items()):
        if fid.rsplit(".", 1)[0] in items:
            fdef = CATALOG.fields.get(fid)
            if fdef is not None and fdef.data_type == "boolean" and v is not None:
                v = bool(v)   # DB는 예/아니요를 1/0으로 저장하므로 입력에는 true/false로 보여 준다
            out[state_key(fid, key)] = {"value": v, "semantic_status": "ANSWERED", "reason": reason}
    return out


def pat_reask_fill(item, rng):
    """재질문 -> 보완. 1턴: 부분·모호한 답 / 상담자 재질문 / 2턴(target): 빠진 정보만 보완."""
    if item.startswith("Q1.") or item in ("Q7", "Q4_1", "Q5_1", "Q7_1", "Q7_2"):
        p = pat_partial(item, rng)
        if not p:
            return None
        first = p["target"]
        missing = [f for f in first["facts"] if f["semantic_status"] == "MISSING"]
        full = {f["field"]: f for f in normal_facts(item, rng)}
        fill = []
        for f in missing:
            nf = dict(full.get(f["field"]) or {})
            if not nf:
                return None
            if item.startswith("Q1."):
                m = rng.random() < 0.5
                nf.update(value=m, _say=f"(보완) 약은 {'먹고 있다' if m else '먹지 않는다'}")
            elif item in ("Q7_1", "Q7_2"):
                # 음주량 보완: 사람들은 "소주 두 병이요"처럼 술·양·단위를 한 번에 다시 말하므로 묶음 전체를 정답으로 둔다.
                bev = first["facts"][0]["value"]
                amt_f, unit_f = first["facts"][1], first["facts"][2]
                u = unit_f["value"] if unit_f["value"] is not None else rng.choice(BEVERAGES.get(bev, ["병"]))
                a = amt_f["value"] if amt_f["value"] is not None else rng.choice(AMOUNT_POOL.get(u, [1, 2]))
                fill += [F(item, "amounts[0].beverage", bev, say=f"(보완) 술 종류: {bev}"),
                         F(item, "amounts[0].amount", a, say=f"(보완) {bev} {n_ko(a)}{u} (양과 단위를 함께)"),
                         F(item, "amounts[0].unit", u, say=f"단위: {u}")]
                break
            else:
                nf["_say"] = "(보완) " + nf["_say"]
            if item not in ("Q7_1", "Q7_2"):
                fill.append(nf)
        prior = [{"role": "user", "labels": first, "describe": "처음 답: 일부 정보를 빠뜨림"},
                 {"role": "assistant", "describe": "상담자가 빠진 정보만 짧게 다시 물음: "
                  + ", ".join(FIELD_KO.get(f["field"].split(".")[-1], f["field"]) for f in missing)}]
        previous = _stored(first)
        rel = relevant(previous, {item})
        for f in missing:
            rel[f"{item}/{f['field']}"] = {"value": None, "semantic_status": "MISSING", "reason": "REASK_TARGET"}
        return {"subtype": "fill_missing", "prior": prior, "previous": previous, "relevant_state": rel,
                "target": labels(fill)}
    # 한 칸 문항: 1턴 모호(가끔 등) -> 재질문 -> 2턴 정확한 값
    full = normal_facts(item, rng)
    if len(full) != 1 and item not in ("Q8_2", "Q9_2"):
        return None
    # 모호한 첫 답은 P02 vague와 같은 규약: 말한 표현을 value 문자열로 두고 판정은 정규화기에 맡긴다.
    word = rng.choice(["가끔", "그때그때 달라요", "조금"])
    first = labels([F(item, full[0]["field"], word, "approximate", "ANSWERED", say=f"'{word}'처럼 숫자 없이 모호하게 답함")])
    prior = [{"role": "user", "labels": first, "describe": "처음 답: 모호함"},
             {"role": "assistant", "describe": "상담자가 구체적으로 다시 물음"}]
    full[0]["_say"] = "(보완) " + full[0]["_say"]
    rel = {f"{item}/{full[0]['field']}": {"value": None, "semantic_status": "AMBIGUOUS", "reason": "REASK_TARGET"}}
    return {"subtype": "clarify_vague", "prior": prior, "previous": {}, "relevant_state": rel, "target": labels(full)}


def _changed_value(f, rng):
    """정정·충돌용으로 같은 칸의 다른 값을 고른다."""
    v = f["value"]
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)):
        cands = [x for x in (v + 1, v + 2, v - 1, v * 2) if x > 0 and x != v]
        if f["item_id"] in ("Q8_1", "Q9_1", "Q10"):
            cands = [x for x in range(0, 8) if x != v]
        return rng.choice(cands)
    if f["field"] == "status":
        return "former" if v == "current" else "current"
    if f["item_id"] == "Q3":
        return rng.choice([x for x in ("yes", "no") if x != v])
    if f["field"] == "unit" and f["item_id"] == "Q7":
        return rng.choice([x for x in ("week", "month") if x != v])
    return None


def _main_fact(fs):
    """정정·충돌 대상이 될 대표 칸(숫자 칸 우선)."""
    for f in fs:
        if f["field"].endswith("amount") or f["field"] in ("frequency", "answer", "minutes", "usage_days",
                                                              "daily_count", "total_years", "family_history"):
            return f
    return fs[-1] if fs[-1]["field"] != "does_not_drink" else fs[0]


def pat_correction(item, rng):
    """정정: 1턴 값 a 저장 -> 2턴(target) 정정 표지어와 함께 새 값 b. A 정답은 새 값 + CORRECTION 관계."""
    first_facts = normal_facts(item, rng)
    if item == "Q7" and len(first_facts) == 1:
        return None
    first = labels(first_facts)
    f = _main_fact(first_facts)
    new = _changed_value(f, rng)
    if new is None:
        return None
    nf = dict(f, value=new, precision="exact", _say="")
    old_txt = f["_say"]
    nf["_say"] = (f"앞서 '{describe(item, f['field'], f['value'])}'라고 했던 것을 정정 표현('아니라', '잘못 말했', '정정' 등)과 함께 "
                  f"'{describe(item, f['field'], new)}'로 바꿈")
    facts = [nf]
    if item in ("Q7_1", "Q7_2"):
        g = f["field"].split(".")[0]
        facts = [dict(x) for x in first_facts if x["field"].startswith(g) and x is not f]
        facts.insert(1, nf)
        for x in facts:
            if x is not nf:
                x["_say"] = "(정정 문장 안에서 함께 말함) " + x["_say"]
    rel = {"item_id": item, "relation": "CORRECTION",
           "correction_target": {"item_id": item, "field": f["field"],
                                 "state_key": None},  # build 단계에서 previous 키로 채운다
           "_say": "정정한다는 표현 (예: '아 잘못 말했어요', '~가 아니라')"}
    previous = _stored(first)
    prior = [{"role": "user", "labels": first, "describe": f"처음 답: {old_txt}"},
             {"role": "assistant", "describe": "상담자가 방금 들은 값을 짧게 되짚음(예: '네, 일주일에 세 번이요.'). 질문하지 않음 "
                                              "(그 뒤에 다음 문항 질문이 붙는다)"}]
    return {"subtype": "correction", "prior": prior, "previous": previous,
            "relevant_state": relevant(previous, {item}), "target": labels(facts, relations=[rel])}


def describe(item, field, value):
    """칸과 값 -> 생성용 한국어 메모. 정정·충돌에서 '예'만 적으면 무엇에 대한 답인지 모르므로 칸 뜻을 함께 쓴다."""
    name = field.split(".")[-1]
    yes = value is True
    if name == "diagnosed":
        return f"{subj(item)} 진단: {'받은 적 있음' if yes else '받은 적 없음'}"
    if name == "on_medication":
        return f"{subj(item)} 약: {'지금 먹고 있음' if yes else '지금 안 먹음'}"
    if name == "family_history":
        return f"부모·형제자매 중 {subj(item)} 앓은 사람: {'있음' if yes else '없음'}"
    if item == "Q3":
        return "B형간염 보유: " + {"yes": "보유자라고 들음", "no": "보유자 아님", "unknown": "모름"}[value]
    if item in ("Q4", "Q5", "Q6"):
        return f"{TOBACCO[item]} 경험: {'있음' if yes else '전혀 없음'}"
    if name == "status":
        return f"{TOBACCO[item]}: {'지금 피움' if value == 'current' else '끊음'}"
    if name == "total_years":
        return f"{n_ko(value)}년 피움"
    if name == "daily_count":
        return f"하루 평균 {n_ko(value)}{STICK.get(item, '개비')}"
    if name == "years_since_quit":
        return f"끊은 지 {n_ko(value)}년"
    if name == "usage_days":
        return f"최근 한 달 액상형 전자담배 쓴 날: {n_ko(value)}일"
    if name == "does_not_drink":
        return "지난 1년 술: " + ("전혀 안 마심" if yes else "마심")
    if item == "Q7" and name == "frequency":
        return f"술 마시는 횟수: {n_ko(value)}번"
    if item == "Q7" and name == "unit":
        return "횟수 기준 기간: " + {"week": "일주일에", "month": "한 달에", "year": "1년에"}[value]
    if name == "amount":
        return f"양: {n_ko(value) if isinstance(value, (int, float)) else value}"
    if name == "answer":
        return f"{ACTIVITY[item]} 하는 날: 일주일에 {n_ko(value)}일"
    if name == "minutes":
        return f"{ACTIVITY[item]} 하는 날 하루 {n_ko(value)}분"
    return f"{field}: {value}"


def _value_text(f):
    v = f["value"]
    if isinstance(v, bool):
        return "예" if v else "아니요"
    return {"current": "지금 피움", "former": "끊음", "week": "주", "month": "월", "year": "년",
            "yes": "예", "no": "아니요"}.get(v, n_ko(v) if isinstance(v, (int, float)) else str(v))


def pat_conflict(item, rng):
    """충돌: R1(안 마심 + 음주량), R3(최대 < 평소), 또는 이전 저장 값과 다른 값(정정 표지어 없음)."""
    # v2(2026-10-13): r1(술 안 마심 + 음주량)은 뺐다. 'Q7 안 마심'이면 A가 Q7_1·Q7_2를 건너뛰므로 실제 흐름에서 생기지 않는다.
    subs = ["prev_diff"]
    if item == "Q7_2":
        subs.append("r3_max_below_usual")
    sub = rng.choice(subs)
    if sub == "r1_does_not_drink":
        first = labels([F("Q7", "does_not_drink", True, say="지난 1년 동안 술을 전혀 마시지 않았다")])
        prev = _stored(first)
        tgt = amount_facts(item, rng)
        prior = [{"role": "user", "labels": first, "describe": "앞 문항(Q7)에서 술을 전혀 안 마신다고 답함"},
                 {"role": "assistant", "describe": "상담자가 다음 질문으로 넘어가며 이 문항을 물음"}]
        return {"subtype": sub, "prior": prior, "previous": prev,
                "relevant_state": relevant(prev, {"Q7"}), "target": labels(tgt)}
    if sub == "r3_max_below_usual":
        name = rng.choice(["소주", "맥주"])
        unit = "병"
        usual = rng.choice([3, 4])
        first = labels([F("Q7_1", "amounts[0].beverage", name), F("Q7_1", "amounts[0].amount", usual),
                        F("Q7_1", "amounts[0].unit", unit)])
        prev = _stored(first)
        mx = rng.choice([1, 2])
        tgt = [F(item, "amounts[0].beverage", name, say=f"술 종류: {name}"),
               F(item, "amounts[0].amount", mx, say=f"가장 많이 마신 날 {name} {mx}{unit} (평소보다 적은 양, 모순을 의식하지 않고 말함)"),
               F(item, "amounts[0].unit", unit, say=f"단위: {unit}")]
        prior = [{"role": "user", "labels": first, "describe": f"평소 음주량(Q7_1): {name} {usual}{unit}"},
                 {"role": "assistant", "describe": "상담자가 가장 많이 마신 날의 양을 물음"}]
        return {"subtype": sub, "prior": prior, "previous": prev,
                "relevant_state": relevant(prev, {"Q7_1"}), "target": labels(tgt)}
    first_facts = normal_facts(item, rng)
    if item == "Q7" and len(first_facts) == 1:
        return None
    first = labels(first_facts)
    f = _main_fact(first_facts)
    new = _changed_value(f, rng)
    if new is None:
        return None
    nf = dict(f, value=new, precision="exact",
              _say=(f"{describe(item, f['field'], new)} (앞의 대화·이전 답은 전혀 언급하지 않고, '아니'·'틀렸'·'잘못'·'정정' 같은 말 없이 "
                    "처음 묻는 질문에 답하듯 말함)"))
    facts = [nf]
    if item in ("Q7_1", "Q7_2"):
        g = f["field"].split(".")[0]
        facts = [dict(x) for x in first_facts if x["field"].startswith(g)]
        facts[1] = nf
    prev = _stored(first)
    prior = [{"role": "user", "labels": first, "describe": f"앞에서 한 답: {f['_say']}"},
             {"role": "assistant", "describe": "상담자가 방금 들은 값을 짧게 되짚음(예: '네, 일주일에 세 번이요.'). 질문하지 않음 "
                                              "(그 뒤에 다음 문항 질문이 붙는다)"}]
    return {"subtype": sub, "prior": prior, "previous": prev,
            "relevant_state": relevant(prev, {item}), "target": labels(facts)}


def pat_prior_ref(item, rng):
    """이전 정보 참조: 앞 문항(REF_SOURCE)에서 한 답을 가리키며 답함. 값은 relevant_state에서 온다."""
    src = REF_SOURCE.get(item)
    if not src:
        return None
    if item == "Q7_2":
        first = labels(amount_facts("Q7_1", rng))
        prev = _stored(first)
        name = first["facts"][0]["value"]
        word = rng.choice(["평소랑 같아요", "평소랑 똑같아요", "평소의 두 배"])
        tgt = [F(item, "amounts[0].beverage", name, say=f"술 종류: {name} (평소 마시는 술과 같음)"),
               F(item, "amounts[0].amount", word, say=f"양은 숫자 대신 '{word}'라고 평소 양을 가리켜 말함"),
               F(item, "amounts[0].unit", None, "unspecified", "MISSING", say="단위(병·잔·캔)는 따로 말하지 않는다")]
        prior = [{"role": "user", "labels": first, "describe": "평소 음주량(Q7_1)을 답함"},
                 {"role": "assistant", "describe": "상담자가 가장 많이 마신 날의 양을 물음"}]
        return {"subtype": "same_as_usual", "prior": prior, "previous": prev,
                "relevant_state": relevant(prev, {"Q7_1"}), "target": labels(tgt)}
    first_facts = normal_facts(src, rng)
    first = labels(first_facts)
    prev = _stored(first)
    tgt = []
    for f in first_facts:
        tgt.append(dict(f, item_id=item,
                        _say=f"앞 문항({SUBJECT_SAY.get(src) or SUBJECT.get(src) or ACTIVITY.get(src) or TOBACCO.get(src, src)})과 같다고 가리켜 말함 "
                             f"('그것도 마찬가지예요', '아까랑 똑같아요' 등, 값 {_value_text(f)}을 직접 말하지 않아도 됨)"))
    prior = [{"role": "user", "labels": first, "describe": f"앞 문항 {src} 답: " + "; ".join(f["_say"] for f in first_facts)},
             {"role": "assistant", "describe": f"상담자가 이번 문항 {item}을 물음"}]
    return {"subtype": "same_as_prior_item", "prior": prior, "previous": prev,
            "relevant_state": relevant(prev, {src}, reason="STORED_PRIOR_ITEM"), "target": labels(tgt)}



# ================================================================ P11 정규화기 규칙·사유 코드 사례 (2026-10-13 보충)
# S3까지 데이터에 한 번도 나오지 않은 정규화기 사유 코드·정리 규칙을 따로 만든다(사용자 요청: 정규화기에서 빠진 것 모두 추가).
# 하위 유형마다 정규화기를 실제로 돌려 의도한 사유 코드(expect_issue)가 나와야 쓴다(build_canonical에서 확인).
# 단어로 판정하는 규칙(몇 대만 피움, 전단계, 운동 전혀 안 함, 부모·형제가 아닌 가족)은 근거 문장 예(ev)를 함께 넣어
# 정답 계산 때도 같은 규칙이 돌게 하고, 실제 발화의 근거로 다시 돌린 결과가 같아야 통과한다(checks.normalized).
# 정답 값은 정규화기 결과 그대로다. 정규화기 코드·규칙은 바꾸지 않는다.

OTHER_BEVERAGE_NAMES = ["칵테일", "담금주", "리큐르", "인삼주", "과실주"]          # 정규화기 술 이름표·도수표에 없는 이름
ABV_BEVERAGE_NAMES = {"하이볼": ["잔"], "소맥": ["잔"], "폭탄주": ["잔"], "매실주": ["잔", "병"], "사케": ["잔", "병"],
                      "청주": ["잔", "병"], "복분자주": ["잔", "병"], "고량주": ["잔", "병"]}   # 도수표로 칸을 정하는 술
OTHER_FAMILY = ["할아버지", "할머니", "삼촌", "고모", "이모", "외삼촌", "큰아버지"]
PRE_DISEASE = {"Q1.D03": "고혈압", "Q1.D04": "당뇨", "Q1.D05": "고지혈증"}
NORM_CASE_ITEMS = {
    "other_beverage": ("Q7_1", "Q7_2"),            # OTHER_BEVERAGE -> REASK
    "abv_beverage": ("Q7_1", "Q7_2"),              # 4.3 ABV_CELL -> NEXT
    "beverage_missing": ("Q7_1", "Q7_2"),          # BEVERAGE_MISSING -> REASK
    "beverage_inherit": ("Q7_2",),                 # 6.2 BEVERAGE_INHERIT -> NEXT
    "max_below_usual": ("Q7_2",),                  # CONFLICT_MAX_BELOW_USUAL -> CONFIRM
    "missing_number": ("Q7", "Q8_1", "Q9_1", "Q10"),   # MISSING_NUMBER -> REASK
    "invalid_option": ("Q3", "Q4_1", "Q5_1"),      # INVALID_OPTION -> REASK
    "frequency_word": ("Q7",),                     # '매일·거의 매일' -> NEXT
    "drinks_rarely": ("Q7",),                      # R1 안 마심 + 횟수 -> 마심으로 정리, NEXT
    "does_not_drink_conflict": ("Q7",),            # CONFLICT_DOES_NOT_DRINK -> CONFIRM
    "no_exercise": ("Q8_1",),                      # 8.5 NO_EXERCISE -> 세 문항 0일, END
    "zero_days_with_time": ("Q8_1", "Q9_1"),       # R6 0일 + 시간 -> 시간은 버림, NEXT
    "relapse": ("Q4_1", "Q5_1"),                   # R5 지금 피움 + 끊은 기간 -> 끊은 기간 해당 없음, NEXT
    "few_smokes": ("Q4", "Q5"),                    # 8.5 FEW_SMOKES -> 경험 없음, NEXT
    "quit": ("Q4", "Q5"),                          # 끊었어요 -> 경험 있음 + 과거 흡연, NEXT
    "not_now_but_before": ("Q4", "Q5"),            # R4 '안 피움' + 과거 흡연 상세 -> 경험 있음, NEXT
    "pre_disease": tuple(PRE_DISEASE),             # 8.5 PRE_DISEASE -> 진단 아님, NEXT
    "medication_only": tuple(f"Q1.D{n:02d}" for n in range(1, 12)),   # 8.5 MED_IMPLIES_DIAGNOSIS -> NEXT
    "not_target_family": tuple(f"Q2.D{n:02d}" for n in range(1, 6)),  # NOT_TARGET_FAMILY -> REDIRECT
}
NORM_CASE_EXPECT = {"other_beverage": "OTHER_BEVERAGE", "beverage_missing": "BEVERAGE_MISSING",
                    "max_below_usual": "CONFLICT_MAX_BELOW_USUAL", "missing_number": "MISSING_NUMBER",
                    "invalid_option": "INVALID_OPTION", "does_not_drink_conflict": "CONFLICT_DOES_NOT_DRINK"}


def ev(fact, text):
    """정답 계산용 근거 문장 예. 단어 규칙이 정답 계산 때도 돌게 한다(생성 뒤에는 실제 발화의 근거로 바뀐다)."""
    fact["evidence"] = {"turn_index": 1, "start": 0, "end": len(text), "text": text}
    return fact


def _when(item):
    return "평소 술 마시는 날 하루에" if item == "Q7_1" else "지난 1년 중 가장 많이 마신 날 하루에"


def pat_norm_case(item, rng):
    """정규화기 규칙·사유 코드 사례. 반환 dict에 expect_issue(있어야 할 사유 코드), extract_items(역추출에 더 보여 줄 문항)를 둔다."""
    subs = [s for s, items in NORM_CASE_ITEMS.items() if item in items]
    if not subs:
        return None
    sub = rng.choice(subs)
    out = {"subtype": sub}
    if sub in NORM_CASE_EXPECT:
        out["expect_issue"] = NORM_CASE_EXPECT[sub]
    if sub == "other_beverage":
        name, unit = rng.choice(OTHER_BEVERAGE_NAMES), rng.choice(["잔", "병"])
        amt = rng.choice(AMOUNT_POOL[unit])
        out["target"] = labels([F(item, "amounts[0].beverage", name, say=f"술 종류: {name}"),
                                F(item, "amounts[0].amount", amt, say=f"{_when(item)} {name} {n_ko(amt)}{unit} (그 술이 어떤 술인지·도수는 설명하지 않음)"),
                                F(item, "amounts[0].unit", unit, say=f"단위: {unit}")])
    elif sub == "abv_beverage":
        name = rng.choice(sorted(ABV_BEVERAGE_NAMES))
        unit = rng.choice(ABV_BEVERAGE_NAMES[name])
        amt = rng.choice([1, 2, 3, 4, 5] if unit == "잔" else [1, 2])
        out["target"] = labels([F(item, "amounts[0].beverage", name, say=f"술 종류: {name}"),
                                F(item, "amounts[0].amount", amt, say=f"{_when(item)} {name} {n_ko(amt)}{unit}"),
                                F(item, "amounts[0].unit", unit, say=f"단위: {unit}")])
    elif sub == "beverage_missing":
        unit = rng.choice(["잔", "병"])
        amt = rng.choice([1, 2, 3, 4] if unit == "병" else [2, 3, 4, 5, 7])
        out["target"] = labels([F(item, "amounts[0].beverage", None, status="MISSING", precision="unspecified",
                                  say="술 이름·종류(소주·맥주 등)는 말하지 않는다"),
                                F(item, "amounts[0].amount", amt, say=f"{_when(item)} {n_ko(amt)}{unit} (무슨 술인지는 말하지 않고 양만)"),
                                F(item, "amounts[0].unit", unit, say=f"단위: {unit}")])
    elif sub == "beverage_inherit":
        name = rng.choice(["소주", "맥주", "막걸리", "와인"])
        unit = {"소주": "병", "맥주": "캔", "막걸리": "병", "와인": "잔"}[name]
        usual = rng.choice([1, 2])
        mx = usual + rng.choice([1, 2, 3])
        first = labels([F("Q7_1", "amounts[0].beverage", name), F("Q7_1", "amounts[0].amount", usual),
                        F("Q7_1", "amounts[0].unit", unit)])
        prev = _stored(first)
        out.update(prior=[{"role": "user", "labels": first, "describe": f"평소 음주량(Q7_1): {name} {usual}{unit}"},
                          {"role": "assistant", "describe": "상담자가 가장 많이 마신 날의 양을 물음"}],
                   previous=prev, relevant_state=relevant(prev, {"Q7_1"}))
        out["target"] = labels([F(item, "amounts[0].amount", mx, say=f"가장 많이 마신 날 {n_ko(mx)}{unit} (술 이름은 다시 말하지 않음. 앞에서 말한 그 술)"),
                                F(item, "amounts[0].unit", unit, say=f"단위: {unit}")])
    elif sub == "max_below_usual":
        name, unit = rng.choice([("소주", "병"), ("맥주", "캔"), ("맥주", "병"), ("막걸리", "병"), ("와인", "잔"), ("소주", "잔")])
        usual = rng.choice([3, 4, 5] if unit != "잔" else [5, 6, 7])
        mx = rng.choice(range(1, usual))
        first = labels([F("Q7_1", "amounts[0].beverage", name), F("Q7_1", "amounts[0].amount", usual),
                        F("Q7_1", "amounts[0].unit", unit)])
        prev = _stored(first)
        out.update(prior=[{"role": "user", "labels": first, "describe": f"평소 음주량(Q7_1): {name} {usual}{unit}"},
                          {"role": "assistant", "describe": "상담자가 가장 많이 마신 날의 양을 물음"}],
                   previous=prev, relevant_state=relevant(prev, {"Q7_1"}))
        out["target"] = labels([F(item, "amounts[0].beverage", name, say=f"술 종류: {name}"),
                                F(item, "amounts[0].amount", mx, say=f"가장 많이 마신 날 {name} {n_ko(mx)}{unit} (이 양만 말한다. 평소 양과 비교하거나 다른 시기·이유를 덧붙이지 않음)"),
                                F(item, "amounts[0].unit", unit, say=f"단위: {unit}")])
    elif sub == "missing_number":
        if item == "Q7":
            out["target"] = labels([F(item, "does_not_drink", False, say="술을 마신다"),
                                    F(item, "frequency", True, say="마시긴 한다고만 하고 몇 번인지·얼마나 자주인지는 말하지 않음 (예: '네, 마셔요')")])
        else:
            out["target"] = labels([F(item, "answer", True, say=f"{ACTIVITY[item]}를 하긴 한다고만 하고 며칠인지 숫자는 말하지 않음 (예: '네, 해요')")])
    elif sub == "invalid_option":
        if item == "Q3":
            out["target"] = labels([F(item, "answer", "예전에 보유자였다가 지금은 아님",
                                      say="예전에 B형간염 보유자라는 말을 들었는데 지금은 아니라고 들었다 (지금 보유자인지 딱 잘라 말하지 않음)")])
        else:
            years = rng.choice([3, 5, 10, 15, 20])
            count = rng.choice([3, 5, 10, 15])
            out["target"] = labels([F(item, "status", "피웠다 끊었다 함",
                                      say=f"{TOBACCO[item]}를 지금 피우는지 끊었는지 딱 잘라 말하지 않고 '피웠다 끊었다 한다'고 말함"),
                                    F(item, "total_years", years, say=f"{years}년쯤 전부터 피웠다 (정확한 값: {years}년)"),
                                    F(item, "daily_count", count, say=f"피울 때는 하루 {count}{STICK[item]}")])
            out["target"]["facts"][1]["_say"] = f"피운 기간 {years}년"
    elif sub == "frequency_word":
        word, (n, unit) = rng.choice([("매일", (7, "week")), ("날마다", (7, "week")), ("거의 매일", (6, "week"))])
        out["target"] = labels([F(item, "does_not_drink", False, say="술을 마신다"),
                                F(item, "frequency", word, say=f"술을 '{word}' 마신다 (숫자 없이 '{word}'라고 말함)")])
    elif sub == "drinks_rarely":
        unit = rng.choice(["month", "year"])
        n = rng.choice([1, 2] if unit == "month" else [1, 2, 3])
        word = {"month": "한 달에", "year": "1년에"}[unit]
        out["target"] = labels([F(item, "does_not_drink", True, say="술은 안 마신다고 먼저 말함"),
                                F(item, "frequency", n, say=f"그래도 {word} {n}번은 마신다고 덧붙임"),
                                F(item, "unit", unit, say=f"기간 단위는 '{word}'")])
    elif sub == "does_not_drink_conflict":
        name, unit = rng.choice([("맥주", "잔"), ("맥주", "캔"), ("소주", "잔"), ("와인", "잔"), ("막걸리", "잔")])
        amt = rng.choice([1, 2])
        out["extract_items"] = ["Q7_1"]
        out["target"] = labels([F(item, "does_not_drink", True, say="술은 안 마신다"),
                                F("Q7_1", "amounts[0].beverage", name, say=f"그런데 모임 때는 {name}를 마신다고 덧붙임"),
                                F("Q7_1", "amounts[0].amount", amt, say=f"그럴 때 {name} {amt}{unit} (몇 번 마시는지·얼마나 자주인지는 말하지 않음)"),
                                F("Q7_1", "amounts[0].unit", unit, say=f"단위: {unit}")])
    elif sub == "no_exercise":
        out["target"] = labels([ev(F(item, "answer", 0, say="운동은 전혀 안 한다 ('운동은 전혀 안 해요', '운동은 아예 안 해요'처럼 '운동'과 '전혀/아예/하나도' + '안'을 넣어 말함)"),
                                   "운동은 전혀 안 해요")])
    elif sub == "zero_days_with_time":
        time_item = {"Q8_1": "Q8_2", "Q9_1": "Q9_2"}[item]
        m = rng.choice([20, 30, 40, 60])
        walk = rng.choice(["걷기", "산책", "동네 한 바퀴 걷기"])
        out["extract_items"] = [time_item]
        out["target"] = labels([F(item, "answer", 0, say=f"{ACTIVITY[item]}는 안 한다"),
                                F(time_item, "minutes", m, say=f"대신 {walk}는 하루 {m}분 한다고 덧붙임")])
    elif sub == "relapse":
        years, count, quit = rng.choice([10, 15, 20]), rng.choice([5, 10, 15]), rng.choice([1, 2, 3])
        out["target"] = labels([F(item, "status", "current", say=f"{TOBACCO[item]}를 지금 피운다 (끊었다가 다시 피우기 시작함)"),
                                F(item, "total_years", years, say=f"모두 {years}년 피웠다"),
                                F(item, "daily_count", count, say=f"하루 {count}{STICK[item]}"),
                                F(item, "years_since_quit", quit, say=f"{quit}년 끊었다가 다시 피우게 됐다")])
    elif sub == "few_smokes":
        out["target"] = labels([ev(F(item, "answer", False, precision="approximate",
                                     say=f"{TOBACCO[item]}는 호기심에 몇 대 피워 본 게 전부다 ('몇 대'나 '한두 대'라는 말을 넣음, 그 뒤로는 안 피움)"),
                                   "호기심에 몇 대 피워 본 게 다예요")])
    elif sub == "quit":
        child = {"Q4": "Q4_1", "Q5": "Q5_1"}[item]
        out["extract_items"] = [child]
        out["target"] = labels([F(item, "answer", True, say=f"{TOBACCO[item]}를 예전에 피웠다"),
                                F(child, "status", "former", say="지금은 끊었다 (몇 년 피웠는지·하루 몇 개비인지는 말하지 않음)")])
    elif sub == "not_now_but_before":
        child = {"Q4": "Q4_1", "Q5": "Q5_1"}[item]
        years = rng.choice([5, 10, 20])
        out["extract_items"] = [child]
        out["target"] = labels([F(item, "answer", False, say="지금은 안 피운다는 뜻으로 '아니요, 안 피워요'라고 먼저 답함"),
                                F(child, "status", "former", say="예전에는 피웠다고 덧붙임"),
                                F(child, "total_years", years, say=f"{years}년 피우다 끊었다")])
    elif sub == "pre_disease":
        name = PRE_DISEASE[item]
        out["target"] = labels([ev(F(item, "diagnosed", True, say=f"건강검진에서 {name} 전단계라는 말을 들었다 ('전단계'나 '경계'라는 말을 넣음)"),
                                   f"{name} 전단계라고 들었어요"),
                                F(item, "on_medication", False, say="약은 안 먹는다")])
    elif sub == "medication_only":
        out["target"] = labels([F(item, "on_medication", True, say=f"지금 {subj(item)} 약을 먹고 있다")])
    elif sub == "not_target_family":
        who = rng.choice(OTHER_FAMILY)
        out["note"] = f"{who}가 {subj(item)}을 앓음 (부모·형제자매 아님)"
        out["target"] = labels([ev(F(item, "family_history", True, say=f"{who}가 {subj(item)}을 앓았다 (부모님·형제자매 얘기는 하지 않음)"),
                                   f"{who}가 {subj(item)}이 있으셨어요")])
    return out


PATTERN_FUNCS = {
    "P01_normal": pat_normal, "P02_range_unit": pat_range_unit, "P03_partial": pat_partial,
    "P04_reask_fill": pat_reask_fill, "P05_correction": pat_correction, "P06_conflict": pat_conflict,
    "P07_prior_ref": pat_prior_ref, "P08_unk_refuse": pat_unknown_refuse, "P09_oos": pat_oos,
    "P10_boundary": pat_boundary, "P11_norm_case": pat_norm_case,
}


# ================================================================ 조립·정규화기 검증

def _assign_keys(target, pattern=None):
    """정답 항목마다 근거 키(k1..)를 붙이고 생성 지시(spec)를 만든다.

    거절·보류·OOS처럼 이번 문항 칸 정답이 없는 경우, 생성 모델이 질문에 답까지 해 버리는 일이 많아
    '질문에 대한 답(예/아니요·숫자)'을 말하지 말 것에 명시한다. 이번 문항의 칸만 말하게 하려고
    여러 칸 문항에서 정답에 없는 칸도 말하지 말 것에 넣는다.
    """
    spec, n = [], 0
    for g in GROUPS:
        for e in target[g]:
            n += 1
            e["_k"] = f"k{n}"
            say = e.get("_say", "")
            # 정확한 숫자인데 '정도·쯤'을 붙이는 생성 오류가 많아 메모에 직접 적는다.
            if g == "facts" and e.get("precision") == "exact" and isinstance(e.get("value"), (int, float)) \
                    and not isinstance(e.get("value"), bool):
                say += " (정확한 값: '정도·쯤·약' 없이)"
            spec.append({"key": e["_k"], "say": say,
                         "kind": g, "silent": e.get("semantic_status") == "MISSING"})
    # 여러 칸 문항에서 이번 정답에 없는 칸(예: 정정 대상이 약 복용뿐일 때 진단 여부)은 말하지 않게 한다.
    items = {f["item_id"] for f in target["facts"]}
    said = {(f["item_id"], f["field"].split(".")[-1]) for f in target["facts"]}
    for item in sorted(items):
        if item.startswith("Q1."):
            names = ["diagnosed", "on_medication"]
        elif item in ("Q4_1", "Q5_1"):
            names = ["status", "total_years", "daily_count"]
        else:
            names = []
        for name in names:
            if (item, name) not in said:
                label = {"diagnosed": "진단을 받았는지 여부"}.get(name) or silent_ko(item, name)
                spec.append({"key": f"x_{name}", "say": f"{label}는 말하지 않는다", "kind": "guard", "silent": True})
    has_value = any(f["semantic_status"] != "MISSING" and f["value"] is not None for f in target["facts"])
    if not has_value and not any(f["semantic_status"] == "UNCERTAIN" for f in target["facts"]):
        spec.append({"key": "x0", "say": "현재 질문에 대한 답(예/아니요, 있다/없다, 숫자)은 절대 말하지 않는다",
                     "kind": "guard", "silent": True})
    return spec


def expected_output(target, previous):
    """근거 없이 정답만으로 정규화기를 돌린 결과 (6장 형식). 생성 후 결과와 비교하는 기준."""
    return run_turn(strip_say(target), CATALOG, previous, utterance=None, today=TODAY, turn_index=1)


def core(out):
    """비교용 핵심: 상태·plan·값(근거 제외)."""
    vals = sorted(tuple(str(x) for x in (v["item_id"], v["repeat_key"], v["field"], repr(v["value"]),
                                         v["precision"], v["status"]))
                  for v in out["normalized_values"])   # None이 섞여도 정렬되게 문자열로 비교
    return {"semantic_status": out["semantic_status"], "action": out["transition_plan"]["action"],
            "targets": out["transition_plan"]["targets"], "values": vals,
            "issues": sorted(i["code"] for i in out["issues"]), "holds": out["holds"]}


def build_canonical(item, pattern, index, seed=20261011, seed_lookup=None, max_tries=40, required_plan=None):
    """한 칸(문항, pattern)의 index번째 canonical. 허용 plan이 나올 때까지 하위 유형을 다시 뽑는다.

    seed_lookup: {(문항, pattern): [seed_id...]} 시드가 있는 칸이면 seed_derived로 표시한다.
    실패하면 None (그 칸은 이 정규화기로 만들 수 없음 -> 보고서에 남긴다).
    """
    cid = f"c_{item}_{pattern}_{index:04d}"
    allowed = {required_plan} if required_plan else ALLOWED_PLANS[pattern]
    salt = f"|{required_plan}" if required_plan else ""   # plan 지정 없이 만든 기존 canonical과 같은 결과를 유지
    for t in range(max_tries):
        h = int(hashlib.sha256(f"{seed}|{cid}|{t}{salt}".encode()).hexdigest()[:12], 16)
        rng = random.Random(h)
        try:
            sc = PATTERN_FUNCS[pattern](item, rng)
        except (KeyError, IndexError, ValueError):
            sc = None
        if not sc:
            continue
        previous = sc.get("previous", {})
        target = sc["target"]
        try:
            exp = expected_output(target, previous)
        except Exception:
            continue
        # 정정 대상 state_key는 정규화 결과에서 CORRECTION이 된 칸으로 정한다(relevant_state 키와 같은 형식).
        fixed = [v for v in exp["normalized_values"] if v["status"] == "CORRECTION"]
        for rel in target["relations"]:
            if len(fixed) != 1:
                break
            v = fixed[0]
            rel["correction_target"]["state_key"] = state_key(f"{v['item_id']}.{v['field']}", v["repeat_key"])
        if target["relations"] and len(fixed) != 1:
            continue
        if exp["transition_plan"]["action"] not in allowed:
            continue
        # P11: 의도한 정규화기 사유 코드가 실제로 나와야 쓴다
        if sc.get("expect_issue") and sc["expect_issue"] not in [i["code"] for i in exp["issues"]]:
            continue
        spec = _assign_keys(target, pattern)
        seeds = (seed_lookup or {}).get((item, pattern), [])
        return {
            "canonical_id": cid, "question_id": item, "pattern_type": pattern, "subtype": sc["subtype"],
            "source": "seed_derived" if seeds else "new_sampled",
            "seed_id": seeds[index % len(seeds)] if seeds else None,
            "sampler_seed": seed, "sampler_try": t, "required_plan": required_plan,
            "prior_turns": [{k: (strip_say(v) if k == "labels" else v) for k, v in p.items()}
                            for p in sc.get("prior", [])],
            "previous": [[k[0], k[1], v] for k, v in sorted(previous.items())],
            "relevant_state": sc.get("relevant_state", {}),
            "target": target, "spec": spec, "expected": exp,
            "note": sc.get("note"),   # 문진표 밖 건강 이야기의 짧은 요약 (LoRA-A 정답 note)
            "extract_items": sc.get("extract_items", []),   # P11: 이번 문항 밖 칸을 함께 말하는 경우 역추출에 보여 줄 문항
        }
    return None


def previous_dict(canonical):
    return {(a, b): v for a, b, v in canonical["previous"]}
