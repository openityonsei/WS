"""v2 입력·출력 계약(2026-10-13 사용자 확정): LoRA-A 정답, LoRA-B 입력, 사람 말 설명표.

역할
- 서비스에는 정규화기가 없다. LoRA-A가 추출 + 정규화 + 절차(action) + 다음 문항(next_item)까지 출력한다.
  이 파일은 정규화기(routing_policy v1.0) 결과를 그 v2 정답 형식으로 바꾼다. 정규화기는 정답을 만드는 기준으로만 쓴다.
- LoRA-B 입력은 A 출력에 서비스 코드가 '표 찾기'로 붙이는 사람 말 설명(topic·known·ask·previous·hold)과
  다음 질문 문장(next)을 더한 것이다. 이 파일의 표와 함수가 그 '서비스 코드'의 기준 구현이다.
- 판단(값·상태·절차 결정)은 하지 않는다. 정규화기 결과를 옮기고, 표에서 문장을 찾아 끼워 넣을 뿐이다.

주요 함수
- a_input(...) -> LoRA-A 입력 dict
- a_target(asked_item, out, note) -> LoRA-A 정답 dict (values / action / reason / targets / note / next_item)
- b_input(a_out, ...) -> LoRA-B 입력 dict
- start_b_input(text) -> 문진 시작(START) B 입력
부작용 없음(정규화기 DB에서 문항 순서만 읽는다).
"""
import re
import sqlite3

from common import CATALOG, NORMALIZER_ROOT

# ================================================================ 문항 순서와 건너뛰기

_ORDER = None


def order():
    """문진 문항 순서(question_items.sequence_no). Q1.D01이 처음, Q10이 마지막."""
    global _ORDER
    if _ORDER is None:
        db = NORMALIZER_ROOT / "dataset" / "db" / "questionnaire_reference.sqlite3"
        with sqlite3.connect(db) as conn:
            _ORDER = [r[0] for r in conn.execute(
                "SELECT item_id FROM question_items WHERE version_id='national_health_2026_v1' ORDER BY sequence_no")]
    return _ORDER


FIRST_ITEM = "Q1.D01"
END = "END"


def next_after(item, values):
    """item 다음에 물을 문항. values는 이번 턴에 저장되는(save=true) 값들이다.
    건너뛰기: Q4·Q5·Q6 '아니요' -> Q4_1·Q5_1·Q6_1 / Q7 '안 마심' -> Q7_1·Q7_2 / Q8_1·Q9_1 '0일' -> Q8_2·Q9_2.
    마지막 문항(Q10) 다음은 END."""
    vals = {(v["item_id"], v["field"]): v["value"] for v in values if v.get("persist")}
    skip = set()
    for a, b in (("Q4", "Q4_1"), ("Q5", "Q5_1"), ("Q6", "Q6_1")):
        if vals.get((a, "answer")) is False:
            skip.add(b)
    if vals.get(("Q7", "does_not_drink")) is True:
        skip |= {"Q7_1", "Q7_2"}
    if vals.get(("Q8_1", "days")) == 0:
        skip.add("Q8_2")
    if vals.get(("Q9_1", "days")) == 0:
        skip.add("Q9_2")
    # 2026-10-13 보충: 한 턴에 뒤 문항의 칸까지 모두 저장되면(예: '운동은 전혀 안 해요' -> Q8_1·Q9_1·Q10 모두 0일) 그 문항도 묻지 않는다.
    # 칸 일부만 정해진 문항(예: '끊었어요' -> Q4_1 상태만)은 남은 칸을 물어야 하므로 건너뛰지 않는다.
    for later in order():
        fields = [f.field_name for f in CATALOG.fields.values() if f.item_id == later]
        if fields and all((later, f) in vals for f in fields):
            skip.add(later)
    seq = order()
    i = seq.index(item) + 1
    while i < len(seq) and seq[i] in skip:
        i += 1
    return seq[i] if i < len(seq) else END


# ================================================================ 사람 말 설명표

DISEASE = {"Q1.D01": "뇌졸중(중풍)", "Q1.D02": "심근경색이나 협심증", "Q1.D03": "고혈압", "Q1.D04": "당뇨병",
           "Q1.D05": "이상지질혈증", "Q1.D06": "폐결핵", "Q1.D07": "우울증", "Q1.D08": "조기정신증",
           "Q1.D09": "C형간염", "Q1.D10": "만성폐쇄성폐질환", "Q1.D11": "암이나 그 밖의 병",
           "Q2.D01": "뇌졸중(중풍)", "Q2.D02": "심근경색이나 협심증", "Q2.D03": "고혈압", "Q2.D04": "당뇨병",
           "Q2.D05": "암이나 그 밖의 병"}
TOBACCO = {"Q4": "일반담배", "Q4_1": "일반담배", "Q5": "가열담배", "Q5_1": "가열담배", "Q6": "액상형 전자담배",
           "Q6_1": "액상형 전자담배"}
EXERCISE = {"Q8_1": "숨이 많이 찰 정도로 힘든 운동", "Q8_2": "숨이 많이 찰 정도로 힘든 운동",
            "Q9_1": "숨이 약간 찰 정도의 운동", "Q9_2": "숨이 약간 찰 정도의 운동", "Q10": "근력 운동"}
BEVERAGE = {"soju": "소주", "beer": "맥주", "spirits": "양주(위스키 등)", "makgeolli": "막걸리", "wine": "와인"}
DRINK_UNIT = {"bottle": "병", "can": "캔", "cc": "cc", "glass": "잔"}
PERIOD = {"week": "일주일에", "month": "한 달에", "year": "1년에"}
USE_PATTERN = {"daily": "매일", "days_10_29": "한 달에 10~29일", "days_3_9": "한 달에 3~9일",
               "days_1_2": "한 달에 1~2일", "no": "안 씀"}


def topic(item):
    """B 입력 'topic': 지금 다루는 문항이 무엇인지 사람 말로. 다른 질환·문항 이름을 섞는 오류(#39)를 막는다."""
    if item.startswith("Q1."):
        return f"{DISEASE[item]} 진단을 받았는지와 지금 약을 먹는지"
    if item.startswith("Q2."):
        return f"부모·형제자매 중 {josa(DISEASE[item], '을/를')} 앓았거나 그 병으로 돌아가신 분이 있는지"
    return {
        "Q3": "B형간염 바이러스 보유자인지",
        "Q4": "일반담배를 평생 5갑(100개비) 이상 피운 적이 있는지",
        "Q4_1": "일반담배를 지금 피우는지, 피운 기간, 하루 개비 수, 끊은 지 얼마나 됐는지",
        "Q5": "가열담배(아이코스·글로 등)를 써 본 적이 있는지",
        "Q5_1": "가열담배를 지금 쓰는지, 쓴 기간, 하루 개비 수, 끊은 지 얼마나 됐는지",
        "Q6": "액상형 전자담배를 써 본 적이 있는지",
        "Q6_1": "최근 한 달 동안 액상형 전자담배를 쓴 날 수",
        "Q7": "지난 1년 동안 술을 얼마나 자주 마시는지(일주일·한 달·1년에 몇 번)",
        "Q7_1": "술 마시는 날 평소에 마시는 양",
        "Q7_2": "지난 1년 중 가장 많이 마신 날 하루에 마신 양",
        "Q8_1": "숨이 많이 찰 정도로 힘든 운동을 일주일에 며칠 하는지",
        "Q8_2": "숨이 많이 찰 정도로 힘든 운동을 하는 날 하루에 얼마나 하는지",
        "Q9_1": "숨이 약간 찰 정도의 운동을 일주일에 며칠 하는지",
        "Q9_2": "숨이 약간 찰 정도의 운동을 하는 날 하루에 얼마나 하는지",
        "Q10": "최근 1주일 동안 근력 운동을 한 날 수",
    }[item]


def short_topic(item):
    """보류·거절 때 '그 부분'을 가리키는 짧은 이름."""
    if item.startswith("Q1."):
        return DISEASE[item]
    if item.startswith("Q2."):
        return f"가족 중 {DISEASE[item]}"
    return {"Q3": "B형간염 보유 여부", "Q4": "흡연 경험", "Q4_1": "일반담배", "Q5": "가열담배 경험", "Q5_1": "가열담배",
            "Q6": "액상형 전자담배 경험", "Q6_1": "액상형 전자담배 쓴 날 수", "Q7": "술 마시는 횟수",
            "Q7_1": "평소 마시는 양", "Q7_2": "가장 많이 마신 날의 양", "Q8_1": "힘든 운동 하는 날 수",
            "Q8_2": "힘든 운동 하는 시간", "Q9_1": "숨이 약간 차는 운동 하는 날 수", "Q9_2": "숨이 약간 차는 운동 시간",
            "Q10": "근력 운동 한 날 수"}[item]


FIELD_SHORT = {"diagnosed": "진단 여부", "on_medication": "약 복용 여부", "family_history": "가족력",
               "status": "지금 피우는지", "total_years": "피운 기간", "daily_count": "하루 개비 수",
               "years_since_quit": "끊은 지 기간", "use_pattern": "쓴 날 수", "does_not_drink": "술을 마시는지",
               "frequency": "마시는 횟수", "unit": "단위", "amount": "양", "days": "날 수",
               "duration_minutes": "하루 시간"}


def josa(word, pair):
    """받침에 맞는 조사: josa('소주', '을/를') -> '소주를'. 괄호로 끝나면 괄호 앞 글자로 판단한다."""
    a, b = pair.split("/")
    base = re.sub(r"\(.*?\)$", "", word).strip() or word
    ch = base[-1]
    if "가" <= ch <= "힣":
        has = (ord(ch) - 0xAC00) % 28 != 0
    else:
        has = ch in "0136789lmn"   # 숫자·영문 끝소리 대략
    return word + (a if has else b)


def n_ko(x):
    """숫자 표기: 2.0 -> '2', 0.5 -> '0.5'."""
    return str(int(x)) if float(x).is_integer() else str(x)


def minutes_ko(m):
    m = int(round(m))
    if m >= 60 and m % 60:
        return f"{m // 60}시간 {m % 60}분"
    if m >= 60:
        return f"{m // 60}시간"
    return f"{m}분"


def years_ko(y):
    return "반년" if y == 0.5 else f"{n_ko(y)}년"


def value_text(item, field, value, repeat_key="", precision="exact"):
    """칸 하나의 값을 상담원이 되짚을 수 있는 사람 말로. 값이 없으면 None."""
    if value is None:
        return None
    approx = "쯤" if precision == "approximate" else ""
    smoke = "쓴" if item == "Q5_1" else "피운"
    if field == "diagnosed":
        return "진단 받음" if value else "진단 안 받음"
    if field == "on_medication":
        return "지금 약 먹음" if value else "지금 약 안 먹음"
    if field == "family_history":
        return "앓은 분 있음" if value else "앓은 분 없음"
    if item == "Q3":
        return {"yes": "보유자임", "no": "보유자 아님", "unknown": "보유 여부 모름"}[value]
    if item in ("Q4", "Q5", "Q6") and field == "answer":
        if item == "Q4":
            return "5갑 넘게 피운 적 있음" if value else "피운 적 없음"
        return "써 본 적 있음" if value else "써 본 적 없음"
    if field == "status":
        now = "지금 씀" if item == "Q5_1" else "지금 피움"
        return now if value == "current" else "끊음"
    if field == "total_years":
        return f"{smoke} 기간 {years_ko(value)}{approx}"
    if field == "daily_count":
        return f"하루 {n_ko(value)}개비{approx}"
    if field == "years_since_quit":
        return f"끊은 지 {years_ko(value)}{approx}"
    if field == "use_pattern":
        return {"no": "최근 한 달 안 씀", "daily": "최근 한 달 매일 씀"}.get(value) or \
            f"최근 한 달 {USE_PATTERN.get(value, value).replace('한 달에 ', '')} 씀"
    if field == "does_not_drink":
        return "지난 1년 술 안 마심" if value else "술 마심"
    if item == "Q7" and field == "frequency":
        return f"{n_ko(value)}번{approx}" if isinstance(value, (int, float)) else str(value)
    if item == "Q7" and field == "unit":
        return f"{PERIOD.get(value, value)} 기준"
    if field == "amount":
        return f"{n_ko(value)}{approx}" if isinstance(value, (int, float)) else str(value)
    if field == "unit":
        return DRINK_UNIT.get(value, value)
    if field == "days":
        week = "최근 일주일" if item == "Q10" else "일주일에"
        return f"{week} {n_ko(value)}일{approx}"
    if field == "duration_minutes":
        return f"하루 {minutes_ko(value)}{approx}"
    return f"{field}: {value}"


def _key(v):
    """values의 키: '문항.칸', 술은 '문항[술코드].칸'."""
    rk = v.get("repeat_key") or ""
    return f"{v['item_id']}[{rk}].{v['field']}" if rk else f"{v['item_id']}.{v['field']}"


def parse_key(key):
    """'Q7_1[soju].amount' -> ('Q7_1', 'soju', 'amount'), 'Q1.D01.diagnosed' -> ('Q1.D01', '', 'diagnosed')."""
    if "[" in key:
        item, rest = key.split("[", 1)
        rk, field = rest.split("].", 1)
        return item, rk, field
    item, field = key.rsplit(".", 1)
    return item, "", field


def _group_texts(rows):
    """[(item, repeat_key, field, value, precision)] -> 사람 말 목록. 같은 문항의 횟수+기간, 술 종류+양+단위는 한 덩어리로 묶는다."""
    out = []
    drinks = {}
    q7 = {}
    for item, rk, field, value, prec in rows:
        if item in ("Q7_1", "Q7_2") and rk:
            drinks.setdefault((item, rk), {})[field] = (value, prec)
            continue
        if item == "Q7" and field in ("frequency", "unit"):
            q7[field] = (value, prec)
            continue
        t = value_text(item, field, value, rk, prec)
        if t:
            out.append(t)
    if q7:
        f = q7.get("frequency", (None, "exact"))
        u = q7.get("unit", (None, "exact"))
        if f[0] is not None and u[0] is not None:
            out.append(f"{PERIOD.get(u[0], u[0])} {value_text('Q7', 'frequency', f[0], '', f[1])}")
        elif f[0] is not None:
            out.append(f"{value_text('Q7', 'frequency', f[0], '', f[1])} (기준 기간은 아직 모름)")
        elif u[0] is not None:
            out.append(value_text("Q7", "unit", u[0]))
    for (item, rk), d in drinks.items():
        name = BEVERAGE.get(rk, rk)
        amt, unit = d.get("amount", (None, "exact")), d.get("unit", (None, "exact"))
        amt_t = value_text(item, "amount", amt[0], rk, amt[1]) if amt[0] is not None else None
        unit_t = DRINK_UNIT.get(unit[0], unit[0]) if unit[0] is not None else None
        if amt_t and unit_t:
            # 어림 표시('쯤')는 단위 뒤에 붙인다: '맥주 1565cc쯤', '소주 2병쯤'
            approx = amt_t.endswith("쯤")
            out.append(f"{name} {amt_t.rstrip('쯤')}{unit_t}{'쯤' if approx else ''}")
        elif unit_t:
            out.append(f"{name}, 단위 {unit_t} (양은 아직 모름)")
        elif amt_t:
            out.append(f"{name} {amt_t} (단위는 아직 모름)")
        else:
            out.append(name)
    return out


# ================================================================ LoRA-A

ACTION = {"NEXT": "NEXT", "ACK_CORRECTION": "CORRECT", "ASK_MISSING": "REASK", "ASK_CLARIFICATION": "REASK",
          "ASK_CONFLICT": "CONFIRM", "ASK_OR_HOLD": "HOLD", "HOLD_OR_SKIP": "SKIP", "REDIRECT": "REDIRECT"}
SAME_ITEM_ACTIONS = ("REASK", "CONFIRM", "REDIRECT")


def reason_of(out):
    """사유 코드: issues의 코드 또는 REDIRECT의 intent. 문진표에 없는 건강 이야기(행 없음, intent 없음)는 OUT_OF_SCHEMA."""
    action = ACTION[out["transition_plan"]["action"]]
    if action == "REDIRECT":
        intents = [i["intent"] for i in out.get("intents", [])]
        return intents[0] if intents else "OUT_OF_SCHEMA"
    codes = [i["code"] for i in out.get("issues", [])]
    # 2026-10-13 보충: 음주량 칸에서 '기억 안 나요'(UNKNOWN)는 술 종류가 없어서 정규화기가 사유를 BEVERAGE_MISSING으로 덮어쓴다.
    # 같은 이름이 '술 종류만 빠진 답'(REASK)에도 쓰이므로, 보류(HOLD)일 때는 다른 문항과 같은 UNCERTAIN으로 맞춘다(동작·저장은 같음).
    if action == "HOLD" and codes and codes[0] == "BEVERAGE_MISSING":
        return "UNCERTAIN"
    return codes[0] if codes else None


def a_state(previous_rows, pending_rows=()):
    """LoRA-A 입력 'state': 저장 값 -> 입력 형식. 어떤 문항을 넣을지는 호출하는 쪽이 정한다(생성: 시나리오 값, 최종: prev_state 규칙).
    previous_rows: [(field_id, repeat_key, value)] 정규화기 확정값(DB의 current_answers와 같은 것)
    pending_rows: [(item, repeat_key, field, status)] 앞 턴에서 비어 있거나 불분명해서 다시 물은 칸(값 null)."""
    state = {}
    for fid, rk, value in previous_rows:
        item, field = fid.rsplit(".", 1)
        fdef = CATALOG.fields.get(fid)
        if fdef is not None and fdef.data_type == "boolean" and value is not None:
            value = bool(value)
        state[_key({"item_id": item, "field": field, "repeat_key": rk})] = {"value": value, "status": "ANSWERED"}
    for item, rk, field, status in pending_rows:
        state[_key({"item_id": item, "field": field, "repeat_key": rk})] = {"value": None, "status": status}
    return state


def a_input(asked_item, current_question, utterance, state):
    return {"question_id": asked_item, "current_question": current_question, "user_utterance": utterance,
            "state": state}


def a_target(asked_item, out, note=None):
    """정규화기 결과(out) -> LoRA-A 정답.
    asked_item: 상담원이 지금 묻고 있던 문항(A 입력 question_id). 정정·충돌이 앞 문항 값에 대한 것이면 값의 문항과 다르다.
    next_item 규칙
    - REASK·CONFIRM: 다시 물을 칸(targets)의 문항
    - REDIRECT: 지금 묻던 문항(asked_item)
    - 그 밖(NEXT·CORRECT·HOLD·SKIP): 값·대상 칸의 문항 다음 문항(건너뛰기 반영). 값이 없으면 asked_item 다음. Q10 다음은 END."""
    action = ACTION[out["transition_plan"]["action"]]
    values = [{"key": _key(v), "value": v["value"], "precision": v["precision"], "status": v["status"],
               "save": bool(v["persist"])} for v in out["normalized_values"]]
    targets = [_key(t) for t in out["transition_plan"].get("targets", [])]
    reason = reason_of(out)
    target_items = [t["item_id"] for t in out["transition_plan"].get("targets", [])]
    value_items = [v["item_id"] for v in out["normalized_values"]]
    if action in ("REASK", "CONFIRM"):
        nxt = target_items[0] if target_items else asked_item
    elif action == "REDIRECT":
        nxt = asked_item
    else:
        base = (value_items or target_items or [asked_item])[0]
        # 이번 턴에 저장되는 값만 건너뛰기에 반영한다(정정은 새 값으로 저장된다)
        nxt = next_after(base, out["normalized_values"])
    res = {"values": values, "action": action}
    if reason and action != "NEXT" and action != "CORRECT":
        res["reason"] = reason
    if targets and action in ("REASK", "CONFIRM", "HOLD", "SKIP"):
        res["targets"] = targets
    if note:
        res["note"] = note
    res["next_item"] = nxt
    return res


# ================================================================ '다시 물을 것' 문장 틀 (ask)

def _drink_ctx(rows_by_key, item, rk):
    name = BEVERAGE.get(rk, rk) if rk else "술"
    unit = rows_by_key.get((item, rk, "unit"))
    unit_ko = DRINK_UNIT.get(unit, unit) if unit else None
    return name, unit_ko


def ask_text(reason, targets, known_rows, utterance_values=None):
    """REASK·CONFIRM에서 상담원이 무엇을 물어야 하는지 사람 말로.
    reason: 사유 코드, targets: 대상 키 목록, known_rows: {(item, rk, field): value} 이번 턴·저장 값."""
    parts = []
    for key in targets:
        item, rk, field = parse_key(key)
        if reason == "MISSING":
            parts.append(_ask_missing(item, rk, field, known_rows))
        elif reason in ("VAGUE_QUANTITY", "MISSING_NUMBER"):
            parts.append(_ask_number(item, rk, field, known_rows))
        elif reason == "OUT_OF_RANGE":
            parts.append({"days": "일주일은 7일이니 일주일 중 며칠인지 다시",
                          "duration_minutes": "하루는 24시간이니 하루에 몇 시간·몇 분인지 다시",
                          "use_pattern": "한 달은 길어야 31일이니 최근 한 달 중 며칠인지 다시",
                          "frequency": "그 기간 안에서 몇 번인지 다시"}.get(field, f"{josa(FIELD_SHORT.get(field, field), '을/를')} 다시"))
        elif reason == "COUNT_EXCEEDS_DAYS":
            parts.append("술을 마신 날을 기준으로 그 기간에 며칠(몇 번) 마시는지")
        elif reason == "RANGE_SPANS_OPTIONS":
            parts.append({"use_pattern": "최근 한 달 동안 며칠 썼는지 하나의 숫자로",
                          "frequency": "평소 몇 번인지 하나의 숫자로"}.get(field, "하나의 값으로"))
        elif reason == "UNKNOWN_UNIT":
            name, _ = _drink_ctx(known_rows, item, rk)
            parts.append(f"{josa(name, '을/를')} 병·잔·캔 같은 단위로 치면 얼마나인지")
        elif reason == "OTHER_BEVERAGE":
            parts.append("그 술이 소주·맥주·막걸리·와인·양주 중 어떤 술과 비슷한지(도수를 알면 도수)")
        elif reason == "BEVERAGE_MISSING":
            parts.append("어떤 술이었는지")
        elif reason == "INVALID_OPTION":
            parts.append(_ask_option(item, field, known_rows))
        elif reason == "CONFLICT_WITH_PREVIOUS":
            parts.append("이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지")
        elif reason == "CONFLICT_MAX_BELOW_USUAL":
            parts.append("가장 많이 마신 날의 양이 맞는지(평소보다 적게 나옴)")
        elif reason == "CONFLICT_DOES_NOT_DRINK":
            parts.append("지난 1년 동안 술을 마신 적이 있는지")
        else:
            parts.append(f"{josa(FIELD_SHORT.get(field, field), '을/를')} 다시")
    # 같은 문장이 반복되면 하나로
    return ", ".join(dict.fromkeys(parts))


def _ask_missing(item, rk, field, rows):
    if field == "diagnosed":
        return f"{DISEASE[item]} 진단을 받은 적이 있는지"
    if field == "on_medication":
        return f"지금 {DISEASE[item]} 약을 먹는지"
    if field == "status":
        return "지금도 피우는지 끊었는지" if item != "Q5_1" else "지금도 쓰는지 끊었는지"
    if field == "total_years":
        return "모두 몇 년 피웠는지" if item != "Q5_1" else "모두 몇 년 썼는지"
    if field == "daily_count":
        return "하루에 몇 개비 피우는지(피웠는지)" if item != "Q5_1" else "하루에 몇 개비 쓰는지(썼는지)"
    if field == "years_since_quit":
        return "끊은 지 몇 년 됐는지"
    if item == "Q7" and field == "unit":
        f = rows.get(("Q7", "", "frequency"))
        n = f"{n_ko(f)}번이 " if isinstance(f, (int, float)) else ""
        return f"{n}일주일에·한 달에·1년에 중 어느 기준인지"
    if item == "Q7" and field == "frequency":
        u = rows.get(("Q7", "", "unit"))
        return f"{PERIOD.get(u, '일주일이나 한 달에')} 몇 번 마시는지"
    if item in ("Q7_1", "Q7_2"):
        name, unit_ko = _drink_ctx(rows, item, rk)
        when = "술 마시는 날 평소에" if item == "Q7_1" else "가장 많이 마신 날"
        if field == "amount":
            return f"{when} {josa(name, '을/를')} 몇 {unit_ko} 마시는지" if unit_ko and unit_ko != "cc" else f"{when} {josa(name, '을/를')} 얼마나 마시는지"
        if field == "unit":
            amt = rows.get((item, rk, "amount"))
            a = f"{n_ko(amt)}" if isinstance(amt, (int, float)) else ""
            return (f"{name} {josa(a, '이/가')} 병·잔·캔 중 어느 단위인지" if a else f"{name}의 단위가 병·잔·캔 중 무엇인지")
    return f"{FIELD_SHORT.get(field, field)}"


def _ask_option(item, field, rows):
    """INVALID_OPTION(선택지에 없는 답): 문진표 선택지를 사람 말로 보여 주며 다시 묻는다. 칸 코드 이름은 쓰지 않는다."""
    if item == "Q3":
        return "B형간염 보유자라고 들은 적이 있는지, 아닌지, 검사를 안 해 봐서 모르는지"
    if field == "status":
        return _ask_missing(item, "", field, rows)
    if item == "Q7" and field == "unit":
        return _ask_missing(item, "", field, rows)
    if field == "use_pattern":
        return "최근 한 달 동안 며칠 썼는지"
    return f"{josa(FIELD_SHORT.get(field, '답'), '을/를')} 문진표 선택지 중에서 다시"


def _ask_number(item, rk, field, rows):
    if field == "days":
        return "일주일에 며칠인지 숫자로" if item != "Q10" else "최근 일주일 중 며칠인지 숫자로"
    if field == "duration_minutes":
        return "하루에 몇 분(몇 시간)인지 숫자로"
    if field == "frequency":
        return "일주일이나 한 달에 몇 번인지 숫자로"
    if field == "daily_count":
        return "하루에 몇 개비인지 숫자로"
    if field == "use_pattern":
        return "최근 한 달 동안 며칠인지 숫자로"
    if field == "amount":
        name, unit_ko = _drink_ctx(rows, item, rk)
        return f"{josa(name, '을/를')} 몇 {unit_ko} 마시는지 숫자로" if unit_ko else f"{josa(name, '을/를')} 얼마나 마시는지 숫자로"
    return f"{josa(FIELD_SHORT.get(field, field), '을/를')} 숫자로"


# ================================================================ LoRA-B

def b_input(a_out, asked_item, utterance, state, next_text, prev_turn_values=None):
    """LoRA-B 입력. a_out: LoRA-A 출력(정답), asked_item: A 입력 question_id, state: A 입력 state,
    next_text: next_item의 질문 문장(문항 은행에서 서비스가 찾음, END면 None).
    키: action, reason, topic, user_utterance, known, ask(REASK·CONFIRM), previous(CONFIRM), hold(HOLD·SKIP),
    note(REDIRECT OUT_OF_SCHEMA), next{type, question_id, text}."""
    action = a_out["action"]
    rows_now = {}
    known_rows = []
    for v in a_out["values"]:
        item, rk, field = parse_key(v["key"])
        rows_now[(item, rk, field)] = v["value"]
        if v["status"] in ("ANSWERED", "CORRECTION") and v["value"] is not None:
            known_rows.append((item, rk, field, v["value"], v["precision"]))
    # 같은 문항의 저장 값도 ask 문장에 쓸 수 있게 합친다(예: 술 종류는 앞 턴에, 양은 이번 턴에)
    rows_all = {}
    for k, s in state.items():
        it, rk, fd = parse_key(k)
        if s.get("value") is not None:
            rows_all[(it, rk, fd)] = s["value"]
    rows_all.update({k: v for k, v in rows_now.items() if v is not None})
    focus = parse_key(a_out["targets"][0])[0] if a_out.get("targets") else \
        (parse_key(a_out["values"][0]["key"])[0] if a_out["values"] else asked_item)
    b = {"action": action}
    if a_out.get("reason"):
        b["reason"] = a_out["reason"]
    b["topic"] = topic(focus)
    b["user_utterance"] = utterance
    # Q7 횟수만 이번에 말했으면(정정 등) 저장된 기준 기간을 붙여서 '일주일에 3번'처럼 뜻이 통하게 한다
    fields_now = {(r[0], r[2]) for r in known_rows}
    if ("Q7", "frequency") in fields_now and ("Q7", "unit") not in fields_now and \
            (state.get("Q7.unit") or {}).get("value") is not None:
        known_rows.append(("Q7", "", "unit", state["Q7.unit"]["value"], "exact"))
    # 확인(CONFIRM) 턴은 값이 아직 정해지지 않았으므로 known을 비우고 previous·current로만 말한다
    b["known"] = "" if action == "CONFIRM" else ", ".join(_known_texts(known_rows, focus))
    if action in ("REASK", "CONFIRM"):
        b["ask"] = ask_text(a_out.get("reason"), a_out.get("targets", []), rows_all)
    if action == "CONFIRM":
        b["previous"] = previous_text(a_out, state)
        b["current"] = ", ".join(_group_texts(_conflict_rows(a_out, state)))
    if action in ("HOLD", "SKIP"):
        b["hold"] = hold_text(a_out.get("targets", []), asked_item)
    if a_out.get("note"):
        b["note"] = a_out["note"]
    nxt = a_out["next_item"]
    if nxt == END:
        b["next"] = {"type": "END"}
    elif action in SAME_ITEM_ACTIONS:
        b["next"] = {"type": "SAME", "question_id": nxt, "text": next_text}
    else:
        b["next"] = {"type": "NEXT", "question_id": nxt, "text": next_text}
    return b


def _known_texts(rows, focus):
    """known 문장 목록. 한 턴에 여러 문항 값이 함께 정해지면(운동을 전혀 안 함 -> Q8_1·Q9_1·Q10 모두 0일,
    끊었어요 -> Q4 경험 있음 + Q4_1 과거 흡연) 지금 문항(focus)이 아닌 값 앞에 그 문항의 짧은 이름을 붙인다.
    한 문항 값만 있으면 기존과 같은 문장이다."""
    if all(r[0] == focus for r in rows):
        return _group_texts(rows)
    out = _group_texts([r for r in rows if r[0] == focus])
    for item in dict.fromkeys(r[0] for r in rows if r[0] != focus):
        texts = _group_texts([r for r in rows if r[0] == item])
        if texts:
            out.append(f"{short_topic(item)}: {', '.join(texts)}")
    return out


MULTI_FIELD = ("Q4_1", "Q5_1", "Q7", "Q7_1", "Q7_2")


def hold_text(targets, asked_item):
    """보류·거절로 비워 두는 부분의 이름. 여러 칸 문항에서 한 칸만 비우면 '일반담배 중 피운 기간'처럼 칸까지 말한다."""
    items = list(dict.fromkeys(parse_key(t)[0] for t in targets)) or [asked_item]
    fields = list(dict.fromkeys(parse_key(t)[2] for t in targets))
    item = items[0]
    if len(items) == 1 and len(fields) == 1 and (item in ("Q4_1", "Q5_1") or item.startswith("Q1.")):
        fs = "지금 쓰는지" if item == "Q5_1" and fields[0] == "status" else FIELD_SHORT.get(fields[0], fields[0])
        return f"{short_topic(item)} 중 {fs}"
    return short_topic(item)


def _conflict_rows(a_out, state=None):
    rows = []
    for v in a_out["values"]:
        if v["status"] == "CONFLICT" and v["value"] is not None:
            item, rk, field = parse_key(v["key"])
            # '술 안 마심'과 음주량이 한 턴에 함께 나온 충돌: '안 마심'은 previous로 말하므로 current에서 뺀다
            if a_out.get("reason") == "CONFLICT_DOES_NOT_DRINK" and (item, field) == ("Q7", "does_not_drink"):
                continue
            rows.append((item, rk, field, v["value"], v["precision"]))
    # 술은 단위가 CONFLICT가 아니어도 함께 말해야 뜻이 통한다
    conflict_drinks = {(r[0], r[1]) for r in rows if r[0] in ("Q7_1", "Q7_2")}
    for v in a_out["values"]:
        item, rk, field = parse_key(v["key"])
        if (item, rk) in conflict_drinks and field == "unit" and v["value"] is not None:
            rows.append((item, rk, field, v["value"], v["precision"]))
    if state and any(r[0] == "Q7" and r[2] == "frequency" for r in rows) and not any(r[0] == "Q7" and r[2] == "unit" for r in rows) \
            and (state.get("Q7.unit") or {}).get("value") is not None:
        rows.append(("Q7", "", "unit", state["Q7.unit"]["value"], "exact"))
    return rows


def previous_text(a_out, state):
    """CONFIRM의 이전 값: 충돌한 칸의 저장 값. 평소량보다 적은 최대량이면 평소량, 안 마신다고 했으면 그 답."""
    reason = a_out.get("reason")
    rows = []
    if reason == "CONFLICT_DOES_NOT_DRINK":
        return "지난 1년 술 안 마심"
    if reason == "CONFLICT_MAX_BELOW_USUAL":
        for k, s in state.items():
            it, rk, fd = parse_key(k)
            if it == "Q7_1" and s.get("value") is not None:
                rows.append((it, rk, fd, s["value"], "exact"))
        t = ", ".join(_group_texts(rows))
        return f"평소 {t}" if t else ""
    keys = set(a_out.get("targets", []))
    if "Q7.frequency" in keys and (state.get("Q7.unit") or {}).get("value") is not None:
        keys.add("Q7.unit")
    for k, s in state.items():
        if k in keys and s.get("value") is not None:
            it, rk, fd = parse_key(k)
            rows.append((it, rk, fd, s["value"], "exact"))
            if it in ("Q7_1", "Q7_2"):
                u = state.get(f"{it}[{rk}].unit")
                if u and fd != "unit" and u.get("value") is not None:
                    rows.append((it, rk, "unit", u["value"], "exact"))
    return ", ".join(_group_texts(rows))


def start_b_input(text):
    """문진 시작: 환자 말 없이 인사와 첫 문항(Q1.D01) 질문을 만든다. LoRA-A는 부르지 않는다."""
    return {"action": "START", "topic": topic(FIRST_ITEM),
            "next": {"type": "NEXT", "question_id": FIRST_ITEM, "text": text}}
