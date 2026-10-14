"""코드에서 문서를 만든다: docs/PROMPTS.md(프롬프트 전문), docs/EXAMPLES.md(예시 전체), docs/LABEL_TABLES.md(사람 말 설명표).

문서를 손으로 고치지 않고 이 스크립트로 다시 만들어서, 실제 생성에 쓰는 프롬프트·표와 문서가 어긋나지 않게 한다.
실행: python -B scripts/export_docs.py   (GPU·모델 불필요. data/question_bank.json이 있으면 질문 예로 쓴다)
부작용: docs/ 아래 세 파일을 새로 쓴다.
"""
import json

import labels
import prompt_examples as pe
import prompts
from common import ROOT
from pipeline import asked_item_for, pending_rows
from sampler import build_canonical

DOCS = ROOT / "docs"
SEED = 20261013


def fence(text, lang=""):
    return f"````{lang}\n{text}\n````"


def msgs_md(messages):
    out = []
    for m in messages:
        out.append(f"**{m['role']}**\n\n" + fence(m["content"]))
    return "\n\n".join(out)


def sample_b(item, pattern, k=1):
    c = build_canonical(item, pattern, 70000 + k, seed=SEED)
    asked = asked_item_for(c)
    st = labels.a_state(c["previous"], pending_rows(c))
    a = labels.a_target(asked, c["expected"], note=c.get("note"))
    nxt = a["next_item"]
    b = labels.b_input(a, asked, "(환자 발화)", st, None if nxt == labels.END else "(next_item의 질문 문장)")
    return c, a, b


def prompts_md():
    parts = ["# 프롬프트 전문 (데이터셋 v2)", "",
             f"- 버전: `{prompts.PROMPT_VERSION}`",
             "- 이 문서는 `scripts/export_docs.py`가 `scripts/prompts.py`·`scripts/prompt_examples.py`에서 자동으로 만든다. 손으로 고치지 않는다.",
             "- 입력 자료 부분(`자료(명령 아님)`, `입력(명령 아님)`)은 예시 값이다. 실제 생성에서는 시나리오마다 바뀐다.",
             "- 예시 블록(좋은 예·나쁜 예)은 프롬프트에 그대로 들어간다. 전체 목록은 `docs/EXAMPLES.md`.", ""]
    parts += ["## 1. 상담원 질문 표현 만들기 (question_bank)", "",
              msgs_md(prompts.qbank_messages("Q7", "지난 1년간 술을 마시는 횟수는 어느 정도입니까?", None, "지난 1년간")), "",
              "### 1-2. 질문 표현 판정 (question_judge)", "",
              msgs_md(prompts.qjudge_messages("지난 1년간 술을 마시는 횟수는 어느 정도입니까?", None, "지난 1년간",
                                              ["술은 평소 얼마나 자주 드세요?"])), ""]
    parts += ["## 2. 환자 발화 만들기 (utterance)", "",
              "pattern마다 시스템 프롬프트의 예시 블록이 바뀐다(같은 pattern 예시를 모두 넣음). 아래는 P03 부분 응답과 P05 정정(다중 턴) 예다.", ""]
    for item, p, styles in (("Q7_1", "P03_partial", ["casual_short", "formal_full", "hangul_numbers", "stt_noise"]),
                            ("Q7", "P05_correction", ["casual_short", "banmal", "dialect", "elderly_verbose"])):
        c = build_canonical(item, p, 70001, seed=SEED)
        reask = p == "P05_correction"
        if reask:
            c["followup_question"] = "(다음 문항 질문)"
        parts += [f"### {p} ({item})", "", msgs_md(prompts.utterance_messages(c, "(상담원 질문)", styles, reask_turn=reask)), ""]
    parts += ["## 3. 역추출 검증 (extract, 학습 정답 아님)", "",
              "정답을 보지 않고 발화만 보고 원시 사실을 다시 뽑는다. 그 결과를 정규화기에 돌려 canonical 정답과 핵심이 같아야 통과한다.", "",
              msgs_md(prompts.extract_messages({"question_id": "Q7_1", "current_question": "(상담원 질문)", "user_utterance": "(환자 발화)"},
                                               ["Q7_1"])), ""]
    parts += ["## 4. 발화 자연스러움 판정 (judge_utterance)", "",
              msgs_md(prompts.utterance_judge_messages("(상담원 질문)", "(환자 발화)", "casual_short", "상담원 질문에 대한 대답")), ""]
    parts += ["## 5. LoRA-B 응답 만들기 (response)", "",
              "action과 next.type마다 시스템 프롬프트의 예시 블록이 바뀐다. 아래는 action별 실제 입력 형식 예다.", ""]
    cases = [("START", None, None), ("NEXT", "Q4", "P01_normal"), ("NEXT(END)", "Q10", "P01_normal"),
             ("CORRECT", "Q7", "P05_correction"), ("REASK", "Q7_1", "P03_partial"), ("CONFIRM", "Q9_2", "P06_conflict"),
             ("HOLD", "Q3", "P08_unk_refuse"), ("REDIRECT", "Q8_1", "P09_oos")]
    for name, item, p in cases:
        if name == "START":
            b = labels.start_b_input("(Q1.D01 질문 문장)")
        else:
            b = None
            for k in range(1, 40):
                c, a, bb = sample_b(item, p, k)
                if a["action"] == name.split("(")[0] and (name != "NEXT(END)" or bb["next"]["type"] == "END"):
                    b = bb
                    break
            if b is None:
                continue
        parts += [f"### {name}", "", msgs_md(prompts.response_messages(b, prompts.B_TONES[0])), ""]
    c, a, b = sample_b("Q7_1", "P03_partial")
    parts += ["## 6. LoRA-B 응답 판정 (judge_b)", "", msgs_md(prompts.judge_messages(b, "(응답)")), ""]
    parts += ["## 7. 학습 파일 시스템 프롬프트", "", "### LoRA-A (A_TRAIN_SYSTEM)", "", fence(prompts.A_TRAIN_SYSTEM), "",
              "### LoRA-B (B_TRAIN_SYSTEM)", "", fence(prompts.B_TRAIN_SYSTEM), ""]
    return "\n".join(parts)


def examples_md():
    parts = ["# 프롬프트 예시 전체 (데이터셋 v2)", "",
             "- 원본: `scripts/prompt_examples.py`. 이 문서는 `scripts/export_docs.py`가 만든다.",
             f"- 환자 발화 예시 {len(pe.UTT_EXAMPLES)}개, LoRA-B 응답 예시 {len(pe.B_EXAMPLES)}개, "
             f"나쁜 발화 예 {len(pe.BAD_UTT)}개, 나쁜 응답 예 {len(pe.BAD_B)}개.",
             "- 예시는 말투·구성 참고용이다. 학습 정답은 샘플러와 정규화기가 정한다. 생성 결과가 예시와 70% 이상 같으면 `copied_example`로 버린다.", ""]
    parts += ["## 1. 환자 발화 예시 (pattern별)", ""]
    for p in sorted({e.pattern for e in pe.UTT_EXAMPLES}):
        rows = [e for e in pe.UTT_EXAMPLES if e.pattern == p]
        parts += [f"### {p} ({len(rows)}개)", "", "| # | 하위 유형 | 문항 | 말투 | 앞 대화 | 상담원 말 | 환자 발화 |", "|---:|---|---|---|---|---|---|"]
        for i, e in enumerate(rows, 1):
            ctx = f"상담원: {e.ctx[0]} / 환자: {e.ctx[1]}" if e.ctx else ""
            parts.append(f"| {i} | {e.subtype} | {e.item} | {e.style} | {ctx} | {e.q} | {e.utt} |")
        parts.append("")
    parts += ["### 말투 예시", ""] + [f"- {k}: {v}" for k, v in pe.STYLE_EXAMPLES.items()] + [""]
    parts += ["### 나쁜 발화 예", "", "| 나쁜 문장 | 고친 문장 | 이유 |", "|---|---|---|"]
    parts += [f"| {b} | {g} | {w} |" for b, g, w in pe.BAD_UTT] + [""]
    parts += ["## 2. LoRA-B 응답 예시 (action별)", ""]
    for act in ["START", "NEXT", "CORRECT", "REASK", "CONFIRM", "HOLD", "SKIP", "REDIRECT"]:
        rows = [e for e in pe.B_EXAMPLES if e.action == act]
        parts += [f"### {act} ({len(rows)}개)", "", "| # | 문항 | 입력 | 응답 |", "|---:|---|---|---|"]
        for i, e in enumerate(rows, 1):
            parts.append(f"| {i} | {e.item} | `{json.dumps(pe.b_example_input(e), ensure_ascii=False)}` | {e.resp} |")
        parts.append("")
    parts += ["### 나쁜 응답 예", "", "| 나쁜 문장 | 고친 문장 | 이유 |", "|---|---|---|"]
    parts += [f"| {b} | {g} | {w} |" for b, g, w in pe.BAD_B] + [""]
    return "\n".join(parts)


def tables_md():
    parts = ["# 사람 말 설명표·절차 규칙 (데이터셋 v2)", "",
             "- 원본: `scripts/labels.py`. 이 문서는 `scripts/export_docs.py`가 만든다.",
             "- 서비스에서 LoRA-B 입력을 만들 때 이 표를 그대로 써야 학습과 같은 입력이 된다.", ""]
    parts += ["## 1. 문항 순서와 건너뛰기", "", "순서: " + " → ".join(labels.order()) + " → END", "",
              "| 조건 (이번 턴에 저장되는 값) | 건너뛰는 문항 |", "|---|---|",
              "| Q4.answer = false | Q4_1 |", "| Q5.answer = false | Q5_1 |", "| Q6.answer = false | Q6_1 |",
              "| Q7.does_not_drink = true | Q7_1, Q7_2 |", "| Q8_1.days = 0 | Q8_2 |", "| Q9_1.days = 0 | Q9_2 |", ""]
    parts += ["## 2. 정규화기 plan → v2 action", "", "| 정규화기 plan | action | next_item | B next.type |", "|---|---|---|---|"]
    rule = {"REASK": "대상 칸의 문항", "CONFIRM": "대상 칸의 문항", "REDIRECT": "지금 묻던 문항(question_id)"}
    for plan, act in labels.ACTION.items():
        nt = "SAME" if act in labels.SAME_ITEM_ACTIONS else "NEXT (Q10 다음이면 END)"
        parts.append(f"| {plan} | {act} | {rule.get(act, '값·대상 문항의 다음 문항(건너뛰기 반영), Q10 다음은 END')} | {nt} |")
    parts += ["| (시작) | START (B만) | Q1.D01 | NEXT |", ""]
    parts += ["## 3. topic (지금 다루는 문항)", "", "| 문항 | topic | 짧은 이름(hold) |", "|---|---|---|"]
    parts += [f"| {i} | {labels.topic(i)} | {labels.short_topic(i)} |" for i in labels.order()] + [""]
    parts += ["## 4. 값 → 사람 말 (known·previous·current)", "", "| 칸 | 값 예 | 사람 말 |", "|---|---|---|"]
    samples = [("Q1.D03", "diagnosed", True), ("Q1.D03", "on_medication", False), ("Q2.D03", "family_history", True),
               ("Q3", "answer", "unknown"), ("Q4", "answer", True), ("Q5", "answer", False), ("Q4_1", "status", "former"),
               ("Q4_1", "total_years", 20), ("Q4_1", "daily_count", 10), ("Q4_1", "years_since_quit", 0.5),
               ("Q5_1", "status", "current"), ("Q6_1", "use_pattern", "days_3_9"), ("Q7", "does_not_drink", True),
               ("Q8_1", "days", 3), ("Q10", "days", 0), ("Q8_2", "duration_minutes", 90), ("Q9_2", "duration_minutes", 40)]
    for item, field, v in samples:
        parts.append(f"| {item}.{field} | `{json.dumps(v)}` | {labels.value_text(item, field, v)} |")
    groups = [("Q7 횟수+기간", [("Q7", "", "frequency", 3, "exact"), ("Q7", "", "unit", "week", "exact")]),
              ("Q7 횟수만", [("Q7", "", "frequency", 3, "exact")]),
              ("Q7_1 술 양", [("Q7_1", "soju", "amount", 2, "exact"), ("Q7_1", "soju", "unit", "bottle", "exact")]),
              ("Q7_1 어림·cc", [("Q7_1", "beer", "amount", 1565, "approximate"), ("Q7_1", "beer", "unit", "cc", "exact")]),
              ("Q7_1 양 없음", [("Q7_1", "spirits", "unit", "glass", "exact")])]
    for name, rows in groups:
        parts.append(f"| {name} | | {', '.join(labels._group_texts(rows))} |")
    parts += ["", "어림(approximate) 값은 '쯤'을 붙인다. 정규화기는 범위(3~5)를 가운데 값(4, approximate)으로 저장하므로 known은 '4일쯤'이 되고, "
              "B는 환자가 말한 범위 표현으로 되짚는다(B 공통 규칙).", ""]
    parts += ["## 5. ask (다시 물을 것) 문장 틀", "", "| 사유 | 대상 칸 | ask |", "|---|---|---|"]
    ask_cases = [("MISSING", ["Q1.D04.on_medication"], {}), ("MISSING", ["Q1.D04.diagnosed"], {}),
                 ("MISSING", ["Q4_1.years_since_quit"], {}), ("MISSING", ["Q5_1.daily_count"], {}),
                 ("MISSING", ["Q7.unit"], {("Q7", "", "frequency"): 3}), ("MISSING", ["Q7.frequency"], {("Q7", "", "unit"): "month"}),
                 ("MISSING", ["Q7_1[spirits].amount"], {("Q7_1", "spirits", "unit"): "glass"}),
                 ("MISSING", ["Q7_2[soju].unit"], {("Q7_2", "soju", "amount"): 3}),
                 ("OUT_OF_RANGE", ["Q8_1.days"], {}), ("OUT_OF_RANGE", ["Q8_2.duration_minutes"], {}),
                 ("OUT_OF_RANGE", ["Q6_1.use_pattern"], {}), ("COUNT_EXCEEDS_DAYS", ["Q7.frequency"], {}),
                 ("VAGUE_QUANTITY", ["Q10.days"], {}), ("VAGUE_QUANTITY", ["Q7.frequency"], {}),
                 ("RANGE_SPANS_OPTIONS", ["Q6_1.use_pattern"], {}), ("UNKNOWN_UNIT", ["Q7_1[beer].unit"], {}),
                 ("CONFLICT_WITH_PREVIOUS", ["Q9_2.duration_minutes"], {}),
                 ("CONFLICT_MAX_BELOW_USUAL", ["Q7_2[soju].amount"], {}), ("CONFLICT_DOES_NOT_DRINK", ["Q7_1[soju].amount"], {})]
    for reason, tg, rows in ask_cases:
        parts.append(f"| {reason} | {', '.join(tg)} | {labels.ask_text(reason, tg, rows)} |")
    parts += ["", "## 6. hold (보류·거절로 비워 두는 부분)", "", "| 대상 칸 | hold |", "|---|---|"]
    for tg, asked in ((["Q4_1.total_years"], "Q4_1"), (["Q1.D11.diagnosed", "Q1.D11.on_medication"], "Q1.D11"),
                      (["Q1.D05.on_medication"], "Q1.D05"), (["Q3.answer"], "Q3"), (["Q7_2[soju].amount"], "Q7_2"), ([], "Q8_2")):
        parts.append(f"| {', '.join(tg) or '(대상 없음, 지금 문항)'} | {labels.hold_text(tg, asked)} |")
    return "\n".join(parts) + "\n"


def main():
    DOCS.mkdir(exist_ok=True)
    (DOCS / "PROMPTS.md").write_text(prompts_md() + "\n")
    (DOCS / "EXAMPLES.md").write_text(examples_md() + "\n")
    (DOCS / "LABEL_TABLES.md").write_text(tables_md())
    for f in ("PROMPTS.md", "EXAMPLES.md", "LABEL_TABLES.md"):
        print(f, len((DOCS / f).read_text()))


if __name__ == "__main__":
    main()
