"""배분표 생성: pattern 비율 x 문항 가중치 -> patterns/allocation_10000.yaml

계산 방법
1. 문항 목표: 31개 문항에 최소 150(10,000 기준)을 먼저 주고, 나머지 5,350을 ITEM_WEIGHTS 비율로 나눈다.
2. pattern 목표: 비율 x 10,000 (draft 초안 / proposed 조정안 두 가지 모두 계산).
3. 문항 x pattern 칸: 적용 불가 칸(taxonomy.applicable)을 0으로 두고, 행(문항)·열(pattern) 합이
   목표에 맞도록 반복 비례 조정(IPF)한 뒤 정수로 반올림한다.
4. 예상 plan 분포: 칸 수 x PLAN_MIX(가정값)로 추정해 9종 plan 하한 3% 위반 여부를 표시한다.
5. 5,000 배분은 10,000 칸 값의 절반(내림 후 남는 수는 큰 소수부부터)으로 만든다.
   S1~S4 부분집합이 서로 포함되도록(nested) 하기 위해 같은 칸 구조를 쓴다.

부작용: patterns/allocation_10000.yaml을 새로 쓴다. 다른 파일은 고치지 않는다.
"""
import json
import math

import yaml

from common import ROOT
from taxonomy import (ITEM_MIN_10000, ITEM_WEIGHTS, MAX_VARIANTS_PER_CANONICAL, MULTI_TURN, PATTERNS,
                      PLAN_MIX, PLANS, STT_MAX_SHARE, STYLE_MIN_SHARE, STYLE_TAGS, applicable)

TOTAL = 10000
PLAN_FLOOR = 0.03


def item_targets(total):
    """문항별 목표 수. 최소량 + 가중치 비례 나머지. 정수 합이 total이 되도록 큰 소수부부터 1씩 더한다."""
    floor = ITEM_MIN_10000 * total / 10000
    rest = total - floor * len(ITEM_WEIGHTS)
    wsum = sum(ITEM_WEIGHTS.values())
    raw = {i: floor + rest * w / wsum for i, w in ITEM_WEIGHTS.items()}
    return largest_remainder(raw, total)


def largest_remainder(raw, total):
    base = {k: math.floor(v) for k, v in raw.items()}
    left = total - sum(base.values())
    for k in sorted(raw, key=lambda k: raw[k] - base[k], reverse=True)[:left]:
        base[k] += 1
    return base


def ipf(rows, cols, iters=500):
    """적용 가능 칸만 1로 시작해 행 합=문항 목표, 열 합=pattern 목표가 되도록 번갈아 비례 조정한다."""
    m = {(i, p): 1.0 if applicable(p, i) else 0.0 for i in rows for p in cols}
    for _ in range(iters):
        for i in rows:
            s = sum(m[i, p] for p in cols)
            for p in cols:
                m[i, p] *= rows[i] / s if s else 0
        for p in cols:
            s = sum(m[i, p] for i in rows)
            for i in rows:
                m[i, p] *= cols[p] / s if s else 0
    return m


def allocate(share_key):
    rows = item_targets(TOTAL)
    cols = largest_remainder({p: PATTERNS[p][share_key] * TOTAL for p in PATTERNS}, TOTAL)
    m = ipf(rows, cols)
    cells = largest_remainder(m, TOTAL)
    # 정수화 후 실제 합계 (IPF 반올림 때문에 목표와 1~2 차이가 날 수 있어 그대로 보고한다)
    item_sum = {i: sum(cells[i, p] for p in cols) for i in rows}
    pat_sum = {p: sum(cells[i, p] for i in rows) for p in cols}
    plan = {k: 0.0 for k in PLANS}
    for p, n in pat_sum.items():
        for k, r in PLAN_MIX[p].items():
            plan[k] += n * r
    plan_share = {k: round(v / TOTAL, 4) for k, v in plan.items()}
    return rows, cols, cells, item_sum, pat_sum, plan_share


def half(cells):
    """10,000 칸 -> 5,000 칸. 각 칸의 절반을 내림하고 남는 수를 소수부 큰 칸부터 채운다."""
    return largest_remainder({k: v / 2 for k, v in cells.items()}, TOTAL // 2)


def main():
    """배분표를 새로 만든다. 이전 데이터·시드는 쓰지 않는다(데이터셋 v2는 모두 새로 샘플링, source=new_sampled)."""
    out = {
        "version": "allocation-dataset-v2-2026-10-13",
        "status": "dataset v2 (2026-10-13 사용자 확정 구조). pattern 비율은 2026-10-11 승인 조정안을 그대로 쓴다",
        "decisions": {
            "allocation": "proposed (조정안, 2026-10-11 승인)",
            "end": "Q10 다음은 END(마무리). END 학습량을 늘리려고 Q10 가중치를 1.5 -> 3.0으로 올림",
            "start": "START(인사 + 첫 질문)는 LoRA-B 전용 레코드로 따로 만든다 (taxonomy.START_TARGET)",
            "model": "Qwen3-30B-A3B-Instruct-2507",
            "source": "new_sampled만 사용 (이전 데이터·시드 없음)",
        },
        "unit": "scenario_id (1 시나리오 = LoRA-A 1 + LoRA-B 1). START는 B만",
        "targets": {"minimum": 5000, "goal": 10000},
        "canonical": {"max_variants_per_canonical": MAX_VARIANTS_PER_CANONICAL,
                      "split_unit": "scenario_family (= 같은 canonical_scenario의 표현 변형 묶음)"},
        "multi_turn_patterns": sorted(MULTI_TURN),
        "plan_floor": PLAN_FLOOR,
        "item_min_10000": ITEM_MIN_10000,
        "item_weights": ITEM_WEIGHTS,
        "style_tags": STYLE_TAGS,
        "style_constraints": {"min_share_each": STYLE_MIN_SHARE, "stt_noise_max_share": STT_MAX_SHARE},
        "split": {"train": 0.8, "val": 0.1, "test": 0.1, "unit": "scenario_family",
                  "test_stratification": "31개 문항 x 10개 pattern 각각 최소 1 family"},
        "stages": [
            {"id": "S1", "cumulative": 1000}, {"id": "S2", "cumulative": 2500},
            {"id": "S3", "cumulative": 5000}, {"id": "S4", "cumulative": 10000},
        ],
        "patterns": {},
    }
    rows, cols, cells, item_sum, pat_sum, plan_share = allocate("proposed")
    cells5 = half(cells)
    out["patterns"]["proposed"] = {
        "share": {p: PATTERNS[p]["proposed"] for p in PATTERNS},
        "count_10000": pat_sum,
        "count_5000": {p: sum(cells5[i, p] for i in rows) for p in cols},
        "expected_plan_share": plan_share,
        "plan_floor_violations": [k for k, v in plan_share.items() if v < PLAN_FLOOR and k != "COMPLETE"],
    }
    out["items_10000"] = item_sum
    out["items_5000"] = {i: sum(cells5[i, p] for p in cols) for i in rows}
    out["cells_10000"] = {i: {p: cells[i, p] for p in cols if cells[i, p]} for i in rows}
    path = ROOT / "patterns" / "allocation_10000.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text("# 자동 생성: scripts/build_allocation.py (손으로 고치지 말고 taxonomy.py를 고친 뒤 재실행)\n"
                    + yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=120))
    print(json.dumps({"patterns": out["patterns"], "items_10000": item_sum}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
