# 사람 말 설명표·절차 규칙 (데이터셋 v2)

- 원본: `scripts/labels.py`. 이 문서는 `scripts/export_docs.py`가 만든다.
- 서비스에서 LoRA-B 입력을 만들 때 이 표를 그대로 써야 학습과 같은 입력이 된다.

## 1. 문항 순서와 건너뛰기

순서: Q1.D01 → Q1.D02 → Q1.D03 → Q1.D04 → Q1.D05 → Q1.D06 → Q1.D07 → Q1.D08 → Q1.D09 → Q1.D10 → Q1.D11 → Q2.D01 → Q2.D02 → Q2.D03 → Q2.D04 → Q2.D05 → Q3 → Q4 → Q4_1 → Q5 → Q5_1 → Q6 → Q6_1 → Q7 → Q7_1 → Q7_2 → Q8_1 → Q8_2 → Q9_1 → Q9_2 → Q10 → END

| 조건 (이번 턴에 저장되는 값) | 건너뛰는 문항 |
|---|---|
| Q4.answer = false | Q4_1 |
| Q5.answer = false | Q5_1 |
| Q6.answer = false | Q6_1 |
| Q7.does_not_drink = true | Q7_1, Q7_2 |
| Q8_1.days = 0 | Q8_2 |
| Q9_1.days = 0 | Q9_2 |

## 2. 정규화기 plan → v2 action

| 정규화기 plan | action | next_item | B next.type |
|---|---|---|---|
| NEXT | NEXT | 값·대상 문항의 다음 문항(건너뛰기 반영), Q10 다음은 END | NEXT (Q10 다음이면 END) |
| ACK_CORRECTION | CORRECT | 값·대상 문항의 다음 문항(건너뛰기 반영), Q10 다음은 END | NEXT (Q10 다음이면 END) |
| ASK_MISSING | REASK | 대상 칸의 문항 | SAME |
| ASK_CLARIFICATION | REASK | 대상 칸의 문항 | SAME |
| ASK_CONFLICT | CONFIRM | 대상 칸의 문항 | SAME |
| ASK_OR_HOLD | HOLD | 값·대상 문항의 다음 문항(건너뛰기 반영), Q10 다음은 END | NEXT (Q10 다음이면 END) |
| HOLD_OR_SKIP | SKIP | 값·대상 문항의 다음 문항(건너뛰기 반영), Q10 다음은 END | NEXT (Q10 다음이면 END) |
| REDIRECT | REDIRECT | 지금 묻던 문항(question_id) | SAME |
| (시작) | START (B만) | Q1.D01 | NEXT |

## 3. topic (지금 다루는 문항)

| 문항 | topic | 짧은 이름(hold) |
|---|---|---|
| Q1.D01 | 뇌졸중(중풍) 진단을 받았는지와 지금 약을 먹는지 | 뇌졸중(중풍) |
| Q1.D02 | 심근경색이나 협심증 진단을 받았는지와 지금 약을 먹는지 | 심근경색이나 협심증 |
| Q1.D03 | 고혈압 진단을 받았는지와 지금 약을 먹는지 | 고혈압 |
| Q1.D04 | 당뇨병 진단을 받았는지와 지금 약을 먹는지 | 당뇨병 |
| Q1.D05 | 이상지질혈증 진단을 받았는지와 지금 약을 먹는지 | 이상지질혈증 |
| Q1.D06 | 폐결핵 진단을 받았는지와 지금 약을 먹는지 | 폐결핵 |
| Q1.D07 | 우울증 진단을 받았는지와 지금 약을 먹는지 | 우울증 |
| Q1.D08 | 조기정신증 진단을 받았는지와 지금 약을 먹는지 | 조기정신증 |
| Q1.D09 | C형간염 진단을 받았는지와 지금 약을 먹는지 | C형간염 |
| Q1.D10 | 만성폐쇄성폐질환 진단을 받았는지와 지금 약을 먹는지 | 만성폐쇄성폐질환 |
| Q1.D11 | 암이나 그 밖의 병 진단을 받았는지와 지금 약을 먹는지 | 암이나 그 밖의 병 |
| Q2.D01 | 부모·형제자매 중 뇌졸중(중풍)을 앓았거나 그 병으로 돌아가신 분이 있는지 | 가족 중 뇌졸중(중풍) |
| Q2.D02 | 부모·형제자매 중 심근경색이나 협심증을 앓았거나 그 병으로 돌아가신 분이 있는지 | 가족 중 심근경색이나 협심증 |
| Q2.D03 | 부모·형제자매 중 고혈압을 앓았거나 그 병으로 돌아가신 분이 있는지 | 가족 중 고혈압 |
| Q2.D04 | 부모·형제자매 중 당뇨병을 앓았거나 그 병으로 돌아가신 분이 있는지 | 가족 중 당뇨병 |
| Q2.D05 | 부모·형제자매 중 암이나 그 밖의 병을 앓았거나 그 병으로 돌아가신 분이 있는지 | 가족 중 암이나 그 밖의 병 |
| Q3 | B형간염 바이러스 보유자인지 | B형간염 보유 여부 |
| Q4 | 일반담배를 평생 5갑(100개비) 이상 피운 적이 있는지 | 흡연 경험 |
| Q4_1 | 일반담배를 지금 피우는지, 피운 기간, 하루 개비 수, 끊은 지 얼마나 됐는지 | 일반담배 |
| Q5 | 가열담배(아이코스·글로 등)를 써 본 적이 있는지 | 가열담배 경험 |
| Q5_1 | 가열담배를 지금 쓰는지, 쓴 기간, 하루 개비 수, 끊은 지 얼마나 됐는지 | 가열담배 |
| Q6 | 액상형 전자담배를 써 본 적이 있는지 | 액상형 전자담배 경험 |
| Q6_1 | 최근 한 달 동안 액상형 전자담배를 쓴 날 수 | 액상형 전자담배 쓴 날 수 |
| Q7 | 지난 1년 동안 술을 얼마나 자주 마시는지(일주일·한 달·1년에 몇 번) | 술 마시는 횟수 |
| Q7_1 | 술 마시는 날 평소에 마시는 양 | 평소 마시는 양 |
| Q7_2 | 지난 1년 중 가장 많이 마신 날 하루에 마신 양 | 가장 많이 마신 날의 양 |
| Q8_1 | 숨이 많이 찰 정도로 힘든 운동을 일주일에 며칠 하는지 | 힘든 운동 하는 날 수 |
| Q8_2 | 숨이 많이 찰 정도로 힘든 운동을 하는 날 하루에 얼마나 하는지 | 힘든 운동 하는 시간 |
| Q9_1 | 숨이 약간 찰 정도의 운동을 일주일에 며칠 하는지 | 숨이 약간 차는 운동 하는 날 수 |
| Q9_2 | 숨이 약간 찰 정도의 운동을 하는 날 하루에 얼마나 하는지 | 숨이 약간 차는 운동 시간 |
| Q10 | 최근 1주일 동안 근력 운동을 한 날 수 | 근력 운동 한 날 수 |

## 4. 값 → 사람 말 (known·previous·current)

| 칸 | 값 예 | 사람 말 |
|---|---|---|
| Q1.D03.diagnosed | `true` | 진단 받음 |
| Q1.D03.on_medication | `false` | 지금 약 안 먹음 |
| Q2.D03.family_history | `true` | 앓은 분 있음 |
| Q3.answer | `"unknown"` | 보유 여부 모름 |
| Q4.answer | `true` | 5갑 넘게 피운 적 있음 |
| Q5.answer | `false` | 써 본 적 없음 |
| Q4_1.status | `"former"` | 끊음 |
| Q4_1.total_years | `20` | 피운 기간 20년 |
| Q4_1.daily_count | `10` | 하루 10개비 |
| Q4_1.years_since_quit | `0.5` | 끊은 지 반년 |
| Q5_1.status | `"current"` | 지금 씀 |
| Q6_1.use_pattern | `"days_3_9"` | 최근 한 달 3~9일 씀 |
| Q7.does_not_drink | `true` | 지난 1년 술 안 마심 |
| Q8_1.days | `3` | 일주일에 3일 |
| Q10.days | `0` | 최근 일주일 0일 |
| Q8_2.duration_minutes | `90` | 하루 1시간 30분 |
| Q9_2.duration_minutes | `40` | 하루 40분 |
| Q7 횟수+기간 | | 일주일에 3번 |
| Q7 횟수만 | | 3번 (기준 기간은 아직 모름) |
| Q7_1 술 양 | | 소주 2병 |
| Q7_1 어림·cc | | 맥주 1565cc쯤 |
| Q7_1 양 없음 | | 양주(위스키 등), 단위 잔 (양은 아직 모름) |

어림(approximate) 값은 '쯤'을 붙인다. 정규화기는 범위(3~5)를 가운데 값(4, approximate)으로 저장하므로 known은 '4일쯤'이 되고, B는 환자가 말한 범위 표현으로 되짚는다(B 공통 규칙).

## 5. ask (다시 물을 것) 문장 틀

| 사유 | 대상 칸 | ask |
|---|---|---|
| MISSING | Q1.D04.on_medication | 지금 당뇨병 약을 먹는지 |
| MISSING | Q1.D04.diagnosed | 당뇨병 진단을 받은 적이 있는지 |
| MISSING | Q4_1.years_since_quit | 끊은 지 몇 년 됐는지 |
| MISSING | Q5_1.daily_count | 하루에 몇 개비 쓰는지(썼는지) |
| MISSING | Q7.unit | 3번이 일주일에·한 달에·1년에 중 어느 기준인지 |
| MISSING | Q7.frequency | 한 달에 몇 번 마시는지 |
| MISSING | Q7_1[spirits].amount | 술 마시는 날 평소에 양주(위스키 등)를 몇 잔 마시는지 |
| MISSING | Q7_2[soju].unit | 소주 3이 병·잔·캔 중 어느 단위인지 |
| OUT_OF_RANGE | Q8_1.days | 일주일은 7일이니 일주일 중 며칠인지 다시 |
| OUT_OF_RANGE | Q8_2.duration_minutes | 하루는 24시간이니 하루에 몇 시간·몇 분인지 다시 |
| OUT_OF_RANGE | Q6_1.use_pattern | 한 달은 길어야 31일이니 최근 한 달 중 며칠인지 다시 |
| COUNT_EXCEEDS_DAYS | Q7.frequency | 술을 마신 날을 기준으로 그 기간에 며칠(몇 번) 마시는지 |
| VAGUE_QUANTITY | Q10.days | 최근 일주일 중 며칠인지 숫자로 |
| VAGUE_QUANTITY | Q7.frequency | 일주일이나 한 달에 몇 번인지 숫자로 |
| RANGE_SPANS_OPTIONS | Q6_1.use_pattern | 최근 한 달 동안 며칠 썼는지 하나의 숫자로 |
| UNKNOWN_UNIT | Q7_1[beer].unit | 맥주를 병·잔·캔 같은 단위로 치면 얼마나인지 |
| CONFLICT_WITH_PREVIOUS | Q9_2.duration_minutes | 이번에 말한 값(current)이 맞는지, 아까 말한 값(previous)이 맞는지 |
| CONFLICT_MAX_BELOW_USUAL | Q7_2[soju].amount | 가장 많이 마신 날의 양이 맞는지(평소보다 적게 나옴) |
| CONFLICT_DOES_NOT_DRINK | Q7_1[soju].amount | 지난 1년 동안 술을 마신 적이 있는지 |

## 6. hold (보류·거절로 비워 두는 부분)

| 대상 칸 | hold |
|---|---|
| Q4_1.total_years | 일반담배 중 피운 기간 |
| Q1.D11.diagnosed, Q1.D11.on_medication | 암이나 그 밖의 병 |
| Q1.D05.on_medication | 이상지질혈증 중 약 복용 여부 |
| Q3.answer | B형간염 보유 여부 |
| Q7_2[soju].amount | 가장 많이 마신 날의 양 |
| (대상 없음, 지금 문항) | 힘든 운동 하는 시간 |
