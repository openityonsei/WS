"""docs/SQL.md의 저장 규칙·SQL이 실제 데이터셋과 맞는지 레코드마다 확인한다.

방법 (레코드 하나마다, DB 임시 복사본에서)
- 문서 경로: LoRA-A 입력 state(저장된 확정값)를 먼저 저장하고, LoRA-A 정답 values를 SQL.md 6.1 대응표와 6.2 SQL대로 저장한다.
- 기준 경로: 같은 시나리오를 정규화기(normalize + store.save_result, 학습 정답을 만든 실제 저장 코드)로 저장한다.
- 두 세션의 current_answers(field_id, repeat_key, resolution_status, 값, precision)가 같아야 한다.
함께 보는 것: 키가 DB 칸·반복 키로 풀리는지, 선택지 코드가 field_options에 있는지, 트리거(자료형·범위·반복 키)에 걸리지 않는지,
state 키가 DB 칸인지.
입력: data/generated/shards/*.jsonl (turn 레코드), --final이면 data/final/{train,val,test}.jsonl.
출력: reports/verify_sql.json (--final이면 verify_sql_final.json). 공유 DB와 정규화기 코드는 바꾸지 않는다(읽기만).
"""
import json
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter

from common import CATALOG, NORMALIZER_ROOT, ROOT, normalize, read_jsonl
from labels import parse_key
from sampler import TODAY

SRC_DB = NORMALIZER_ROOT / "dataset" / "db" / "questionnaire_reference.sqlite3"
VERSION = "national_health_2026_v1"
RES = {"MISSING": "PARTIAL", "UNCLEAR": "AMBIGUOUS", "UNKNOWN": "UNCERTAIN"}   # SQL.md 6.1


def value_cols(field_id, value):
    """SQL.md 5.2 '값 열': 칸 자료형에 맞는 열 하나에 값을 넣는다. true/false는 1/0."""
    dt = CATALOG.fields[field_id].data_type
    cols = {"value_boolean": None, "value_number": None, "value_option": None, "value_text": None}
    if value is None:
        return cols
    key = {"boolean": "value_boolean", "integer": "value_number", "number": "value_number",
           "option": "value_option", "text": "value_text"}[dt]
    cols[key] = int(value) if dt == "boolean" else value
    return cols


def current(conn, sid, field_id, rk):
    return conn.execute("SELECT resolution_status, value_boolean, value_number, value_option, value_text, revision_no "
                        "FROM current_answers WHERE session_id=? AND field_id=? AND repeat_key=?", (sid, field_id, rk)).fetchone()


def doc_save(conn, sid, rows):
    """SQL.md 6.2 문장 그대로 저장. rows: [(field_id, repeat_key, resolution_status, value, precision, change_reason, confirmed)]"""
    stored = 0
    with conn:
        for fid, rk, res, value, prec, reason, confirmed in rows:
            prev = current(conn, sid, fid, rk)
            if prev and prev[0] == "CONFIRMED":
                pv = next((v for v in prev[1:5] if v is not None), None)
                if not confirmed:
                    continue                                   # 미확정으로 확정값을 덮지 않음
                same = (float(pv) == float(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and pv is not None else pv == (int(value) if isinstance(value, bool) else value)
                if same:
                    continue                                   # 같은 값이면 저장하지 않음
                if reason != "CORRECTION":
                    continue                                   # 다른 값은 CORRECTION일 때만
            aid = f"{fid}#{rk}"
            prev_rev = prev[5] if prev else None
            conn.execute("INSERT OR IGNORE INTO answers(session_id, answer_id, version_id, field_id, repeat_key) VALUES (?, ?, ?, ?, ?)",
                         (sid, aid, VERSION, fid, rk))
            cols = value_cols(fid, value)
            conn.execute("INSERT INTO answer_revisions(session_id, answer_id, revision_no, version_id, field_id, previous_revision,"
                         " resolution_status, applicability_status, value_boolean, value_number, value_option, value_text, precision,"
                         " change_reason, actor, ruleset_version) VALUES (?, ?, ?, ?, ?, ?, ?, 'APPLICABLE', ?, ?, ?, ?, ?, ?, 'lora_a', 'dataset-v2')",
                         (sid, aid, (prev_rev or 0) + 1, VERSION, fid, prev_rev, res, cols["value_boolean"], cols["value_number"],
                          cols["value_option"], cols["value_text"], prec, reason))
            conn.execute("UPDATE answers SET current_revision=? WHERE session_id=? AND answer_id=?", ((prev_rev or 0) + 1, sid, aid))
            stored += 1
        if stored:
            conn.execute("UPDATE sessions SET revision = revision + 1 WHERE session_id=?", (sid,))


def snapshot(conn, sid):
    return sorted((f, k, s, next((v for v in (vb, vn, vo, vt) if v is not None), None), p)
                  for f, k, s, vb, vn, vo, vt, p in conn.execute(
                      "SELECT field_id, repeat_key, resolution_status, value_boolean, value_number, value_option, value_text, precision "
                      "FROM current_answers WHERE session_id=?", (sid,)))


def new_session(conn, sid):
    with conn:
        conn.execute("INSERT INTO subjects(subject_id, is_synthetic) VALUES (?, 1)", (f"sub-{sid}",))
        conn.execute("INSERT INTO sessions(session_id, subject_id, version_id, status) VALUES (?, ?, ?, 'IN_PROGRESS')",
                     (sid, f"sub-{sid}", VERSION))


def main():
    sys.path.insert(0, str(NORMALIZER_ROOT))
    from normalizer import store
    tmp = tempfile.TemporaryDirectory()
    path = f"{tmp.name}/verify.sqlite3"
    shutil.copy2(SRC_DB, path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    options = {(f, o) for f, o in conn.execute("SELECT field_id, option_code FROM field_options")}
    # --final: 최종 파일(build_final이 넓힌 state)을 검사한다. 기본은 생성 shard 전체.
    if "--final" in sys.argv:
        paths = [ROOT / "data" / "final" / f"{s}.jsonl" for s in ("train", "val", "test")]
    else:
        paths = sorted((ROOT / "data" / "generated" / "shards").glob("*.jsonl"))
    recs = [r for p in paths for r in read_jsonl(p) if r["record_type"] == "turn"]
    stats, problems = Counter(), []
    for n, r in enumerate(recs):
        a_in, a_out = r["lora_a_input"], r["lora_a_target"]
        # 1) 키 -> DB 칸·반복 키, 선택지 코드
        bad = []
        for k in list(a_in["state"]) + [v["key"] for v in a_out["values"]]:
            item, rk, field = parse_key(k)
            if item in ("Q7_1", "Q7_2") and "[" not in k:
                continue                                       # 6.1: 술 종류 없는 음주량 키는 저장하지 않음(아래에서 건너뜀)
            fid = f"{item}.{field}"
            f = CATALOG.fields.get(fid)
            if f is None or rk not in f.repeat_keys:
                bad.append(("unknown_field_or_repeat_key", k))
        for v in a_out["values"]:
            item, rk, field = parse_key(v["key"])
            fid = f"{item}.{field}"
            if CATALOG.fields.get(fid) is not None and CATALOG.fields[fid].data_type == "option" and v["value"] is not None \
                    and (fid, v["value"]) not in options:
                bad.append(("unknown_option", v["key"], v["value"]))
        if bad:
            problems.append({"scenario_id": r["scenario_id"], "problems": bad})
            stats["key_problem"] += 1
            continue
        prev_rows = []
        for k, s in a_in["state"].items():
            if s["status"] == "ANSWERED" and s["value"] is not None:
                item, rk, field = parse_key(k)
                prev_rows.append((f"{item}.{field}", rk, "CONFIRMED", s["value"], "exact", "NEW_INFORMATION", True))
        # 2) 문서 경로
        sid_doc, sid_ref = f"d{n}", f"r{n}"
        new_session(conn, sid_doc)
        try:
            doc_save(conn, sid_doc, prev_rows)
            rows = []
            for v in a_out["values"]:
                item, rk, field = parse_key(v["key"])
                st = v["status"]
                if st == "CONFLICT":
                    continue                                   # 6.1: CONFLICT는 저장하지 않음
                if item in ("Q7_1", "Q7_2") and "[" not in v["key"]:
                    continue                                   # 6.1: 술 종류 없는 음주량은 저장하지 않음(정규화기 NO_REPEAT_KEY)
                if st in ("ANSWERED", "CORRECTION"):
                    res = "CONFIRMED"
                elif st == "REJECTED":
                    res = "DEFERRED" if a_out.get("reason") == "REQUEST_SKIP" else "REFUSED"
                else:
                    res = RES[st]
                rows.append((f"{item}.{field}", rk, res, v["value"] if v["save"] else None, v["precision"],
                             "CORRECTION" if st == "CORRECTION" else "NEW_INFORMATION", bool(v["save"])))
            doc_save(conn, sid_doc, rows)
        except sqlite3.Error as e:
            problems.append({"scenario_id": r["scenario_id"], "doc_sql_error": str(e)})
            stats["doc_sql_error"] += 1
            continue
        # 3) 기준 경로 (정규화기 저장 코드)
        new_session(conn, sid_ref)
        try:
            # 이전 확정값은 두 세션에 같은 방법으로 넣는다(시험 대상은 '이번 턴' 저장이다)
            doc_save(conn, sid_ref, prev_rows)
            prev = store.confirmed_answers(conn, sid_ref)
            res = normalize(r["label_source"]["raw_labels"], CATALOG, prev, utterance=r["user_utterance"], today=TODAY)
            store.save_result(conn, sid_ref, res)
        except Exception as e:
            problems.append({"scenario_id": r["scenario_id"], "ref_error": f"{type(e).__name__}: {e}"})
            stats["ref_error"] += 1
            continue
        a, b = snapshot(conn, sid_doc), snapshot(conn, sid_ref)
        if a == b:
            stats["match"] += 1
        else:
            stats["mismatch"] += 1
            problems.append({"scenario_id": r["scenario_id"], "action": a_out["action"], "doc": a, "normalizer": b})
    rep = {"records": len(recs), "stats": dict(stats), "problems": problems[:200]}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / ("verify_sql_final.json" if "--final" in sys.argv else "verify_sql.json")).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({"records": len(recs), "stats": dict(stats)}, ensure_ascii=False))
    for p in problems[:10]:
        print(json.dumps(p, ensure_ascii=False, default=str)[:600])


if __name__ == "__main__":
    main()
