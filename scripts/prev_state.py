"""LoRA-A 입력 state를 서비스가 실제로 만드는 범위로 채운다 (2026-10-14).

배경: 생성 단계는 state에 '정답을 정하는 데 필요한 값'(정정·충돌·재질문·앞 답 참조)만 넣어서 72%가 빈 state였다.
서비스는 이번 턴이 정정인지 미리 모르므로 매 턴 같은 규칙으로 state를 만든다. 그 규칙(SQL.md 7.1)을 학습 데이터에도 맞춘다.

서비스 state 규칙 (매 턴 같음)
- 지금 문항(question_id)의 저장 값과 재질문 중인 칸
- 직전에 물은 문항(대화 순서, 건너뛰기 반영)의 저장 값
- 참조 원천 문항(taxonomy.REF_SOURCE, 예: Q10 -> Q9_1)의 저장 값. '아까랑 같아요'가 가리킬 수 있는 문항이다.
  모름·거절로 넘어간 문항은 저장 값이 없으므로 state에 나오지 않는다.

방법 (레코드마다, scenario_id로 정한 고정 시드)
1. 이미 state에 있는 문항 값은 그대로 두고, 그 문항들과 참조 원천을 지나 지금 문항에 닿는 대화 흐름을 앞에서부터 만든다.
   빈 문항은 sampler.normal_facts(평범한 답)를 정규화기에 돌려 저장 값을 얻고, 일부(HELD_SHARE)는 보류로 두어 값이 없게 한다.
   흐름은 labels.next_after(건너뛰기)를 따라가며, 지금 문항에 정확히 닿아야 쓴다.
2. 넓힌 state로 정규화기를 다시 돌린다. 정규화 핵심 결과·LoRA-A 정답·LoRA-B 입력이 원래 state로 돌린 것과 모두 같아야 한다.
   다르면 다른 흐름으로 다시 뽑고(MAX_TRIES), 끝내 다르면 그 레코드는 쓰지 않는다(정답이 state에 따라 바뀌는 경우).
정규화기 코드·규칙은 바꾸지 않는다(읽기·실행만). 발화·B 응답 문장은 그대로 둔다.
"""
import copy
import hashlib
import random

import labels as L
from common import CATALOG, run_turn
from sampler import TODAY, core, normal_facts, strip_say
from sampler import labels as make_labels
from taxonomy import REF_SOURCE

HELD_SHARE = 0.06    # 직전 문항을 모름·거절로 넘긴 경우의 비율(최종 데이터 HOLD+SKIP 약 8%에 맞춘 근사)
MAX_TRIES = 30
VERSION = "prev_state_2026-10-14"


def _rng(sid, t):
    return random.Random(int(hashlib.sha256(f"prev_state|{sid}|{t}".encode()).hexdigest()[:12], 16))


def _sample_rows(item, rng):
    """item의 평범한 답 -> 정규화기 저장 값 [(field_id, repeat_key, value)]."""
    out = run_turn(strip_say(make_labels(normal_facts(item, rng))), CATALOG, {}, utterance=None, today=TODAY, turn_index=1)
    return [(f"{v['item_id']}.{v['field']}", v["repeat_key"], v["value"]) for v in out["normalized_values"]
            if v["persist"] and v["status"] == "ANSWERED"]


def _as_values(rows):
    return [{"item_id": fid.rsplit(".", 1)[0], "field": fid.rsplit(".", 1)[1], "value": v, "persist": True}
            for fid, _, v in rows]


def walk(asked, fixed, rng):
    """asked에 닿는 대화 흐름 하나. fixed: {문항: 저장 값 rows} (원래 state에 있던 지금 문항 밖 값).
    반환: {문항: rows} 중 state에 넣을 직전 문항·참조 원천만. 흐름이 asked에 닿지 않으면 None. 첫 문항이면 {}."""
    seq = L.order()
    ai = seq.index(asked)
    if ai == 0:
        return {}
    ref = REF_SOURCE.get(asked)
    must = set(fixed)
    anchors = must | ({ref} if ref else set())
    start = min(anchors, key=seq.index) if anchors else rng.choice(seq[max(0, ai - 3):ai])
    if seq.index(start) >= ai:
        return None
    visited, cur = {}, start
    while cur != asked:
        if cur == L.END or seq.index(cur) > ai:
            return None
        if cur in fixed:
            rows = fixed[cur]
        elif rng.random() < HELD_SHARE:
            rows = []                       # 모름·거절로 넘어감: 저장 값 없음, 건너뛰기도 없음
        else:
            rows = _sample_rows(cur, rng)
        visited[cur] = rows
        cur = L.next_after(cur, _as_values(rows))
    if not must <= set(visited):
        return None
    prev = list(visited)[-1]
    keep = [prev] + ([ref] if ref in visited and ref != prev else [])
    return {i: visited[i] for i in keep}


def _split_state(state, asked):
    """원래 state -> (지금 문항 밖 확정값 {문항: rows}, 전체 확정 rows, 재질문 칸 rows)."""
    other, answered, pending = {}, [], []
    for k, s in state.items():
        item, rk, field = L.parse_key(k)
        if s["status"] == "ANSWERED":
            row = (f"{item}.{field}", rk, s["value"])
            answered.append(row)
            if item != asked:
                other.setdefault(item, []).append(row)
        else:
            pending.append((item, rk, field, s["status"]))
    return other, answered, pending


def _derive(r, rows, pending):
    """state 저장 값 rows로 정규화기를 돌려 (state, 정규화 결과, A 정답, B 입력)을 만든다."""
    a_in, a_out, b_in = r["lora_a_input"], r["lora_a_target"], r["lora_b_input"]
    asked = a_in["question_id"]
    state = L.a_state(rows, pending)
    prev = {(fid, rk): v for fid, rk, v in rows}
    out = run_turn(r["label_source"]["raw_labels"], CATALOG, prev, utterance=a_in["user_utterance"], today=TODAY, turn_index=1)
    a2 = L.a_target(asked, out, note=a_out.get("note"))
    nxt = b_in.get("next") or {}
    b2 = L.b_input(a2, asked, a_in["user_utterance"], state, nxt.get("text"))
    return state, out, a2, b2


def augment(r):
    """turn 레코드 하나의 state를 서비스 규칙으로 넓힌 새 레코드. 정답이 바뀌지 않는 흐름이 없으면 None.
    반환 레코드: lora_a_input.state만 바뀌고 validation.prev_state에 넣은 문항·시도 횟수가 남는다."""
    a_in = r["lora_a_input"]
    asked = a_in["question_id"]
    other, answered, pending = _split_state(a_in["state"], asked)
    base = _derive(r, answered, pending)
    for t in range(MAX_TRIES):
        add = walk(asked, other, _rng(r["scenario_id"], t))
        if add is None:
            continue
        new_rows = list(answered) + [row for item, rows in add.items() if item not in other for row in rows]
        got = _derive(r, new_rows, pending)
        if core(got[1]) == core(base[1]) and got[2] == base[2] and got[3] == base[3]:
            r2 = copy.deepcopy(r)
            r2["lora_a_input"]["state"] = got[0]
            r2["validation"]["prev_state"] = {"version": VERSION, "try": t,
                                              "added_items": [i for i in add if i not in other],
                                              "held_items": [i for i, rows in add.items() if not rows]}
            return r2
    return None
