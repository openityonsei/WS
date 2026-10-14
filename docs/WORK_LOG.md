# 작업 기록 (데이터셋 v2)

## 2026-10-13

### 결정 (사용자)
1. 서비스에는 정규화기가 없다. LoRA-A가 추출 + 정규화 + 절차 + 다음 문항까지 정한다. LoRA-B는 말만 만든다.
2. 재질문일 때 B 입력에 코드만 넣지 않고 무엇을 물을지(ask)·받은 값(known)·이전 값(previous)을 사람 말로 넣는다.
3. 다음 문항(next_item)은 LoRA-A가 정한다.
4. 시작(START)을 넣는다. 종료(END)는 Q10 다음에만 쓴다.
5. 모든 것을 새로 만든다. 이전 데이터·시드는 가져오지 않는다. 폴더는 `/home/openit/WS/dataset`.
6. 목표: LoRA-A·LoRA-B 각 약 5,000건.
7. 서비스 목표 환경: RTX 4090 1장, Qwen3-8B + LoRA 2개(참고).

### 만든 것
- `scripts/labels.py`(v2 계약), `prompt_examples.py`(발화 145, 응답 135, 나쁜 예 29), `prompts.py`(v2 B 프롬프트·판정, 학습 시스템 프롬프트),
  `checks.py`(v2 B 가드), `pipeline.py`(START 포함), `build_final.py`, `export_docs.py`, `selftest.py`.
- `sampler.py`: 정정·충돌 흐름을 다음 문항으로 넘어간 뒤로 바꿈, 충돌 r1 제외, 범위 밖 소재 확장, note.
- 배분표 새로 계산(시드 없음, Q10 가중치 3.0).
- 이전 프로젝트에서 복사했던 question_bank·seed_registry·배분표는 지우고 새로 만들었다.

### 시험
- selftest: v2 변환 규칙 위반 0, 좋은 응답 예시 모두 가드 통과, 나쁜 응답 예 17/18 걸림.
- 이전 데이터 5,000건의 정규화 결과로 변환기만 시험(오류 0). 새 데이터에는 넣지 않았다.

### 파일럿 1 (시나리오 80, START 12)
- 통과 72건, 변형 통과율 22.5%.
- 문제 1: 응답 판정기가 next.text 원문과 글자가 다르면 떨어뜨림. 판정 기준을 규칙("뜻은 그대로, 말투는 친근하게")에 맞게 고침.
- 문제 2: 예시 베끼기 검사가 짧은 흔한 맞장구까지 걸음. 첫 문장 15자 이상, 80% 이상만 걸도록 고침.
- 문제 3: 발화 판정 출력 길이 부족(파싱 실패 14). 300 -> 700 토큰.
- 문제 4: START 인사가 거의 같음. 구성 힌트 8종과 인사 부분 중복 검사(질문 부분은 늘 같아서 제외)를 넣음.
- 숫자 말투("두 년", "다섯 날") 탈락은 실제 오류라 유지하고 프롬프트 규칙을 구체화함.

### 파일럿 2 (시나리오 40, START 18 추가)
- 통과 61건, 변형 통과율 38.1%.
- 표본 확인에서 추가로 고침: 확인(CONFIRM) 응답이 확인 질문 뒤에 원래 질문을 또 붙임 -> 질문 두 개 금지 가드, '삼 날' 같은 숫자 말투 가드.

### 본 생성 S3 (5,000 + START 150) 시작

### SQL 문서 (docs/SQL.md)
- 정규화기 참조 DB를 읽기 전용(mode=ro)으로 열어 스키마·트리거·문항·칸·선택지·규칙을 정리. 저장 SQL은 정규화기 store.save_result 문장을 옮김.
- 문서의 저장 예시 SQL은 DB 임시 복사본에서 실행해 확인함(CONFIRMED 1줄, PARTIAL 1줄 저장, 세션 revision 1).
- DB 규칙과 데이터셋 규칙이 다른 곳: Q8_2·Q9_2 건너뛰기(exercise_zero_duration PENDING), Q10 다음 END(next_unresolved·review_same_revision). 확인 필요.

### SQL 문서와 데이터셋 일치 확인 (scripts/verify_sql.py)
- 레코드마다 DB 임시 복사본에 두 번 저장: (1) SQL.md 6.1·6.2 규칙대로 LoRA-A 정답 values, (2) 정규화기 normalize + store.save_result. current_answers 비교.
- 10:40 기준 생성분 750건(파일럿 + S3 일부): 750건 일치, 키·반복 키·선택지 오류 0, SQL 오류 0.
- 검사 민감도: 규칙 하나(MISSING -> AMBIGUOUS)를 일부러 틀리게 바꾸면 8건 불일치로 잡힘.
- 아직 표본이 적은 상태: MISSING 8, UNCLEAR 1. 생성이 끝나면 5,000건 전체로 다시 확인한다.

### 본 생성 S3 결과 (2026-10-13 12:54 종료, 약 2시간 40분)
- 대화 턴 5,776건(파일럿 133 포함), START 135건. 변형 통과율 24.9%. 288칸 중 59칸이 목표 미달(합계 811건).
- 동작별: NEXT 3,714, CORRECT 818, HOLD 335, REDIRECT 270, SKIP 251, CONFIRM 209, REASK 179.
- 미달이 큰 곳: 부분 응답(P03) 438(Q1 질환 칸, Q4_1·Q5_1), 충돌(P06) 203, 범위·단위(P02)·경계(P10) 139.
- 원인 확인: Q1 부분 응답은 발화가 짧아 중복(385)과 B 판정기의 잘못된 탈락(264, "지금 약도 드세요?"를 'ask와 다름'으로 판정).
  최대 음주량 충돌(r3)은 샘플러에 있었지만 발화 중복·정보 덧붙임으로 모두 탈락해 0건.

### 정규화기 사례 보충 설계 (사용자 요청: "정규화에서 추가 안한것들 다 추가해서 더 돌려")
- S3 데이터를 정규화기에 다시 돌려 사유 코드·정리 규칙 사용 여부를 셌다. 한 번도 안 나온 것:
  OTHER_BEVERAGE, MISSING_NUMBER, INVALID_OPTION, BEVERAGE_MISSING(술 종류만 빠짐), CONFLICT_MAX_BELOW_USUAL, CONFLICT_DOES_NOT_DRINK,
  규칙 4.3 ABV_CELL, 6.2 BEVERAGE_INHERIT, 8.5 FEW_SMOKES·QUIT·PRE_DISEASE·MED_IMPLIES_DIAGNOSIS·NO_EXERCISE, R1(안 마심 + 횟수), R4, R5, R6,
  매일·거의 매일, NOT_TARGET_FAMILY(부모·형제가 아닌 가족).
- 넣지 않은 것: TYPE_MISMATCH·UNKNOWN_FIELD·INVALID_REPEAT_KEY·UNASKED. 추출 결과 형식이 틀렸을 때의 내부 방어 코드라
  환자 발화로 만들 상황이 없다(술 칸의 반복 키는 Q7_1·Q7_2가 같아서 INVALID_REPEAT_KEY도 말로 생기지 않음).
- 새 pattern P11_norm_case(하위 유형 19개, sampler.NORM_CASE_ITEMS). 하위 유형마다 정규화기를 실제로 돌려 의도한 사유 코드가 나와야 쓴다.
  단어로 판정하는 규칙은 근거 문장 예를 넣어 정답을 계산하고, 생성 뒤 실제 발화 근거로 다시 돌린 결과가 같아야 통과한다.
- 목표: taxonomy.NORM_CASE_QUOTA 38칸 합계 589건. 보충 단계 T1 = S3 부족 칸 다시 채우기 + P11 + START 150까지.

### labels.py 변경 (v2 계약, 정규화기 코드는 그대로)
- ask 문장: OTHER_BEVERAGE("소주·맥주·막걸리·와인·양주 중 어떤 술과 비슷한지"), BEVERAGE_MISSING("어떤 술이었는지"),
  INVALID_OPTION(선택지를 사람 말로. 전에는 'answer를 다시'처럼 칸 코드가 새어 나왔음).
- known: 한 턴에 여러 문항 값이 정해지면 다른 문항 값 앞에 문항 이름을 붙인다(예: 운동을 전혀 안 함 -> 세 문항 0일).
- 다음 문항: 한 턴에 뒤 문항의 칸까지 모두 저장되면 그 문항도 건너뛴다(운동 전혀 안 함 -> END).
- 같은 턴의 술 충돌(안 마심 + 음주량): current에서 '안 마심'을 뺀다(previous로 말함).
- 음주량 보류(HOLD)의 사유 BEVERAGE_MISSING -> UNCERTAIN. 정규화기가 '기억 안 나요'에도 이 이름을 덮어써서 REASK의 BEVERAGE_MISSING과 겹쳤다.
  기존 레코드는 build_final에서 사유 이름만 바꾼다(validation.relabel 표시, 값·동작·응답 그대로).
- 회귀: 기존 5,776건의 A 정답·B 입력을 새 labels.py로 다시 만들어 비교 -> 바뀐 것은 위 HOLD 사유 62건과, 이전 수정이 반영 안 된 known 1건뿐.

### 프롬프트 (PROMPT_VERSION dataset-v2-prompts-2026-10-13b)
- P11 하위 유형별 발화 성격(UTT_NATURE), 발화 예시 14개.
- B 판정: ask 대상을 앞 말에 기대어 줄여 묻는 것("중풍 진단을 받으셨군요. 지금 약도 드세요?")은 통과로 본다.

### 보충 생성 T1 시작 (16:06)
- selftest: 규칙 위반 0, 나쁜 응답 예 17/18. P11 38칸 모두 생성·DB 저장 가능(feasible).

### 보충 T1 1차 결과 (16:06~16:59)
- 통과 785건(변형 통과율 9.0%). 누적 대화 턴 6,561건, START 137건(인사 중복으로 거의 늘지 않음).
- 동작별 누적: NEXT 3,972, CORRECT 818, REASK 536, HOLD 338, REDIRECT 328, CONFIRM 317, SKIP 252.
- P11 통과 438건. 0건인 하위 유형: 숫자 없는 "네"(MISSING_NUMBER), 선택지 밖 답(INVALID_OPTION), 안 마심 + 음주량 충돌, 안 마심 + 횟수,
  0일 + 다른 활동 시간, 전단계. 운동 전혀 안 함 2건.
- 원인: 발화는 맞는데 검증용 역추출(정답을 안 보는 추출)이 원시 값을 다르게 적음. 예: '운동은 전혀 안 해요' -> MISSING,
  '매일' -> 1번 + unit 'day', '네 병' -> 술 이름, '예전엔 보유자였는데 지금은 아니래요' -> 'yes', 다른 문항 칸에 MISSING 추가.

### 역추출 규칙 보강 (PROMPT_VERSION dataset-v2-prompts-2026-10-13c, 검증 전용)
- 숫자 칸 '네, 해요' -> true / 운동 안 함 -> 0 / 선택지로 못 정하는 답 -> 말한 표현 그대로 / 몇 대만 -> null AMBIGUOUS /
  전단계 -> 진단 true + 근거에 '전단계' / 가족력 근거에 호칭 포함 / 다른 문항 칸은 말한 것만 / 안 마신다 -> does_not_drink true,
  '매일'은 그대로 / 술 이름 없이 양만 -> beverage MISSING. 학습 정답(LoRA-A)은 그대로 정규화기 결과다.
- 17:08 T1 이어서 실행(부족 칸만, 칸마다 canonical 12개 이상 시도 후 통과율 3% 미만이면 멈춤).

### 보충 T1 2차 결과 (17:08~17:31)
- 통과 216건(변형 통과율 4.6%). 누적 대화 턴 6,777건, START 140건. P11 누적 545건.
- 역추출 규칙 보강 뒤 새로 들어온 것: 0일 + 다른 활동 시간 43, 전단계 20, 매일 30(누적), 약만 먹음 65(누적), 운동 전혀 안 함 7.
- 여전히 적음: 숫자 없는 "네" 6, 선택지 밖 답 2, 안 마심 + 음주량 충돌 1, 안 마심 + 횟수 1. 역추출 모델이 이 원시 값 표기를 잘 따르지 못함.

### 최종 빌드 (build_final --upto T1, 17:35)
- 학습용 대화 턴 5,080(train 3,982 / val 549 / test 549), START 110(train 87 / val 11 / test 12). 할당량 초과 예비분 1,448, MinHash 근접 중복 116 제외.
- 동작 비율: NEXT 60.5%, REASK 11.9%, CORRECT 8.8%, CONFIRM 6.6%, REDIRECT 4.6%, HOLD 4.5%, SKIP 3.3%. 하한(3%) 위반 없음, 문항 최소량 미달 없음.
- next 유형: NEXT 3,728, SAME 1,167, END 185. P11은 할당량 안에서 463건.
- 음주 HOLD 사유 이름 바꿈 62건(BEVERAGE_MISSING -> UNCERTAIN).

### 표본 점검에서 찾은 문제 (미해결)
- '끊었어요'·'안 피워요 + 과거 흡연'처럼 Q4_1·Q5_1의 상태(status)가 이미 정해진 채 다음 문항이 Q4_1·Q5_1이면,
  next.text(문항 은행 질문)가 상태까지 다시 물어서 B 응답이 "지금 피우세요?"를 다시 묻는다. 57건 중 20건 이상.
  계약 수정 필요: 일부 칸이 이미 정해진 다음 문항은 남은 칸만 묻는 next.text(또는 ask)를 줘야 한다.

### SQL 문서·검증
- 전체 6,777건 검증: 6,619건 일치, 158건 '키 문제'. 158건은 모두 술 종류 없이 끝난 음주량 칸(Q7_1.amount 등, 보류·재질문)이다.
  정규화기 저장 코드는 이 행을 NO_REPEAT_KEY로 건너뛴다. SQL.md 6.1에 이 규칙이 빠져 있어서 추가하고 검증기도 같은 규칙으로 고쳐 다시 돌림.
- 규칙 추가 뒤 다시 검증: 6,777건 모두 일치(키·선택지·SQL 오류 0).

## 2026-10-14

### LoRA-A state를 서비스 규칙으로 넓힘 (scripts/prev_state.py, build_final 0단계)
- 문제: 생성 단계 state는 '정답에 필요한 값'만 넣어서 72%가 빈 state였다. 서비스는 이번 턴이 정정인지 모르므로 매 턴 같은 규칙으로
  state를 만든다. 학습에서는 'state에 값이 있으면 정정·확인, 모름·거절·딴소리는 빈 state일 때만'이라는 지름길이 생겼다
  (빈 state: NEXT 68·REASK 17·HOLD 6·REDIRECT 6·SKIP 4%, 같은 문항 값 있음: CORRECT 41·NEXT 35·CONFIRM 25%).
  SQL.md 7.1에 '학습 데이터와 같은 범위'라고 적었지만 확인하지 않았던 것이 원인이다. 검증은 정답·DB 저장만 보고 '서비스가 이 입력을 만들 수 있는가'는 보지 않았다.
- 규칙(매 턴 같음): 지금 문항(재질문 칸 포함) + 직전에 물은 문항(대화 순서, 건너뛰기 반영) + 참조 원천 문항(REF_SOURCE).
- 방법: 기존 state 값을 고정하고 대화 흐름을 앞에서부터 만들어(빈 문항은 normal_facts, 6%는 보류로 값 없음) 지금 문항에 닿게 한다.
  넓힌 state로 정규화기를 다시 돌려 정규화 핵심·A 정답·B 입력이 원래 state 결과와 모두 같을 때만 쓴다(30회 시도).
- 재현 확인: 원래 state로 다시 돌리면 저장된 정답·B 입력·state가 5,080건 모두 같다.
- 결과: 7건 제외(모두 Q7_2, Q7_1 값이 있으면 술 종류를 물려받아 정답이 달라지는 경우). 최종 턴 5,077(train 3,982 / val 549 / test 546).
  state 크기 0: 288건(첫 문항·직전 보류), 1~2: 3,781건, 3 이상: 1,008건. 다른 문항 값만 있는 state의 동작: NEXT 69·REASK 15·REDIRECT 6·HOLD 5·SKIP 4·CONFIRM 2%.
- verify_sql.py에 --final 추가: 최종 5,077건 모두 일치. selftest 그대로 통과(라벨 문제 0, 나쁜 B 17/18).
- A 학습 system 문구, SQL.md 7.1, IO_SPEC, README의 state 설명을 새 규칙으로 고침. 고치기 전 final은 scratchpad에 백업.

### 사람 검수 페이지 + 직접 수정 반영 (scripts/human_edits.py, build_final 0-2단계)
- 검수 페이지(claude.ai artifact)에서 판정(OK/문제)·태그·메모와 직접 수정(발화, A 정답 JSON, B 응답, 빼기)을 레코드별로 저장한다.
- 반영: Claude가 페이지 저장소를 내려받아 `python -B scripts/human_edits.py collect <폴더>` -> review/human_edits.json -> build_final.
  A 정답을 고치면 B 입력을 labels.b_input으로 다시 만들고, B 응답을 안 고쳤으면 b_needs_check로 보고한다. 형식이 틀린 A 정답은 반영하지 않고 보고한다.
  human_review: human_edited / human_ok / human_flagged (사람 판정이 있을 때만). 판정을 지어내지 않는다.

### 새로 찾은 문제 (미해결)
- 이전 턴 환자 말과 state가 반대인 레코드(예: "뇌졸중은 없어요"인데 diagnosed=true). 이전 턴 문장이 이전 정답과 맞는지 검사하지 않았다.
  간단한 표현 검사로 15건(Q1 P04). 다른 문항·표현은 아직 안 봤다.
- current_question: 학습은 대부분 질문 문장만, 서비스는 B의 응답 전체(앞 답 되짚기 + 질문)가 들어간다.
- (추가) 입력도 직접 수정: 검수 페이지에서 LoRA-A 입력(JSON)·LoRA-B 입력(JSON)도 고칠 수 있다. human_edits.py가 a_input·b_input을 반영하고
  형식 오류는 rejected_input, A 정답과 B 입력의 행동이 다르면 ab_action_mismatch로 보고한다. B 입력을 사람이 고쳤으면 다시 계산하지 않는다.
- 페이지는 저장하는 즉시 카드에 고친 값을 보여 주고 '수정됨'·'원본 보기'·'빌드 대기/반영됨'을 표시한다(반영됨 = 수정 시각이 데이터 빌드 시각보다 앞이고 데이터에 human_edited 표시).
- 끝에서 끝 시험: 저장소에 시험용 B 응답 수정 1건 -> 내려받기 -> collect -> build_final -> train.jsonl·lora_b_train.jsonl에 반영 확인.
  시험 문서와 human_edits.json은 지우고 다시 빌드함(최종 5,077턴, 사람 수정 0건).
