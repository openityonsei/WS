"""데이터셋 v2 증강 파이프라인: canonical 샘플 -> 환자 발화 생성 -> 검증 -> 역추출 -> 정규화기(정답 기준) ->
LoRA-A 정답(v2) -> LoRA-B 입력(v2) -> 응답 생성 -> 가드·판정 -> 저장. START(인사 + 첫 질문)는 B 전용으로 따로 만든다.

실행 (openit-llm 환경, 프로젝트 루트 기준):
  python -B scripts/pipeline.py --stage pilot      # 파일럿: pattern마다 canonical 8개 + START 12건
  python -B scripts/pipeline.py --stage S3         # 누적 5,000 시나리오까지 (START 150건 포함)
  python -B scripts/pipeline.py --stage T1         # 보충(2026-10-13): S3 부족 칸 + P11 정규화기 사례(NORM_CASE_QUOTA) + START 150건

저장 (data/generated/)
- shards/{stage}_{nnnn}.jsonl   통과 레코드 (형식은 make_record / make_start_record, README 4장)
- rejects/{stage}.jsonl          탈락 후보와 사유
- progress/{stage}.jsonl         처리한 canonical_id (재시작 시 건너뜀)
- calls/{stage}.jsonl            모델 요청·응답 원문
- status_{stage}.json            진행·탈락률·처리량
- data/question_bank.json        문항별 상담원 질문 표현 (처음 실행 때 한 번 생성)

재시작: 같은 명령을 다시 실행하면 progress에 있는 canonical은 건너뛴다. data/generated/STOP 파일이 있으면 배치 사이에 멈춘다.
생성은 시드를 고정한다. human_review는 모두 pending이다. 자동 검증 통과는 사람 검수 통과가 아니다.
정규화기 코드는 읽기만 한다(정답 기준). 이전 데이터·시드는 쓰지 않는다(source=new_sampled).
"""
import argparse
import hashlib
import json
import math
import random
import re
import sqlite3
import time
from collections import Counter

import yaml

import checks
import labels
import prompts
from common import CATALOG, NORMALIZER_ROOT, ROOT, read_jsonl, ruleset_version
from question_templates import curated_for
from sampler import build_canonical
from taxonomy import MAX_VARIANTS_PER_CANONICAL, NORM_CASE_QUOTA, PLAN_MIX, START_TARGET, STYLE_TAGS, ITEM_WEIGHTS, applicable

GEN = ROOT / "data" / "generated"
SEED = 20261013
STAGE_TARGET = {"S1": 1000, "S2": 2500, "S3": 5000, "T1": 5000, "S4": 10000}   # T1: S3 목표를 다시 채우는 보충 단계
B_TRIES = 3   # LoRA-B 응답만 실패했을 때 다시 생성하는 최대 횟수
EXPECTED_PER_CANON = 1.2   # canonical 하나(변형 4개)에서 기대하는 통과 수 (v1.17 파일럿 실측 약 1.3)
MAX_CANON_FACTOR = 8       # 칸당 최대 시도 = 8 x 필요한 canonical 수
EARLY_MIN_TRIES = 12       # 이번 실행에서 canonical을 12개 이상 시도한 칸의
EARLY_MIN_YIELD = 0.03     # 변형 통과율이 3%보다 낮으면 더 시도하지 않고 부족분으로 보고한다
CLOSINGS = ["이걸로 문진은 모두 끝났어요. 답해 주셔서 감사합니다.", "질문은 여기까지예요. 수고 많으셨어요.",
            "오늘 문진은 이걸로 끝이에요. 고맙습니다."]


def h32(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# ================================================================ 문항 정보·상담원 질문 표현

def question_rows():
    db = NORMALIZER_ROOT / "dataset" / "db" / "questionnaire_reference.sqlite3"
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT item_id, question_text, subject_label, reference_period FROM question_items"
                            " WHERE version_id='national_health_2026_v1' ORDER BY sequence_no").fetchall()


def official_text(item, text, subject):
    return f"{subject}: {text}" if subject else text


# 문항별 질문 표현 필수·금지 키워드. 조사 범위·대상·단위가 바뀐 표현을 걸러낸다('친척 중', '병원에 자주' 같은 변형).
Q_REQUIRE = {
    "Q1": [("진단",), ("약", "치료")], "Q2": [("부모",), ("형제", "자매")], "Q3": [("B형",)],
    "Q4": [("일반담배", "궐련"), ("5갑", "100개비", "백 개비", "다섯 갑")], "Q4_1": [("일반담배", "궐련"), ("현재", "지금", "요즘")],
    "Q5": [("가열", "궐련형", "아이코스")], "Q5_1": [("가열", "궐련형", "아이코스"), ("현재", "지금", "요즘")],
    "Q6": [("액상",)], "Q6_1": [("액상",), ("한 달", "한달")],
    # Q7은 '평소 얼마나 자주(주·월·년 단위)'를 묻는다. 1년 총횟수로 뜻이 바뀐 표현은 금지(Q_FORBID_ITEM).
    "Q7": [("자주",)], "Q7_1": [("보통", "평소", "평균")],
    "Q7_2": [("가장 많이", "최대", "제일 많이")],
    "Q8_1": [("고강도", "숨이 많이"), ("며칠",)], "Q9_1": [("중강도", "숨이 약간", "숨이 조금", "숨이 살짝"), ("며칠",)],
    "Q10": [("근력",), ("며칠",)],
    "Q8_2": [("고강도", "숨이 많이"), ("시간", "얼마나")], "Q9_2": [("중강도", "숨이 약간", "숨이 조금", "숨이 살짝"), ("시간", "얼마나")],
}
Q_FORBID = ("친척", "친족", "가족 중", "자주 가", "건강에 문제", "예를 들어", "예컨대")
Q_FORBID_ITEM = {"Q7": ("몇 번 마셨", "몇 번을 마셨", "횟수", "대략", "기록", "대체")}


def _q_ok(item, q, key):
    rule = Q_REQUIRE["Q1" if item.startswith("Q1.") else "Q2" if item.startswith("Q2.") else item]
    if key and key not in q:
        return False
    if any(w in q for w in Q_FORBID + Q_FORBID_ITEM.get(item, ())):
        return False
    return all(any(w in q for w in group) for group in rule)


def ensure_question_bank(llm):
    """문항마다 상담원 질문 표현: 12개 생성 -> 키워드 필터 -> 원문과 같은 뜻인지 판정 -> 통과분 + 직접 쓴 표현(question_templates).
    파일이 있으면 그대로 읽는다. 생성·판정 모두 같은 모델의 자동 처리이며 human_review는 pending."""
    path = ROOT / "data" / "question_bank.json"
    if path.exists():
        return json.loads(path.read_text())
    rows = question_rows()
    reqs = [(item, prompts.qbank_messages(item, text, subject, period), h32(SEED, "qb", item))
            for item, text, subject, period in rows]
    res = llm.chat_json("question_bank", reqs, prompts.QBANK_SCHEMA, 0.8, 1500)
    cands = {}
    for item, text, subject, period in rows:
        parsed, gen = res[item]
        key = (subject or "").split("(")[0].split("/")[0].strip()
        if key.startswith("기타"):
            key = "암"   # Q2.D05 '기타(암포함)'
        qs = [q.strip() for q in (parsed or {}).get("questions", []) if 8 <= len(q.strip()) <= 150]
        cands[item] = (list(dict.fromkeys(q for q in qs if _q_ok(item, q, key))), gen, text, subject, period)
    jreqs = [(item, prompts.qjudge_messages(c[2], c[3], c[4], c[0]), h32(SEED, "qj", item))
             for item, c in cands.items() if c[0]]
    jres = llm.chat_json("question_judge", jreqs, prompts.QJUDGE_SCHEMA, 0.0, 2000)
    bank = {}
    for item, (qs, gen, text, subject, period) in cands.items():
        verdicts = {v["i"]: v["same_meaning"] for v in ((jres.get(item) or (None,))[0] or {}).get("verdicts", [])}
        ok = [q for k, q in enumerate(qs) if verdicts.get(k) is True]
        cur = [q for q in curated_for(item, subject) if q not in ok]
        variants = ok + cur or [official_text(item, text, subject)]
        bank[item] = {"official": official_text(item, text, subject), "variants": variants,
                      "sources": ["llm_filtered_judged"] * len(ok) + ["curated_by_claude"] * len(cur),
                      "candidates": len(qs), "generation": gen, "prompt_version": prompts.PROMPT_VERSION,
                      "human_review": "pending"}
    path.write_text(json.dumps(bank, ensure_ascii=False, indent=1))
    return bank


def pick_question(bank, item, salt):
    vs = bank[item]["variants"]
    return vs[h32(SEED, "q", item, salt) % len(vs)]


# ================================================================ 생성 계획

PATTERN_LIST = ["P01_normal", "P02_range_unit", "P03_partial", "P04_reask_fill", "P05_correction",
                "P06_conflict", "P07_prior_ref", "P08_unk_refuse", "P09_oos", "P10_boundary", "P11_norm_case"]


def pilot_slots(per=8):
    """파일럿: pattern마다 canonical per개, 문항은 pattern에 맞는 문항을 고르게 돈다(index 9000번대)."""
    items = list(ITEM_WEIGHTS)
    slots = []
    for n, p in enumerate(PATTERN_LIST):
        cands = [i for i in items if applicable(p, i)]
        for k in range(per):
            slots.append((cands[(n * 3 + k * 5) % len(cands)], p, 9000 + k))
    return slots


def same_item_reask(c):
    """같은 문항 다중 턴(P04·P05·P06 prev_diff): 이전 환자 답이 이번 문항과 같은 문항이면 True.
    이때 환자는 모델이 쓴 상담원 턴(재질문 또는 되짚기)에 대답하므로 그 말을 current_question으로 쓴다."""
    if not c["prior_turns"]:
        return False
    items = {f["item_id"] for p in c["prior_turns"] if p.get("labels") for f in p["labels"]["facts"]}
    return items == {c["question_id"]}


def followup_flow(c):
    """정정(P05)과 충돌 prev_diff(P06): 상담원이 앞 답을 되짚고 다음 문항으로 넘어간 뒤 환자가 앞 답을 고치거나 다르게 말하는 흐름."""
    return c["pattern_type"] == "P05_correction" or (c["pattern_type"] == "P06_conflict" and c["subtype"] == "prev_diff")


def asked_item_for(c):
    """A 입력 question_id(상담원이 지금 묻고 있는 문항). 정정·충돌 흐름이면 앞 답 기준 다음 문항(건너뛰기 반영),
    다음 문항이 없으면(Q10) 그 문항 자체. 그 밖에는 canonical 문항."""
    if not followup_flow(c):
        return c["question_id"]
    st = labels.a_state(c["previous"])
    vals = []
    for k, v in st.items():
        item, rk, field = labels.parse_key(k)
        vals.append({"item_id": item, "field": field, "value": v["value"], "persist": True})
    nxt = labels.next_after(c["question_id"], vals)
    return c["question_id"] if nxt == labels.END else nxt


def arrange_turns(c, gen_turns, first_question, bank, followup):
    """대화 순서. 반환: (current_question, prior_turns).
    - 같은 문항(P04·P05·P06 prev_diff): [상담원 처음 질문(질문 뱅크), 환자 첫 답] + current_question = 모델이 쓴 상담원 말.
      정정·충돌 흐름이면 그 말(되짚기) 뒤에 다음 문항 질문(followup)을 붙인다.
    - 앞 문항 참조(P07, P06 r3): [상담원 앞 문항 질문(질문 뱅크), 환자 앞 문항 답] + current_question = 이번 문항 질문"""
    users = [t for t in gen_turns if t.get("role") == "user"]
    assistants = [t for t in gen_turns if t.get("role") == "assistant"]
    if not users:
        return first_question, []
    if same_item_reask(c):
        cq = assistants[-1]["content"].strip() if assistants else ""
        if followup and cq:
            cq = f"{cq.rstrip()} {followup}"
        return cq, [{"role": "assistant", "content": first_question}, users[0]]
    prior_item = next(f["item_id"] for p in c["prior_turns"] if p.get("labels") for f in p["labels"]["facts"])
    prev_q = pick_question(bank, prior_item, c["canonical_id"] + "_prev")
    return first_question, [{"role": "assistant", "content": prev_q}, users[0]]


def cell_quota(stage_target):
    """누적 목표 N에서 문항 x pattern 칸별 할당량 = round(10,000 배분 x N / 10,000)."""
    alloc = yaml.safe_load((ROOT / "patterns" / "allocation_10000.yaml").read_text())
    raw = {(i, p): n * stage_target / 10000 for i, cells in alloc["cells_10000"].items() for p, n in cells.items()}
    base = {k: math.floor(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - base[k], reverse=True)[:stage_target - sum(base.values())]:
        base[k] += 1
    return base


_FEASIBLE = {}


def feasible(item, pattern, plan):
    """그 칸에서 해당 plan의 정답을 만들 수 있는지(샘플러 시험 생성, LLM 호출 없음, DB 저장까지 확인)."""
    key = (item, pattern, plan)
    if key not in _FEASIBLE:
        ok = False
        rt = _rt()
        for k in range(3):
            c = build_canonical(item, pattern, 90000 + k, seed=SEED, required_plan=plan)
            if c is None:
                continue
            try:
                target = {g: [{x: y for x, y in e.items() if not x.startswith("_")} for e in c["target"][g]]
                          for g in ("facts", "intents", "relations", "unmapped_facts")}
                rt.check(c, target, "", c["expected"])
                ok = True
                break
            except checks.Reject:
                continue
        _FEASIBLE[key] = ok
    return _FEASIBLE[key]


_RT = None


def _rt():
    global _RT
    _RT = _RT or checks.RoundTrip()
    return _RT


def plan_quota(stage_target):
    """칸 할당량을 PLAN_MIX 비율로 정규화기 plan별로 나눈다. 만들 수 없는 plan의 몫은 같은 칸의 가능한 plan으로 옮긴다.
    (칸 단위로만 채우면 수율 높은 하위 유형만 살아남아 드문 plan이 3% 하한 아래로 내려간다.)"""
    out = {}
    for (item, p), q in cell_quota(stage_target).items():
        mix = {k: v for k, v in PLAN_MIX[p].items() if feasible(item, p, k)}
        if not mix:
            continue
        tot = sum(mix.values())
        raw = {k: q * v / tot for k, v in mix.items()}
        base = {k: math.floor(v) for k, v in raw.items()}
        for k in sorted(raw, key=lambda k: raw[k] - base[k], reverse=True)[:q - sum(base.values())]:
            base[k] += 1
        for k, n in base.items():
            if n:
                out[(item, p, k)] = n
    return out


def stage_quota(stage):
    """단계별 칸 할당량 {(문항, pattern, plan): 누적 목표}. T1(보충)은 S3와 같은 10,000 배분 몫에 P11 칸(NORM_CASE_QUOTA)을 더한다."""
    quota = plan_quota(STAGE_TARGET[stage])
    if stage == "T1":
        for (item, plan), n in NORM_CASE_QUOTA.items():
            quota[(item, "P11_norm_case", plan)] = n
    return quota


def accepted_by_cell():
    """본 생성 단계(S1~S4, 보충 T1)에서 통과한 시나리오 수를 (문항, pattern, 정규화기 plan)별로 센다. 파일럿·START는 세지 않는다."""
    out = Counter()
    shards = list((GEN / "shards").glob("S*_*.jsonl")) + list((GEN / "shards").glob("T*_*.jsonl"))
    for p in sorted(shards):
        for r in read_jsonl(p):
            if r["record_type"] == "turn":
                out[(r["question_id"], r["pattern_type"], r["normalizer_plan"])] += 1
    return out


def pick_styles(cid, k=MAX_VARIANTS_PER_CANONICAL):
    """비율(STYLE_TAGS share)에 맞춰 서로 다른 말투 k개를 고른다. STT 오류형은 상한을 넘지 않게 비율이 작다."""
    rng = random.Random(h32(SEED, "style", cid))
    tags, weights = list(STYLE_TAGS), [STYLE_TAGS[t]["share"] for t in STYLE_TAGS]
    chosen = []
    while len(chosen) < k:
        t = rng.choices(tags, weights)[0]
        if t not in chosen:
            chosen.append(t)
    return chosen


# ================================================================ 레코드

def make_record(c, v, stage, shard, ctx):
    """LoRA-A 1 + LoRA-B 1 시나리오 레코드 (README 4장 스키마)."""
    canonical_fact = [{k: f[k] for k in ("item_id", "field", "value", "precision", "semantic_status")}
                      for f in v["target"]["facts"]]
    return {
        "record_type": "turn",
        "scenario_id": f"{c['canonical_id']}_v{v['vi']}",
        "scenario_family": c["canonical_id"],
        "canonical_scenario_id": c["canonical_id"],
        "question_id": c["question_id"],
        "asked_item": ctx["asked_item"],
        "pattern_type": c["pattern_type"],
        "subtype": c["subtype"],
        "source": "new_sampled",
        "style_tag": v["style"],
        "previous_turns": ctx["prior_turns"],
        "user_utterance": v["utterance"],
        "lora_a_input": v["a_input"],
        "lora_a_target": v["a_target"],
        "lora_b_input": v["b_input"],
        "lora_b_target": {"response_text": v["response"]},
        "action": v["a_target"]["action"],
        "next_type": v["b_input"]["next"]["type"],
        "normalizer_plan": v["out"]["transition_plan"]["action"],
        "label_source": {"normalizer_output": v["out"], "raw_labels": v["target"], "canonical_fact": canonical_fact,
                         "ruleset_version": ctx["ruleset"]},
        "generation": {"stage": stage, "shard": shard, "prompt_version": prompts.PROMPT_VERSION,
                       "utterance": ctx["utt_gen"], "response": v["resp_gen"], "extract": v["ext_gen"],
                       "sampler_seed": c["sampler_seed"], "sampler_try": c["sampler_try"],
                       "required_plan": c.get("required_plan"), "start_greeting_used": ctx.get("start_used", False),
                       "created_at": time.strftime("%Y-%m-%d %H:%M:%S")},
        "validation": {"schema_valid": True, "normalizer_valid": True, "idempotent": True,
                       "extraction_core_match": True, "extraction_raw_match": v["raw_match"],
                       "evidence_fallback": v["evidence_fallback"],
                       "boundary_case": (not v["raw_match"]) or v["evidence_fallback"] > 0,
                       "db_roundtrip": True, "b_guard": True,
                       "b_judge": v["judge"], "utterance_judge": v["utterance_judge"], "human_review": "pending"},
    }


def make_start_record(idx, b_input, response, resp_gen, judge, stage, shard):
    """START(문진 시작) 레코드: LoRA-B만 있다. A 입력·정답은 null."""
    sid = f"start_{idx:04d}"
    return {
        "record_type": "start", "scenario_id": sid, "scenario_family": sid, "canonical_scenario_id": sid,
        "question_id": labels.FIRST_ITEM, "asked_item": labels.FIRST_ITEM, "pattern_type": "START", "subtype": "start",
        "source": "new_sampled", "style_tag": None, "previous_turns": [], "user_utterance": None,
        "lora_a_input": None, "lora_a_target": None,
        "lora_b_input": b_input, "lora_b_target": {"response_text": response},
        "action": "START", "next_type": "NEXT", "normalizer_plan": None, "label_source": None,
        "generation": {"stage": stage, "shard": shard, "prompt_version": prompts.PROMPT_VERSION, "response": resp_gen,
                       "created_at": time.strftime("%Y-%m-%d %H:%M:%S")},
        "validation": {"b_guard": True, "b_judge": judge, "human_review": "pending"},
    }


# ================================================================ 실행

class Runner:
    def __init__(self, stage, batch):
        self.stage, self.batch = stage, batch
        for d in ("shards", "rejects", "progress", "calls"):
            (GEN / d).mkdir(parents=True, exist_ok=True)
        self.progress_path = GEN / "progress" / f"{stage}.jsonl"
        self.reject_path = GEN / "rejects" / f"{stage}.jsonl"
        # 처리한 canonical: 모든 단계의 progress를 읽어 canonical 번호가 단계 사이에 겹치지 않게 한다.
        self.done = set()
        for path in sorted((GEN / "progress").glob("*.jsonl")):
            self.done |= {r["canonical_id"] for r in read_jsonl(path)}
        # 중복 판정·START 풀은 모든 단계의 통과 레코드를 합쳐서 쓴다(재시작해도 유지).
        self.seen, self.seen_b = set(), set()
        self.start_pool = []
        self.accepted = Counter()
        for p in sorted((GEN / "shards").glob("*.jsonl")):
            for r in read_jsonl(p):
                if r["record_type"] == "turn":
                    self.seen.add(checks.surface(r["user_utterance"]))
                else:
                    self.start_pool.append(r["lora_b_target"]["response_text"])
                self.seen_b.add(checks.surface(r["lora_b_target"]["response_text"]))
                self.accepted[(r["generation"]["stage"], r["record_type"])] += 1
        self.reasons = Counter()
        self.stats = Counter()
        self.ruleset = ruleset_version()
        self.rt = checks.RoundTrip()
        from llm import LLM
        # 프롬프트에 예시가 많이 들어가서(B NEXT 약 1만 자) 최대 길이를 16,384 토큰으로 둔다.
        self.llm = LLM(GEN / "calls" / f"{stage}.jsonl", seed=SEED, max_model_len=16384)
        self.bank = ensure_question_bank(self.llm)
        self.t_start = time.time()

    def reject(self, cid, vi, reason, detail=None):
        self.reasons[reason] += 1
        with open(self.reject_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"canonical_id": cid, "variant": vi, "reason": reason, "detail": detail},
                               ensure_ascii=False) + "\n")

    # ---------------------------------------------------------------- B 응답 생성 (공통)
    def generate_b(self, items):
        """items: [{"key", "b_input", ...}] -> 통과한 item 목록(각 item에 response·resp_gen·judge 채움).
        가드(checks.check_response) -> 판정(judge_b). 실패하면 말투·시드를 바꿔 최대 B_TRIES번 다시 만든다."""
        for s in items:
            s["b_fail"] = []
        pending, done = list(items), []
        for attempt in range(B_TRIES):
            if not pending:
                break
            reqs = []
            for s in pending:
                tone = prompts.B_TONES[(h32(SEED, "tone", s["key"]) + attempt) % len(prompts.B_TONES)]
                reqs.append((s["key"], prompts.response_messages(s["b_input"], tone, h32(SEED, "var", s["key"]) + attempt),
                             h32(SEED, "resp", s["key"], attempt)))
            temp = 1.0 if all(s["b_input"]["action"] == "START" for s in pending) else 0.8
            resp = self.llm.chat_json("response", reqs, prompts.B_SCHEMA, temp, 400)
            judge_reqs, after_guard = [], []
            for s in pending:
                parsed, gen = resp[s["key"]]
                s["resp_gen"] = dict(gen, attempt=attempt)
                try:
                    if not parsed or not parsed.get("response_text"):
                        raise checks.Reject("b_parse_error")
                    s["response"] = parsed["response_text"].strip()
                    checks.check_response(s["b_input"], s["response"])
                    if checks.surface(s["response"]) in self.seen_b:
                        raise checks.Reject("b_duplicate")
                    if s["b_input"]["action"] == "START" and self.near_start(s["response"]):
                        raise checks.Reject("b_start_near_duplicate")
                except checks.Reject as e:
                    s["b_fail"].append(e.args[0])
                    continue
                after_guard.append(s)
                judge_reqs.append((s["key"], prompts.judge_messages(s["b_input"], s["response"]),
                                   h32(SEED, "judge", s["key"], attempt)))
            jd = self.llm.chat_json("judge_b", judge_reqs, prompts.JUDGE_SCHEMA, 0.0, 700)
            for s in after_guard:
                parsed, _ = jd[s["key"]]
                if not parsed:
                    s["b_fail"].append("judge_parse_error")
                elif not parsed.get("action_ok"):
                    s["b_fail"].append("b_judge_action_mismatch")
                elif parsed.get("natural", 0) < 3:
                    s["b_fail"].append("b_judge_unnatural")
                elif checks.surface(s["response"]) in self.seen_b:
                    s["b_fail"].append("b_duplicate")
                else:
                    s["judge"] = dict(parsed, b_attempts=len(s["b_fail"]) + 1, b_failures=list(s["b_fail"]))
                    self.seen_b.add(checks.surface(s["response"]))
                    done.append(s)
            ok = {id(x) for x in done}
            pending = [s for s in pending if id(s) not in ok]
        return done, pending

    # ---------------------------------------------------------------- START
    @staticmethod
    def _greeting(text):
        """START 응답에서 마지막 질문 문장을 뺀 인사·안내 부분. 첫 질문(뇌졸중)은 늘 같아서 비교에서 뺀다."""
        parts = re.split(r"(?<=[.?!])\s+", text.strip())
        return " ".join(parts[:-1]) if len(parts) > 1 else ""

    def near_start(self, text, threshold=0.9):
        """이미 만든 START와 인사·안내 부분이 거의 같으면(글자 4-gram 90% 이상) True. 질문 부분의 반복은 허용한다."""
        mine = checks._grams(self._greeting(text))
        if len(mine) < 5:
            return False
        return any(len(mine & checks._grams(self._greeting(t))) / len(mine) >= threshold for t in self.start_pool)

    def run_start(self, target, shard):
        """START 레코드를 누적 target건이 될 때까지 만든다. 질문 문장은 Q1.D01 질문 표현을 돌아가며 쓴다."""
        have = len(self.start_pool)
        if have >= target:
            return 0
        n_new = 0
        idx = have
        tries = 0
        while len(self.start_pool) < target and tries < 8:
            need = target - len(self.start_pool)
            items = []
            for k in range(math.ceil(need * 1.5)):
                i = idx + k
                text = pick_question(self.bank, labels.FIRST_ITEM, f"start{i}")
                items.append({"key": f"start_{i:04d}", "idx": i, "b_input": labels.start_b_input(text)})
            idx += len(items)
            done, failed = self.generate_b(items)
            for s in failed:
                self.reject(s["key"], None, s["b_fail"][-1] if s["b_fail"] else "b_failed",
                            {"b_failures": s["b_fail"], "last_response": s.get("response")})
            recs = []
            for s in done:
                if len(recs) >= need:
                    break
                if self.near_start(s["response"]):   # 같은 배치에서 먼저 뽑힌 START와 거의 같으면 버린다
                    self.reject(s["key"], None, "b_start_near_duplicate", s["response"])
                    continue
                recs.append(make_start_record(s["idx"], s["b_input"], s["response"], s["resp_gen"], s["judge"], self.stage, shard))
                self.start_pool.append(s["response"])
            if recs:
                with open(GEN / "shards" / f"{self.stage}_{shard:04d}.jsonl", "a", encoding="utf-8") as f:
                    for r in recs:
                        f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            self.accepted[(self.stage, "start")] += len(recs)
            n_new += len(recs)
            tries += 1
        return n_new

    # ---------------------------------------------------------------- 시나리오 배치
    def run_batch(self, slots, shard):
        cans = []
        for slot in slots:
            item, p, idx = slot[:3]
            plan = slot[3] if len(slot) > 3 else None
            c = build_canonical(item, p, idx, seed=SEED, required_plan=plan)
            if c is None:
                self.reject(f"c_{item}_{p}_{idx:04d}", None, "sampler_failed")
                continue
            cans.append(c)
        ctxs, reqs = {}, []
        for c in cans:
            cid = c["canonical_id"]
            q = pick_question(self.bank, c["question_id"], cid)
            ctx = {"first_question": q, "question": q, "styles": pick_styles(cid), "ruleset": self.ruleset,
                   "reask_turn": same_item_reask(c), "asked_item": asked_item_for(c), "followup": None}
            # 문진 첫 문항(Q1.D01) 단일 턴은 절반을 START 응답(인사 + 첫 질문)으로 시작한다(실제 서비스의 첫 상담원 말).
            if c["question_id"] == labels.FIRST_ITEM and not c["prior_turns"] and self.start_pool and h32(SEED, "st", cid) % 2 == 0:
                ctx["question"] = ctx["first_question"] = self.start_pool[h32(SEED, "sp", cid) % len(self.start_pool)]
                ctx["start_used"] = True
            if followup_flow(c):
                if ctx["asked_item"] == c["question_id"]:      # 마지막 문항(Q10): 다음 질문 대신 마무리 말
                    ctx["followup"] = CLOSINGS[h32(SEED, "close", cid) % len(CLOSINGS)]
                else:
                    ctx["followup"] = pick_question(self.bank, ctx["asked_item"], cid + "_asked")
                c["followup_question"] = ctx["followup"]
            ctxs[cid] = ctx
            reqs.append((cid, prompts.utterance_messages(c, q, ctx["styles"], reask_turn=ctx["reask_turn"]),
                         h32(SEED, "utt", cid)))
        # 이전 턴 수가 canonical마다 달라서 같은 스키마끼리 묶어 호출한다
        utt, by_schema = {}, {}
        for r, c in zip(reqs, cans):
            by_schema.setdefault(len(c["prior_turns"]), []).append(r)
        for n_prior, rs in by_schema.items():
            utt.update(self.llm.chat_json("utterance", rs, prompts.utt_schema(n_prior, MAX_VARIANTS_PER_CANONICAL), 0.9, 2000))

        # 1차 검증: 화자·길이·질문/메모 베끼기·새 숫자·말투·중복, 이전 턴
        survivors = []
        for c in cans:
            cid = c["canonical_id"]
            parsed, gen = utt[cid]
            ctx = ctxs[cid]
            ctx["utt_gen"] = gen
            if not parsed:
                self.reject(cid, None, "utterance_parse_error")
                continue
            ctx["prior_turns"] = []
            if c["prior_turns"]:
                ctx["question"], ctx["prior_turns"] = arrange_turns(c, parsed.get("prior_turns", []), ctx["first_question"],
                                                                    self.bank, ctx["followup"])
                try:
                    checks.check_prior_turns(c, ctx["prior_turns"], ctx["question"], ctx["reask_turn"])
                except checks.Reject as e:
                    self.reject(cid, None, e.args[0], {"prior_turns": ctx["prior_turns"], "current_question": ctx["question"]})
                    continue
            for vi, var in enumerate(parsed.get("variants", [])[:MAX_VARIANTS_PER_CANONICAL]):
                self.stats["variants_generated"] += 1
                text = (var.get("utterance") or "").strip()
                style = ctx["styles"][vi] if vi < len(ctx["styles"]) else var.get("style")
                try:
                    checks.check_utterance(c, text, ctx["question"])
                    checks.check_utterance_v117(c, text, style)
                    sf = checks.surface(text)
                    if sf in self.seen:
                        raise checks.Reject("duplicate_surface")
                    self.seen.add(sf)
                except checks.Reject as e:
                    self.reject(cid, vi, e.args[0], text)
                    continue
                survivors.append({"c": c, "vi": vi, "style": style, "utterance": text, "key": f"{cid}_v{vi}"})

        # 2차: 역추출(정답을 보지 않음) -> 핵심 일치 -> 근거 조립 -> 정규화기 재실행 일치. 발화 자연스러움 판정도 같이.
        reqs = []
        for s in survivors:
            c = s["c"]
            ex_input = {"question_id": c["question_id"], "current_question": ctxs[c["canonical_id"]]["question"],
                        "user_utterance": s["utterance"]}
            if c["relevant_state"]:
                ex_input["relevant_state"] = c["relevant_state"]
            items = [c["question_id"]] + sorted(({k.split("/")[0] for k in c["relevant_state"]} | set(c.get("extract_items", [])))
                                                - {c["question_id"]})
            reqs.append((s["key"], prompts.extract_messages(ex_input, items), h32(SEED, "ext", s["key"])))
        ext = self.llm.chat_json("extract", reqs, prompts.EXTRACT_SCHEMA, 0.0, 1200)

        def nature(c):
            n = prompts.UTT_NATURE.get(c["pattern_type"], {})
            return n.get(c["subtype"]) or n.get("*", "상담원 질문에 대한 대답")
        ureqs = [(s["key"], prompts.utterance_judge_messages(ctxs[s["c"]["canonical_id"]]["question"], s["utterance"], s["style"],
                                                             nature(s["c"])),
                  h32(SEED, "ujudge", s["key"])) for s in survivors]
        uj = self.llm.chat_json("judge_utterance", ureqs, prompts.UJUDGE_SCHEMA, 0.0, 700)
        stage2 = []
        for s in survivors:
            parsed, gen = ext[s["key"]]
            s["ext_gen"] = gen
            try:
                uparsed, _ = uj[s["key"]]
                if not uparsed:
                    raise checks.Reject("utterance_judge_parse_error")
                if uparsed.get("failure") is not False or uparsed.get("natural", 0) < 3:
                    raise checks.Reject("utterance_unnatural")
                s["utterance_judge"] = uparsed
                if not parsed:
                    raise checks.Reject("extraction_parse_error")
                s["raw_match"], ext_clean = checks.check_extraction(s["c"], parsed, s["utterance"])
                s["target"], s["evidence_fallback"] = checks.assemble_target(s["c"], s["utterance"], ext_clean)
                s["out"] = checks.normalized(s["c"], s["target"], s["utterance"])
            except checks.Reject as e:
                self.reject(s["c"]["canonical_id"], s["vi"], e.args[0], s["utterance"])
                continue
            except Exception as e:   # 한 후보의 예외로 전체 배치를 멈추지 않는다(사유를 남김)
                self.reject(s["c"]["canonical_id"], s["vi"], "internal_error", f"{type(e).__name__}: {e}")
                continue
            stage2.append(s)

        # v2 LoRA-A 정답과 B 입력 (labels.py). 정규화기 결과를 옮길 뿐 값을 새로 정하지 않는다.
        for s in stage2:
            c, ctx = s["c"], ctxs[s["c"]["canonical_id"]]
            state = labels.a_state(c["previous"], pending_rows(c))
            s["a_input"] = labels.a_input(ctx["asked_item"], ctx["question"], s["utterance"], state)
            s["a_target"] = labels.a_target(ctx["asked_item"], s["out"], note=c.get("note"))
            nxt = s["a_target"]["next_item"]
            text = None if nxt == labels.END else pick_question(self.bank, nxt, s["key"] + "_next")
            s["b_input"] = labels.b_input(s["a_target"], ctx["asked_item"], s["utterance"], state, text)
        done, failed = self.generate_b(stage2)
        for s in failed:
            self.reject(s["c"]["canonical_id"], s["vi"], s["b_fail"][-1] if s["b_fail"] else "b_failed",
                        {"b_failures": s["b_fail"], "last_response": s.get("response"), "b_input": s["b_input"]})
        records = []
        for s in done:
            try:
                self.rt.check(s["c"], s["target"], s["utterance"], s["out"])
            except checks.Reject as e:
                self.reject(s["c"]["canonical_id"], s["vi"], e.args[0], s["utterance"])
                continue
            records.append(make_record(s["c"], s, self.stage, shard, ctxs[s["c"]["canonical_id"]]))

        if self.rt.issues:
            with open(GEN / "normalizer_issue_candidates.jsonl", "a", encoding="utf-8") as f:
                for x in self.rt.issues:
                    f.write(json.dumps(dict(x, stage=self.stage), ensure_ascii=False) + "\n")
            self.rt.issues.clear()
        if records:
            with open(GEN / "shards" / f"{self.stage}_{shard:04d}.jsonl", "a", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        with open(self.progress_path, "a", encoding="utf-8") as f:
            for slot in slots:
                item, p, idx = slot[:3]
                f.write(json.dumps({"canonical_id": f"c_{item}_{p}_{idx:04d}",
                                    "required_plan": slot[3] if len(slot) > 3 else None}) + "\n")
        self.accepted[(self.stage, "turn")] += len(records)
        self.stats["canonicals"] += len(slots)
        self.stats["accepted"] += len(records)
        return len(records)

    def status(self, state, total_slots, extra=None):
        elapsed = time.time() - self.t_start
        rep = {
            "stage": self.stage, "state": state, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": "Qwen3-30B-A3B-Instruct-2507", "prompt_version": prompts.PROMPT_VERSION, "ruleset": self.ruleset,
            "accepted_this_run": self.stats["accepted"],
            "accepted_by_stage": {f"{k[0]}/{k[1]}": v for k, v in sorted(self.accepted.items())},
            "turn_records_total": sum(v for k, v in self.accepted.items() if k[1] == "turn"),
            "start_records_total": len(self.start_pool),
            "canonicals_processed_this_run": self.stats["canonicals"], "slots_total": total_slots,
            "variants_generated": self.stats["variants_generated"],
            "variant_acceptance_rate": round(self.stats["accepted"] / max(self.stats["variants_generated"], 1), 4),
            "reject_reasons": dict(self.reasons.most_common()),
            "model_load_seconds": self.llm.load_seconds, "gpu_generate_seconds": round(self.llm.gpu_seconds, 1),
            "wall_seconds": round(elapsed, 1), "out_tokens": self.llm.out_tokens,
            "scenarios_per_hour": round(self.stats["accepted"] / max(elapsed, 1) * 3600, 1),
            "human_review": "pending",
        }
        rep.update(extra or {})
        (GEN / f"status_{self.stage}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
        print(json.dumps({k: rep[k] for k in ("stage", "state", "accepted_this_run", "turn_records_total",
                                              "start_records_total", "variant_acceptance_rate")}, ensure_ascii=False), flush=True)
        return rep


def pending_rows(c):
    """재질문 보완(P04)의 '앞 턴에서 비어 있거나 불분명했던 칸'을 A 입력 state에 값 null로 넣는다.
    앞 턴 정답을 정규화기에 돌려 MISSING·UNCLEAR가 된 행을 그대로 쓴다(정규화기 결과를 옮길 뿐)."""
    if c["pattern_type"] != "P04_reask_fill":
        return []
    from common import run_turn
    from sampler import TODAY
    first = next((p["labels"] for p in c["prior_turns"] if p.get("labels")), None)
    if not first:
        return []
    out = run_turn(first, CATALOG, {}, utterance=None, today=TODAY, turn_index=1)
    return [(v["item_id"], v["repeat_key"], v["field"], v["status"]) for v in out["normalized_values"]
            if v["status"] in ("MISSING", "UNCLEAR")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["pilot", "S1", "S2", "S3", "T1", "S4"])
    ap.add_argument("--batch", type=int, default=64, help="한 배치의 canonical 수")
    ap.add_argument("--pilot-per", type=int, default=8, help="파일럿: pattern마다 canonical 수(이미 처리한 번호는 건너뜀)")
    args = ap.parse_args()
    run = Runner(args.stage, args.batch)
    shard = len(list((GEN / "shards").glob(f"{args.stage}_*.jsonl")))
    # 1. START를 먼저 만든다(Q1.D01 시나리오의 첫 상담원 말로도 쓰기 때문)
    run.run_start(START_TARGET[args.stage], shard)
    shard += 1
    if args.stage == "pilot":
        slots = pilot_slots(args.pilot_per)
        todo = [s for s in slots if f"c_{s[0]}_{s[1]}_{s[2]:04d}" not in run.done]
        run.status("RUNNING", len(slots))
        for i in range(0, len(todo), args.batch):
            if (GEN / "STOP").exists():
                run.status("STOPPED_BY_FILE", len(slots))
                return
            run.run_batch(todo[i:i + args.batch], shard)
            shard += 1
            run.status("RUNNING", len(slots))
        run.status("STAGE_FINISHED", len(slots))
        return
    # 2. 본 생성: 칸별 누적 할당량을 채울 때까지, 모자란 칸에만 canonical을 더 만든다.
    quota = stage_quota(args.stage)
    used, tried = Counter(), Counter()
    for cid in run.done:
        body = cid[2:]
        head, _ = body.rsplit("_", 1)
        item, p = head.split("_P", 1)
        used[(item, "P" + p)] += 1
    run.status("RUNNING", sum(quota.values()))
    start_have = accepted_by_cell()
    early_stopped = {}
    while True:
        if (GEN / "STOP").exists():
            run.status("STOPPED_BY_FILE", sum(quota.values()))
            return
        have = accepted_by_cell()
        batch = []
        for key, q in sorted(quota.items()):
            item, p, plan = key
            deficit = q - have[key]
            if deficit <= 0:
                continue
            if tried[key] >= EARLY_MIN_TRIES:
                rate = (have[key] - start_have[key]) / (tried[key] * MAX_VARIANTS_PER_CANONICAL)
                if rate < EARLY_MIN_YIELD:
                    early_stopped["|".join(key)] = {"tried_canonicals": tried[key], "variant_yield": round(rate, 4)}
                    continue
            cap = MAX_CANON_FACTOR * math.ceil(q / MAX_VARIANTS_PER_CANONICAL) + 2
            need = min(math.ceil(deficit / EXPECTED_PER_CANON), cap - tried[key])
            for _ in range(max(0, need)):
                idx = used[(item, p)]
                while f"c_{item}_{p}_{idx:04d}" in run.done:
                    idx += 1
                batch.append((item, p, idx, plan))
                used[(item, p)] = idx + 1
                tried[key] += 1
        if not batch:
            break
        for i in range(0, len(batch), args.batch):
            if (GEN / "STOP").exists():
                run.status("STOPPED_BY_FILE", sum(quota.values()))
                return
            run.run_batch(batch[i:i + args.batch], shard)
            shard += 1
            run.done |= {f"c_{a}_{b}_{c:04d}" for a, b, c, _ in batch[i:i + args.batch]}
            run.status("RUNNING", sum(quota.values()))
    have = accepted_by_cell()
    short = {"|".join(k): q - have[k] for k, q in quota.items() if have[k] < q}
    run.status("STAGE_FINISHED" if not short else "STAGE_FINISHED_WITH_SHORTFALL", sum(quota.values()),
               {"cell_shortfall": short, "cells_total": len(quota), "early_stopped_cells": early_stopped})


if __name__ == "__main__":
    import os
    import traceback
    try:
        main()
        code = 0
    except BaseException:
        traceback.print_exc()
        code = 1
    # vLLM 엔진 하위 프로세스가 남아 GPU를 잡고 있지 않도록 프로세스를 바로 끝낸다.
    __import__("sys").stdout.flush()
    os._exit(code)
