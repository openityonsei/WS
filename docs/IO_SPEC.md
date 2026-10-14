# LoRA-A / LoRA-B 입력·출력 형식 v2 (확정, 2026-10-13)

> 상태: **확정 (2026-10-13 사용자 승인).** 다음 문항(next_item)은 LoRA-A가 정한다. 시작(START)을 넣는다. 종료(END)는 Q10 다음에만 쓴다.
> 기준 구현: `scripts/labels.py`. 표 전체: `docs/LABEL_TABLES.md`. 실제 데이터 스키마: `README.md` 4장.
>
> 초안 이후 바뀐 점
> - LoRA-B 입력에 `topic`(지금 다루는 문항)과 `current`(CONFIRM의 이번 값), `hold`(HOLD·SKIP에서 비워 두는 부분)를 더했다.
> - 정정·충돌 흐름: 상담원이 앞 답을 되짚고 다음 문항으로 넘어간 뒤 환자가 앞 답을 고치거나 다르게 말한다. A 입력 question_id는 그때 묻던 문항이다.
> - 7장 1번(범위 답)은 정규화기 규약(가운데 값, approximate)을 따른다.

## 0. 바뀐 구조

```
지금:  환자 말 → LoRA-A(추출만) → 정규화기(값 정리 + plan) → LoRA-B(응답)
v2:    [시작] 서비스 → LoRA-B(START: 인사 + Q1.D01 질문)
       환자 말 → LoRA-A(추출 + 정규화 + 절차 + 다음 문항) → 서비스(표 찾기) → LoRA-B(응답)
```

- 서비스에는 정규화기가 없다. 학습 데이터의 정답을 만들 때만 정규화기(routing_policy v1.0)를 기준으로 쓴다.
- 서비스 코드가 하는 일은 **표 찾기**뿐이다(문항 번호 → 질문 문장, 칸 → 사람 말 설명). 판단은 하지 않는다.
- 문항 순서: Q1.D01(처음) … Q10(마지막), 31개.

## 1. 절차(action) 종류

LoRA-A가 고른다. `START`만 서비스가 시작할 때 쓴다.

| action | 언제 | reason (사유 코드) | 지금 plan |
|---|---|---|---|
| `START` | 문진 시작(환자 말 없음, A를 부르지 않음) | – | (새로 생김) |
| `NEXT` | 답을 다 받음 → 저장하고 다음 문항 | – | NEXT |
| `CORRECT` | 앞서 한 답을 고침 → 새 값으로 바꾸고 다음 문항 | – | ACK_CORRECTION |
| `REASK` | 같은 문항을 다시 물음 | MISSING(빠짐), OUT_OF_RANGE(범위 밖), UNKNOWN_UNIT(단위 불분명), VAGUE_QUANTITY(양이 막연), RANGE_SPANS_OPTIONS(범위가 선택지 둘에 걸침), COUNT_EXCEEDS_DAYS(횟수가 날수보다 큼) | ASK_MISSING, ASK_CLARIFICATION |
| `CONFIRM` | 이전 답과 달라 어느 쪽이 맞는지 확인 | CONFLICT_WITH_PREVIOUS, CONFLICT_DOES_NOT_DRINK, CONFLICT_MAX_BELOW_USUAL | ASK_CONFLICT |
| `HOLD` | 모름 → 그 칸은 비워 두고 다음 문항 | UNCERTAIN, BEVERAGE_MISSING | ASK_OR_HOLD |
| `SKIP` | 거절·나중에 → 넘어가고 다음 문항 | REQUEST_SKIP, REFUSED | HOLD_OR_SKIP |
| `REDIRECT` | 문진과 상관없는 말 → 짧게 반응하고 현재 질문으로 돌아옴 | ASK_PURPOSE(왜 묻냐), OFF_TOPIC(잡담), OUT_OF_SCHEMA(문진표에 없는 건강 정보) | REDIRECT |

**종료(END)는 action이 아니라 `next_item`의 값이다.** Q10에서도 정정·모름·거절이 나오기 때문이다(현재 데이터: Q10 NEXT 70, 정정 12, 모름 5, 거절 5건).
예) Q10에서 모름 → `action: HOLD`, `next_item: "END"` → "모르시면 비워 둘게요. 이걸로 문진은 다 끝났어요."

## 2. LoRA-A

### 2.1 입력

```json
{
  "question_id": "Q7_1",
  "current_question": "술을 마시는 날은 평균적으로 어느 정도 드시나요?",
  "user_utterance": "위스키를 잔 단위로 마십니다",
  "state": {}
}
```

| 키 | 뜻 |
|---|---|
| `question_id` | 지금 묻는 문항 |
| `current_question` | 상담원이 방금 한 말(LoRA-B의 앞 응답 그대로. 인사·되짚기가 붙어 있을 수 있음) |
| `user_utterance` | 환자 말 1턴 |
| `state` | 매 턴 같은 규칙: 지금 문항(재질문 중인 칸 포함)·직전에 물은 문항·참조 원천 문항(REF_SOURCE)의 저장 값. 첫 문항이거나 직전 문항을 보류했으면 비거나 작음 (2026-10-14 변경, SQL.md 7.1) |

`state` 예: `{"Q9_2.duration_minutes": {"value": 15, "status": "ANSWERED"}}`

### 2.2 출력

```json
{
  "values": [
    {"key": "Q7_1[whisky].beverage", "value": "위스키", "precision": "exact", "status": "ANSWERED", "save": true},
    {"key": "Q7_1[whisky].unit", "value": "잔", "precision": "exact", "status": "ANSWERED", "save": true},
    {"key": "Q7_1[whisky].amount", "value": null, "precision": "unspecified", "status": "MISSING", "save": false}
  ],
  "action": "REASK",
  "reason": "MISSING",
  "targets": ["Q7_1[whisky].amount"],
  "next_item": "Q7_1"
}
```

| 키 | 뜻 |
|---|---|
| `values` | 이번 말에서 정한 칸 값들. `key`는 `문항.칸` (술 종류처럼 반복되는 칸은 `문항[종류].칸`) |
| `value` | DB에 들어갈 값(정규화된 값: 숫자, true/false, 선택지 코드) |
| `precision` | exact / approximate / unspecified |
| `status` | ANSWERED / CORRECTION / MISSING / UNCLEAR / CONFLICT / UNKNOWN / REJECTED |
| `save` | 이 값을 DB에 저장하는지 |
| `action`, `reason` | 1장의 표 |
| `targets` | REASK·CONFIRM·HOLD·SKIP에서 해당 칸들 |
| `next_item` | **다음에 물을 문항.** REASK·CONFIRM·REDIRECT는 현재 문항, 나머지는 순서상 다음 문항(건너뛰기 반영), Q10 다음은 `"END"` |

건너뛰기 규칙(A가 배움): Q4·Q5·Q6 "아니요" → Q4_1·Q5_1·Q6_1 건너뜀 / Q7 "안 마심" → Q7_1·Q7_2 건너뜀 / Q8_1·Q9_1 "0일" → Q8_2·Q9_2 건너뜀.

- 근거 위치(evidence)는 빼서 출력을 줄인다(속도).
- REDIRECT의 OUT_OF_SCHEMA는 `"note": "알레르기 이야기"`처럼 짧은 요약을 넣어 B가 반응할 수 있게 한다.

## 3. 서비스가 붙이는 것 (표 찾기)

A 출력을 받아 서비스가 B 입력을 만든다. 모델 호출 없음.

| B 입력 키 | 만드는 법 |
|---|---|
| `next.text` | `next_item`의 질문 문장(문항 은행) |
| `known` | `save`된 값을 사람 말로: 칸 설명표 + 값 (예: "술 종류: 위스키, 단위: 잔") |
| `ask` | REASK·CONFIRM일 때 `targets` 칸을 사람 말로: 문장 틀 표 + 이미 받은 값 (예: "술 마시는 날 평소에 위스키를 몇 잔 드시는지") |
| `previous` | CONFIRM일 때 `state`의 이전 값을 사람 말로 (예: "하루 15분") |

`ask` 문장 틀 표(31문항 × 칸)는 이 초안이 확인되면 따로 만들어 확인받는다.

## 4. LoRA-B

### 4.1 입력

```json
{
  "action": "REASK",
  "reason": "MISSING",
  "user_utterance": "위스키를 잔 단위로 마십니다",
  "known": "술 종류: 위스키, 단위: 잔",
  "ask": "술 마시는 날 평소에 위스키를 몇 잔 드시는지",
  "next": {"type": "SAME", "question_id": "Q7_1", "text": "술을 마시는 날은 보통 어느 정도 마십니까?"}
}
```

| 키 | 뜻 |
|---|---|
| `action`, `reason` | A가 정한 절차 |
| `user_utterance` | 환자 말(반응을 자연스럽게 하려고 넣음. 값은 `known`에 있는 것만 말한다) |
| `known` | 되짚을 수 있는 값 |
| `ask` | REASK·CONFIRM에서만. 다시 물을 것 |
| `previous` | CONFIRM에서만. 이전 값 |
| `next.type` | `NEXT`(다음 문항으로) / `SAME`(같은 문항 다시) / `END`(마무리) |
| `next.text` | 물을 질문 문장(`END`면 없음) |

### 4.2 출력

응답 문장 그대로(텍스트). JSON으로 감싸지 않아서 바로 스트리밍할 수 있다.

```
위스키 드시는군요. 보통 한 번 드실 때 몇 잔 정도 드세요?
```

## 5. 절차별 예

### 5.1 START (시작)
- A: 부르지 않음
- B 입력: `{"action": "START", "next": {"type": "NEXT", "question_id": "Q1.D01", "text": "뇌졸중(중풍)으로 진단을 받았거나, 현재 약물 치료 중이십니까?"}}`
- B 출력: `안녕하세요. 지금부터 건강검진 문진표를 같이 작성해 볼게요. 먼저, 뇌졸중(중풍) 진단을 받으신 적이 있거나 지금 약을 드시고 계세요?`

### 5.2 NEXT (정상)
- A 입력: `{"question_id": "Q1.D01", "current_question": "(5.1의 B 출력)", "user_utterance": "네 오년 전에 진단받고 지금 약 먹어요", "state": {}}`
- A 출력: `{"values": [{"key": "Q1.D01.diagnosed", "value": true, ...}, {"key": "Q1.D01.on_medication", "value": true, ...}], "action": "NEXT", "next_item": "Q1.D02"}`
- B 입력: `{"action": "NEXT", "known": "진단: 받음, 지금 약: 먹음", "next": {"type": "NEXT", "question_id": "Q1.D02", "text": "심근경색이나 협심증으로 진단을 받으셨거나 약을 드시나요?"}, ...}`
- B 출력: `진단받으시고 지금 약도 드시는군요. 그럼 심근경색이나 협심증 진단을 받으신 적 있으세요?`

### 5.3 NEXT + 건너뛰기
- A 입력: Q4 "담배는 평생 안 피웠어요"
- A 출력: `{"values": [{"key": "Q4.answer", "value": false, ...}], "action": "NEXT", "next_item": "Q5"}` (Q4_1 건너뜀)
- B 출력: `담배는 안 피우셨군요. 그럼 아이코스나 글로 같은 가열식 전자담배를 써 보신 적은 있으세요?`

### 5.4 REASK (빠짐) — 4장의 위스키 예

### 5.5 CONFIRM (충돌)
- A 입력: `{"question_id": "Q9_2", "user_utterance": "운동하는 날 하루에 열여섯 분 해요", "state": {"Q9_2.duration_minutes": {"value": 15, "status": "ANSWERED"}}, ...}`
- A 출력: `{"values": [{"key": "Q9_2.duration_minutes", "value": 16, "status": "CONFLICT", "save": false}], "action": "CONFIRM", "reason": "CONFLICT_WITH_PREVIOUS", "targets": ["Q9_2.duration_minutes"], "next_item": "Q9_2"}`
- B 입력: `{"action": "CONFIRM", "known": "", "previous": "하루 15분", "ask": "하루 16분이 맞는지", "next": {"type": "SAME", ...}, ...}`
- B 출력: `아까는 하루 15분이라고 하셨는데요, 16분이 맞을까요?`

### 5.6 CORRECT (정정)
- A 입력: Q2.D02 `state: {"Q2.D02.family_history": {"value": false}}`, 환자 "아 잘못 말했어요, 심근경색 앓은 분 있어요"
- A 출력: `{"values": [{"key": "Q2.D02.family_history", "value": true, "status": "CORRECTION", "save": true}], "action": "CORRECT", "next_item": "Q2.D03"}`
- B 출력: `심근경색이나 협심증 앓은 분이 계신 걸로 고쳐 둘게요. 그럼 부모님이나 형제자매 중 고혈압을 앓은 분은 있으세요?`

### 5.7 HOLD (모름)
- A 출력: `{"values": [...UNKNOWN...], "action": "HOLD", "reason": "UNCERTAIN", "targets": ["Q1.D11.diagnosed", "Q1.D11.on_medication"], "next_item": "Q2.D01"}`
- B 출력: `기억 안 나시면 괜찮아요, 그 부분은 비워 둘게요. 부모님이나 형제자매 중 뇌졸중을 앓은 분이 있으세요?`

### 5.8 REDIRECT (범위 밖)
- A 입력: Q8_2, 환자 "근데 이거 왜 물어보는 거예요?"
- A 출력: `{"values": [], "action": "REDIRECT", "reason": "ASK_PURPOSE", "next_item": "Q8_2"}`
- B 출력: `건강검진 문진표에 들어가는 내용이라서요. 숨이 많이 찰 정도로 운동하는 날은 하루에 얼마나 하세요?`

### 5.9 END (Q10 다음)
- A 입력: Q10, 환자 "일주일에 세 번 아령 해요"
- A 출력: `{"values": [{"key": "Q10.days", "value": 3, ...}], "action": "NEXT", "next_item": "END"}`
- B 입력: `{"action": "NEXT", "known": "근력 운동: 일주일에 3일", "next": {"type": "END"}, ...}`
- B 출력: `일주일에 3일 하시는군요. 이걸로 문진은 다 끝났어요. 답해 주셔서 감사합니다.`

## 6. 데이터에 미치는 영향

| 대상 | 할 일 | GPU |
|---|---|---|
| A 정답 5,000건 | 이미 저장된 정규화 결과 + 순서 규칙으로 새 형식 정답을 코드로 다시 만듦. 환자 발화·A 입력은 그대로 | 불필요 |
| B | 입력 형식이 바뀌므로 응답을 다시 생성. 파일럿 먼저 | 필요 |
| START·END | B 데이터 각 150~200건 새로 생성(3% 하한 대상 아님) | 필요 |
| A 입력 `current_question` | Q1.D01 일부에 START 응답(인사 + 질문)을 넣음 | 불필요 |

## 7. 아직 정할 것

1. **범위 답 저장값:** 지금 정규화기 규약(3~5일 → 4, approximate)을 A가 그대로 배울지, 범위 그대로 둘지. 정하기 전까지는 지금 규약을 따른다.
2. `ask` 문장 틀 표와 칸 설명표(이 초안 확인 후).
3. 서비스 담당자와 B 입력 형식 맞추기.
