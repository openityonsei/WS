# 문진 DB와 SQL 정리

- 대상 DB: 정규화기 참조 DB `questionnaire_reference.sqlite3` (`/home/openit/WS/labeled_questionnaire_100_handoff/db/`, 정규화기 4곳의 `dataset` 링크가 가리키는 공유 파일)
- 문진표 버전: `national_health_2026_v1` (국가 건강검진 문진표, 개정일 2026-01-01, 정책 prototype_policy_1, 상태 LOCAL_PROTOTYPE)
- 이 문서는 `scripts/export_sql_doc.py`가 DB를 **읽기 전용**으로 열어서 만든다. 저장 SQL은 정규화기 `store.py`의 문장을 옮겨 적은 것이다. DB·정규화기 코드는 바꾸지 않았다.
- 데이터셋 v2에서는 이 DB를 (1) 문항 순서·질문 원문, (2) 칸 정의·선택지, (3) 생성 검증의 저장·조회 왕복(임시 복사본)에 쓴다.

## 1. 테이블 한눈에

| 테이블 | 구분 | 역할 | 현재 행 수 |
|---|---|---|---:|
| `questionnaire_versions` | 참조 | 문진표 버전 | 1 |
| `question_items` | 참조 | 문항 31개(순서·원문·조사 기간) | 31 |
| `question_fields` | 참조 | 칸 52개(자료형·단위·범위·반복 키) | 52 |
| `field_options` | 참조 | 선택지 코드 | 23 |
| `questionnaire_rules` | 참조 | 적용 조건·필수 칸·운영 정책 | 70 |
| `subjects` | 세션 | 대상자 | 0 |
| `intake_snapshots` | 세션 | 접수 정보(이름·연락처 등) | 0 |
| `sessions` | 세션 | 문진 세션, revision·진행 상태 | 0 |
| `messages` | 세션 | 대화 메시지(환자·상담원) | 0 |
| `extracted_facts` | 세션 | 추출 원시 사실(JSON) | 0 |
| `fact_evidence` | 세션 | 추출 근거 구간(환자 말의 위치) | 0 |
| `answers` | 세션 | 칸별 답(현재 revision을 가리킴) | 0 |
| `answer_revisions` | 세션 | 답 이력(수정 불가, 새 revision 추가) | 0 |
| `answer_sources` | 세션 | revision과 근거 사실 연결 | 0 |
| `finalizations` | 세션 | 최종 확인 스냅샷(수정 불가) | 0 |
| `session_events` | 세션 | 요청 단위 처리 기록(중복 요청 방지) | 0 |

- 참조 테이블은 문진표 정의라서 서비스 중에 바뀌지 않는다. 세션 테이블은 상담마다 쌓인다(이 파일은 비어 있음).
- 뷰 `current_answers`: 칸마다 현재 revision 한 줄. 서비스가 '지금 저장된 답'을 읽을 때 쓴다.

## 2. 관계

```
questionnaire_versions ─┬─ question_items ── question_fields ── field_options
                        └─ questionnaire_rules
subjects ── sessions ─┬─ messages ── fact_evidence ── extracted_facts
                      ├─ answers ── answer_revisions ── answer_sources ── extracted_facts
                      ├─ session_events
                      └─ finalizations
```

## 3. 스키마 전체 (DDL)

### table

#### `answer_revisions`

```sql
CREATE TABLE answer_revisions (
 session_id TEXT NOT NULL, answer_id TEXT NOT NULL, revision_no INTEGER NOT NULL CHECK(revision_no>0),
 version_id TEXT NOT NULL, field_id TEXT NOT NULL, previous_revision INTEGER,
 resolution_status TEXT NOT NULL CHECK(resolution_status IN ('UNASKED','PARTIAL','AMBIGUOUS','UNCERTAIN','REFUSED','DEFERRED','CONFLICT','CONFIRMED')),
 applicability_status TEXT NOT NULL CHECK(applicability_status IN ('APPLICABLE','NOT_APPLICABLE','WAIT_PARENT')),
 value_boolean INTEGER CHECK(value_boolean IN (0,1)), value_number REAL, value_option TEXT, value_text TEXT,
 precision TEXT NOT NULL DEFAULT 'exact' CHECK(precision IN ('exact','approximate','unspecified')),
 change_reason TEXT NOT NULL, actor TEXT NOT NULL, ruleset_version TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(session_id,answer_id,revision_no),
 CHECK(previous_revision IS NULL OR previous_revision<revision_no),
 CHECK((value_boolean IS NOT NULL)+(value_number IS NOT NULL)+(value_option IS NOT NULL)+(value_text IS NOT NULL)<=1),
 CHECK(resolution_status!='CONFIRMED' OR (applicability_status='APPLICABLE' AND (value_boolean IS NOT NULL)+(value_number IS NOT NULL)+(value_option IS NOT NULL)+(value_text IS NOT NULL)=1)),
 CHECK(applicability_status='APPLICABLE' OR (value_boolean IS NULL AND value_number IS NULL AND value_option IS NULL AND value_text IS NULL)),
 FOREIGN KEY(session_id,answer_id,version_id,field_id) REFERENCES answers(session_id,answer_id,version_id,field_id),
 FOREIGN KEY(session_id,answer_id,previous_revision) REFERENCES answer_revisions(session_id,answer_id,revision_no),
 FOREIGN KEY(version_id,field_id,value_option) REFERENCES field_options(version_id,field_id,option_code)
);
```

#### `answer_sources`

```sql
CREATE TABLE answer_sources (
 session_id TEXT NOT NULL, answer_id TEXT NOT NULL, revision_no INTEGER NOT NULL, fact_id TEXT NOT NULL,
 PRIMARY KEY(session_id,answer_id,revision_no,fact_id),
 FOREIGN KEY(session_id,answer_id,revision_no) REFERENCES answer_revisions(session_id,answer_id,revision_no),
 FOREIGN KEY(session_id,fact_id) REFERENCES extracted_facts(session_id,fact_id)
);
```

#### `answers`

```sql
CREATE TABLE answers (
 session_id TEXT NOT NULL, answer_id TEXT NOT NULL, version_id TEXT NOT NULL, field_id TEXT NOT NULL,
 repeat_key TEXT NOT NULL DEFAULT '', current_revision INTEGER,
 PRIMARY KEY(session_id,answer_id), UNIQUE(session_id,field_id,repeat_key),
 UNIQUE(session_id,answer_id,version_id,field_id),
 FOREIGN KEY(session_id,version_id) REFERENCES sessions(session_id,version_id),
 FOREIGN KEY(version_id,field_id) REFERENCES question_fields(version_id,field_id),
 FOREIGN KEY(session_id,answer_id,current_revision) REFERENCES answer_revisions(session_id,answer_id,revision_no) DEFERRABLE INITIALLY DEFERRED
);
```

#### `extracted_facts`

```sql
CREATE TABLE extracted_facts (
 session_id TEXT NOT NULL, fact_id TEXT NOT NULL, version_id TEXT NOT NULL, field_id TEXT,
 raw_json TEXT NOT NULL CHECK(json_valid(raw_json)), model_version TEXT, extraction_status TEXT NOT NULL,
 PRIMARY KEY(session_id,fact_id),
 FOREIGN KEY(session_id,version_id) REFERENCES sessions(session_id,version_id),
 FOREIGN KEY(version_id,field_id) REFERENCES question_fields(version_id,field_id)
);
```

#### `fact_evidence`

```sql
CREATE TABLE fact_evidence (
 session_id TEXT NOT NULL, fact_id TEXT NOT NULL, message_id TEXT NOT NULL,
 start_offset INTEGER NOT NULL CHECK(start_offset>=0), end_offset INTEGER NOT NULL CHECK(end_offset>start_offset),
 evidence_text TEXT NOT NULL,
 PRIMARY KEY(session_id,fact_id,message_id,start_offset,end_offset),
 FOREIGN KEY(session_id,fact_id) REFERENCES extracted_facts(session_id,fact_id),
 FOREIGN KEY(session_id,message_id) REFERENCES messages(session_id,message_id)
);
```

#### `field_options`

```sql
CREATE TABLE field_options (
 version_id TEXT NOT NULL, field_id TEXT NOT NULL, option_code TEXT NOT NULL, label TEXT NOT NULL,
 PRIMARY KEY(version_id,field_id,option_code),
 FOREIGN KEY(version_id,field_id) REFERENCES question_fields(version_id,field_id)
);
```

#### `finalizations`

```sql
CREATE TABLE finalizations (
 finalization_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
 session_revision INTEGER NOT NULL, confirmation_message_id TEXT NOT NULL,
 completion_scope TEXT NOT NULL CHECK(completion_scope IN ('HEALTH_QUESTIONS','FULL_FORM')),
 snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(session_id,session_revision,completion_scope),
 FOREIGN KEY(session_id,confirmation_message_id) REFERENCES messages(session_id,message_id)
);
```

#### `intake_snapshots`

```sql
CREATE TABLE intake_snapshots (
 intake_id TEXT PRIMARY KEY, subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
 name TEXT, protected_identity_ref TEXT, home_phone TEXT, mobile_phone TEXT, address TEXT, email TEXT,
 delivery_methods_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(delivery_methods_json)),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(intake_id,subject_id)
);
```

#### `messages`

```sql
CREATE TABLE messages (
 session_id TEXT NOT NULL REFERENCES sessions(session_id), message_id TEXT NOT NULL,
 sequence_no INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
 content TEXT NOT NULL, request_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(session_id,message_id), UNIQUE(session_id,sequence_no), UNIQUE(session_id,request_id)
);
```

#### `question_fields`

```sql
CREATE TABLE question_fields (
 version_id TEXT NOT NULL, field_id TEXT NOT NULL, item_id TEXT NOT NULL, field_name TEXT NOT NULL,
 data_type TEXT NOT NULL CHECK(data_type IN ('boolean','integer','number','option','text')),
 unit TEXT, constraints_json TEXT NOT NULL CHECK(json_valid(constraints_json)),
 repeat_keys_json TEXT NOT NULL CHECK(json_valid(repeat_keys_json)), source_locator TEXT NOT NULL,
 PRIMARY KEY(version_id,field_id), UNIQUE(version_id,item_id,field_name),
 FOREIGN KEY(version_id,item_id) REFERENCES question_items(version_id,item_id)
);
```

#### `question_items`

```sql
CREATE TABLE question_items (
 version_id TEXT NOT NULL REFERENCES questionnaire_versions(version_id), item_id TEXT NOT NULL,
 official_number TEXT NOT NULL, section_name TEXT NOT NULL, question_text TEXT NOT NULL,
 subject_label TEXT, sequence_no INTEGER NOT NULL, reference_period TEXT, instructions TEXT,
 source_page INTEGER NOT NULL CHECK(source_page IN (1,2)), source_locator TEXT NOT NULL,
 PRIMARY KEY(version_id,item_id), UNIQUE(version_id,sequence_no)
);
```

#### `questionnaire_rules`

```sql
CREATE TABLE questionnaire_rules (
 version_id TEXT NOT NULL REFERENCES questionnaire_versions(version_id), rule_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('APPLICABILITY','FIELD_REQUIREMENT','OPERATION_POLICY','COMPLETION')),
 item_id TEXT, field_id TEXT, condition_json TEXT CHECK(condition_json IS NULL OR json_valid(condition_json)),
 origin TEXT NOT NULL CHECK(origin IN ('official_explicit','project_interpretation','operational_policy')),
 status TEXT NOT NULL CHECK(status IN ('ACTIVE_PROTOTYPE','PENDING')),
 description TEXT NOT NULL, source_locator TEXT,
 PRIMARY KEY(version_id,rule_id),
 FOREIGN KEY(version_id,item_id) REFERENCES question_items(version_id,item_id),
 FOREIGN KEY(version_id,field_id) REFERENCES question_fields(version_id,field_id)
);
```

#### `questionnaire_versions`

```sql
CREATE TABLE questionnaire_versions (
 version_id TEXT PRIMARY KEY, title TEXT NOT NULL, form_revision_date TEXT NOT NULL,
 source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL, schema_sha256 TEXT NOT NULL,
 policy_version TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('LOCAL_PROTOTYPE','APPROVED','RETIRED'))
);
```

#### `session_events`

```sql
CREATE TABLE session_events (
 session_id TEXT NOT NULL REFERENCES sessions(session_id), request_id TEXT NOT NULL,
 kind TEXT NOT NULL, payload_sha256 TEXT NOT NULL, result_json TEXT NOT NULL CHECK(json_valid(result_json)),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(session_id,request_id)
);
```

#### `sessions`

```sql
CREATE TABLE sessions (
 session_id TEXT PRIMARY KEY, subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
 version_id TEXT NOT NULL REFERENCES questionnaire_versions(version_id), intake_id TEXT,
 status TEXT NOT NULL CHECK(status IN ('IN_PROGRESS','PAUSED','NEEDS_REVIEW','READY_FOR_REVIEW','COMPLETED')),
 revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0), progress_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(progress_json)),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(session_id,version_id),
 FOREIGN KEY(intake_id,subject_id) REFERENCES intake_snapshots(intake_id,subject_id)
);
```

#### `subjects`

```sql
CREATE TABLE subjects (
 subject_id TEXT PRIMARY KEY, external_subject_ref TEXT UNIQUE, is_synthetic INTEGER NOT NULL CHECK(is_synthetic IN (0,1))
);
```

### view

#### `current_answers`

```sql
CREATE VIEW current_answers AS
 SELECT a.repeat_key,r.* FROM answers a JOIN answer_revisions r
 ON r.session_id=a.session_id AND r.answer_id=a.answer_id AND r.revision_no=a.current_revision;
```

### trigger

#### `answer_history_no_delete`

```sql
CREATE TRIGGER answer_history_no_delete BEFORE DELETE ON answer_revisions BEGIN SELECT RAISE(ABORT,'immutable_answer_history'); END;
```

#### `answer_history_no_update`

```sql
CREATE TRIGGER answer_history_no_update BEFORE UPDATE ON answer_revisions BEGIN SELECT RAISE(ABORT,'immutable_answer_history'); END;
```

#### `answer_type`

```sql
CREATE TRIGGER answer_type BEFORE INSERT ON answer_revisions BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM question_fields f WHERE f.version_id=NEW.version_id AND f.field_id=NEW.field_id AND
 ((NEW.value_boolean IS NOT NULL AND f.data_type!='boolean') OR (NEW.value_number IS NOT NULL AND f.data_type NOT IN ('number','integer'))
 OR (NEW.value_option IS NOT NULL AND f.data_type!='option') OR (NEW.value_text IS NOT NULL AND f.data_type!='text')
 OR (f.data_type='integer' AND NEW.value_number!=cast(NEW.value_number AS INTEGER))
 OR (NEW.value_number<json_extract(f.constraints_json,'$.minimum'))
 OR (NEW.value_number>json_extract(f.constraints_json,'$.maximum'))
 OR (NEW.value_number<=json_extract(f.constraints_json,'$.exclusive_minimum'))))
 THEN RAISE(ABORT,'invalid_answer_type_or_range') END;
END;
```

#### `evidence_is_user_text`

```sql
CREATE TRIGGER evidence_is_user_text BEFORE INSERT ON fact_evidence BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM messages m WHERE m.session_id=NEW.session_id AND m.message_id=NEW.message_id
  AND m.role='user' AND NEW.end_offset<=length(m.content)
  AND substr(m.content,NEW.start_offset+1,NEW.end_offset-NEW.start_offset)=NEW.evidence_text)
 THEN RAISE(ABORT,'evidence_mismatch') END;
END;
```

#### `finalization_no_delete`

```sql
CREATE TRIGGER finalization_no_delete BEFORE DELETE ON finalizations BEGIN SELECT RAISE(ABORT,'immutable_finalization'); END;
```

#### `finalization_no_update`

```sql
CREATE TRIGGER finalization_no_update BEFORE UPDATE ON finalizations BEGIN SELECT RAISE(ABORT,'immutable_finalization'); END;
```

#### `finalization_revision`

```sql
CREATE TRIGGER finalization_revision BEFORE INSERT ON finalizations BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sessions s JOIN messages m ON m.session_id=s.session_id
 WHERE s.session_id=NEW.session_id AND s.revision=NEW.session_revision AND s.status='READY_FOR_REVIEW'
 AND m.message_id=NEW.confirmation_message_id AND m.role='user') THEN RAISE(ABORT,'invalid_final_confirmation') END;
END;
```

#### `valid_repeat_key`

```sql
CREATE TRIGGER valid_repeat_key BEFORE INSERT ON answers BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM question_fields f,json_each(f.repeat_keys_json) k
 WHERE f.version_id=NEW.version_id AND f.field_id=NEW.field_id AND k.value=NEW.repeat_key)
 THEN RAISE(ABORT,'invalid_repeat_key') END;
END;
```

## 4. 트리거가 막는 것

| 트리거 | 막는 것 | 오류 메시지 |
|---|---|---|
| `answer_type` | 칸 자료형과 다른 값 열, integer에 소수, 최소·최대·exclusive_minimum 범위 밖 | `invalid_answer_type_or_range` |
| `valid_repeat_key` | 칸에 정의되지 않은 반복 키(예: Q7_1에 빈 키 '') | `invalid_repeat_key` |
| `answer_history_no_update` / `_no_delete` | 답 이력 수정·삭제 | `immutable_answer_history` |
| `evidence_is_user_text` | 환자 메시지에 없는 근거 구간 | `evidence_mismatch` |
| `finalization_revision` | 최신 revision이 아니거나 READY_FOR_REVIEW가 아닌 세션의 최종 확인 | `invalid_final_confirmation` |
| `finalization_no_update` / `_no_delete` | 최종 확인 수정·삭제 | `immutable_finalization` |

CHECK 제약: 값 열(value_boolean / value_number / value_option / value_text)은 한 줄에 하나만, CONFIRMED는 값이 꼭 하나 있어야 하고, APPLICABLE이 아니면 값이 없어야 한다.

## 5. 참조 데이터

### 5.1 문항 (question_items, 순서대로)

| 순서 | item_id | 번호 | 구역 | 대상 | 조사 기간 | 질문 원문 |
|---:|---|---|---|---|---|---|
| 1 | Q1.D01 | Q1 | 질환력(과거력, 가족력) | 뇌졸중(중풍) |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 2 | Q1.D02 | Q1 | 질환력(과거력, 가족력) | 심근경색/협심증 |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 3 | Q1.D03 | Q1 | 질환력(과거력, 가족력) | 고혈압 |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 4 | Q1.D04 | Q1 | 질환력(과거력, 가족력) | 당뇨병 |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 5 | Q1.D05 | Q1 | 질환력(과거력, 가족력) | 이상지질혈증 |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 6 | Q1.D06 | Q1 | 질환력(과거력, 가족력) | 폐결핵 |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 7 | Q1.D07 | Q1 | 질환력(과거력, 가족력) | 우울증 |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 8 | Q1.D08 | Q1 | 질환력(과거력, 가족력) | 조기정신증 |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 9 | Q1.D09 | Q1 | 질환력(과거력, 가족력) | C형간염 |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 10 | Q1.D10 | Q1 | 질환력(과거력, 가족력) | 만성폐쇄성폐질환 |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 11 | Q1.D11 | Q1 | 질환력(과거력, 가족력) | 기타(암포함) |  | 다음과 같은 질병으로 진단을 받았거나, 현재 약물 치료 중이십니까? |
| 12 | Q2.D01 | Q2 | 질환력(과거력, 가족력) | 뇌졸중(중풍) |  | 부모, 형제, 자매 중에 다음 질환을 앓았거나 해당 질환으로 사망한 경우가 있으십니까? |
| 13 | Q2.D02 | Q2 | 질환력(과거력, 가족력) | 심근경색/협심증 |  | 부모, 형제, 자매 중에 다음 질환을 앓았거나 해당 질환으로 사망한 경우가 있으십니까? |
| 14 | Q2.D03 | Q2 | 질환력(과거력, 가족력) | 고혈압 |  | 부모, 형제, 자매 중에 다음 질환을 앓았거나 해당 질환으로 사망한 경우가 있으십니까? |
| 15 | Q2.D04 | Q2 | 질환력(과거력, 가족력) | 당뇨병 |  | 부모, 형제, 자매 중에 다음 질환을 앓았거나 해당 질환으로 사망한 경우가 있으십니까? |
| 16 | Q2.D05 | Q2 | 질환력(과거력, 가족력) | 기타(암포함) |  | 부모, 형제, 자매 중에 다음 질환을 앓았거나 해당 질환으로 사망한 경우가 있으십니까? |
| 17 | Q3 | Q3 | 질환력(과거력, 가족력) |  |  | B형간염 바이러스 보유자입니까? |
| 18 | Q4 | Q4 | 흡연 및 전자담배 |  |  | 지금까지 평생 총 5갑(100개비) 이상의 일반담배(궐련)를 피운 적이 있습니까? |
| 19 | Q4_1 | Q4-1 | 흡연 및 전자담배 |  |  | 현재 일반담배(궐련)를 피우십니까? |
| 20 | Q5 | Q5 | 흡연 및 전자담배 |  |  | 지금까지 궐련형 전자담배(가열담배, 예: 아이코스, 글로, 릴 등)를 사용한 적 있습니까? |
| 21 | Q5_1 | Q5-1 | 흡연 및 전자담배 |  |  | 현재 궐련형 전자담배(가열담배)를 사용하십니까? |
| 22 | Q6 | Q6 | 흡연 및 전자담배 |  |  | 액상형 전자담배를 사용한 경험이 있습니까? |
| 23 | Q6_1 | Q6-1 | 흡연 및 전자담배 |  | 최근 한 달 | 최근 한 달 동안 액상형 전자담배를 사용한 경험이 있습니까? |
| 24 | Q7 | Q7 | 음주 |  | 지난 1년간 | 지난 1년간 술을 마시는 횟수는 어느 정도입니까? |
| 25 | Q7_1 | Q7-1 | 음주 |  | 지난 1년간 | 술을 마시는 날은 보통 어느 정도 마십니까? |
| 26 | Q7_2 | Q7-2 | 음주 |  | 지난 1년간 | 하루 동안 가장 많이 마셨던 음주량은 어느 정도입니까? |
| 27 | Q8_1 | Q8-1 | 신체활동(운동) |  | 평소 1주일간 | 평소 1주일간, 숨이 많이 차게 만드는 고강도 신체활동을 며칠 하십니까? |
| 28 | Q8_2 | Q8-2 | 신체활동(운동) |  | 평소 활동일 하루 | 평소 하루에 숨이 많이 차게 만드는 고강도 신체활동을 몇 시간 하십니까? |
| 29 | Q9_1 | Q9-1 | 신체활동(운동) |  | 평소 1주일간 | 평소 1주일간, 숨이 약간 차게 만드는 중강도 신체활동을 며칠 하십니까? |
| 30 | Q9_2 | Q9-2 | 신체활동(운동) |  | 평소 활동일 하루 | 평소 하루에 숨이 약간 차게 만드는 중강도 신체활동을 몇 시간 하십니까? |
| 31 | Q10 | Q10 | 신체활동(운동) |  | 최근 1주일 | 최근 1주일 동안 팔굽혀펴기, 윗몸일으키기, 아령, 역기, 철봉 등 근력 운동을 한 날은 며칠입니까? |

### 5.2 칸 (question_fields)

| field_id | 자료형 | 단위 | 범위 | 반복 키 | 값 열 |
|---|---|---|---|---|---|
| Q1.D01.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D01.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D02.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D02.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D03.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D03.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D04.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D04.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D05.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D05.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D06.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D06.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D07.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D07.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D08.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D08.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D09.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D09.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D10.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D10.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D11.diagnosed | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q1.D11.on_medication | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q2.D01.family_history | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q2.D02.family_history | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q2.D03.family_history | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q2.D04.family_history | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q2.D05.family_history | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q3.answer | option |  |  | (빈 키 '') | value_option |
| Q4.answer | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q4_1.daily_count | number | 개비 | minimum=0 | (빈 키 '') | value_number |
| Q4_1.status | option |  |  | (빈 키 '') | value_option |
| Q4_1.total_years | integer | 년 | minimum=0 | (빈 키 '') | value_number (정수) |
| Q4_1.years_since_quit | number | 년 | minimum=0 | (빈 키 '') | value_number |
| Q5.answer | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q5_1.daily_count | number | 개비 | minimum=0 | (빈 키 '') | value_number |
| Q5_1.status | option |  |  | (빈 키 '') | value_option |
| Q5_1.total_years | integer | 년 | minimum=0 | (빈 키 '') | value_number (정수) |
| Q5_1.years_since_quit | number | 년 | minimum=0 | (빈 키 '') | value_number |
| Q6.answer | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q6_1.use_pattern | option |  |  | (빈 키 '') | value_option |
| Q7.does_not_drink | boolean |  |  | (빈 키 '') | value_boolean (0/1) |
| Q7.frequency | number |  | exclusive_minimum=0 | (빈 키 '') | value_number |
| Q7.unit | option |  |  | (빈 키 '') | value_option |
| Q7_1.amount | number |  | minimum=0 | soju, beer, spirits, makgeolli, wine | value_number |
| Q7_1.unit | option |  |  | soju, beer, spirits, makgeolli, wine | value_option |
| Q7_2.amount | number |  | minimum=0 | soju, beer, spirits, makgeolli, wine | value_number |
| Q7_2.unit | option |  |  | soju, beer, spirits, makgeolli, wine | value_option |
| Q8_1.days | integer | day/week | maximum=7, minimum=0 | (빈 키 '') | value_number (정수) |
| Q8_2.duration_minutes | integer | minute | minimum=0 | (빈 키 '') | value_number (정수) |
| Q9_1.days | integer | day/week | maximum=7, minimum=0 | (빈 키 '') | value_number (정수) |
| Q9_2.duration_minutes | integer | minute | minimum=0 | (빈 키 '') | value_number (정수) |
| Q10.days | integer | day/week | maximum=7, minimum=0 | (빈 키 '') | value_number (정수) |

### 5.3 선택지 (field_options)

| field_id | 코드 | 이름 |
|---|---|---|
| Q3.answer | `no` | 아니요 |
| Q3.answer | `unknown` | 모름 |
| Q3.answer | `yes` | 예 |
| Q4_1.status | `current` | 현재 피움 |
| Q4_1.status | `former` | 과거에는 피웠으나 현재 피우지 않음 |
| Q5_1.status | `current` | 현재 피움 |
| Q5_1.status | `former` | 과거에는 피웠으나 현재 피우지 않음 |
| Q6_1.use_pattern | `daily` | 매일 |
| Q6_1.use_pattern | `days_10_29` | 월 10-29일 |
| Q6_1.use_pattern | `days_1_2` | 월 1-2일 |
| Q6_1.use_pattern | `days_3_9` | 월 3-9일 |
| Q6_1.use_pattern | `no` | 아니요 |
| Q7.unit | `month` | 월 |
| Q7.unit | `week` | 주 |
| Q7.unit | `year` | 년 |
| Q7_1.unit | `bottle` | 병 |
| Q7_1.unit | `can` | 캔 |
| Q7_1.unit | `cc` | cc |
| Q7_1.unit | `glass` | 잔 |
| Q7_2.unit | `bottle` | 병 |
| Q7_2.unit | `can` | 캔 |
| Q7_2.unit | `cc` | cc |
| Q7_2.unit | `glass` | 잔 |

### 5.4 규칙 (questionnaire_rules)

| rule_id | 종류 | 대상 | 조건 | 상태 | 설명 |
|---|---|---|---|---|---|
| applies_Q4_1 | APPLICABILITY | Q4_1 | `{"field":"answer","item_id":"Q4","op":"equals","value":true}` | ACTIVE_PROTOTYPE | 상위 답변 미확인 시 WAIT_PARENT, 일치 시 적용, 불일치 시 비해당 |
| applies_Q5_1 | APPLICABILITY | Q5_1 | `{"field":"answer","item_id":"Q5","op":"equals","value":true}` | ACTIVE_PROTOTYPE | 상위 답변 미확인 시 WAIT_PARENT, 일치 시 적용, 불일치 시 비해당 |
| applies_Q6_1 | APPLICABILITY | Q6_1 | `{"field":"answer","item_id":"Q6","op":"equals","value":true}` | ACTIVE_PROTOTYPE | 상위 답변 미확인 시 WAIT_PARENT, 일치 시 적용, 불일치 시 비해당 |
| applies_Q7_1 | APPLICABILITY | Q7_1 | `{"field":"does_not_drink","item_id":"Q7","op":"equals","value":false}` | ACTIVE_PROTOTYPE | 상위 답변 미확인 시 WAIT_PARENT, 일치 시 적용, 불일치 시 비해당 |
| applies_Q7_2 | APPLICABILITY | Q7_2 | `{"field":"does_not_drink","item_id":"Q7","op":"equals","value":false}` | ACTIVE_PROTOTYPE | 상위 답변 미확인 시 WAIT_PARENT, 일치 시 적용, 불일치 시 비해당 |
| review_same_revision | COMPLETION |  | `` | ACTIVE_PROTOTYPE | 동일 revision의 최종 확인 후 완료. 미해결 항목이 남으면 완료 금지 |
| required_Q4_1.years_since_quit | FIELD_REQUIREMENT | Q4_1.years_since_quit | `{"field":"status","item_id":"Q4_1","op":"equals","value":"former"}` | ACTIVE_PROTOTYPE | 해당 문항이 적용되면 이 조건에서 필요한 필드 |
| required_Q5_1.years_since_quit | FIELD_REQUIREMENT | Q5_1.years_since_quit | `{"field":"status","item_id":"Q5_1","op":"equals","value":"former"}` | ACTIVE_PROTOTYPE | 해당 문항이 적용되면 이 조건에서 필요한 필드 |
| required_Q7.frequency | FIELD_REQUIREMENT | Q7.frequency | `{"field":"does_not_drink","item_id":"Q7","op":"equals","value":false}` | ACTIVE_PROTOTYPE | 해당 문항이 적용되면 이 조건에서 필요한 필드 |
| required_Q7.unit | FIELD_REQUIREMENT | Q7.unit | `{"field":"does_not_drink","item_id":"Q7","op":"equals","value":false}` | ACTIVE_PROTOTYPE | 해당 문항이 적용되면 이 조건에서 필요한 필드 |
| beverage_list_complete | OPERATION_POLICY |  | `` | ACTIVE_PROTOTYPE | 술 종류 목록의 완결성을 progress_json에 별도 기록. 미언급 술을 0으로 채우지 않음 |
| delivery_cardinality | OPERATION_POLICY |  | `` | PENDING | 결과 수령방법의 단일/복수 선택 허용 여부 확정 필요 |
| exercise_zero_duration | OPERATION_POLICY |  | `` | PENDING | 운동 0일이면 시간 생략/0 처리 여부 확정 필요; 자동 생략하지 않음 |
| explicit_correction | OPERATION_POLICY |  | `` | ACTIVE_PROTOTYPE | 정정 대상·근거 확인 후 새 revision. 미해결 모순은 덮어쓰기 금지 |
| intake_required | OPERATION_POLICY |  | `` | PENDING | 성명·식별정보·연락처 등 필수 접수 필드 범위는 기관 정책 필요 |
| never_guess | OPERATION_POLICY |  | `` | ACTIVE_PROTOTYPE | 모름·거부·미응답은 false/0으로 바꾸지 않음 |
| next_unresolved | OPERATION_POLICY |  | `` | ACTIVE_PROTOTYPE | 확인된 필드는 건너뛰고 미해결 필드를 질문. 마지막 번호만으로 완료 금지 |
| one_unit_per_beverage | OPERATION_POLICY |  | `` | ACTIVE_PROTOTYPE | 같은 술 종류는 한 단위의 양으로 기록; 혼합 단위는 확인 |
| other_beverage_mapping | OPERATION_POLICY |  | `` | PENDING | 기타 술을 비슷한 종류에 분류하는 기준이 필요. 모델 임의 분류 금지 |
| preserve_period_unit | OPERATION_POLICY |  | `` | ACTIVE_PROTOTYPE | 질문의 기준 기간과 횟수 단위를 분리하며 임의 환산하지 않음 |
| raw_range_before_option | OPERATION_POLICY |  | `` | ACTIVE_PROTOTYPE | Q6_1 원시 범위 전체가 선택지에 포함될 때만 매핑. 30일만으로 매일 추정 금지 |
| recompute_children | OPERATION_POLICY |  | `` | ACTIVE_PROTOTYPE | 상위 답변 변경 시 하위 적용 여부 재평가. 과거 답변 자동 재확정 금지 |

항상 필요한 칸(FIELD_REQUIREMENT, op=always) 48개: `Q1.D01.diagnosed`, `Q1.D01.on_medication`, `Q1.D02.diagnosed`, `Q1.D02.on_medication`, `Q1.D03.diagnosed`, `Q1.D03.on_medication`, `Q1.D04.diagnosed`, `Q1.D04.on_medication`, `Q1.D05.diagnosed`, `Q1.D05.on_medication`, `Q1.D06.diagnosed`, `Q1.D06.on_medication`, `Q1.D07.diagnosed`, `Q1.D07.on_medication`, `Q1.D08.diagnosed`, `Q1.D08.on_medication`, `Q1.D09.diagnosed`, `Q1.D09.on_medication`, `Q1.D10.diagnosed`, `Q1.D10.on_medication`, `Q1.D11.diagnosed`, `Q1.D11.on_medication`, `Q10.days`, `Q2.D01.family_history`, `Q2.D02.family_history`, `Q2.D03.family_history`, `Q2.D04.family_history`, `Q2.D05.family_history`, `Q3.answer`, `Q4.answer`, `Q4_1.daily_count`, `Q4_1.status`, `Q4_1.total_years`, `Q5.answer`, `Q5_1.daily_count`, `Q5_1.status`, `Q5_1.total_years`, `Q6.answer`, `Q6_1.use_pattern`, `Q7.does_not_drink`, `Q7_1.amount`, `Q7_1.unit`, `Q7_2.amount`, `Q7_2.unit`, `Q8_1.days`, `Q8_2.duration_minutes`, `Q9_1.days`, `Q9_2.duration_minutes`

## 6. LoRA-A 출력을 DB에 저장하는 법

서비스에는 정규화기가 없으므로, LoRA-A 출력(`values`)을 서비스 코드가 아래 규칙으로 저장한다. 규칙과 SQL은 정규화기 `store.save_result`와 같다(학습 정답이 이 규칙으로 만들어졌으므로 저장도 같아야 한다).

### 6.1 키·값·상태 대응

| LoRA-A 출력 | DB |
|---|---|
| `key` `Q1.D03.diagnosed` | field_id `Q1.D03.diagnosed`, repeat_key `''` |
| `key` `Q7_1[soju].amount` | field_id `Q7_1.amount`, repeat_key `soju` |
| `value` | 칸 자료형에 맞는 열 하나(5.2의 '값 열'). true/false는 1/0 |
| `precision` | precision (exact / approximate / unspecified) |
| `status` ANSWERED (`save` true) | resolution_status `CONFIRMED`, change_reason `NEW_INFORMATION` |
| `status` CORRECTION (`save` true) | resolution_status `CONFIRMED`, change_reason `CORRECTION` (새 revision) |
| `status` MISSING | resolution_status `PARTIAL`, 값 없음 |
| `status` UNCLEAR | resolution_status `AMBIGUOUS`, 값 없음 |
| `status` UNKNOWN | resolution_status `UNCERTAIN`, 값 없음 |
| `status` REJECTED, reason REFUSED | resolution_status `REFUSED`, 값 없음 |
| `status` REJECTED, reason REQUEST_SKIP | resolution_status `DEFERRED`, 값 없음 |
| `status` CONFLICT | **저장하지 않음** (확인 질문 뒤 CORRECTION 또는 같은 값으로 다시 들어온다) |
| 반복 문항(Q7_1·Q7_2) 키에 `[술 종류]`가 없음 (예: `Q7_1.amount`) | **저장하지 않음** (술 종류를 모르는 보류·재질문. 정규화기 저장 코드도 NO_REPEAT_KEY로 건너뜀) |

- `save`=true는 '확정값(CONFIRMED)으로 저장'이라는 뜻이다. save=false 줄도 상태만 있는 revision으로 남길 수 있다(정규화기와 같음).
- 이미 CONFIRMED인 칸: 미확정 상태(PARTIAL 등)로 덮어쓰지 않는다. 값이 같으면 저장하지 않는다. 값이 다르면 CORRECTION일 때만 새 revision을 쓴다(정책 `explicit_correction`).
- applicability_status는 저장하는 줄에서 `APPLICABLE`이다.

### 6.2 저장 SQL (한 턴 = 한 트랜잭션)

```sql
-- 0) 연결마다
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
COMMIT;
```

- `actor`는 저장 주체(예: `lora_a`), `ruleset_version`은 모델·데이터 버전(예: `dataset-v2`)을 넣는다. 정규화기는 `normalizer`, `normalizer-0.4`를 썼다.
- 트리거에 걸리면 트랜잭션 전체가 롤백된다. 예: Q7_1 거절을 빈 repeat_key로 저장하면 `invalid_repeat_key`(알려진 이슈, README 7장).

### 6.3 예: "위스키를 잔 단위로 마십니다" (Q7_1, REASK)

```json
{"values": [{"key": "Q7_1[spirits].amount", "value": null, "precision": "unspecified", "status": "MISSING", "save": false},
            {"key": "Q7_1[spirits].unit", "value": "glass", "precision": "exact", "status": "ANSWERED", "save": true}],
 "action": "REASK", "reason": "MISSING", "targets": ["Q7_1[spirits].amount"], "next_item": "Q7_1"}
```

```sql
-- unit: 확정값
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

UPDATE sessions SET revision = revision + 1 WHERE session_id = 's1';
```

## 7. 서비스에서 쓰는 조회 SQL

### 7.1 LoRA-A 입력 `state` 만들기 (저장된 확정값)

```sql
SELECT field_id, repeat_key, value_boolean, value_number, value_option, value_text
  FROM current_answers
 WHERE session_id = :session_id AND resolution_status = 'CONFIRMED';
-- -> {"<item>.<field>" 또는 "<item>[<repeat_key>].<field>": {"value": ..., "status": "ANSWERED"}}
--    (field_id 'Q7_1.amount' + repeat_key 'soju' -> 'Q7_1[soju].amount', value_boolean 1/0 -> true/false)
```

- 매 턴 같은 규칙으로 세 문항의 값만 넣는다: 지금 문항, 직전에 물은 문항(대화 순서, 건너뛰기 반영), 참조 원천 문항(taxonomy.REF_SOURCE, 예: Q10 -> Q9_1). 학습 데이터도 build_final이 이 규칙으로 state를 넓힌다(scripts/prev_state.py, 2026-10-14). 모름·거절로 넘긴 문항은 확정값이 없어 나오지 않는다.
- 재질문 중인 칸은 상태만 넣는다: `resolution_status IN ('PARTIAL','AMBIGUOUS')` -> `{"value": null, "status": "MISSING|UNCLEAR"}`.

### 7.2 B 입력 `previous` (CONFIRM일 때 이전 값)

```sql
SELECT value_boolean, value_number, value_option, value_text
  FROM current_answers
 WHERE session_id = :session_id AND field_id = :field_id AND repeat_key = :repeat_key
   AND resolution_status = 'CONFIRMED';
-- 평소량보다 적은 최대량(CONFLICT_MAX_BELOW_USUAL)이면 Q7_1의 같은 술(repeat_key) amount·unit을 읽는다
```

### 7.3 다음 질문 문장 (next.text)

```sql
SELECT question_text, subject_label FROM question_items
 WHERE version_id = 'national_health_2026_v1' AND item_id = :next_item;
-- 데이터셋은 data/question_bank.json의 상담원 말 표현을 쓴다(원문 대신 바꿔 말한 질문)
```

### 7.4 아직 안 끝난 칸 (마무리 전 점검용)

```sql
SELECT f.field_id, a.repeat_key, r.resolution_status
  FROM question_fields f
  LEFT JOIN current_answers r ON r.session_id = :session_id AND r.field_id = f.field_id
  LEFT JOIN answers a ON a.session_id = :session_id AND a.answer_id = r.answer_id
 WHERE f.version_id = 'national_health_2026_v1'
   AND (r.resolution_status IS NULL OR r.resolution_status != 'CONFIRMED');
-- 적용 조건(questionnaire_rules APPLICABILITY)과 조건부 필수 칸(FIELD_REQUIREMENT)은 결과에서 따로 걸러야 한다
```

## 8. 데이터셋 v2 규칙과 DB 규칙이 다른 곳 (확인 필요)

| 항목 | 데이터셋 v2 (LoRA-A가 배우는 것) | DB 규칙 | 메모 |
|---|---|---|---|
| Q4_1·Q5_1·Q6_1·Q7_1·Q7_2 건너뛰기 | 상위 답이 아니요·안 마심이면 건너뜀 | `applies_*` APPLICABILITY 규칙과 같음 | 일치 |
| Q8_2·Q9_2 건너뛰기 | Q8_1·Q9_1이 0일이면 건너뜀 | `exercise_zero_duration`: PENDING, '자동 생략하지 않음' | **다름.** 운동 0일이면 시간 질문을 생략할지 정책 확정 필요 |
| 마무리 | Q10 다음은 END | `next_unresolved`: 미해결 칸을 다시 묻고 마지막 번호만으로 완료 금지, `review_same_revision`: 최종 확인 뒤 완료 | **다름.** 서비스에서 END 전에 7.4로 미해결 칸(보류·거절)을 점검할지 정해야 함 |
| 범위 답 | 가운데 값 + approximate | `raw_range_before_option`(Q6_1은 범위 전체가 한 선택지에 들 때만 매핑) | Q6_1은 일치, 나머지 숫자 칸은 정규화기 규약 |
| 술 단위 섞임 | cc로 환산, approximate | `one_unit_per_beverage`: 같은 술은 한 단위로, 섞이면 확인 | 정규화기가 환산함. 확인 질문으로 바꿀지 정책 확인 필요 |
| Q7_1·Q7_2 거절·보류 | SKIP 데이터 적음 | `valid_repeat_key`가 빈 반복 키를 막음 | 정규화기 이슈 후보 |

