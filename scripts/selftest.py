"""GPU 없이 돌리는 자체 시험 (데이터셋 v2). 생성 전에 코드 경로가 맞는지 확인한다.

1. 샘플러 -> 정규화기 -> v2 LoRA-A 정답 -> v2 LoRA-B 입력: 적용 가능한 (문항, pattern) 칸마다 canonical 3개씩 만들어
   action·next_item·next.type이 규칙대로 나오는지 센다(예: REASK·CONFIRM -> SAME, Q10 다음 -> END, 정정 흐름의 asked_item).
2. B 가드: 프롬프트의 좋은 응답 예시가 가드(checks.check_response)를 통과하는지(베끼기 검사는 끔), 나쁜 예 일부가 걸리는지.
3. 발화 가드: 좋은 발화 예시가 숫자 말투·문진표 낱말 가드를 통과하는지.
출력: reports/selftest.json. 실패가 있으면 종료 코드 1. 데이터 파일은 만들지 않는다.
"""
import json
import sys
from collections import Counter

import checks
import labels
import prompt_examples as pe
from common import ROOT
from pipeline import asked_item_for, followup_flow, pending_rows
from sampler import build_canonical
from taxonomy import ITEM_WEIGHTS, PATTERNS, applicable


def test_labels():
    stats, problems = Counter(), []
    examples = {}
    for item in ITEM_WEIGHTS:
        for p in PATTERNS:
            if not applicable(p, item):
                continue
            for k in range(3):
                c = build_canonical(item, p, 80000 + k, seed=20261013)
                if c is None:
                    stats["sampler_none"] += 1
                    continue
                asked = asked_item_for(c)
                state = labels.a_state(c["previous"], pending_rows(c))
                a = labels.a_target(asked, c["expected"], note=c.get("note"))
                nxt = a["next_item"]
                b = labels.b_input(a, asked, "(발화)", state, None if nxt == labels.END else "(질문)")
                key = (p, a["action"], b["next"]["type"])
                stats[key] += 1
                examples.setdefault(key, {"item": item, "asked": asked, "a": a, "b": b})
                # 규칙 검사
                if a["action"] in ("REASK", "CONFIRM", "REDIRECT") and b["next"]["type"] != "SAME":
                    problems.append(("same_item_expected", item, p, a))
                if a["action"] not in ("REASK", "CONFIRM", "REDIRECT") and b["next"]["type"] == "SAME":
                    problems.append(("unexpected_same", item, p, a))
                if item == "Q10" and a["action"] in ("NEXT", "HOLD", "SKIP", "CORRECT") and nxt != labels.END \
                        and not followup_flow(c):
                    problems.append(("q10_not_end", item, p, a))
                if followup_flow(c) and item != "Q10" and asked == item:
                    problems.append(("followup_asked_same", item, p, asked))
                if a["action"] == "CONFIRM" and not b.get("previous"):
                    problems.append(("confirm_no_previous", item, p, b))
                if a["action"] in ("REASK", "CONFIRM") and not b.get("ask"):
                    problems.append(("no_ask", item, p, b))
                if a["action"] == "REDIRECT" and a.get("reason") == "OUT_OF_SCHEMA" and not a.get("note"):
                    problems.append(("oos_no_note", item, p, a))
    return stats, problems, examples


def test_b_guard():
    checks.copies_example = lambda text, threshold=0.7, min_len=10: False   # 예시 자신은 베끼기 검사에서 뺀다
    fails = []
    for e in pe.B_EXAMPLES:
        b = pe.b_example_input(e)
        b["topic"] = labels.topic(e.item)
        if e.next_type != "END" and not e.next_text:
            b["next"]["text"] = e.resp.split(". ")[-1]
        try:
            checks.check_response(b, e.resp)
        except checks.Reject as r:
            fails.append({"action": e.action, "item": e.item, "resp": e.resp, "reason": r.args[0]})
    bad_caught = 0
    for bad, _good, _why in pe.BAD_B:
        b = {"action": "NEXT", "topic": "", "known": "", "next": {"type": "NEXT", "text": "질문"}, "user_utterance": ""}
        try:
            checks.check_response(b, bad.split(" (")[0])
        except checks.Reject:
            bad_caught += 1
    return fails, bad_caught


def test_utt_guard():
    fails = []
    for e in pe.UTT_EXAMPLES:
        for rx, code in ((checks.U_FORM_WORDS, "u_form_words"), (checks.U_META, "u_meta_comment")):
            if rx.search(e.utt):
                fails.append({"utt": e.utt, "reason": code})
        if e.style != "stt_noise" and checks.U_BAD_NUMBER.search(e.utt):
            fails.append({"utt": e.utt, "reason": "u_bad_number"})
    return fails


def main():
    stats, problems, examples = test_labels()
    b_fails, bad_caught = test_b_guard()
    u_fails = test_utt_guard()
    rep = {
        "label_stats": {"|".join(map(str, k)) if isinstance(k, tuple) else k: v for k, v in sorted(stats.items(), key=str)},
        "label_problems": [list(map(str, p)) for p in problems[:50]], "label_problem_count": len(problems),
        "b_example_guard_fails": b_fails, "bad_b_caught": f"{bad_caught}/{len(pe.BAD_B)}",
        "utt_example_guard_fails": u_fails,
        "examples": {"|".join(k): v for k, v in list(examples.items())[:40]},
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "selftest.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(json.dumps({k: rep[k] for k in ("label_problem_count", "bad_b_caught")}, ensure_ascii=False))
    print("label_stats", json.dumps(rep["label_stats"], ensure_ascii=False))
    for p in problems[:15]:
        print("PROBLEM", p)
    for f in b_fails:
        print("B_FAIL", f)
    for f in u_fails:
        print("U_FAIL", f)
    return 1 if problems or b_fails or u_fails else 0


if __name__ == "__main__":
    sys.exit(main())
