"""생성 shard -> 중복 제거·누수 검사·family 분할·학습 파일·부분집합·검수 큐·분포 보고 (데이터셋 v2).

실행: python -B scripts/build_final.py --upto T1 [--include-pilot]   (T1 = S3 + 보충, 2026-10-13)

처리
1. 중복 제거 (칸별 할당량으로 자르기 전에 전체에서 먼저 한다)
   - 시나리오(turn): 환자 발화의 정확 일치·정규화 문자열 일치(checks.surface), MinHash 근접 중복(글자 3-gram, 128 permutation,
     LSH 32 band x 4 row, 추정 Jaccard >= 0.85면 나중 레코드를 뺌)
   - START: 응답 문장의 정규화 문자열 일치
2. 할당량: 칸(문항, pattern, 정규화기 plan)별 누적 할당량까지만 쓰고 넘는 것은 예비분(reserve)으로 남긴다. START는 START_TARGET까지.
3. family 간 누수: 서로 다른 family의 발화가 Jaccard >= 0.70이면 두 family를 한 묶음으로 같은 split에 둔다.
4. 분할: 묶음 해시로 train/val/test = 80/10/10. test에 31개 문항·10개 pattern이 각각 최소 1 family 있도록 train에서 옮긴다.
5. 출력 (data/final/)
   - {train,val,test}.jsonl: 마스터 레코드(README 4장) + split
   - lora_a_{split}.jsonl: messages(system=A_TRAIN_SYSTEM, user=A 입력 JSON, assistant=A 정답 JSON). START는 넣지 않는다.
   - lora_b_{split}.jsonl: messages(system=B_TRAIN_SYSTEM, user=B 입력 JSON, assistant=응답 문장). START 포함.
   - subsets/{1000,2500,5000,10000}_manifest.txt: 생성 순서 앞에서부터 N개 시나리오 중 train scenario_id (nested)
   - review/review_queue.csv: pattern x 문항 묶음 층마다 5건 + 전체 5% + 역추출 경계 판정 전수 + START 10건
   - reports/distribution_{upto}.json: 배분 대비 실제, 문항 최소량, action·next 분포, plan 하한, 말투 비율
human_review: 검수 큐에 든 것은 pending, 나머지는 auto_only. 사람 검수 페이지 판정이 있으면 human_ok/human_flagged/human_edited
(human_edits.py). 이 스크립트는 검수 결과를 지어내지 않는다.
"""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict

import numpy as np
import yaml

import checks
import human_edits
import prev_state
import prompts
from common import ROOT, read_jsonl, write_jsonl
from taxonomy import ITEM_MIN_10000, PATTERNS, START_TARGET, STT_MAX_SHARE, STYLE_MIN_SHARE, STYLE_TAGS

GEN, FINAL = ROOT / "data" / "generated", ROOT / "data" / "final"
STAGES = ["pilot", "S1", "S2", "S3", "T1", "S4"]
TARGET = {"S1": 1000, "S2": 2500, "S3": 5000, "T1": 5000, "S4": 10000}   # T1: S3 보충 + P11 칸(pipeline.stage_quota)
NEAR_DUP, LEAK = 0.85, 0.70
NPERM, BANDS = 128, 32
PLAN_FLOOR = 0.03
ACTIONS = ["NEXT", "CORRECT", "REASK", "CONFIRM", "HOLD", "SKIP", "REDIRECT"]
MASK = (1 << 61) - 1


def h(s):
    return int(hashlib.sha256(s.encode()).hexdigest()[:15], 16)


# ================================================================ MinHash

_rng = np.random.RandomState(20261013)
_A = _rng.randint(1, MASK, NPERM, dtype=np.int64)
_B = _rng.randint(0, MASK, NPERM, dtype=np.int64)


def minhash(text):
    s = checks.surface(text)
    grams = {s[i:i + 3] for i in range(max(len(s) - 2, 1))}
    x = np.array([h(g) & 0x7FFFFFFF for g in grams], dtype=np.int64)
    return ((np.outer(x, _A) + _B) % MASK).min(axis=0)


def jaccard(a, b):
    return float((a == b).mean())


def candidate_pairs(sigs):
    rows = NPERM // BANDS
    buckets = defaultdict(list)
    for i, s in enumerate(sigs):
        for b in range(BANDS):
            buckets[(b, s[b * rows:(b + 1) * rows].tobytes())].append(i)
    pairs = set()
    for idx in buckets.values():
        if 1 < len(idx) < 200:
            for x in range(len(idx)):
                for y in range(x + 1, len(idx)):
                    pairs.add((idx[x], idx[y]))
    return pairs


# ================================================================ 분할

class DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def split_groups(records, dsu):
    groups = defaultdict(list)
    for r in records:
        groups[dsu.find(r["scenario_family"])].append(r)
    split = {}
    for g in groups:
        x = h("split|" + g) % 100
        split[g] = "train" if x < 80 else "val" if x < 90 else "test"
    # test 층화: 모든 문항과 모든 pattern이 최소 1 family (train에서 가장 작은 묶음을 옮김)
    for key in ("question_id", "pattern_type"):
        present = {r[key] for g, rs in groups.items() if split[g] == "test" for r in rs}
        for value in sorted({r[key] for r in records} - present):
            cands = sorted((len(rs), g) for g, rs in groups.items()
                           if split[g] == "train" and any(r[key] == value for r in rs))
            if cands:
                split[cands[0][1]] = "test"
    return groups, split


# ================================================================ 학습 파일

def lora_a_row(r):
    return {"scenario_id": r["scenario_id"], "split": r["split"], "human_review": r["validation"]["human_review"],
            "messages": [{"role": "system", "content": prompts.A_TRAIN_SYSTEM},
                         {"role": "user", "content": prompts.js(r["lora_a_input"])},
                         {"role": "assistant", "content": prompts.js(r["lora_a_target"])}]}


def lora_b_row(r):
    return {"scenario_id": r["scenario_id"], "split": r["split"], "human_review": r["validation"]["human_review"],
            "messages": [{"role": "system", "content": prompts.B_TRAIN_SYSTEM},
                         {"role": "user", "content": prompts.js(r["lora_b_input"])},
                         {"role": "assistant", "content": r["lora_b_target"]["response_text"]}]}


# ================================================================ 분포 검사

def distribution(turns, starts, upto):
    alloc = yaml.safe_load((ROOT / "patterns" / "allocation_10000.yaml").read_text())
    n = len(turns)
    scale = TARGET.get(upto, n) / 10000
    pat = Counter(r["pattern_type"] for r in turns)
    items = Counter(r["question_id"] for r in turns)
    acts = Counter(r["action"] for r in turns)
    nexts = Counter(r["next_type"] for r in turns)
    styles = Counter(r["style_tag"] for r in turns)
    item_min = math.floor(ITEM_MIN_10000 * scale)
    return {
        "turn_scenarios": n, "start_records": len(starts), "families": len({r["scenario_family"] for r in turns}),
        "pattern_actual_vs_target": {p: {"actual": pat[p], "share": round(pat[p] / max(n, 1), 4),
                                         "target_share": PATTERNS[p]["proposed"]} for p in PATTERNS},
        "item_min_required": item_min,
        "item_below_min": {i: items[i] for i in alloc["items_10000"] if items[i] < item_min},
        "action_share": {a: round(acts[a] / max(n, 1), 4) for a in ACTIONS},
        "action_floor_violations": [a for a in ACTIONS if acts[a] / max(n, 1) < PLAN_FLOOR],
        "next_type_count": dict(nexts),
        "end_by_action": dict(Counter(r["action"] for r in turns if r["next_type"] == "END")),
        "normalizer_plan_share": {k: round(v / max(n, 1), 4) for k, v in Counter(r["normalizer_plan"] for r in turns).items()},
        "style_share": {s: round(styles[s] / max(n, 1), 4) for s in STYLE_TAGS},
        "style_violations": [s for s in STYLE_TAGS if styles[s] / max(n, 1) < STYLE_MIN_SHARE]
                            + (["stt_noise_over_max"] if styles["stt_noise"] / max(n, 1) > STT_MAX_SHARE else []),
        "b_response_unique_ratio": round(len({r["lora_b_target"]["response_text"] for r in turns}) / max(n, 1), 4),
        "utterance_unique_ratio": round(len({r["user_utterance"] for r in turns}) / max(n, 1), 4),
        "boundary_cases": sum(r["validation"]["boundary_case"] for r in turns),
        "start_greeting_in_a_inputs": sum(r["generation"].get("start_greeting_used", False) for r in turns),
    }


# ================================================================ 검수 큐

def item_group(qid):
    """검수 층용 문항 묶음: 질환·가족력·B형간염·흡연·음주·신체활동 6개."""
    if qid.startswith("Q1."):
        return "disease"
    if qid.startswith("Q2."):
        return "family_history"
    if qid == "Q3":
        return "hepatitis_b"
    if qid.startswith(("Q4", "Q5", "Q6")):
        return "smoking"
    if qid.startswith("Q7"):
        return "alcohol"
    return "activity"


def review_queue(turns, starts):
    layers = defaultdict(list)
    for r in turns:
        layers[(r["pattern_type"], item_group(r["question_id"]))].append(r)
    picked = {}
    target_total = max(1, round(len(turns) * 0.05))
    for key, rs in sorted(layers.items()):
        for r in sorted(rs, key=lambda r: h("review|" + r["scenario_id"]))[:5]:
            picked[r["scenario_id"]] = "stratified_sample"
    rest = sorted((r for r in turns if r["scenario_id"] not in picked), key=lambda r: h("review2|" + r["scenario_id"]))
    for r in rest[:max(0, target_total - len(picked))]:
        picked[r["scenario_id"]] = "random_fill"
    for r in turns:
        if r["validation"]["boundary_case"]:
            picked[r["scenario_id"]] = picked[r["scenario_id"]] + "+boundary" if r["scenario_id"] in picked else "boundary_full"
    for r in sorted(starts, key=lambda r: h("review|" + r["scenario_id"]))[:10]:
        picked[r["scenario_id"]] = "start_sample"
    path = ROOT / "review" / "review_queue.csv"
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario_id", "split", "why", "question_id", "asked_item", "pattern_type", "subtype", "style_tag",
                    "previous_turns", "current_question", "user_utterance", "lora_a_target", "lora_b_input", "lora_b_response",
                    "decision(KEEP/FIX/HOLD)", "reviewer", "notes"])
        for r in turns + starts:
            why = picked.get(r["scenario_id"])
            if not why:
                continue
            w.writerow([r["scenario_id"], r["split"], why, r["question_id"], r["asked_item"], r["pattern_type"], r["subtype"],
                        r["style_tag"], " / ".join(f"{x['role']}: {x['content']}" for x in r["previous_turns"]),
                        (r["lora_a_input"] or {}).get("current_question", ""), r["user_utterance"] or "",
                        prompts.js(r["lora_a_target"]) if r["lora_a_target"] else "", prompts.js(r["lora_b_input"]),
                        r["lora_b_target"]["response_text"], "", "", ""])
    return picked


def order_key(r):
    return (STAGES.index(r["generation"]["stage"]), r["generation"]["shard"], r["scenario_id"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", required=True, choices=STAGES)
    ap.add_argument("--include-pilot", action="store_true")
    args = ap.parse_args()
    stages = STAGES[:STAGES.index(args.upto) + 1]
    if not args.include_pilot and args.upto != "pilot":
        stages = [s for s in stages if s != "pilot"]
    records = []
    for st in stages:
        for p in sorted(GEN.glob(f"shards/{st}_*.jsonl")):
            records += read_jsonl(p)
    n0 = len(records)
    records.sort(key=order_key)
    # 2026-10-13: 음주량 '기억 안 나요' 보류의 사유 이름을 labels.reason_of와 같게 맞춘다(BEVERAGE_MISSING -> UNCERTAIN).
    # 그 전에 만든 레코드만 해당한다. 값·동작·다음 문항·응답은 그대로이고 사유 이름만 바뀐다.
    relabeled = 0
    for r in records:
        a = r.get("lora_a_target") or {}
        if r["record_type"] == "turn" and a.get("action") == "HOLD" and a.get("reason") == "BEVERAGE_MISSING":
            a["reason"] = "UNCERTAIN"
            r["lora_b_input"]["reason"] = "UNCERTAIN"
            r["validation"]["relabel"] = "hold_reason_beverage_missing_to_uncertain_2026-10-13"
            relabeled += 1
    turns = [r for r in records if r["record_type"] == "turn"]
    starts = [r for r in records if r["record_type"] == "start"]

    # 0. 2026-10-14: LoRA-A state를 서비스 규칙(지금 문항 + 직전 문항 + 참조 원천, SQL.md 7.1)으로 넓힌다.
    # 넓힌 state로 정규화기를 다시 돌려 정답·B 입력이 그대로인 흐름만 쓰고, 끝내 달라지는 레코드는 뺀다(prev_state.py).
    prev_state_dropped = 0
    widened = []
    for r in turns:
        r2 = prev_state.augment(r)
        if r2 is None:
            prev_state_dropped += 1
            continue
        widened.append(r2)
    turns = widened

    # 0-2. 2026-10-14: 사람 검수 페이지에서 직접 고친 내용(review/human_edits.json)을 반영한다(human_edits.py).
    # 제외 표시는 여기서 빼므로 아래 할당량 선택에서 예비분이 그 칸을 채운다.
    from pipeline import pick_question
    bank = json.loads((ROOT / "data" / "question_bank.json").read_text())
    edited, human_rep = human_edits.apply(turns + starts, bank, pick_question)
    turns = [r for r in edited if r["record_type"] == "turn"]
    starts = [r for r in edited if r["record_type"] == "start"]

    # 1. 정확·정규화 문자열 중복
    dropped = Counter()
    seen, kept = set(), []
    for r in turns:
        k = checks.surface(r["user_utterance"])
        if k in seen:
            dropped["surface_dup"] += 1
            continue
        seen.add(k)
        kept.append(r)
    turns = kept
    seen, kept = set(), []
    for r in starts:
        k = checks.surface(r["lora_b_target"]["response_text"])
        if k in seen:
            dropped["start_dup"] += 1
            continue
        seen.add(k)
        kept.append(r)
    starts = kept[:START_TARGET.get(args.upto, len(kept))]
    # 1-2. MinHash 근접 중복
    sigs = [minhash(r["user_utterance"]) for r in turns]
    remove = set()
    for i, j in sorted(candidate_pairs(sigs)):
        if i not in remove and j not in remove and jaccard(sigs[i], sigs[j]) >= NEAR_DUP:
            remove.add(max(i, j))
            dropped["minhash_near_dup"] += 1
    sig_of = {r["scenario_id"]: sigs[k] for k, r in enumerate(turns) if k not in remove}
    turns = [r for k, r in enumerate(turns) if k not in remove]

    # 2. 칸별 누적 할당량까지만 쓴다. 넘는 것은 지우지 않고 예비분으로 남긴다.
    reserve = []
    if args.upto in TARGET:
        from pipeline import stage_quota
        quota = stage_quota(args.upto)
        kept, used = [], Counter()
        for r in turns:
            cell = (r["question_id"], r["pattern_type"], r["normalizer_plan"])
            if r["generation"]["stage"] != "pilot" and used[cell] >= quota.get(cell, 0):
                reserve.append(r)
                continue
            used[cell] += 1
            kept.append(r)
        turns = kept

    # 3. family 간 누수
    sigs = [sig_of[r["scenario_id"]] for r in turns]
    dsu = DSU()
    for r in turns + starts:
        dsu.find(r["scenario_family"])
    leaks = 0
    for i, j in sorted(candidate_pairs(sigs)):
        if turns[i]["scenario_family"] != turns[j]["scenario_family"] and jaccard(sigs[i], sigs[j]) >= LEAK:
            dsu.union(turns[i]["scenario_family"], turns[j]["scenario_family"])
            leaks += 1

    # 4. 분할 (START는 해시로만 나눈다)
    groups, split = split_groups(turns, dsu)
    for g, rs in groups.items():
        for r in rs:
            r["split"] = split[g]
    for r in starts:
        x = h("split|" + r["scenario_id"]) % 100
        r["split"] = "train" if x < 80 else "val" if x < 90 else "test"
    picked = review_queue(turns, starts)
    for r in turns + starts:
        if not r["validation"].get("human_review", "").startswith("human_"):   # 사람 판정은 덮지 않는다
            r["validation"]["human_review"] = "pending" if r["scenario_id"] in picked else "auto_only"

    FINAL.mkdir(parents=True, exist_ok=True)
    for s in ("train", "val", "test"):
        t_rows = [r for r in turns if r["split"] == s]
        s_rows = [r for r in starts if r["split"] == s]
        write_jsonl(FINAL / f"{s}.jsonl", t_rows + s_rows)
        write_jsonl(FINAL / f"lora_a_{s}.jsonl", [lora_a_row(r) for r in t_rows])
        write_jsonl(FINAL / f"lora_b_{s}.jsonl", [lora_b_row(r) for r in t_rows + s_rows])
    # nested 부분집합 (시나리오 수 기준, START는 비율대로 함께 넣는다)
    order = sorted(turns, key=order_key)
    (FINAL / "subsets").mkdir(exist_ok=True)
    subset_sizes = {}
    for size in (1000, 2500, 5000, 10000):
        if size > len(order) and size != min(x for x in (1000, 2500, 5000, 10000) if x >= len(order)):
            continue
        n_start = round(len(starts) * min(size, len(order)) / max(len(order), 1))
        ids = [r["scenario_id"] for r in order[:size] if r["split"] == "train"] + \
              [r["scenario_id"] for r in starts[:n_start] if r["split"] == "train"]
        (FINAL / "subsets" / f"{size}_manifest.txt").write_text("\n".join(ids) + "\n")
        subset_sizes[size] = {"turns_in_prefix": min(size, len(order)), "train_ids": len(ids), "complete": len(order) >= size}

    fam_split = defaultdict(set)
    for r in turns:
        fam_split[r["scenario_family"]].add(r["split"])
    rep = distribution(turns, starts, args.upto)
    rep.update({
        "input_records": n0, "reserve_over_quota": len(reserve), "dropped": dict(dropped), "relabeled_hold_reason": relabeled,
        "prev_state_dropped": prev_state_dropped, "human_edits": human_rep, "a_state_size": dict(sorted(Counter(len(r["lora_a_input"]["state"]) for r in turns).items())),
        "cross_family_leak_links": leaks,
        "split_counts": dict(Counter(r["split"] for r in turns)),
        "start_split_counts": dict(Counter(r["split"] for r in starts)),
        "families_in_multiple_splits": sum(len(v) > 1 for v in fam_split.values()),
        "test_items": len({r["question_id"] for r in turns if r["split"] == "test"}),
        "test_patterns": len({r["pattern_type"] for r in turns if r["split"] == "test"}),
        "review_queue": dict(Counter(v.split("+")[0] for v in picked.values())), "subsets": subset_sizes,
        "thresholds": {"near_dup_jaccard": NEAR_DUP, "leak_jaccard": LEAK, "minhash_perm": NPERM, "lsh_bands": BANDS},
    })
    write_jsonl(GEN / f"reserve_after_{args.upto}.jsonl", reserve)
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / f"distribution_{args.upto}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
