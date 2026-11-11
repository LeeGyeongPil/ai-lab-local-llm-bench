"""mock 모드용 '가짜 Ollama' 서버 (연습용 목).

결과 파일을 그냥 읽어 주는 게 아니다. 진짜 Ollama처럼 HTTP로 /api/chat 을 스트리밍하고,
녹화 프로필(fixtures/profiles.json)의 숫자로 '시간만' 흉내 낸다.

  - 슬롯은 lock 1개 -> 동시 요청은 실제로 줄을 선다 (Ollama 기본 NUM_PARALLEL=1 과 같음)
  - 모델/num_ctx 가 바뀌면 load_ms 만큼 기다린다 (콜드 로드)
  - 프리필 시간 = (캐시에 없는 입력 토큰) / prefill_tps
  - 디코드 = 토큰마다 1/decode_tps 간격으로 청크 전송
  - 앞 프롬프트와 접두어가 같으면 그만큼 캐시 적중 (nonce 가 접두어를 깨뜨려 막는다)
  - /api/ps 메모리 = 가중치 + KV 바이트/토큰 x num_ctx

그래서 '계단 TTFT'와 '입력 길이 효과'는 녹화값을 베낀 것이 아니라 여기서 실제로 생겨난다.
speed 배 빠르게 잠을 자고, 서버가 보고하는 ns 구간은 녹화 시간 척도로 되돌려 보고한다.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .prompts import estimate_tokens

PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "profiles.json"
)


CACHE_BLOCK = 8  # 캐시는 8토큰 블록 단위로 적중 -> 접두어가 거의 같을 때만 적중(nonce 는 이를 깬다)


def load_profiles(path: str = PROFILE_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _common_prefix(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


class FakeOllama:
    def __init__(self, profiles: dict | None = None, speed: float = 10.0, host: str = "127.0.0.1", tags: bool = True):
        self.profiles = profiles or load_profiles()
        self.speed = speed
        self.tags = tags  # False 면 /api/tags 미지원 서버를 흉내 낸다(404)
        self.version = self.profiles["meta"]["ollama_version"]
        self.slot = threading.Lock()  # 슬롯 1개 -> 줄 서기
        self.loaded = None  # (model, num_ctx)
        self.last_prompt = ""  # 프롬프트 캐시(마지막 한 개)
        self._server = ThreadingHTTPServer((host, 0), self._make_handler())  # 포트 0 = 빈 포트 자동
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        h, p = self._server.server_address[:2]
        return f"http://{h}:{p}"

    def start(self) -> "FakeOllama":
        self._thread.start()
        return self

    def stop(self) -> None:  # 종료 경로: 서버 멈추고 소켓 닫고 스레드 합류
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ---- 시간 흉내 ----
    def _sleep_until(self, deadline: float) -> None:
        d = deadline - time.perf_counter()
        if d > 0:
            time.sleep(d)

    def _ps_entry(self) -> list:
        if not self.loaded:
            return []
        model, num_ctx = self.loaded
        p = self.profiles["models"][model]
        size = p["weights_bytes"] + p["kv_bytes_per_token"] * num_ctx
        return [{
            "name": model, "model": model, "size": size, "size_vram": size,
            "details": {"quantization_level": p["quantization_level"]},
            "context_length": num_ctx,
        }]

    def _make_handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # 테스트 출력 조용히
                pass

            def _json(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/version":
                    self._json(200, {"version": fake.version})
                elif self.path == "/api/ps":
                    self._json(200, {"models": fake._ps_entry()})
                elif self.path == "/api/tags" and fake.tags:
                    names = list(fake.profiles["models"])
                    self._json(200, {"models": [{"name": m, "model": m} for m in names]})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                if self.path != "/api/chat":
                    return self._json(404, {"error": "not found"})
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                model = body["model"]
                if model not in fake.profiles["models"]:
                    return self._json(404, {"error": f"model '{model}' not found"})
                try:
                    fake._chat(self, body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # 클라이언트가 끊음 -> 슬롯은 with 블록이 이미 풀었다

        return Handler

    def _chat(self, h, body: dict) -> None:
        arrive = time.perf_counter()
        model = body["model"]
        opts = body.get("options", {})
        num_ctx = opts.get("num_ctx", 4096)
        n_predict = opts.get("num_predict", 64)
        prompt = body["messages"][-1]["content"]
        p = self.profiles["models"][model]
        sp = self.speed

        h.send_response(200)
        h.send_header("Content-Type", "application/x-ndjson")
        h.end_headers()

        def send(obj):
            h.wfile.write((json.dumps(obj) + "\n").encode())
            h.wfile.flush()

        with self.slot:  # 여기서 줄을 선다. 대기 시간은 total_duration 에 그대로 들어간다
            now = time.perf_counter()
            # 1) 로드: 다른 모델이거나 num_ctx 가 바뀌면 다시 올린다
            load_ms = 0.0
            if self.loaded != (model, num_ctx):
                load_ms = p["load_ms"]
                self._sleep_until(now + load_ms / 1000 / sp)
                self.loaded = (model, num_ctx)
                self.last_prompt = ""  # 다시 올리면 캐시도 비워진다
            # 2) 프리필: 캐시에 없는 토큰만 처리
            n_tok = estimate_tokens(prompt)
            common = estimate_tokens(prompt[: _common_prefix(prompt, self.last_prompt)])
            cached = min(common // CACHE_BLOCK * CACHE_BLOCK, n_tok - 1)  # 블록 단위로만 재사용
            self.last_prompt = prompt
            pe_ms = max(1, n_tok - cached) / p["prefill_tps"] * 1000
            t = time.perf_counter()
            self._sleep_until(t + pe_ms / 1000 / sp)
            # 3) 디코드: 일정한 간격으로 토큰 청크 전송 (마감 시각 기준이라 오차가 쌓이지 않음)
            interval = 1 / p["decode_tps"] / sp
            start = time.perf_counter()
            for i in range(n_predict):
                self._sleep_until(start + (i + 1) * interval)
                send({"model": model, "message": {"role": "assistant", "content": f"w{i} "}, "done": False})
            eval_ms = n_predict / p["decode_tps"] * 1000
            total_ms = (time.perf_counter() - arrive) * sp * 1000  # 대기 포함, 녹화 시간 척도

        send({
            "model": model, "message": {"role": "assistant", "content": ""},
            "done": True, "done_reason": "length",
            "total_duration": int(total_ms * 1e6),
            "load_duration": int(load_ms * 1e6),
            "prompt_eval_count": n_tok,
            "prompt_eval_cached_count": cached,
            "prompt_eval_duration": int(pe_ms * 1e6),
            "eval_count": n_predict,
            "eval_duration": int(eval_ms * 1e6),
        })
