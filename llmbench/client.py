"""Ollama /api/chat 스트리밍 호출 — 실제 모드와 mock 모드가 똑같이 쓰는 클라이언트.

잰 것:
- ttft_ms : 요청을 보낸 뒤 '내용이 있는 첫 청크'가 도착할 때까지(클라이언트 벽시계)
- 서버 구간(ns -> ms) : load / prompt_eval / eval / total (done 청크의 값)
- queue_ms : total - load - prompt_eval - eval  (대기열 추정, 0 미만은 0)
"""
import json
import time
import urllib.error
import urllib.request


class OllamaUnreachable(Exception):
    """서버에 연결할 수 없을 때."""


class OllamaError(Exception):
    """서버가 오류 응답을 줬을 때(모델 없음 등)."""


def normalize_host(host: str) -> str:
    """'127.0.0.1:11434' 같은 값도 'http://127.0.0.1:11434' 로 맞춘다."""
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host


class OllamaClient:
    def __init__(self, host: str, time_scale: float = 1.0, timeout: float = 900.0):
        self.host = normalize_host(host)
        # mock 은 시간을 time_scale 배 빠르게 돌리므로, 벽시계 값에 곱해서 녹화 시간 척도로 되돌린다
        self.time_scale = time_scale
        self.timeout = timeout  # 공유 서버는 느릴 수 있어 넉넉히(느림은 오류가 아님)

    def _open(self, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.host + path, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise OllamaError(f"HTTP {e.code}: {detail}") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            raise OllamaUnreachable(str(e)) from None

    def _get_json(self, path: str) -> dict:
        with self._open(path) as r:
            return json.loads(r.read())

    def version(self) -> str:
        return self._get_json("/api/version").get("version", "unknown")

    def ps(self) -> list:
        """지금 메모리에 올라 있는 모델 목록(/api/ps)."""
        return self._get_json("/api/ps").get("models", [])

    def ps_info(self, model: str) -> dict:
        """모델 하나의 메모리 추정치(size, 바이트로 해석)·양자화·컨텍스트."""
        for m in self.ps():
            if m.get("name") == model or m.get("model") == model:
                return {
                    "ps_size": m.get("size"),
                    "quantization_level": m.get("details", {}).get("quantization_level"),
                    "context_length": m.get("context_length"),
                }
        return {"ps_size": None, "quantization_level": None, "context_length": None}

    def chat(self, model: str, prompt: str, num_ctx: int, num_predict: int, seed: int = 1) -> dict:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "think": False,
            "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": 0, "seed": seed},
        }
        t0 = time.perf_counter()
        ttft = None
        last = {}
        with self._open("/api/chat", body) as resp:
            for line in resp:  # 줄마다 JSON 청크 하나
                if not line.strip():
                    continue
                d = json.loads(line)
                if "error" in d:
                    raise OllamaError(d["error"])
                # 첫 '내용 있는' 청크 도착 = TTFT
                if ttft is None and d.get("message", {}).get("content"):
                    ttft = time.perf_counter() - t0
                if d.get("done"):
                    last = d
        wall = time.perf_counter() - t0
        return self._row(last, ttft if ttft is not None else wall, wall)

    def _row(self, d: dict, ttft: float, wall: float) -> dict:
        ms = lambda k: d.get(k, 0) / 1e6  # noqa: E731  ns -> ms
        load, pe, ev, total = ms("load_duration"), ms("prompt_eval_duration"), ms("eval_duration"), ms("total_duration")
        n = d.get("eval_count", 0)
        pn = d.get("prompt_eval_count", 0)
        s = self.time_scale
        # 클라이언트가 직접 잰 디코드 속도: 첫 토큰 이후 구간으로 계산(서버 보고값과 비교용)
        decode_wall = (wall - ttft) * s
        return {
            "ttft_ms": round(ttft * s * 1000, 1),
            "wall_ms": round(wall * s * 1000, 1),
            "load_ms": round(load, 1),
            "prompt_eval_ms": round(pe, 1),
            "eval_ms": round(ev, 1),
            "total_ms": round(total, 1),
            "queue_ms": round(max(0.0, total - load - pe - ev), 1),
            "prompt_eval_count": pn,
            "prompt_eval_cached_count": d.get("prompt_eval_cached_count", 0),
            "eval_count": n,
            # 공식: eval_count / eval_duration * 1e9
            "decode_tps": round(n / (ev / 1000), 2) if ev else 0.0,
            "prefill_tps": round(pn / (pe / 1000), 1) if pe else 0.0,
            "client_decode_tps": round((n - 1) / decode_wall, 2) if n > 1 and decode_wall > 0 else 0.0,
        }
