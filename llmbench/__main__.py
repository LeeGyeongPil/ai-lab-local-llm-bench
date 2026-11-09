"""llmbench CLI.   python3 -m llmbench run --mock

M1: `run` 하위 명령(측정 코어). report / record-profile 은 이후 마일스톤에서 추가한다.
"""
import argparse
import hashlib
import json
import os
import sys
import time

from . import __version__
from .client import OllamaClient, OllamaError, OllamaUnreachable, normalize_host
from .fake_ollama import FakeOllama, load_profiles
from .matrix import Config, read_jsonl, run_matrix, _append
from .prompts import SIZES
from .stats import summarize

MOCK_BANNER = "MOCK — 녹화된 측정 프로필을 재생하는 연습용(mock) 모드입니다. 실제 모델 속도가 아닙니다."
DEFAULT_REAL_MODELS = "qwen3:0.6b-q4_K_M,qwen3:0.6b-q8_0,qwen3:0.6b-fp16"


def _ints(s: str) -> list:
    return [int(x) for x in s.split(",") if x.strip()]


def _strs(s: str) -> list:
    return [x.strip() for x in s.split(",") if x.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmbench", description="로컬 LLM(Ollama) 속도 해부 도구")
    p.add_argument("--version", action="version", version=f"llmbench {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="측정 매트릭스 실행")
    r.add_argument("--mock", action="store_true", help="가짜 Ollama(녹화 프로필)로 측정 — 연습용. LLMBENCH_MOCK=1 도 같음")
    r.add_argument("--mock-speed", type=float, default=10.0, help="mock 시간 배율(기본 10배 빠르게)")
    r.add_argument("--host", default=None, help="Ollama 주소(기본: $OLLAMA_HOST 또는 http://localhost:11434)")
    r.add_argument("--models", default=None, help="쉼표로 구분한 모델 태그")
    r.add_argument("--concurrency", default="1,2,4", help="동시 요청 수 목록")
    r.add_argument("--prompt-sizes", default="short,medium,long", help=f"입력 길이 목록({','.join(SIZES)})")
    r.add_argument("--repeat", type=int, default=2, help="칸마다 반복 횟수")
    r.add_argument("--num-ctx", default="4096", help="컨텍스트 길이 목록(기본 4096 하나로 고정)")
    r.add_argument("--num-predict", type=int, default=64, help="생성 토큰 상한")
    r.add_argument("--no-nonce", action="store_true", help="프롬프트 접두어(nonce)를 끈다 -> 캐시 적중 관찰")
    r.add_argument("--out", default=".", help="결과 폴더(results/ 아래에 JSONL)")
    r.add_argument("--run-id", default=None, help="결과 파일 이름(기본: 설정 해시 -> 같은 명령이면 이어하기)")
    r.add_argument("--fresh", action="store_true", help="이어하지 않고 새 run-id(시각)로 측정")
    r.add_argument("--max-cells", type=int, default=None, help="이번 실행에서 잴 칸 상한(이어하기 시험용)")
    return p


def _run_id(args, cfg: Config, mock: bool) -> str:
    if args.run_id:
        return args.run_id
    if args.fresh:
        return time.strftime("run-%Y%m%d-%H%M%S")
    key = json.dumps([mock, cfg.models, cfg.num_ctxs, cfg.concurrencies, cfg.sizes,
                      cfg.repeat, cfg.num_predict, cfg.nonce, cfg.seed])
    return "run-" + hashlib.sha1(key.encode()).hexdigest()[:8]


def validate_args(args) -> None:
    """잘못된 입력은 서버를 띄우거나 측정하기 전에 친절한 ValueError 로 끝낸다."""
    try:
        conc, ctxs = _ints(args.concurrency), _ints(args.num_ctx)
    except ValueError:
        raise ValueError("--concurrency / --num-ctx 는 쉼표로 구분한 정수여야 합니다 (예: 1,2,4)")
    if not conc or any(n < 1 for n in conc):
        raise ValueError("--concurrency 는 1 이상의 정수 목록이어야 합니다 (예: 1,2,4)")
    if not ctxs or any(n < 1 for n in ctxs):
        raise ValueError("--num-ctx 는 1 이상의 정수 목록이어야 합니다 (예: 4096)")
    sizes = _strs(args.prompt_sizes)
    bad = [s for s in sizes if s not in SIZES]
    if not sizes or bad:
        raise ValueError(f"--prompt-sizes 에 알 수 없는 값 {bad or ['(빈 값)']}: 가능한 값은 {', '.join(SIZES)}")
    if args.repeat < 1:
        raise ValueError("--repeat 는 1 이상이어야 합니다")
    if args.num_predict < 1:
        raise ValueError("--num-predict 는 1 이상이어야 합니다")
    if args.mock_speed <= 0:
        raise ValueError("--mock-speed 는 0 보다 커야 합니다")


def cmd_run(args) -> int:
    try:
        validate_args(args)
    except ValueError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    mock = args.mock or os.environ.get("LLMBENCH_MOCK") == "1"
    fake = None
    try:
        if mock:
            print(MOCK_BANNER)
            profiles = load_profiles()
            fake = FakeOllama(profiles, speed=args.mock_speed).start()
            host, scale = fake.url, args.mock_speed
            models = _strs(args.models) if args.models else list(profiles["models"])
        else:
            host = normalize_host(args.host or os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
            scale = 1.0
            models = _strs(args.models or DEFAULT_REAL_MODELS)
        cfg = Config(models=models, num_ctxs=_ints(args.num_ctx), concurrencies=_ints(args.concurrency),
                     sizes=_strs(args.prompt_sizes), repeat=args.repeat, num_predict=args.num_predict,
                     nonce=not args.no_nonce)
        client = OllamaClient(host, time_scale=scale)
        return _run(args, cfg, client, mock)
    except OllamaUnreachable as e:
        print(f"오류: Ollama 서버({client_host(args)})에 연결할 수 없습니다 ({e}).\n"
              "  - 서버를 켜세요: `ollama serve`  (다른 주소면 --host 또는 OLLAMA_HOST)\n"
              "  - 서버·모델 없이 먼저 해 보려면: python3 -m llmbench run --mock", file=sys.stderr)
        return 2
    except OllamaError as e:
        print(f"오류: Ollama 가 요청을 거절했습니다: {e}\n  모델이 없다면 `ollama pull <태그>` 로 받으세요.", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    finally:
        if fake:
            fake.stop()


def client_host(args) -> str:
    return normalize_host(args.host or os.environ.get("OLLAMA_HOST", "http://localhost:11434"))


def _run(args, cfg: Config, client: OllamaClient, mock: bool) -> int:
    version = client.version()  # 여기서 연결 실패가 먼저 드러난다
    ps_before = client.ps()
    names = [m.get("name") for m in ps_before]
    mode = "MOCK" if mock else "REAL"
    print(f"[{mode}] ollama {version} @ {client.host}")
    others = [n for n in names if n not in cfg.models]
    if others:
        print(f"경고: 다른 모델이 이미 메모리에 있습니다({', '.join(others)}) — 메모리·속도에 영향을 줄 수 있습니다.")
    print(f"측정 칸 {cfg.total_cells()}개, 요청 약 {cfg.total_requests()}개 (+워밍업), 생성 {cfg.num_predict}토큰")

    out = os.path.join(args.out, "results")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, _run_id(args, cfg, mock) + ".jsonl")
    _append(path, {"type": "meta", "mode": mode, "ollama_version": version, "time_scale": client.time_scale,
                   "host": client.host, "ps_before": ps_before, "config": cfg.__dict__,
                   "started": time.strftime("%Y-%m-%dT%H:%M:%S")})
    done = len(read_jsonl(path))
    if done > 1:
        print(f"이어하기: {path}")
    try:
        res = run_matrix(client, cfg, path, max_cells=args.max_cells)
    except KeyboardInterrupt:
        print(f"\n중단했습니다. 같은 명령을 다시 실행하면 이어서 측정합니다: {path}")
        return 130
    print(f"건너뜀 {res['skipped']}칸, 새로 측정 {res['done']}칸" + (" (상한에서 멈춤)" if res["stopped"] else ""))
    _print_table(summarize(read_jsonl(path)))
    print(f"결과: {path}")
    return 0


def _print_table(rows) -> None:
    if not rows:
        return
    print(f"\n{'model':<24}{'ctx':>6}{'동시':>5}{'입력':>8}{'TTFT p50':>10}{'p95':>9}{'디코드':>8}{'합계tok/s':>10}{'메모리MB':>9}")
    for r in rows:
        mb = f"{r['ps_size'] / 1e6:.0f}" if r["ps_size"] else "-"
        print(f"{r['model']:<24}{r['num_ctx']:>6}{r['concurrency']:>5}{r['size']:>8}"
              f"{r['ttft_p50']:>10.0f}{r['ttft_p95']:>9.0f}{r['decode_tps']:>8.1f}{r['agg_tps']:>10.1f}{mb:>9}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
