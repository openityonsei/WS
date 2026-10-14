"""문진 DB(SQLite) 구조와 LoRA-A 출력 -> DB 저장 SQL을 정리한 문서 docs/SQL.md를 만든다.

입력: 정규화기 참조 DB(읽기 전용으로 연다, mode=ro). 경로는 common.NORMALIZER_ROOT/dataset/db/questionnaire_reference.sqlite3
      (정규화기의 dataset은 /home/openit/WS/labeled_questionnaire_100_handoff를 가리키는 링크다).
      저장 SQL은 정규화기 store.py(save_result)에 있는 문장을 그대로 옮겨 적는다(코드는 고치지 않음).
출력: docs/SQL.md. DB와 정규화기 파일은 바꾸지 않는다.
실행: python -B scripts/export_sql_doc.py
"""
import json
import sqlite3

from common import NORMALIZER_ROOT, ROOT

DB = NORMALIZER_ROOT / "dataset" / "db" / "questionnaire_reference.sqlite3"
VERSION = "national_health_2026_v1"


def connect_ro():
    """읽기 전용 연결. 다른 담당자가 쓰는 공유 DB라 쓰기 모드로 열지 않는다."""
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def fence(text, lang="sql"):
    return f"```{lang}\n{text}\n```"


def main():
    c = connect_ro()
    ver = c.execute("SELECT version_id, title, form_revision_date, policy_version, status FROM questionnaire_versions").fetchall()
    objs = c.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name").fetchall()
    counts = {n: c.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0]
              for (n,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    items = c.execute("SELECT item_id, official_number, section_name, subject_label, reference_period, question_text "
                      "FROM question_items WHERE version_id=? ORDER BY sequence_no", (VERSION,)).fetchall()
    fields = c.execute("SELECT f.field_id, f.data_type, f.unit, f.constraints_json, f.repeat_keys_json FROM question_fields f "
                       "JOIN question_items i ON i.version_id=f.version_id AND i.item_id=f.item_id "
                       "WHERE f.version_id=? ORDER BY i.sequence_no, f.field_id", (VERSION,)).fetchall()
    options = c.execute("SELECT field_id, option_code, label FROM field_options WHERE version_id=? ORDER BY field_id, option_code",
                        (VERSION,)).fetchall()
    rules = c.execute("SELECT rule_id, kind, item_id, field_id, condition_json, origin, status, description FROM questionnaire_rules "
                      "WHERE version_id=? ORDER BY kind, rule_id", (VERSION,)).fetchall()

    P = ["# 문진 DB와 SQL 정리", "",
         "- 대상 DB: 정규화기 참조 DB `questionnaire_reference.sqlite3` "
         "(`/home/openit/WS/labeled_questionnaire_100_handoff/db/`, 정규화기 4곳의 `dataset` 링크가 가리키는 공유 파일)",
         f"- 문진표 버전: `{ver[0][0]}` ({ver[0][1]}, 개정일 {ver[0][2]}, 정책 {ver[0][3]}, 상태 {ver[0][4]})",
         "- 이 문서는 `scripts/export_sql_doc.py`가 DB를 **읽기 전용**으로 열어서 만든다. 저장 SQL은 정규화기 `store.py`의 문장을 옮겨 적은 것이다. "
         "DB·정규화기 코드는 바꾸지 않았다.",
         "- 데이터셋 v2에서는 이 DB를 (1) 문항 순서·질문 원문, (2) 칸 정의·선택지, (3) 생성 검증의 저장·조회 왕복(임시 복사본)에 쓴다.", ""]

    # 1. 테이블 한눈에
    role = {
        "questionnaire_versions": ("참조", "문진표 버전"), "question_items": ("참조", "문항 31개(순서·원문·조사 기간)"),
        "question_fields": ("참조", "칸 52개(자료형·단위·범위·반복 키)"), "field_options": ("참조", "선택지 코드"),
        "questionnaire_rules": ("참조", "적용 조건·필수 칸·운영 정책"),
        "subjects": ("세션", "대상자"), "intake_snapshots": ("세션", "접수 정보(이름·연락처 등)"),
        "sessions": ("세션", "문진 세션, revision·진행 상태"), "messages": ("세션", "대화 메시지(환자·상담원)"),
        "extracted_facts": ("세션", "추출 원시 사실(JSON)"), "fact_evidence": ("세션", "추출 근거 구간(환자 말의 위치)"),
        "answers": ("세션", "칸별 답(현재 revision을 가리킴)"), "answer_revisions": ("세션", "답 이력(수정 불가, 새 revision 추가)"),
        "answer_sources": ("세션", "revision과 근거 사실 연결"), "finalizations": ("세션", "최종 확인 스냅샷(수정 불가)"),
        "session_events": ("세션", "요청 단위 처리 기록(중복 요청 방지)"),
    }
    P += ["## 1. 테이블 한눈에", "", "| 테이블 | 구분 | 역할 | 현재 행 수 |", "|---|---|---|---:|"]
    for n, (k, d) in role.items():
        P.append(f"| `{n}` | {k} | {d} | {counts.get(n, '-')} |")
    P += ["", "- 참조 테이블은 문진표 정의라서 서비스 중에 바뀌지 않는다. 세션 테이블은 상담마다 쌓인다(이 파일은 비어 있음).",
          "- 뷰 `current_answers`: 칸마다 현재 revision 한 줄. 서비스가 '지금 저장된 답'을 읽을 때 쓴다.", ""]

    # 2. 관계
    P += ["## 2. 관계", "", fence("""questionnaire_versions ─┬─ question_items ── question_fields ── field_options
                        └─ questionnaire_rules
subjects ── sessions ─┬─ messages ── fact_evidence ── extracted_facts
                      ├─ answers ── answer_revisions ── answer_sources ── extracted_facts
                      ├─ session_events
                      └─ finalizations""", ""), ""]

    # 3. DDL 전체
    P += ["## 3. 스키마 전체 (DDL)", ""]
    for kind in ("table", "view", "trigger"):
        rows = [(n, s) for t, n, s in objs if t == kind and not n.startswith("sqlite_")]
        if not rows:
            continue
        P += [f"### {kind}", ""]
        for n, s in rows:
            P += [f"#### `{n}`", "", fence(s.strip() + ";"), ""]

    # 4. 트리거가 막는 것
    P += ["## 4. 트리거가 막는 것", "", "| 트리거 | 막는 것 | 오류 메시지 |", "|---|---|---|",
          "| `answer_type` | 칸 자료형과 다른 값 열, integer에 소수, 최소·최대·exclusive_minimum 범위 밖 | `invalid_answer_type_or_range` |",
          "| `valid_repeat_key` | 칸에 정의되지 않은 반복 키(예: Q7_1에 빈 키 '') | `invalid_repeat_key` |",
          "| `answer_history_no_update` / `_no_delete` | 답 이력 수정·삭제 | `immutable_answer_history` |",
          "| `evidence_is_user_text` | 환자 메시지에 없는 근거 구간 | `evidence_mismatch` |",
          "| `finalization_revision` | 최신 revision이 아니거나 READY_FOR_REVIEW가 아닌 세션의 최종 확인 | `invalid_final_confirmation` |",
          "| `finalization_no_update` / `_no_delete` | 최종 확인 수정·삭제 | `immutable_finalization` |", "",
          "CHECK 제약: 값 열(value_boolean / value_number / value_option / value_text)은 한 줄에 하나만, "
          "CONFIRMED는 값이 꼭 하나 있어야 하고, APPLICABLE이 아니면 값이 없어야 한다.", ""]

    # 5. 참조 데이터
    P += ["## 5. 참조 데이터", "", "### 5.1 문항 (question_items, 순서대로)", "",
          "| 순서 | item_id | 번호 | 구역 | 대상 | 조사 기간 | 질문 원문 |", "|---:|---|---|---|---|---|---|"]
    for k, (iid, num, sec, subj, per, q) in enumerate(items, 1):
        P.append(f"| {k} | {iid} | {num} | {sec} | {subj or ''} | {per or ''} | {q} |")
    P += ["", "### 5.2 칸 (question_fields)", "", "| field_id | 자료형 | 단위 | 범위 | 반복 키 | 값 열 |", "|---|---|---|---|---|---|"]
    col = {"boolean": "value_boolean (0/1)", "integer": "value_number (정수)", "number": "value_number",
           "option": "value_option", "text": "value_text"}
    for fid, dt, unit, cons, rks in fields:
        rk = ", ".join(k for k in json.loads(rks) if k) or "(빈 키 '')"
        cj = json.loads(cons)
        rng = ", ".join(f"{k}={v}" for k, v in cj.items()) or ""
        P.append(f"| {fid} | {dt} | {unit or ''} | {rng} | {rk} | {col[dt]} |")
    P += ["", "### 5.3 선택지 (field_options)", "", "| field_id | 코드 | 이름 |", "|---|---|---|"]
    P += [f"| {f} | `{o}` | {l} |" for f, o, l in options]
    P += ["", "### 5.4 규칙 (questionnaire_rules)", "", "| rule_id | 종류 | 대상 | 조건 | 상태 | 설명 |", "|---|---|---|---|---|---|"]
    for rid, kind, iid, fid, cond, origin, st, desc in rules:
        if kind == "FIELD_REQUIREMENT" and cond == '{"op":"always"}':
            continue   # 항상 필요한 칸은 아래 한 줄로 요약
        P.append(f"| {rid} | {kind} | {fid or iid or ''} | `{cond or ''}` | {st} | {desc} |")
    always = [fid for rid, kind, iid, fid, cond, o, st, d in rules if kind == "FIELD_REQUIREMENT" and cond == '{"op":"always"}']
    P += ["", f"항상 필요한 칸(FIELD_REQUIREMENT, op=always) {len(always)}개: " + ", ".join(f"`{f}`" for f in always), ""]

    # 6. LoRA-A 출력 -> DB 저장
    P += ["## 6. LoRA-A 출력을 DB에 저장하는 법", "",
          "서비스에는 정규화기가 없으므로, LoRA-A 출력(`values`)을 서비스 코드가 아래 규칙으로 저장한다. "
          "규칙과 SQL은 정규화기 `store.save_result`와 같다(학습 정답이 이 규칙으로 만들어졌으므로 저장도 같아야 한다).", "",
          "### 6.1 키·값·상태 대응", "",
          "| LoRA-A 출력 | DB |", "|---|---|",
          "| `key` `Q1.D03.diagnosed` | field_id `Q1.D03.diagnosed`, repeat_key `''` |",
          "| `key` `Q7_1[soju].amount` | field_id `Q7_1.amount`, repeat_key `soju` |",
          "| `value` | 칸 자료형에 맞는 열 하나(5.2의 '값 열'). true/false는 1/0 |",
          "| `precision` | precision (exact / approximate / unspecified) |",
          "| `status` ANSWERED (`save` true) | resolution_status `CONFIRMED`, change_reason `NEW_INFORMATION` |",
          "| `status` CORRECTION (`save` true) | resolution_status `CONFIRMED`, change_reason `CORRECTION` (새 revision) |",
          "| `status` MISSING | resolution_status `PARTIAL`, 값 없음 |",
          "| `status` UNCLEAR | resolution_status `AMBIGUOUS`, 값 없음 |",
          "| `status` UNKNOWN | resolution_status `UNCERTAIN`, 값 없음 |",
          "| `status` REJECTED, reason REFUSED | resolution_status `REFUSED`, 값 없음 |",
          "| `status` REJECTED, reason REQUEST_SKIP | resolution_status `DEFERRED`, 값 없음 |",
          "| `status` CONFLICT | **저장하지 않음** (확인 질문 뒤 CORRECTION 또는 같은 값으로 다시 들어온다) |",
          # 2026-10-13: 정규화기 store.save_result의 NO_REPEAT_KEY 건너뛰기와 같게 맞춘다(술 종류를 모르는 음주량 칸).
          "| 반복 문항(Q7_1·Q7_2) 키에 `[술 종류]`가 없음 (예: `Q7_1.amount`) | **저장하지 않음** (술 종류를 모르는 보류·재질문. 정규화기 저장 코드도 NO_REPEAT_KEY로 건너뜀) |", "",
          "- `save`=true는 '확정값(CONFIRMED)으로 저장'이라는 뜻이다. save=false 줄도 상태만 있는 revision으로 남길 수 있다(정규화기와 같음).",
          "- 이미 CONFIRMED인 칸: 미확정 상태(PARTIAL 등)로 덮어쓰지 않는다. 값이 같으면 저장하지 않는다. "
          "값이 다르면 CORRECTION일 때만 새 revision을 쓴다(정책 `explicit_correction`).",
          "- applicability_status는 저장하는 줄에서 `APPLICABLE`이다.", "",
          "### 6.2 저장 SQL (한 턴 = 한 트랜잭션)", "",
          fence("""-- 0) 연결마다
PRAGMA foreign_keys = ON;

BEGIN;
-- 1) 칸의 현재 답 확인 (CONFIRMED면 6.1의 덮어쓰기 규칙 적용)
SELECT resolution_status, value_boolean, value_number, value_option, value_text, revision_no
  FROM current_answers
 WHERE session_id = :session_id AND field_id = :field_id AND repeat_key = :repeat_key;

-- 2) 처음 저장하는 칸이면 answers 행을 만든다 (answer_id = field_id || '#' || repeat_key)
INSERT OR IGNORE INTO answers(session_id, answer_id, version_id, field_id, repeat_key)
VALUES (:session_id, :answer_id, 'national_health_2026_v1', :field_id, :repeat_key);

-- 3) 새 revision 추가 (이전 revision이 없으면 previous_revision NULL, revision_no 1)
INSERT INTO answer_revisions(session_id, answer_id, revision_no, version_id, field_id, previous_revision,
                             resolution_status, applicability_status,
                             value_boolean, value_number, value_option, value_text, precision,
                             change_reason, actor, ruleset_version)
VALUES (:session_id, :answer_id, :prev_rev + 1, 'national_health_2026_v1', :field_id, :prev_rev,
        :resolution_status, 'APPLICABLE',
        :value_boolean, :value_number, :value_option, :value_text, :precision,
        :change_reason, :actor, :ruleset_version);

-- 4) 현재 revision 가리키기
UPDATE answers SET current_revision = :prev_rev + 1
 WHERE session_id = :session_id AND answer_id = :answer_id;

-- 5) 이번 턴에 하나라도 저장했으면 세션 revision 올리기
UPDATE sessions SET revision = revision + 1 WHERE session_id = :session_id;
COMMIT;"""), "",
          "- `actor`는 저장 주체(예: `lora_a`), `ruleset_version`은 모델·데이터 버전(예: `dataset-v2`)을 넣는다. 정규화기는 `normalizer`, `normalizer-0.4`를 썼다.",
          "- 트리거에 걸리면 트랜잭션 전체가 롤백된다. 예: Q7_1 거절을 빈 repeat_key로 저장하면 `invalid_repeat_key`(알려진 이슈, README 7장).", "",
          "### 6.3 예: \"위스키를 잔 단위로 마십니다\" (Q7_1, REASK)", "",
          fence('{"values": [{"key": "Q7_1[spirits].amount", "value": null, "precision": "unspecified", "status": "MISSING", "save": false},\n'
                '            {"key": "Q7_1[spirits].unit", "value": "glass", "precision": "exact", "status": "ANSWERED", "save": true}],\n'
                ' "action": "REASK", "reason": "MISSING", "targets": ["Q7_1[spirits].amount"], "next_item": "Q7_1"}', "json"), "",
          fence("""-- unit: 확정값
INSERT OR IGNORE INTO answers(session_id, answer_id, version_id, field_id, repeat_key)
VALUES ('s1', 'Q7_1.unit#spirits', 'national_health_2026_v1', 'Q7_1.unit', 'spirits');
INSERT INTO answer_revisions(session_id, answer_id, revision_no, version_id, field_id, previous_revision,
  resolution_status, applicability_status, value_option, precision, change_reason, actor, ruleset_version)
VALUES ('s1', 'Q7_1.unit#spirits', 1, 'national_health_2026_v1', 'Q7_1.unit', NULL,
  'CONFIRMED', 'APPLICABLE', 'glass', 'exact', 'NEW_INFORMATION', 'lora_a', 'dataset-v2');
UPDATE answers SET current_revision = 1 WHERE session_id = 's1' AND answer_id = 'Q7_1.unit#spirits';

-- amount: 빠진 칸(상태만)
INSERT OR IGNORE INTO answers(session_id, answer_id, version_id, field_id, repeat_key)
VALUES ('s1', 'Q7_1.amount#spirits', 'national_health_2026_v1', 'Q7_1.amount', 'spirits');
INSERT INTO answer_revisions(session_id, answer_id, revision_no, version_id, field_id, previous_revision,
  resolution_status, applicability_status, precision, change_reason, actor, ruleset_version)
VALUES ('s1', 'Q7_1.amount#spirits', 1, 'national_health_2026_v1', 'Q7_1.amount', NULL,
  'PARTIAL', 'APPLICABLE', 'unspecified', 'NEW_INFORMATION', 'lora_a', 'dataset-v2');
UPDATE answers SET current_revision = 1 WHERE session_id = 's1' AND answer_id = 'Q7_1.amount#spirits';

UPDATE sessions SET revision = revision + 1 WHERE session_id = 's1';"""), ""]

    # 7. 조회 SQL
    P += ["## 7. 서비스에서 쓰는 조회 SQL", "",
          "### 7.1 LoRA-A 입력 `state` 만들기 (저장된 확정값)", "",
          fence("""SELECT field_id, repeat_key, value_boolean, value_number, value_option, value_text
  FROM current_answers
 WHERE session_id = :session_id AND resolution_status = 'CONFIRMED';
-- -> {"<item>.<field>" 또는 "<item>[<repeat_key>].<field>": {"value": ..., "status": "ANSWERED"}}
--    (field_id 'Q7_1.amount' + repeat_key 'soju' -> 'Q7_1[soju].amount', value_boolean 1/0 -> true/false)"""), "",
          "- 매 턴 같은 규칙으로 세 문항의 값만 넣는다: 지금 문항, 직전에 물은 문항(대화 순서, 건너뛰기 반영), 참조 원천 문항(taxonomy.REF_SOURCE, 예: Q10 -> Q9_1). 학습 데이터도 build_final이 이 규칙으로 state를 넓힌다(scripts/prev_state.py, 2026-10-14). 모름·거절로 넘긴 문항은 확정값이 없어 나오지 않는다.",
          "- 재질문 중인 칸은 상태만 넣는다: `resolution_status IN ('PARTIAL','AMBIGUOUS')` -> `{\"value\": null, \"status\": \"MISSING|UNCLEAR\"}`.", "",
          "### 7.2 B 입력 `previous` (CONFIRM일 때 이전 값)", "",
          fence("""SELECT value_boolean, value_number, value_option, value_text
  FROM current_answers
 WHERE session_id = :session_id AND field_id = :field_id AND repeat_key = :repeat_key
   AND resolution_status = 'CONFIRMED';
-- 평소량보다 적은 최대량(CONFLICT_MAX_BELOW_USUAL)이면 Q7_1의 같은 술(repeat_key) amount·unit을 읽는다"""), "",
          "### 7.3 다음 질문 문장 (next.text)", "",
          fence("""SELECT question_text, subject_label FROM question_items
 WHERE version_id = 'national_health_2026_v1' AND item_id = :next_item;
-- 데이터셋은 data/question_bank.json의 상담원 말 표현을 쓴다(원문 대신 바꿔 말한 질문)"""), "",
          "### 7.4 아직 안 끝난 칸 (마무리 전 점검용)", "",
          fence("""SELECT f.field_id, a.repeat_key, r.resolution_status
  FROM question_fields f
  LEFT JOIN current_answers r ON r.session_id = :session_id AND r.field_id = f.field_id
  LEFT JOIN answers a ON a.session_id = :session_id AND a.answer_id = r.answer_id
 WHERE f.version_id = 'national_health_2026_v1'
   AND (r.resolution_status IS NULL OR r.resolution_status != 'CONFIRMED');
-- 적용 조건(questionnaire_rules APPLICABILITY)과 조건부 필수 칸(FIELD_REQUIREMENT)은 결과에서 따로 걸러야 한다"""), ""]

    # 8. 데이터셋 규칙과 DB 규칙의 차이
    P += ["## 8. 데이터셋 v2 규칙과 DB 규칙이 다른 곳 (확인 필요)", "",
          "| 항목 | 데이터셋 v2 (LoRA-A가 배우는 것) | DB 규칙 | 메모 |", "|---|---|---|---|",
          "| Q4_1·Q5_1·Q6_1·Q7_1·Q7_2 건너뛰기 | 상위 답이 아니요·안 마심이면 건너뜀 | `applies_*` APPLICABILITY 규칙과 같음 | 일치 |",
          "| Q8_2·Q9_2 건너뛰기 | Q8_1·Q9_1이 0일이면 건너뜀 | `exercise_zero_duration`: PENDING, '자동 생략하지 않음' | **다름.** 운동 0일이면 시간 질문을 생략할지 정책 확정 필요 |",
          "| 마무리 | Q10 다음은 END | `next_unresolved`: 미해결 칸을 다시 묻고 마지막 번호만으로 완료 금지, `review_same_revision`: 최종 확인 뒤 완료 | **다름.** 서비스에서 END 전에 7.4로 미해결 칸(보류·거절)을 점검할지 정해야 함 |",
          "| 범위 답 | 가운데 값 + approximate | `raw_range_before_option`(Q6_1은 범위 전체가 한 선택지에 들 때만 매핑) | Q6_1은 일치, 나머지 숫자 칸은 정규화기 규약 |",
          "| 술 단위 섞임 | cc로 환산, approximate | `one_unit_per_beverage`: 같은 술은 한 단위로, 섞이면 확인 | 정규화기가 환산함. 확인 질문으로 바꿀지 정책 확인 필요 |",
          "| Q7_1·Q7_2 거절·보류 | SKIP 데이터 적음 | `valid_repeat_key`가 빈 반복 키를 막음 | 정규화기 이슈 후보 |", ""]
    out = ROOT / "docs" / "SQL.md"
    out.write_text("\n".join(P) + "\n")
    print(out, len(out.read_text()))


if __name__ == "__main__":
    main()
