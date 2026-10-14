"""자동 검증 (데이터셋 v2): 발화·근거 조립, 정규화기 재실행 일치, 역추출 일치, 숫자·화자·문항 복사 검사,
v2 LoRA-B 가드(check_response), 임시 SQLite 저장·조회 왕복.

모든 함수는 실패하면 Reject(사유 코드)를 던진다. 사유 코드는 탈락률 집계에 그대로 쓰인다.
검증은 정답을 고치지 않는다. 맞지 않으면 그 후보를 버린다.
"""
import copy
import re
import shutil
import sqlite3
import tempfile
import unicodedata

from common import CATALOG, NORMALIZER_ROOT, normalize, run_turn
from normalizer.mappings import CORRECTION_PATTERN
from sampler import GROUPS, TODAY, core, previous_dict, strip_say

DB = NORMALIZER_ROOT / "dataset" / "db" / "questionnaire_reference.sqlite3"


class Reject(Exception):
    """검증 탈락. args[0] = 사유 코드."""


# ================================================================ 문자열 도구

def surface(text):
    """중복 판정용 정규화 문자열: 유니코드 정규화 + 공백·문장부호 제거 + 한글 숫자 일부 통일."""
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"[\s\W_]+", "", t)
    return t


NUM_WORDS = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "석": 3, "네": 4, "넷": 4, "다섯": 5,
             "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10, "열한": 11, "열두": 12, "열다섯": 15,
             "스무": 20, "스물": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60,
             "하루": 1, "이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5, "엿새": 6, "이레": 7}
COUNTERS = r"(?:병|잔|캔|번|회|일|년|개비|개|시간|분|갑|달|주|살|cc|씨씨|리터)"
_KO_NUM = re.compile(r"(?<![가-힣])(" + "|".join(sorted(NUM_WORDS, key=len, reverse=True)) + r")\s*" + COUNTERS)
_SINO = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9, "십": 10}


# 문진 기간을 가리키는 고정 표현(최근 1주일, 지난 1년, 한 달, 하루)은 값이 아니므로 숫자 검사에서 뺀다.
PERIOD = re.compile(r"(최근|지난|평소)?\s*(1|한)\s*(주일|주간|년간|년|달|개월)|하루\s*(기준|동안|에|평균)?")


DAY_WORDS = {"이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5, "엿새": 6, "이레": 7, "열흘": 10}
_DAY = re.compile(r"(?<![가-힣])(" + "|".join(DAY_WORDS) + r")")


def numbers_in(text):
    """글 속 숫자 집합: 아라비아 숫자 + '두 병'처럼 단위가 붙은 한글 고유어 숫자 + 날 수 낱말(이틀·사흘…). 완벽한 파서는 아니다."""
    text = PERIOD.sub(" ", text or "")
    out = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))}
    out |= {float(NUM_WORDS[m]) for m in _KO_NUM.findall(text)}
    out |= {float(DAY_WORDS[m]) for m in _DAY.findall(text)}
    return out


def lcs_len(a, b):
    """두 문자열(공백 제거)의 가장 긴 공통 부분 문자열 길이. 상담자 질문 베끼기 검사용."""
    a, b = re.sub(r"\s+", "", a), re.sub(r"\s+", "", b)
    best, prev = 0, [0] * (len(b) + 1)
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


COUNSELOR_PHRASES = ("말씀해 주세요", "말씀해주세요", "알려 주세요", "알려주세요", "답해 주세요", "기록하겠습니다",
                     "반영했습니다", "말씀하신")


# ================================================================ 1. 발화 + 근거 -> LoRA-A 정답

def assemble_target(canonical, utterance, ext):
    """canonical 정답(값은 그대로)에 근거 구간을 붙여 LoRA-A 정답(turn_index=1 기준)을 만든다.

    근거 출처: 정답을 보지 않은 역추출 결과(ext)에서 같은 (문항, 칸) / 같은 intent / 같은 relation의 evidence.text.
    그 text가 발화의 부분 문자열일 때만 쓴다. 없으면 발화 전체를 근거로 둔다(기존 데이터의 문장 단위 근거와 같은 수준).
    말하지 않은 칸(MISSING)은 근거 null.
    반환: (target, 대체 근거를 쓴 항목 수)
    """
    def span(text):
        if text and text.strip() and text in utterance:
            st = utterance.find(text)
            return {"turn_index": 1, "start": st, "end": st + len(text), "text": text}
        return None

    whole = {"turn_index": 1, "start": 0, "end": len(utterance), "text": utterance}
    ext_f = {(f["item_id"], f["field"]): (f.get("evidence") or {}).get("text") for f in ext.get("facts", [])}
    ext_i = {i["intent"]: (i.get("evidence") or {}).get("text") for i in ext.get("intents", [])}
    ext_r = {r["relation"]: (r.get("evidence") or {}).get("text") for r in ext.get("relations", [])}
    ext_u = [(u.get("evidence") or {}).get("text") for u in ext.get("unmapped_facts", [])]
    target = copy.deepcopy(canonical["target"])
    fallback = 0
    for g in GROUPS:
        for n, e in enumerate(target[g]):
            e.pop("_k", None)
            e.pop("_say", None)
            if g == "facts" and e["semantic_status"] == "MISSING":
                e["evidence"] = None
                continue
            text = {"facts": lambda: ext_f.get((e["item_id"], e["field"])),
                    "intents": lambda: ext_i.get(e["intent"]),
                    "relations": lambda: ext_r.get(e["relation"]),
                    "unmapped_facts": lambda: ext_u[n] if n < len(ext_u) else None}[g]()
            ev = span(text)
            if ev is None:
                fallback += 1
                ev = dict(whole)
            e["evidence"] = ev
    return target, fallback


def check_utterance(canonical, utterance, current_question):
    """화자·길이·질문 베끼기·새 숫자 검사."""
    if not 2 <= len(utterance) <= 200:
        raise Reject("utterance_length")
    if any(p in utterance for p in COUNSELOR_PHRASES):
        raise Reject("speaker_confusion")
    if re.search(r"\((범위|어림|정확|말함|보완)|말함\)|메모|문진표에 (없|안)", utterance):
        raise Reject("memo_leak")
    # 글말 종결(메모 문장 그대로)과 환자 자기 존칭은 실제 상담 발화가 아니다.
    if re.search(r"(는다|있다|없다|한다|했다|이다|않는다)\s*[.!]?\s*$", utterance) or re.search(r"(드시는 편|하십니다|드십니다|계십니다)", utterance):
        raise Reject("written_style")
    if lcs_len(utterance, current_question) >= 14:
        raise Reject("copies_question")
    # 메모 문장을 거의 그대로 옮긴 발화(문진표 말투)는 자연스럽지 않으므로 뺀다.
    for s in canonical["spec"]:
        memo = re.sub(r"\(.*?\)|\s+", "", s["say"])
        if len(memo) >= 10 and lcs_len(utterance, memo) >= 0.8 * len(memo):
            raise Reject("copies_spec")
    # 충돌(정정 표지어 없이 다른 값)인데 발화에 정정 표지어가 있으면 정정과 구분되지 않는다.
    # 정규화기는 근거 구간만 보고 판정하므로, 발화 전체를 따로 검사한다.
    if canonical["pattern_type"] == "P06_conflict" and re.search(CORRECTION_PATTERN, utterance):
        raise Reject("conflict_has_correction_marker")
    # 어림 메모가 없는데 '쯤/정도/대략'을 붙이면 precision 레이블(exact)과 발화가 어긋난다.
    approx_ok = any(f.get("precision") in ("approximate", "range") for f in canonical["target"]["facts"])
    # '그 정도'는 앞 답을 가리키는 말(이전 정보 참조)이라 어림 표현으로 보지 않는다.
    # '숨이 찰 정도의 운동'처럼 정도를 묘사하는 '정도의/정도로'는 어림이 아니다.
    if not approx_ok and re.search(r"쯤|(?<!그 )(?<!그)정도(?!의|로)|대략|대충|얼추|약\s*\d|약\s*[한두세네다]", utterance):
        raise Reject("unexpected_approx")
    allowed = set()
    for g in GROUPS:
        for e in canonical["target"][g]:
            allowed |= _nums_of(e.get("value"))
    for _, _, v in canonical["previous"]:
        allowed |= _nums_of(v)
    allowed |= {0.5 * x for x in list(allowed)} | {x * 60 for x in list(allowed)}
    extra = {n for n in numbers_in(utterance) if n not in allowed and n not in (1.0,)}
    if extra:
        raise Reject("new_number")


# ---------------------------------------------------------------- v1.17 발화 가드 (2026-10-12 사용자 승인안 4장)
# 문진표 낱말을 그대로 읽은 발화, 자기 답을 보증하는 군말, 틀린 숫자 말투. STT 오류형도 똑같이 검사한다.
U_FORM_WORDS = re.compile(r"신체\s?활동|기타\s?질환|피운\s?기간|형제자매\s?중에서[^.?!]{0,25}분은")
U_META = re.compile(r"정확히[^.?!,]{0,12}(입니다|이에요|예요|이야)|단위는|정확한\s?수치|이상하긴\s?한데")
# 2026-10-13: v1.17 파일럿에서 '다섯 날', '다섯에서 일곱 날', '열백 개비'가 나와 '다섯~아홉 날'과 '열백'을 더했다.
U_BAD_NUMBER = re.compile(r"(?<![가-힣])(두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무)\s?년|(?<![가-힣])(한|두|세|네|다섯|여섯|일곱|여덟|아홉)\s?날(?!씨)"
                          r"|(?<![가-힣])(한|두|세|네|다섯|여섯|열)병(?!원)|열백|천백"
                          r"|(?<![가-힣])(일|이|삼|사|오|육|칠|팔|구|십)\s?날(?!씨)")   # '삼 날'처럼 한자어 숫자 + 날


def check_utterance_v117(canonical, utterance, style):
    """v1.17 추가 발화 검사(2026-10-12 사용자 승인, v2에서도 그대로 쓴다). 실패하면 Reject(u_form_words / u_meta_comment / u_bad_number / copied_example)."""
    if U_FORM_WORDS.search(utterance):
        raise Reject("u_form_words")
    if U_META.search(utterance):
        raise Reject("u_meta_comment")
    if style != "stt_noise" and U_BAD_NUMBER.search(utterance):
        raise Reject("u_bad_number")
    if copies_example(utterance, 0.8, 12):
        raise Reject("copied_example")


def _grams(text, n=4):
    t = surface(text)
    return {t[i:i + n] for i in range(len(t) - n + 1)}


_EXAMPLE_GRAMS = None


def copies_example(text, threshold=0.7, min_len=10):
    """프롬프트 예시 문장과 거의 같은지: 글자 4-gram의 70% 이상이 한 예시와 겹치면 베낀 것으로 본다.
    짧은 말(공백·문장부호 빼고 10자 미만, 예: '이틀요')은 자연스럽게 겹칠 수 있어서 검사하지 않는다."""
    global _EXAMPLE_GRAMS
    if len(surface(text)) < min_len:
        return False
    if _EXAMPLE_GRAMS is None:
        import prompt_examples
        _EXAMPLE_GRAMS = [g for g in (_grams(x) for x in prompt_examples.all_example_texts()) if g]
    mine = _grams(text)
    return bool(mine) and any(len(mine & g) / len(mine) >= threshold for g in _EXAMPLE_GRAMS)


# 이전 턴 검사 (v1.17): 이전 턴은 학습 정답이 아니지만 입력 맥락이 앞뒤가 맞아야 한다.
PRIOR_CORRECTION = re.compile(r"정정|잘못|아니라|아니고|바꿀|바꿔|수정|다시 말|틀렸|처음에|앞서|아까|실은|사실은")
PRIOR_QUESTION = re.compile(r"\?|(나요|까요|인가요|습니까|있어요\?)\s*$")
ASKS = re.compile(r"\?\s*$|(세요|까요|나요|가요|신가요|으세요|어요|니까|겠어요)\s*[.]?\s*$")


def check_prior_turns(canonical, turns, current_question, reask_turn):
    """turns: 정리된 이전 턴(상담원 처음 질문, 환자 첫 답). current_question: 환자가 지금 대답하는 상담원 말.
    reask_turn: 같은 문항 다중 턴(P04·P05·P06 prev_diff)이면 current_question은 모델이 쓴 재질문·확인 말이다."""
    users = [t["content"] for t in turns if t["role"] == "user"]
    if any(PRIOR_QUESTION.search(u.strip()) for u in users):
        raise Reject("prior_user_question")
    if canonical["pattern_type"] == "P05_correction" and users and PRIOR_CORRECTION.search(users[0]):
        raise Reject("prior_first_answer_corrected")
    cq = (current_question or "").strip()
    if not cq:
        raise Reject("prior_empty_current_question")
    if any(t["role"] == "assistant" and surface(t["content"]) == surface(cq) for t in turns):
        raise Reject("prior_repeats_question")
    if reask_turn and canonical["pattern_type"] in ("P04_reask_fill", "P06_conflict") and not ASKS.search(cq):
        raise Reject("prior_reask_not_question")


def _nums_of(v):
    if isinstance(v, bool) or v is None:
        return set()
    if isinstance(v, (int, float)):
        return {float(v)}
    if isinstance(v, str):
        return {float(x) for x in re.findall(r"\d+(?:\.\d+)?", v)}
    return set()


# ================================================================ 2. 정규화기 재실행 일치

def normalized(canonical, target, utterance):
    """조립한 정답 + 실제 발화로 정규화기를 다시 돌린다. 기준(근거 없는 실행)과 핵심이 같아야 통과."""
    out = run_turn(target, CATALOG, previous_dict(canonical), utterance=utterance, today=TODAY, turn_index=1)
    if core(out) != core(canonical["expected"]):
        raise Reject("normalizer_mismatch")
    again = run_turn(target, CATALOG, previous_dict(canonical), utterance=utterance, today=TODAY, turn_index=1)
    if again != out:
        raise Reject("not_idempotent")
    return out


# ================================================================ 3. 역추출 일치

def _clean_extraction(ext, item):
    """역추출 JSON의 직렬화 차이만 정리한다(문자열 숫자 -> 숫자, 'true' -> true). 값 의미는 바꾸지 않는다."""
    ext = copy.deepcopy(ext)
    groups = {}
    for f in ext.get("facts", []):
        # 표기 실수만 바로잡는다: item_id에 state_key 형식("Q5/answer")을 쓴 경우, 음주량 칸에 번호를 빠뜨린 경우
        if isinstance(f.get("item_id"), str):
            f["item_id"] = f["item_id"].split("/", 1)[0].replace("칸", "").strip()
        if f.get("item_id") in ("Q7_1", "Q7_2") and f.get("field") in ("beverage", "amount", "unit"):
            groups.setdefault(f["item_id"], []).append(f)
    for item, fs in groups.items():
        if len(fs) == len({x["field"] for x in fs}):   # 술 한 종류일 때만 amounts[0]으로 본다
            for x in fs:
                x["field"] = f"amounts[0].{x['field']}"
    for f in ext.get("facts", []):
        v = f.get("value")
        if isinstance(v, str) and v in ("true", "false"):
            f["value"] = v == "true"
        elif isinstance(v, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", v.strip()):
            f["value"] = float(v) if "." in v else int(v)
        f["evidence"] = {"turn_index": 1, "text": (f.get("evidence") or {}).get("text", "")}
    for g in ("intents", "relations", "unmapped_facts"):
        for e in ext.get(g, []):
            if isinstance(e.get("item_id"), str) and "/" in e["item_id"]:
                e["item_id"] = e["item_id"].split("/", 1)[0]
            e["evidence"] = {"turn_index": 1, "text": (e.get("evidence") or {}).get("text", "")}
    # 같은 문항의 같은 intent를 두 번 쓴 경우만 하나로 합친다(직렬화 반복). 다른 intent는 그대로 둔다.
    seen, uniq = set(), []
    for i in ext.get("intents", []):
        k = (i.get("item_id"), i.get("intent"))
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    ext["intents"] = uniq
    return ext


def raw_signature(labels):
    """원시 레이블 비교용: (문항, 칸, 값, precision, 상태) + intent + relation 종류 + unmapped 수."""
    facts = sorted((f["item_id"], f["field"], repr(f["value"]), f.get("precision"), f["semantic_status"])  # item_id 포함 비교
                   for f in labels["facts"])
    return {"facts": facts,
            "intents": sorted((i["item_id"], i["intent"]) for i in labels["intents"]),
            "relations": sorted((r["item_id"], r["relation"]) for r in labels["relations"]),
            "unmapped": len(labels["unmapped_facts"])}


def check_extraction(canonical, extraction, utterance):
    """역추출 결과를 정규화기에 돌린 핵심이 기준과 같은지(필수), 원시 레이블까지 같은지(경계 판정용).

    반환: (raw_match, ext_labels). 핵심이 다르면 Reject.
    """
    try:
        ext = _clean_extraction(extraction, canonical["question_id"])
        out = run_turn(ext, CATALOG, previous_dict(canonical), utterance=utterance, today=TODAY, turn_index=1)
        same = core(out) == core(canonical["expected"])
    except Exception:
        raise Reject("extraction_normalize_error")   # 역추출 JSON이 정규화기 입력 형식을 벗어남(item_id null 등)
    if not same:
        raise Reject("blind_extraction_mismatch")
    try:
        raw = raw_signature(ext) == raw_signature(strip_say(canonical["target"]))
    except Exception:
        raw = False
    return raw, ext


# ================================================================ 4. LoRA-B 가드 (v2 입력 계약)

FORBIDDEN_B = [r"진단(됩|되|이 의심|으로 보)", r"의심(됩|돼)", r"위험(합|해|하|도|이 있)", r"권(장|고)", r"처방",
               r"치료(가|를) 받", r"줄이(세요|시는|셔야)", r"끊으(세요|시는|셔야)", r"건강에 (좋|나쁘|해)", r"과음",
               r"중독", r"병원에 (가|방문)"]
COMPLETION_B = re.compile(r"문진(이|을|은)?\s*(모두|전부|다)?\s*(끝났|끝이에요|끝입니다|마쳤|마치겠|마무리|완료)|모든 (질문|문항)|"
                          r"마지막 (질문|문항)|수고(하셨|많으셨)|(설문|문진)\s*완료|질문은 여기까지|여기까지예요")
CLOSING_B = re.compile(r"끝(났|나|이에요|입니다)|마쳤|마치겠|여기까지|마무리")
CODE_WORDS = ("bottle", "glass", "can", "week", "month", "year", "current", "former", "days_", "soju", "beer", "spirits",
              "makgeolli", "wine", "known", "previous", "topic", "next.text", "next_item", "REASK", "CONFIRM", "HOLD", "SKIP",
              "REDIRECT", "action")
B_STIFF = re.compile(r"답변하셨습니다|답변해\s?주셨|이해했습니다|확인되었습니다|확인했습니다|말씀하셨습니다|기록하였습니다|"
                     r"다음 질문 드리겠습니다|!|하셨다니|잘 기억해|수치이므로")
B_APPROX = re.compile(r"쯤|(?<!그 )(?<!그)정도(?!의|로)|대략|약\s*\d|약\s*[한두세네다]")
B_LEADING = re.compile(r"(맞죠|맞으시죠|드시죠|하시죠|있으시죠|계시죠|피우시죠|쓰시죠|아니시죠)\s*\??\s*$|"
                       r"(맞죠|드시죠|하시죠|있으시죠|계시죠)\?")
B_DOUBLE_HON = re.compile(r"시시(는|고|죠|네|군|며|면|던)|셨셨")
DISEASE_WORDS = ["뇌졸중", "중풍", "심근경색", "협심증", "고혈압", "당뇨", "이상지질혈증", "폐결핵", "우울증", "조기정신증",
                 "C형간염", "B형간염", "만성폐쇄성폐질환"]
B_ASKS = re.compile(r"\?\s*$|(세요|까요|나요|가요|신가요|으세요|어요|니까|겠어요|주시겠어요|있으세요)\s*[.]?\s*$")
DRINK_AMT = re.compile(r"(\d+(?:\.\d+)?|" + "|".join(sorted(NUM_WORDS, key=len, reverse=True)) + r")\s*(병|잔|캔|cc|씨씨)")


def _b_texts(b):
    """B 입력에서 응답이 숫자·이름을 가져와도 되는 글: known·ask·previous·current·hold·note·next.text·환자 말."""
    keys = ("known", "ask", "previous", "current", "hold", "note", "user_utterance", "topic")
    return " ".join(str(b.get(k) or "") for k in keys) + " " + str((b.get("next") or {}).get("text") or "")


def allowed_numbers_b(b):
    text = _b_texts(b)
    nums = numbers_in(text) | {float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)}
    for n in list(nums):
        if n >= 60:
            nums |= {float(n // 60), float(n % 60)}
        if n < 60 and float(n).is_integer():
            nums.add(n * 60)
    return nums | {0.5, 1.0}


def _recap(text):
    """응답에서 질문 문장(물음표가 있는 문장)을 뺀 나머지: 되짚기·인사 부분."""
    parts = re.split(r"(?<=[.?!])\s+", text.strip())
    return " ".join(p for p in parts if "?" not in p)


def _drink_amounts(text):
    out = set()
    for num, _unit in DRINK_AMT.findall(text or ""):
        out.add(float(num) if re.fullmatch(r"\d+(?:\.\d+)?", num) else float(NUM_WORDS[num]))
    return out


def check_response(b, text):
    """v2 LoRA-B 응답 가드. b: v2 B 입력(labels.b_input / start_b_input), text: 응답. 실패하면 Reject(코드)."""
    action, ntype = b["action"], b["next"]["type"]
    utt = b.get("user_utterance") or ""
    t = text.strip()
    if not 4 <= len(t) <= (300 if action == "START" else 240):
        raise Reject("b_length")
    if any(re.search(p, t) for p in FORBIDDEN_B):
        raise Reject("b_medical_advice")
    low = t.lower()
    if any(w.lower() in low for w in CODE_WORDS):
        raise Reject("b_code_leak")
    if B_STIFF.search(t):
        raise Reject("b_stiff_phrase")
    if B_DOUBLE_HON.search(t):
        raise Reject("b_honorific_error")
    if B_LEADING.search(t):
        raise Reject("b_leading_question")
    extra = {n for n in numbers_in(t) if n not in allowed_numbers_b(b)}
    if extra:
        raise Reject("b_new_number")
    # 끝맺음: END는 마무리 인사(질문 없음), NEXT·SAME은 질문으로 끝남, END가 아니면 문진 종료를 말하지 않음
    if ntype == "END":
        if "?" in t or not CLOSING_B.search(t):
            raise Reject("b_end_not_closing")
    else:
        if COMPLETION_B.search(t):
            raise Reject("b_completion_claim")
        if not B_ASKS.search(t):
            raise Reject("b_no_question")
    if action == "START":
        if "안녕" not in t:
            raise Reject("b_start_no_greeting")
        return _copy_check(t, start=True)
    # 다른 질환 이름: topic·next.text·환자 말에 없는 질환을 말하면 문항 혼동(파일럿 #39)
    ok_text = (b.get("topic") or "") + " " + str(b["next"].get("text") or "") + " " + utt
    for w in DISEASE_WORDS:
        if w in t and w not in ok_text and not (w == "중풍" and "뇌졸중" in ok_text) and not (w == "뇌졸중" and "중풍" in ok_text):
            raise Reject("b_wrong_topic")
    recap = _recap(t)
    known = " ".join(str(b.get(k) or "") for k in ("known", "previous", "current"))
    # 환자가 안 한 어림 표현
    if action in ("NEXT", "CORRECT") and "쯤" not in known and not B_APPROX.search(utt) and B_APPROX.search(recap):
        raise Reject("b_added_approx")
    topic = b.get("topic") or ""
    if "마시는 양" in topic or "마신 양" in topic:
        for u in ("병", "잔", "캔"):
            if u in recap and u not in utt and u not in known:
                raise Reject("b_unit_mismatch")
        if "가장 많이" in topic and re.search(r"일주일|한 주|주에|한 달|달에", recap):
            raise Reject("b_period_mismatch")
        # 환자가 말한 술의 양이 둘 이상인데 되짚기에서 빠뜨림(파일럿 #14)
        said = _drink_amounts(utt)
        # 정정은 고치기 전 양도 함께 말하므로 NEXT만 본다
        if action == "NEXT" and len(said) >= 2 and _drink_amounts(recap) and not said <= numbers_in(recap):
            raise Reject("b_dropped_amount")
    # 같은 문항 다시 묻기(REASK·CONFIRM)는 질문을 하나만 한다. 확인 질문 뒤에 원래 질문을 또 붙이면 무엇에 답할지 모호하다(파일럿 2차).
    if action in ("REASK", "CONFIRM") and t.count("?") > 1:
        raise Reject("b_two_questions")
    # 확인: 이전 값에 숫자가 있으면 그 숫자를 말해야 한다(무엇과 다른지 모호하지 않게)
    if action == "CONFIRM":
        prev_nums = numbers_in(b.get("previous") or "") | {float(x) for x in re.findall(r"\d+", b.get("previous") or "")}
        if prev_nums and not (prev_nums & numbers_in(t)):
            raise Reject("b_confirm_no_previous")
    # 잡담·문진표 밖 건강 이야기에 목적 설명만 하고 반응하지 않음(파일럿 #68·#76·#77)
    if action == "REDIRECT" and b.get("reason") in ("OFF_TOPIC", "OUT_OF_SCHEMA") and re.search(r"문진표.{0,8}(때문에|위해|작성)", t):
        raise Reject("b_redirect_no_reaction")
    # 환자 말 첫 문장을 그대로 복사
    if utt:
        first_u = re.split(r"[.?!]\s*", utt.strip())[0]
        first_b = re.split(r"[.?!]\s*", t)[0]
        if len(surface(first_u)) >= 2 and surface(first_u) == surface(first_b):
            raise Reject("b_copies_user")
    _copy_check(recap)


def _copy_check(text, start=False):
    """예시 베끼기 검사 (파일럿 뒤 2026-10-13 완화). 질문·마무리 인사는 정해진 말이라 겹치는 게 자연스럽고,
    '네, 나중에 말씀해 주셔도 괜찮아요' 같은 짧은 맞장구도 흔한 말이라 걸지 않는다.
    첫 문장(되짚기)만, 공백 빼고 15자 이상일 때, 80% 이상 겹치면 베낀 것으로 본다. START는 검사하지 않는다(중복은 near_start가 본다)."""
    if start:
        return
    first = re.split(r"(?<=[.?!])\s+", _recap(text).strip())[0] if _recap(text).strip() else ""
    if first and copies_example(first, 0.8, 15):
        raise Reject("copied_example")


# ================================================================ 5. DB 저장·조회 왕복

class RoundTrip:
    """기준 문진 DB를 임시 폴더에 복사해 두고, 시나리오마다 새 세션으로 저장·조회를 확인한다."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = f"{self.tmp.name}/rt.sqlite3"
        shutil.copy2(DB, self.path)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.n = 0
        self.issues = []   # DB 저장 거부 사례 (정규화기 이슈 후보)
        from normalizer import store
        self.store = store

    def check(self, canonical, target, utterance, out):
        """이전 턴 확정값 저장 -> 이번 턴 저장 -> current_answers 조회. persist=true 칸은 값이 같아야 한다."""
        self.n += 1
        sid = f"rt{self.n}"
        self.store.create_session(self.conn, sid)
        for p in canonical["prior_turns"]:
            if p.get("labels"):
                prev_res = normalize(p["labels"], CATALOG, self.store.confirmed_answers(self.conn, sid), today=TODAY)
                self.store.save_result(self.conn, sid, prev_res)
        res = normalize(target, CATALOG, self.store.confirmed_answers(self.conn, sid), utterance=utterance, today=TODAY)
        try:
            self.store.save_result(self.conn, sid, res)
        except sqlite3.Error as e:
            # 정규화 결과를 DB 트리거가 거부함(예: 반복 문항의 repeat_key가 빈 값). 정규화기 코드는 고치지 않고
            # 이 후보를 버린 뒤 정규화기 이슈 후보로 남긴다.
            self.issues.append({"canonical_id": canonical["canonical_id"], "utterance": utterance, "error": str(e),
                                "rows": [(r.field_id, r.repeat_key, r.resolution_status, r.reason) for r in res.records]})
            raise Reject("db_save_error")
        saved = self.store.confirmed_answers(self.conn, sid)
        for v in out["normalized_values"]:
            key = (f"{v['item_id']}.{v['field']}", v["repeat_key"])
            if v["persist"]:
                got = saved.get(key)
                same = (float(got) == float(v["value"])) if isinstance(v["value"], (int, float)) and got is not None \
                    else got == v["value"]
                if not same:
                    raise Reject("db_roundtrip_mismatch")
            elif v["status"] == "CONFLICT" and saved.get(key) is not None and previous_dict(canonical).get(key) is None:
                raise Reject("db_conflict_saved")
        return True
