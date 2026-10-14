"""증강 규모 확장(5,000~10,000 시나리오) 작업의 공용 경로·정규화기 호출 함수.

역할
- 원천 데이터·정규화기 위치를 한곳에 모은다. 원천 파일은 읽기만 하고 고치지 않는다.
- 정규화기는 신민지 담당 openit-normalizer(routing_policy v1.0)를 sys.path로 불러와 그대로 실행한다.
  정규화 규칙·필드 매핑·저장 동작은 이 작업에서 바꾸지 않는다(AGENTS.md).
- ruleset_version은 정규화기 소스 파일 해시로 만든다. 정규화기가 바뀌면 값이 달라져서
  어떤 규칙으로 계산한 레코드인지 구분할 수 있다.
"""
import copy
import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WS = ROOT.parent
NORMALIZER_ROOT = Path("/home/openit/minji/openit-normalizer")
ALIGN = WS / "old version" / "normalizer_alignment_20261005"   # 2026-10-13 old version 폴더로 옮김 (v2 생성에서는 쓰지 않음)

# 시드 원천 (읽기 전용)
MASTER_ALIGNED = ALIGN / "output" / "master_aligned.jsonl"          # 219건 (Toy 100건 포함)
QWEN_DUAL = ALIGN / "bulk5000_dual" / "data" / "master_new.jsonl"   # Qwen3-14B 증강 437건
CODEX_REVIEW = ALIGN / "codex_review_100_20261006" / "review_results.jsonl"  # 437건 중 100건 표본 검수

DEFAULT_TODAY = "2026-10-05"   # 기존 219건의 상담일. 시드 재계산은 같은 날짜로 해야 결과가 같다.

sys.path.insert(0, str(NORMALIZER_ROOT))
from normalizer import Catalog, normalize  # noqa: E402
from normalizer.normalizer_adapter import run_turn  # noqa: E402

CATALOG = Catalog()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ruleset_version():
    """정규화기 소스(normalizer/*.py)와 문진 DB를 묶은 해시. 레코드마다 기록한다."""
    h = hashlib.sha256()
    files = sorted((NORMALIZER_ROOT / "normalizer").glob("*.py"))
    files.append(NORMALIZER_ROOT / "dataset" / "db" / "questionnaire_reference.sqlite3")
    for p in files:
        h.update(p.name.encode())
        h.update(sha256_file(p).encode())
    return "openit-routing-v1.0@" + h.hexdigest()[:12]


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def prepare_labels(labels):
    """기존 A 레이블의 {lower, upper} 범위 객체를 정규화기 입력 문자열 "lo~hi"로 바꾼 복사본.

    원시 레이블은 건드리지 않는다. 이전 어댑터(adapter.prepare_input)와 같은 변환이다.
    """
    copied = copy.deepcopy(labels)
    for f in copied.get("facts", []):
        v = f.get("value")
        if isinstance(v, dict) and set(v) == {"lower", "upper"}:
            f["value"] = f"{v['lower']}~{v['upper']}"
    return copied


def previous_from_state(state_before, today):
    """기존 레코드의 state_before.confirmed(원시 사실 묶음) -> v1.0 정규화기의 previous 형식.

    출력: {(field_id, repeat_key): 정규화된 확정값}
    확정 사실만 따로 정규화해 CONFIRMED 행만 남긴다. 이전 턴 정보가 없으면 빈 dict.
    """
    facts = list((state_before or {}).get("confirmed", {}).values())
    if not facts:
        return {}
    labels = {"facts": facts, "intents": [], "relations": [], "unmapped_facts": []}
    result = normalize(prepare_labels(labels), CATALOG, None, today=today)
    return {(r.field_id, r.repeat_key): r.value
            for r in result.records if r.resolution_status == "CONFIRMED"}


def last_user_utterance(context):
    return [c for c in context if c["role"] == "user"][-1]["content"]


def run_v10(labels, state_before, context, today=DEFAULT_TODAY):
    """기존 형식 레코드 하나를 v1.0 어댑터로 실행해 6장 형식 JSON을 돌려준다."""
    day = datetime.date.fromisoformat(today)
    return run_turn(prepare_labels(labels), CATALOG, previous_from_state(state_before, day),
                    utterance=last_user_utterance(context), today=day)
