# 건강검진 문진 상담 LoRA 데이터셋 v2

건강검진 문진 상담 에이전트용 학습 데이터입니다. 두 LoRA를 학습하는 데 씁니다.

- **LoRA-A**: 환자 말을 읽고 저장할 값과 다음 절차를 정합니다.
- **LoRA-B**: 정해진 절차를 상담원 말로 전합니다.

이 폴더는 2026-10-13에 확정한 v2 구조로 **처음부터 새로 만든** 데이터셋입니다.

- 이전 데이터(`/home/openit/WS/old version/augmentation_scale_20261011`, toy dataset v1·v2)와 시드는 쓰지 않습니다.
- 모든 시나리오는 `source = new_sampled`입니다.
- 상담원 질문 표현 모음(`data/question_bank.json`)도 첫 실행 때 새로 만들었습니다.

| 항목 | 값 |
|---|---|
| 생성 모델 | Qwen3-30B-A3B-Instruct-2507 (로컬 GPU, vLLM) |
| 정답 기준 | 정규화기 `openit-normalizer` routing_policy v1.0 (읽기만 함) |
| 목표 | 시나리오 5,000개 = LoRA-A 5,000건 + LoRA-B 5,000건, 여기에 LoRA-B 전용 START 150건 |
| 현재 (T1 빌드) | 5,077턴(train 3,982 / val 549 / test 546) + START 110건 |
| 분할 | scenario_family 단위 train/val/test = 80/10/10 |
| 검증 | 생성 7단계 + 빌드 + 사후(`verify_sql --final` 5,077/5,077 일치). 자세한 내용은 3장 |
| 사람 검수 | 진행 전 (검수 큐 `review/review_queue.csv`, 검수 페이지 반영은 3.5) |

## 1. 구조

```
[문진 시작]  서비스 ──> LoRA-B(START): 인사 + 첫 질문(Q1.D01 뇌졸중)
[매 턴]     환자 말 ──> LoRA-A: 추출 + 정규화 + 절차(action) + 다음 문항(next_item)
                    ──> 서비스: 표 찾기(질문 문장, 사람 말 설명; scripts/labels.py)
                    ──> LoRA-B: 상담원 응답
[Q10 다음]  LoRA-A next_item = END ──> LoRA-B: 마무리 인사
```

- **서비스에는 정규화기가 없습니다.** 값 정규화(선택지 코드, 분 단위 환산, 술 종류 코드 등), 상태, 절차, 다음 문항은 모두 LoRA-A가 출력합니다.
- **정규화기는 학습 정답을 만드는 기준으로만 씁니다.** 생성 파이프라인이 정답을 정규화기에 돌리고, 그 결과를 v2 형식으로 옮깁니다(`scripts/labels.py`).
- **서비스 코드는 판단하지 않습니다.** 하는 일은 표 찾기뿐입니다.
  - 문항 번호로 질문 문장을 찾습니다.
  - 값을 사람 말 설명으로 바꿉니다(`known`, `ask`, `previous`, `current`, `hold`).
  - 이 표의 기준 구현이 `scripts/labels.py`이고, 문서는 `docs/LABEL_TABLES.md`입니다.

## 2. 규칙

### 2.1 문항 순서와 건너뛰기
- 순서: Q1.D01 → … → Q1.D11 → Q2.D01 → … → Q2.D05 → Q3 → Q4 → Q4_1 → Q5 → Q5_1 → Q6 → Q6_1 → Q7 → Q7_1 → Q7_2 → Q8_1 → Q8_2 → Q9_1 → Q9_2 → Q10 → END (31문항)
- 건너뛰기는 이번 턴에 저장되는 값만 보고 정합니다.

| 조건 | 건너뛰는 문항 |
|---|---|
| Q4·Q5·Q6 = 아니요 | Q4_1·Q5_1·Q6_1 |
| Q7 = 술 안 마심 | Q7_1·Q7_2 |
| Q8_1·Q9_1 = 0일 | Q8_2·Q9_2 |

### 2.2 절차 (action)

| action | 뜻 | 정규화기 plan | next_item | B next.type |
|---|---|---|---|---|
| START | 문진 시작 (B만, A 없음) | – | Q1.D01 | NEXT |
| NEXT | 답을 받고 다음 문항으로 | NEXT | 다음 문항 | NEXT / END |
| CORRECT | 앞 답을 고치고 다음 문항으로 | ACK_CORRECTION | 고친 문항의 다음 문항(건너뛰기 다시 계산) | NEXT / END |
| REASK | 같은 문항에서 빠졌거나 불분명한 칸을 다시 물음 | ASK_MISSING, ASK_CLARIFICATION | 대상 칸의 문항 | SAME |
| CONFIRM | 저장된 값과 달라서 확인함 | ASK_CONFLICT | 대상 칸의 문항 | SAME |
| HOLD | 모름이라 그 칸을 비우고 다음 문항으로 | ASK_OR_HOLD | 다음 문항 | NEXT / END |
| SKIP | 거절·나중에라서 넘어가고 다음 문항으로 | HOLD_OR_SKIP | 다음 문항 | NEXT / END |
| REDIRECT | 문진과 상관없는 말에 반응하고 지금 질문으로 돌아옴 | REDIRECT | 지금 묻던 문항 | SAME |

- **END는 action이 아니라 next_item 값입니다.** Q10에서는 정정·모름·거절 뒤에도 마무리해야 하기 때문입니다.
- **reason(사유 코드)** 은 action마다 다음 값을 씁니다.

| action | reason |
|---|---|
| REASK | MISSING, OUT_OF_RANGE, VAGUE_QUANTITY, RANGE_SPANS_OPTIONS, UNKNOWN_UNIT, COUNT_EXCEEDS_DAYS |
| CONFIRM | CONFLICT_WITH_PREVIOUS, CONFLICT_MAX_BELOW_USUAL |
| HOLD | UNCERTAIN, BEVERAGE_MISSING |
| SKIP | REFUSED, REQUEST_SKIP |
| REDIRECT | ASK_PURPOSE, OFF_TOPIC, OUT_OF_SCHEMA |

### 2.3 정답 규약 (정규화기 v1.0 그대로)
- 범위 답("3~5일")은 가운데 값과 어림(`4`, `approximate`)으로 저장합니다.
  - 응답은 환자가 말한 범위 표현으로 되짚습니다.
  - 범위를 그대로 저장할지는 정규화기 담당자와 정할 일입니다(7장).
- Q6_1은 일수 구간 코드로 저장합니다(days_1_2 / days_3_9 / days_10_29 / daily).
- Q7_1·Q7_2는 술 종류 코드(soju·beer·spirits·makgeolli·wine)별 양과 단위로 저장합니다.
  - 여러 단위를 섞어 말하면 cc로 환산하고 어림으로 표시합니다.
- 시간(Q8_2·Q9_2)은 분으로 저장합니다.

### 2.4 LoRA-B 응답 규칙
- **말투:** 친근한 존댓말로 1~3문장입니다(`~하시는군요`, `~세요?`, `~할게요`).
  - 보고체("~라고 답변하셨습니다", "이해했습니다"), 느낌표·감탄·칭찬, 진단·조언·처방은 쓰지 않습니다.
- **문항:** topic의 문항만 말합니다. 다른 질환이나 문항 이름을 섞지 않습니다.
- **되짚기:** 짧게 한 번만 합니다.
  - 값은 known·previous·current에 있는 것만 말하고, 표현은 환자가 한 말을 따릅니다.
  - 환자가 말한 여러 양을 빠뜨리지 않습니다.
  - 환자가 하지 않은 '정도·쯤'을 붙이지 않습니다.
  - 단위나 기간을 바꿔 말하지 않습니다.
- **끝맺음:**
  - next.type NEXT: next.text를 묻고 끝냅니다.
  - next.type SAME: ask(없으면 next.text)를 질문 하나로 묻고 끝냅니다.
  - next.type END: 질문 없이 마무리 인사로 끝냅니다.
  - END가 아니면 "문진이 끝났다"는 말을 하지 않습니다.
- **유도 질문 금지:** "맞죠?", "드시죠?"는 쓰지 않습니다. 확인할 때는 "~이 맞을까요?"로 묻습니다.
- **START:** 인사와 짧은 안내 뒤에 뇌졸중(중풍) 질문을 합니다. 질문 부분은 비슷할 수밖에 없고, 인사·안내 부분만 서로 다르게 만듭니다.

### 2.5 환자 발화 규칙 (v1.17 승인안 + v2)
- 말투 8종: formal_full, casual_short, banmal, elderly_verbose, hesitant_filler, hangul_numbers, dialect, stt_noise.
  - 말투마다 최소 5%이고, STT 오류형은 15% 이하입니다.
- 문진표 낱말("중강도 신체활동", "암을 포함한 기타 질환")을 그대로 쓰지 않습니다.
- 자기 답을 보증하는 군말을 붙이지 않습니다. 틀린 숫자 말투("두 년", "다섯 날", "열백")를 쓰지 않습니다.
- 정정(P05)·충돌(P06 prev_diff)은 상담원이 앞 답을 되짚고 다음 질문으로 넘어간 뒤, 환자가 앞 답을 고치거나 다르게 말하는 흐름입니다.
  - A 입력의 `question_id`는 그때 묻고 있던 다음 문항입니다.
- Q1.D01 단일 턴의 약 절반은 START 응답(인사 + 첫 질문)을 상담원 말로 씁니다.

### 2.6 시나리오 유형 (pattern)과 배분
- 1 시나리오 = LoRA-A 1건 + LoRA-B 1건입니다.
- 배분표는 `patterns/allocation_10000.yaml`입니다(`scripts/build_allocation.py`가 `scripts/taxonomy.py`에서 만듭니다).

| pattern | 뜻 | 5,000 기준 |
|---|---|---:|
| P01_normal | 정상 답 | 1,403 |
| P02_range_unit | 범위·어림·단위·여러 술 | 796 |
| P03_partial | 일부 칸만 답함 | 501 |
| P04_reask_fill | 재질문 뒤 보완 | 399 |
| P05_correction | 정정 | 448 |
| P06_conflict | 충돌(정정 표현 없이 다른 값, 평소량보다 적은 최대량) | 398 |
| P07_prior_ref | 앞 답 참조("아까랑 같아요") | 206 |
| P08_unk_refuse | 모름·거절·나중에 | 398 |
| P09_oos | 목적 질문·잡담·문진표 밖 건강 이야기 | 203 |
| P10_boundary | 경계값·범위 밖 | 248 |
| P11_norm_case | 정규화기 사유 코드·정리 규칙 사례 (보충 T1, 배분표 밖) | 589 |

- 모든 action은 최소 3%를 넘게 배분했습니다(NEXT가 가장 많습니다).
- 문항마다 최소 75건입니다(10,000 기준 150건).
- END 학습량을 늘리려고 Q10 가중치를 3.0으로 올렸습니다.
- **P11(2026-10-13 보충):** S3까지 한 번도 나오지 않은 정규화기 사유 코드·규칙을 따로 만듭니다(하위 유형 19개, `sampler.NORM_CASE_ITEMS`,
  칸별 목표 `taxonomy.NORM_CASE_QUOTA`).
  - REASK: OTHER_BEVERAGE(모르는 술), BEVERAGE_MISSING(술 종류 빠짐), MISSING_NUMBER(숫자 없이 "네"), INVALID_OPTION(선택지 밖 답)
  - CONFIRM: CONFLICT_MAX_BELOW_USUAL(최대량 < 평소량), CONFLICT_DOES_NOT_DRINK(안 마신다면서 양을 말함)
  - NEXT: 도수로 칸 정하기(하이볼·사케 등), 술 이름 이어받기, 매일·거의 매일, 안 마심 + 횟수, 몇 대만 피움, 끊었어요,
    "안 피워요" + 과거 흡연, 다시 피움(끊은 기간 버림), 전단계, 약만 먹음(진단 추론), 운동 전혀 안 함(세 문항 0일 -> END), 0일 + 다른 활동 시간
  - REDIRECT: 부모·형제자매가 아닌 가족의 병(NOT_TARGET_FAMILY)
  - 넣지 않은 것: TYPE_MISMATCH·UNKNOWN_FIELD·INVALID_REPEAT_KEY·UNASKED(추출 형식 오류용 내부 코드라 환자 발화로 생기지 않음)

## 3. 생성 과정과 검증

### 3.1 원칙

- **정답은 정규화기가 정하고, LLM은 사람이 하는 말만 씁니다.**
  - LLM이 쓰는 것: 환자 발화, 상담원 응답(LoRA-B), 역추출과 판정
  - 정규화기가 정하는 것: 저장 값, 상태, 절차(action), 다음 문항. 이 결과를 `labels.py`가 v2 형식으로 옮깁니다.
- **검증은 정답을 고치지 않습니다.** 검사에 걸린 후보는 버리고 사유 코드를 남깁니다(`checks.Reject`).
- **검증은 세 번 합니다.** 레코드를 만들 때(생성), 학습 파일로 묶을 때(빌드), 다 만든 뒤(사후)입니다. 그 위에 사람 검수가 있습니다.

```
[생성] sampler ─ 발화 생성 ─ ①발화 검사 ─ ②역추출 일치 ─ ③자연스러움 판정 ─ ④정규화기 재실행
         ─ labels(A 정답, B 입력) ─ B 응답 생성 ─ ⑤응답 가드 ─ ⑥응답 판정 ─ ⑦DB 왕복 ─> shard
                                                  (실패: 말투·시드 바꿔 최대 3번)
[빌드] state 넓히기(정답 불변 확인) ─ 사람 수정 반영 ─ 중복 제거 ─ 할당량 ─ 누수 묶기 ─ 분할 ─> data/final
[사후] verify_sql --final(DB 저장 규칙) · selftest(가드 자체 시험) · 사람 검수 페이지
```

### 3.2 생성 단계 검증 (`pipeline.py`, `checks.py`)

시나리오 하나는 아래 순서를 모두 통과해야 저장됩니다. 탈락 수는 S3+T1 합계입니다(전체 30,737건, `data/generated/rejects/`).

| 순서 | 검사 | 코드 | 막는 문제 | 주요 탈락 사유 (건수) |
|---|---|---|---|---|
| 0 | **canonical 샘플** | `sampler.build_canonical` | 의도한 pattern이 아닌 시나리오. 정규화기 plan이 pattern에 맞을 때만 씁니다 | – |
| ① | **발화 검사** | `check_utterance`, `check_utterance_v117`, `check_prior_turns` | 길이, 화자 혼동, 메모 노출, 글말, 질문·메모·예시 베끼기, 시나리오에 없는 숫자, 없는 어림 표현, 문진표 낱말, 틀린 숫자 말투, 앞 대화 모순, 중복 | duplicate_surface 7,815 · unexpected_approx 2,590 · u_bad_number 1,580 · copies_spec 1,419 · new_number 1,326 · copies_question 493 · copied_example 347 |
| ② | **역추출 일치** | `check_extraction` | 발화가 정답 내용을 실제로 담지 않음. 정답을 보지 않은 LLM이 발화만 보고 다시 추출하고, 그 결과를 정규화기에 돌린 핵심이 정답과 같아야 합니다 | blind_extraction_mismatch 6,002 |
| ③ | **발화 자연스러움 판정** (LLM) | `prompts.utterance_judge_messages` | 실패 유형 9가지(상담원 말투, 자기 존칭, 작성 지시 노출, 말이 안 되는 숫자, 예·아니요가 모호함, 문진표 낱말 읽기, 보증 군말, 앞뒤 어긋남, 글말) 또는 자연스러움 3점 미만 | utterance_unnatural 4,051 |
| ④ | **정규화기 재실행** | `checks.normalized` | 근거 구간을 붙인 정답으로 다시 돌린 결과가 기준과 다름. 두 번 돌려 결과가 달라짐 | normalizer_mismatch, not_idempotent |
| – | **A 정답, B 입력 만들기** | `labels.a_target`, `labels.b_input` | 검사가 아니라 옮기기만 합니다. 값을 새로 정하지 않습니다 | – |
| ⑤ | **응답 가드** | `check_response` | 의료 조언, 코드 노출, 보고체, 유도 질문, 새 숫자, 끝맺음(END는 인사, NEXT·SAME은 질문), 다른 질환 이름, 없는 어림, 술 단위·기간 바꿈, 양 누락, 질문 두 개, 확인할 때 이전 값을 말하지 않음, 환자 말 복사, 중복 | b_duplicate 1,369 · b_start_near_duplicate 932 · b_no_question 287 · b_new_number 159 |
| ⑥ | **응답 판정** (LLM) | `prompts.judge_messages` | 응답이 action·next와 맞지 않음, 자연스러움 3점 미만 | b_judge_action_mismatch 1,564 |
| ⑦ | **DB 왕복** | `checks.RoundTrip` | 기준 문진 DB 임시 복사본에 이전 턴과 이번 턴을 저장하고 조회합니다. `save=true` 칸이 같은 값으로 저장되지 않거나 DB 트리거가 거부함 | db_roundtrip_mismatch, db_save_error |

- ⑤⑥에서 떨어지면 발화는 두고 B 응답만 말투와 시드를 바꿔 최대 3번(`B_TRIES`) 다시 만듭니다.
- DB가 거부한 사례는 정규화기 이슈 후보로 `data/generated/normalizer_issue_candidates.jsonl`에 남깁니다. 정규화기 코드는 고치지 않습니다.
- 통과한 레코드의 판정 점수와 역추출 일치 여부는 `validation`(`utterance_judge`, `b_judge`, `extraction_raw_match`)에 남습니다.

### 3.3 빌드 단계 검증 (`build_final.py`)

| 순서 | 처리 | 코드 | 기준 | T1 결과 |
|---|---|---|---|---|
| 0 | **state 넓히기** | `prev_state.augment` | A 입력 state를 서비스 규칙(지금 문항, 직전 문항, 참조 원천; SQL.md 7.1)으로 넓히고 정규화기를 다시 돌립니다. 정규화 핵심, A 정답, B 입력이 원래와 모두 같아야 씁니다(최대 30번 다른 흐름 시도) | 7건 제외 (모두 Q7_2: Q7_1 술 종류를 이어받아 정답이 바뀜) |
| 0-2 | **사람 수정 반영** | `human_edits.apply` | 검수 페이지에서 고친 A 입력, A 정답, B 입력, B 응답의 형식을 검사하고 반영합니다. A와 B의 action이 다르거나 B 입력이 바뀌었는데 응답을 그대로 둔 건은 보고서에 따로 나옵니다 | 현재 0건 |
| 1 | **중복 제거** | `checks.surface`, MinHash | 정규화 문자열 일치, 글자 3-gram 추정 Jaccard 0.85 이상 | 근접 중복 116건 제외 |
| 2 | **할당량** | `pipeline.stage_quota` | 칸(문항, pattern, plan)별 누적 할당량까지만 쓰고 넘는 것은 예비분으로 둡니다 | 예비 1,444건 |
| 3 | **누수 묶기** | DSU | 다른 family끼리 발화 Jaccard 0.70 이상이면 같은 split에 둡니다 | 243개 연결, 여러 split에 걸친 family 0 |
| 4 | **분할** | `split_groups` | 묶음 해시로 80/10/10. test에 31개 문항, 모든 pattern이 들어가게 합니다 | train 3,982 / val 549 / test 546, test 문항 31·pattern 11 |

결과는 `reports/distribution_T1.json`에 남습니다. 배분 대비 실제 수, 문항 최소량, action·next 분포, state 크기 분포가 들어 있습니다.

### 3.4 사후 검증

| 명령 | 확인하는 것 | 현재 결과 |
|---|---|---|
| `verify_sql.py --final` | 최종 레코드마다 두 경로로 같은 DB 결과가 나오는지 봅니다. 문서 경로는 A 입력 state와 A 정답을 `docs/SQL.md` 대응표와 SQL대로 저장하고, 기준 경로는 정규화기의 실제 저장 코드로 저장합니다. 키가 DB 칸인지, 선택지 코드가 있는지, 트리거에 걸리지 않는지도 봅니다 | 5,077 / 5,077 일치 (`reports/verify_sql_final.json`) |
| `selftest.py` | GPU 없이 도는 자체 시험입니다. pattern·action 조합별 A 정답과 B 입력 변환, 좋은 예가 가드를 통과하는지, 일부러 만든 나쁜 응답 18개를 가드가 잡는지 봅니다 | 변환 문제 0, 좋은 예 탈락 0, 나쁜 응답 17/18 잡음 (`reports/selftest.json`) |

### 3.5 사람 검수

- **검수 큐** (`review/review_queue.csv`): 층(pattern × 문항 묶음)마다 5건, 전체의 5%, 역추출 원시 레이블이 다른 경계 판정 전수, START 일부를 뽑습니다. 이 레코드는 `human_review = pending`, 나머지는 `auto_only`입니다.
- **검수 페이지**: 레코드마다 OK/문제 판정, 태그, 메모를 남기고 A 입력, A 정답, B 입력, B 응답을 직접 고칠 수 있습니다. 자동 의심 표시(이전 턴과 state의 모순, 다음 문항 일부가 이미 채워짐, 아는 흡연 여부 재질문, 판정 점수 낮음)는 먼저 볼 후보를 고르는 휴리스틱입니다. 정답 판정은 아닙니다.
- **반영 순서**: 페이지 저장소를 내려받습니다 → `human_edits.py collect <폴더>`로 `review/human_edits.json`을 만듭니다 → `build_final.py --upto T1` → `verify_sql.py --final`.
  - 사람 수정은 생성 원본 위에 덮어씁니다. 그래서 다시 빌드해도 유지됩니다.
  - A 정답만 고치면 B 입력은 새 정답으로 다시 계산합니다. B 입력을 직접 고치면 고친 그대로 씁니다.
- **human_review 값**:

| 값 | 뜻 |
|---|---|
| `auto_only` | 자동 검증만 통과 |
| `pending` | 검수 큐에 들어 있고 아직 판정 없음 |
| `human_ok` | 사람이 OK 판정 |
| `human_flagged` | 사람이 문제로 판정했고 고치지 않음 |
| `human_edited` | 사람이 직접 고침 (`validation.human_edit`에 고친 칸이 남음) |

- 자동 판정은 생성과 같은 모델이 합니다. 그래서 사람 검수를 대신하지 않습니다. 코드는 사람 판정을 만들어 넣지 않습니다.

### 3.6 검증이 잡지 못하는 것

| 빈 곳 | 영향 | 현재 대응 |
|---|---|---|
| 이전 턴 환자 말과 state 값이 맞는지 | 예: 앞 턴에서 "뇌졸중은 없어요"라고 했는데 state가 true입니다. 학습 입력에는 이전 턴이 들어가지 않지만 검수할 때 헷갈립니다 | 검수 페이지 의심 표시(후보 15건) |
| B가 이미 아는 칸을 다시 묻는지 | 다음 문항(Q4_1·Q5_1)의 흡연 상태가 이미 저장됐는데 "지금 피우세요?"라고 다시 묻습니다 | 의심 표시(18건). 가드 규칙은 아직 없음 |
| 판정 LLM의 오판 | 같은 모델이 쓰고 판정합니다 | 사람 검수 |
| 역추출이 정답과 같은 쪽으로 틀림 | 발화가 모호한데 두 LLM이 같은 뜻으로 읽으면 통과합니다 | 원시 레이블이 다른 경계 판정 전수를 검수 큐에 넣음 |
| current_question 형태 | 학습은 대부분 문항 은행 질문을 씁니다. 서비스에서는 B 응답 전체(되짚기 + 질문)가 들어옵니다 | 미결 (7장) |

## 4. 데이터셋 스키마

### 4.1 파일

| 파일 | 내용 |
|---|---|
| `data/final/{train,val,test}.jsonl` | 마스터 레코드(4.2) |
| `data/final/lora_a_{split}.jsonl` | LoRA-A 학습용 messages(system, user=A 입력 JSON, assistant=A 출력 JSON). START 제외 |
| `data/final/lora_b_{split}.jsonl` | LoRA-B 학습용 messages(system, user=B 입력 JSON, assistant=응답 문장). START 포함 |
| `data/final/subsets/{1000,2500,5000}_manifest.txt` | 앞에서부터 N개 시나리오의 train scenario_id (nested) |
| `review/review_queue.csv` | 사람 검수 큐(층별 표본 + 경계 판정 전수 + START 10건) |
| `reports/distribution_T1.json` | 분포·하한·중복·누수·state 크기·사람 수정 보고 |
| `reports/verify_sql_final.json`, `reports/selftest.json` | 사후 검증 결과 |

> git 저장소에는 코드와 문서만 올립니다. `data/`, `reports/`, `review/`는 `.gitignore`로 빠져 있어서 서버의 작업 폴더에만 있습니다.

### 4.2 마스터 레코드

```jsonc
{
  "record_type": "turn",               // turn(A+B) | start(B만)
  "scenario_id": "c_Q7_1_P03_partial_0003_v1",
  "scenario_family": "c_Q7_1_P03_partial_0003",   // split 단위(같은 canonical의 말투 변형 묶음)
  "question_id": "Q7_1",               // 값·대상의 문항(배분 기준)
  "asked_item": "Q7_1",                // 상담원이 묻고 있던 문항 = A 입력 question_id
  "pattern_type": "P03_partial", "subtype": "missing_amounts[0].amount",
  "source": "new_sampled", "style_tag": "formal_full",
  "previous_turns": [{"role": "assistant|user", "content": "..."}],   // 다중 턴의 앞 대화(학습 입력 아님)
  "user_utterance": "위스키를 잔 단위로 마십니다",
  "lora_a_input": {...},   // 4.3
  "lora_a_target": {...},  // 4.4
  "lora_b_input": {...},   // 4.5
  "lora_b_target": {"response_text": "위스키 드시는군요. 보통 한 번 드실 때 몇 잔 정도 드세요?"},
  "action": "REASK", "next_type": "SAME", "normalizer_plan": "ASK_MISSING",
  "label_source": {"normalizer_output": {...}, "raw_labels": {...}, "canonical_fact": [...], "ruleset_version": "openit-routing-v1.0@..."},
  "generation": {"stage": "S3", "prompt_version": "dataset-v2-prompts-2026-10-13", "utterance": {...}, "response": {...}, ...},
  "validation": {"extraction_raw_match": true, "boundary_case": false, "b_judge": {...}, "utterance_judge": {...},
                 "human_review": "auto_only|pending|human_ok|human_flagged|human_edited",
                 "prev_state": {...}, "split": "train"}
}
```

### 4.3 LoRA-A 입력

```json
{"question_id": "Q7_1",
 "current_question": "술을 마시는 날은 평균적으로 어느 정도 드시나요?",
 "user_utterance": "위스키를 잔 단위로 마십니다",
 "state": {}}
```

- `state`는 매 턴 같은 규칙으로 만든 저장 값입니다: 지금 문항, 직전에 물은 문항, 참조 원천 문항(REF_SOURCE). 서비스가 DB에서 그대로 만들 수 있는 범위이며(SQL.md 7.1), 학습 데이터는 build_final이 `scripts/prev_state.py`로 이 범위까지 넓힙니다(2026-10-14).
  - 형식: `{"Q9_2.duration_minutes": {"value": 15, "status": "ANSWERED"}}`
  - 재질문 대상 칸은 `{"value": null, "status": "MISSING|UNCLEAR"}`입니다.

### 4.4 LoRA-A 출력

```json
{"values": [{"key": "Q7_1[spirits].amount", "value": null, "precision": "unspecified", "status": "MISSING", "save": false},
            {"key": "Q7_1[spirits].unit", "value": "glass", "precision": "exact", "status": "ANSWERED", "save": true}],
 "action": "REASK", "reason": "MISSING",
 "targets": ["Q7_1[spirits].amount"],
 "next_item": "Q7_1"}
```

| 키 | 뜻 |
|---|---|
| `key` | `문항.칸`. 술은 `문항[술 코드].칸` |
| `value` | DB 값(숫자, true/false, 선택지 코드) |
| `precision` | exact / approximate / unspecified |
| `status` | ANSWERED, CORRECTION, MISSING, UNCLEAR, CONFLICT, UNKNOWN, REJECTED |
| `save` | DB 저장 여부 |
| `reason` | NEXT·CORRECT에는 없음 |
| `targets` | REASK·CONFIRM·HOLD·SKIP만 |
| `note` | 문진표 밖 건강 이야기의 짧은 요약(REDIRECT OUT_OF_SCHEMA) |
| `next_item` | 문항 번호 또는 `END` |

### 4.5 LoRA-B 입력

```json
{"action": "REASK", "reason": "MISSING",
 "topic": "술 마시는 날 평소에 마시는 양",
 "user_utterance": "위스키를 잔 단위로 마십니다",
 "known": "양주(위스키 등), 단위 잔 (양은 아직 모름)",
 "ask": "술 마시는 날 평소에 양주(위스키 등)를 몇 잔 마시는지",
 "next": {"type": "SAME", "question_id": "Q7_1", "text": "술을 마시는 날은 보통 어느 정도 마십니까?"}}
```

| 키 | 언제 |
|---|---|
| `topic` | 항상(START 포함) |
| `known` | START 말고 항상. CONFIRM이면 빈 문자열 |
| `ask` | REASK·CONFIRM |
| `previous`, `current` | CONFIRM |
| `hold` | HOLD·SKIP |
| `note` | REDIRECT OUT_OF_SCHEMA |
| `next` | `{"type": "NEXT"|"SAME"|"END", "question_id", "text"}`. END면 type만 있음 |

START 입력: `{"action": "START", "topic": "...", "next": {"type": "NEXT", "question_id": "Q1.D01", "text": "..."}}`

### 4.6 LoRA-B 출력

응답 문장 그대로입니다(학습 파일 assistant 내용). JSON으로 감싸지 않아서 서비스에서 바로 스트리밍할 수 있습니다.

## 5. 실행

```bash
cd /home/openit/WS/dataset
PY=~/miniconda3/envs/openit-llm/bin/python
$PY -B scripts/selftest.py                      # GPU 없이 하는 자체 시험 (v2 변환 규칙, 가드가 예시를 통과하는지)
$PY -B scripts/pipeline.py --stage pilot        # 파일럿
$PY -B scripts/pipeline.py --stage S3           # 5,000 시나리오 + START 150 (중간에 멈추면 같은 명령으로 이어서)
$PY -B scripts/pipeline.py --stage T1           # 보충: S3 부족 칸 + P11 정규화기 사례 589 + START 150까지
$PY -B scripts/build_final.py --upto T1         # 중복 제거·분할·학습 파일·검수 큐·분포 보고 (S3 + T1)
$PY -B scripts/verify_sql.py --final            # 최종 데이터가 SQL.md 저장 규칙대로 DB에 저장되는지 (3.4)
$PY -B scripts/export_docs.py                   # docs/PROMPTS.md, EXAMPLES.md, LABEL_TABLES.md 다시 만들기
$PY -B scripts/export_sql_doc.py                # docs/SQL.md 다시 만들기
$PY -B scripts/human_edits.py collect <폴더>     # 검수 페이지에서 내려받은 판정·수정 모으기 (3.5)
```

- 멈추기: `touch data/generated/STOP` (배치 사이에 멈춤)
- `pkill -f`는 쓰지 않습니다. 셸까지 함께 끝납니다.

## 6. 문서

| 문서 | 내용 |
|---|---|
| `docs/PROMPTS.md` | 모든 생성·판정 프롬프트 전문과 학습용 시스템 프롬프트 (코드에서 자동 생성) |
| `docs/EXAMPLES.md` | 프롬프트에 넣는 좋은 예·나쁜 예 전체 (발화 145, 응답 135, 나쁜 예 29) |
| `docs/LABEL_TABLES.md` | 사람 말 설명표(topic·known·ask·hold), 건너뛰기, action 대응 |
| `docs/IO_SPEC.md` | 입출력 계약 확정본 |
| `docs/SQL.md` | 문진 DB 스키마(DDL·트리거·참조 데이터), LoRA-A 출력 -> DB 저장 SQL, 서비스 조회 SQL, DB 규칙과 다른 곳 (`scripts/export_sql_doc.py`가 DB를 읽기 전용으로 열어 만듦) |
| `docs/WORK_LOG.md` | 작업 기록, 결정, 파일럿 결과 |

## 7. 알려진 한계와 미결

- **자동 생성 + 자동 판정입니다.** 사람 검수가 끝나기 전까지 human_review는 pending 또는 auto_only입니다. 자동 검증이 잡지 못하는 것은 3.6에 있습니다.
- **범위 답 저장 규약(가운데 값)은 정규화기 규약을 그대로 따랐습니다.** 바꾸려면 정규화기 담당자와 정해야 합니다.
- **Q7_1·Q7_2 거절·보류는 DB에 저장되지 않습니다.** 반복 키가 비어 있어서입니다(정규화기 이슈 후보). 그래서 이 칸의 SKIP 데이터가 적습니다.
- **A 입력의 current_question 대부분은 문항 은행 질문입니다.** 서비스에서는 앞 응답의 되짚기가 붙은 질문이 들어옵니다. 예외는 정정·충돌 흐름과 Q1.D01의 START입니다.
- **충돌 r1(술 안 마심 + 음주량)은 넣지 않았습니다.** v2 흐름에서는 Q7_1·Q7_2를 건너뛰어서 생기지 않습니다.
