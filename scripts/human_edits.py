"""검수 페이지(사람 검수)에서 사람이 직접 고친 내용을 최종 데이터에 반영한다 (2026-10-14).

흐름
1. 검수 페이지는 레코드마다 판정(OK/문제)·태그·메모와 직접 수정(edit)을 페이지 저장소 reviews/<scenario_id>에 남긴다.
2. Claude가 저장소를 읽어 문서별 JSON으로 내려받고, `python -B scripts/human_edits.py collect <내려받은 폴더>`로
   review/human_edits.json 하나로 모은다(이 파일이 반영의 원천이며 사람이 쓴 그대로다).
3. build_final이 apply()로 반영한다. 반영 규칙
   - exclude: 그 레코드를 최종 데이터에서 뺀다(할당량 선택 전이라 예비분이 칸을 채울 수 있다).
   - a_input: LoRA-A 입력(question_id·current_question·user_utterance·state)을 사람이 쓴 JSON으로 바꾼다.
     user_utterance가 바뀌면 마스터 user_utterance와 B 입력의 user_utterance도 같게 맞춘다.
   - utterance: (이전 페이지 형식) 환자 발화만 바꾼다. a_input과 같은 방식으로 맞춘다.
   - a_target: LoRA-A 정답을 사람이 쓴 JSON으로 바꾼다. 사람이 B 입력을 따로 고치지 않았으면 B 입력을 labels.b_input으로
     (고친 A 입력 state 기준) 다시 만든다. 다음 문항이 바뀌면 질문 문장은 문항 은행에서 고정 시드로 고른다.
   - b_input: LoRA-B 입력을 사람이 쓴 JSON 그대로 쓴다(다시 계산하지 않는다).
   - b_response: LoRA-B 응답 문장을 바꾼다.
   - A 정답·입력을 고쳐 B 입력이 달라졌는데 B 응답은 안 고쳤으면 validation.human_edit.b_needs_check=true로 남긴다(보고서에 나옴).
   - human_review: 수정이 있으면 human_edited, 판정 OK뿐이면 human_ok, 판정 '문제'인데 수정이 없으면 human_flagged.
     검수하지 않은 레코드는 기존 값(pending/auto_only)을 그대로 둔다. 이 모듈은 사람 판정을 지어내지 않는다.
사람이 고친 A 정답이 DB에 저장되는지는 build 뒤 verify_sql.py --final로 확인한다(형식 오류는 여기서 거부하고 보고한다).
"""
import copy
import json
import sys
from pathlib import Path

import labels as L
from common import CATALOG, ROOT

EDITS = ROOT / "review" / "human_edits.json"
ACTIONS = {"NEXT", "CORRECT", "REASK", "CONFIRM", "HOLD", "SKIP", "REDIRECT"}
STATUSES = {"ANSWERED", "CORRECTION", "MISSING", "UNCLEAR", "CONFLICT", "UNKNOWN", "REJECTED"}


def load():
    """review/human_edits.json -> {scenario_id: 문서}. 파일이 없으면 빈 dict(검수 전)."""
    if not EDITS.exists():
        return {}
    return json.loads(EDITS.read_text())


def check_a_target(a):
    """사람이 쓴 A 정답의 형식 검사. 문제 목록을 돌려준다(빈 목록이면 통과)."""
    bad = []
    if not isinstance(a, dict):
        return ["a_target_not_object"]
    if a.get("action") not in ACTIONS:
        bad.append(f"action:{a.get('action')}")
    nxt = a.get("next_item")
    if nxt != L.END and nxt not in L.order():
        bad.append(f"next_item:{nxt}")
    for v in a.get("values", []):
        try:
            item, rk, field = L.parse_key(v["key"])
        except Exception:
            bad.append(f"key:{v.get('key')}")
            continue
        if f"{item}.{field}" not in CATALOG.fields:
            bad.append(f"field:{v['key']}")
        if v.get("status") not in STATUSES or not isinstance(v.get("save"), bool):
            bad.append(f"status_or_save:{v['key']}")
    return bad


def _obj(x):
    """페이지는 JSON을 문자열로 저장한다. 문자열이면 파싱, dict면 그대로."""
    return x if isinstance(x, dict) else json.loads(x)


def check_a_input(a):
    """사람이 쓴 A 입력의 형식 검사. 네 키가 있어야 하고 state 키는 DB 칸이어야 한다."""
    if not isinstance(a, dict):
        return ["a_input_not_object"]
    bad = [f"missing:{k}" for k in ("question_id", "current_question", "user_utterance", "state") if k not in a]
    if a.get("question_id") not in L.order():
        bad.append(f"question_id:{a.get('question_id')}")
    for k, v in (a.get("state") or {}).items():
        try:
            item, rk, field = L.parse_key(k)
        except Exception:
            bad.append(f"state_key:{k}")
            continue
        if f"{item}.{field}" not in CATALOG.fields or not isinstance(v, dict) or "status" not in v or "value" not in v:
            bad.append(f"state:{k}")
    return bad


def check_b_input(b):
    """사람이 쓴 B 입력의 형식 검사. action·topic·next{type}이 있어야 한다."""
    if not isinstance(b, dict):
        return ["b_input_not_object"]
    bad = [f"missing:{k}" for k in ("action", "topic", "next") if k not in b]
    if b.get("action") not in ACTIONS | {"START"}:
        bad.append(f"action:{b.get('action')}")
    if (b.get("next") or {}).get("type") not in ("NEXT", "SAME", "END"):
        bad.append("next.type")
    return bad


def apply(records, bank, pick_question):
    """turn·start 레코드 목록에 사람 수정을 반영한다. 반환: (남은 레코드, 보고 dict).
    bank·pick_question: 다음 문항이 바뀌었을 때 질문 문장을 고르는 문항 은행과 함수(pipeline.pick_question)."""
    edits = load()
    rep = {"docs": len(edits), "excluded": 0, "edited": 0, "human_ok": 0, "human_flagged": 0,
           "rejected_a_target": [], "rejected_input": [], "b_needs_check": [], "ab_action_mismatch": [], "unknown_ids": []}
    seen, out = set(), []
    for r in records:
        doc = edits.get(r["scenario_id"])
        if not doc:
            out.append(r)
            continue
        seen.add(r["scenario_id"])
        e = doc.get("edit") or {}
        if e.get("exclude"):
            rep["excluded"] += 1
            continue
        r = copy.deepcopy(r)
        changed = []
        b_before = copy.deepcopy(r["lora_b_input"])
        if e.get("a_input") and r["record_type"] == "turn":
            ai = _obj(e["a_input"])
            bad = check_a_input(ai)
            if bad:
                rep["rejected_input"].append({"scenario_id": r["scenario_id"], "which": "a_input", "problems": bad})
            else:
                r["lora_a_input"] = ai
                r["user_utterance"] = r["lora_b_input"]["user_utterance"] = ai["user_utterance"]
                r["asked_item"] = ai["question_id"]
                changed.append("a_input")
        if e.get("utterance") and r["record_type"] == "turn" and "a_input" not in changed:
            u = e["utterance"].strip()
            r["user_utterance"] = r["lora_a_input"]["user_utterance"] = r["lora_b_input"]["user_utterance"] = u
            changed.append("utterance")
        if e.get("a_target") and r["record_type"] == "turn":
            a = _obj(e["a_target"])
            bad = check_a_target(a)
            if bad:
                rep["rejected_a_target"].append({"scenario_id": r["scenario_id"], "problems": bad})
            else:
                old_b = r["lora_b_input"]
                asked = r["lora_a_input"]["question_id"]
                nxt = a["next_item"]
                text = None if nxt == L.END else (old_b.get("next") or {}).get("text") \
                    if (old_b.get("next") or {}).get("question_id") == nxt else pick_question(bank, nxt, r["scenario_id"] + "_human")
                r["lora_a_target"] = a
                r["action"] = a["action"]
                if not e.get("b_input"):
                    r["lora_b_input"] = L.b_input(a, asked, r["lora_a_input"]["user_utterance"], r["lora_a_input"]["state"], text)
                changed.append("a_target")
        if e.get("b_input"):
            bi = _obj(e["b_input"])
            bad = check_b_input(bi)
            if bad:
                rep["rejected_input"].append({"scenario_id": r["scenario_id"], "which": "b_input", "problems": bad})
            else:
                r["lora_b_input"] = bi
                changed.append("b_input")
        if r["record_type"] == "turn":
            r["next_type"] = r["lora_b_input"]["next"]["type"]
            # 사람이 A 정답과 B 입력을 따로 고쳐 행동이 서로 다르면 보고한다(반영은 사람이 쓴 그대로)
            if changed and r["lora_b_input"].get("action") != r["lora_a_target"]["action"]:
                rep["ab_action_mismatch"].append(r["scenario_id"])
        if r["lora_b_input"] != b_before and not e.get("b_response"):
            rep["b_needs_check"].append(r["scenario_id"])
        if e.get("b_response"):
            r["lora_b_target"]["response_text"] = e["b_response"].strip()
            changed.append("b_response")
        v = r["validation"]
        if changed:
            v["human_review"] = "human_edited"
            v["human_edit"] = {"fields": changed, "b_needs_check": r["scenario_id"] in rep["b_needs_check"],
                               "verdict": doc.get("verdict"), "tags": doc.get("tags", []), "memo": doc.get("memo", "")}
            rep["edited"] += 1
        elif doc.get("verdict") == "ok":
            v["human_review"] = "human_ok"
            rep["human_ok"] += 1
        elif doc.get("verdict") == "bad":
            v["human_review"] = "human_flagged"
            v["human_edit"] = {"fields": [], "verdict": "bad", "tags": doc.get("tags", []), "memo": doc.get("memo", "")}
            rep["human_flagged"] += 1
        out.append(r)
    rep["unknown_ids"] = sorted(set(edits) - seen)[:50]
    return out, rep


def collect(folder):
    """ArtifactData로 내려받은 reviews/<id>.json 파일들 -> review/human_edits.json (사람이 쓴 내용 그대로)."""
    docs = {}
    for p in sorted(Path(folder).rglob("*.json")):
        d = json.loads(p.read_text())
        body = d.get("data", d) if isinstance(d, dict) else d
        docs[p.stem] = body
    EDITS.parent.mkdir(exist_ok=True)
    EDITS.write_text(json.dumps(docs, ensure_ascii=False, indent=1, sort_keys=True))
    print(f"{len(docs)} docs -> {EDITS}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "collect":
        collect(sys.argv[2])
    else:
        print("usage: python -B scripts/human_edits.py collect <folder>")
