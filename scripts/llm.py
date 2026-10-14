"""vLLM 배치 호출 래퍼 (Qwen3-30B-A3B-Instruct-2507, openit-llm 환경).

- 한 프로세스에서 모델을 한 번만 올리고, 요청 묶음을 llm.chat으로 한꺼번에 보낸다.
- 출력은 JSON 스키마 구조화 출력(StructuredOutputsParams)으로 강제한다. 파싱 실패는 None으로 돌려준다.
- 모든 요청·응답 원문을 calls 로그(jsonl)에 남긴다. 생성 파라미터·시드·모델명을 레코드에 기록할 수 있게 돌려준다.
- sm120(Blackwell)에서는 moe_backend='triton'이 필요하다.
"""
import json
import time
from pathlib import Path

MODEL_PATH = "/home/openit/LLM/Qwen3-30B-A3B-Instruct-2507"
MODEL_NAME = "Qwen3-30B-A3B-Instruct-2507"


class LLM:
    def __init__(self, log_path, seed=20261011, max_model_len=8192, gpu_util=0.90):
        from vllm import LLM as VLLM
        from vllm.sampling_params import SamplingParams, StructuredOutputsParams
        self._SP, self._SO = SamplingParams, StructuredOutputsParams
        t0 = time.time()
        self.llm = VLLM(model=MODEL_PATH, moe_backend="triton", max_model_len=max_model_len,
                        gpu_memory_utilization=gpu_util, seed=seed)
        self.load_seconds = round(time.time() - t0, 1)
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.gpu_seconds = 0.0
        self.out_tokens = 0

    def chat_json(self, kind, requests, schema, temperature, max_tokens, top_p=0.95, bad_words=None):
        """requests: [(call_id, messages, seed)] -> {call_id: (parsed 또는 None, params)}.

        bad_words: {call_id: [금지 단어]} 요청별 디코딩 금지어 (예: 정확한 값 발화에서 '정도'·'쯤').
        """
        if not requests:
            return {}
        bad_words = bad_words or {}
        params = [self._SP(temperature=temperature, top_p=top_p, max_tokens=max_tokens, seed=seed,
                           structured_outputs=self._SO(json=schema), bad_words=bad_words.get(cid) or None)
                  for cid, _, seed in requests]
        t0 = time.time()
        outs = self.llm.chat([m for _, m, _ in requests], params, use_tqdm=False)
        self.gpu_seconds += time.time() - t0
        result = {}
        with open(self.log_path, "a", encoding="utf-8") as log:
            for (cid, messages, seed), o in zip(requests, outs):
                text = o.outputs[0].text
                finish = o.outputs[0].finish_reason
                self.out_tokens += len(o.outputs[0].token_ids)
                try:
                    parsed = json.loads(text) if finish == "stop" else None
                except json.JSONDecodeError:
                    parsed = None
                gen = {"model": MODEL_NAME, "kind": kind, "temperature": temperature, "top_p": top_p,
                       "max_tokens": max_tokens, "seed": seed, "bad_words": bad_words.get(cid) or []}
                log.write(json.dumps({"call_id": cid, "gen": gen, "messages": messages, "output": text,
                                      "finish_reason": finish}, ensure_ascii=False) + "\n")
                result[cid] = (parsed, gen)
        return result
