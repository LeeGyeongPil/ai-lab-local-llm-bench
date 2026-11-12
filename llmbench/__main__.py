"""llmbench CLI.   python3 -m llmbench run --mock

M1: `run` 하위 명령(측정 코어). report / record-profile 은 이후 마일스톤에서 추가한다.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

from . import __version__
from .client import OllamaClient, OllamaError, OllamaUnreachable, normalize_host
from .fake_ollama import FakeOllama, load_profiles
from .i18n import LANGS, CodedError, current_lang, pad, resolve_lang, set_lang, t
from .matrix import Config, read_jsonl, run_matrix, _append
from .prompts import SIZES
from .stats import summarize

DEFAULT_REAL_MODELS = "qwen3:0.6b-q4_K_M,qwen3:0.6b-q8_0,qwen3:0.6b-fp16"


def _ints(s: str) -> list:
    return [int(x) for x in s.split(",") if x.strip()]


def _strs(s: str) -> list:
    return [x.strip() for x in s.split(",") if x.strip()]


class _Formatter(argparse.HelpFormatter):
    """Help formatter whose 'usage:' prefix follows the screen language."""

    def add_usage(self, usage, actions, groups, prefix=None):
        if prefix is None:
            prefix = t("argp.usage") + " "
        return super().add_usage(usage, actions, groups, prefix)


# English argparse error text -> (message code, parameter name); used only to localize errors.
_ERROR_PATTERNS = (
    (re.compile(r"^unrecognized arguments: (.*)$", re.S), "argp.unrecognized", "args"),
    (re.compile(r"^the following arguments are required: (.*)$", re.S), "argp.required", "args"),
    (re.compile(r"^invalid int value: (.*)$", re.S), "argp.invalid_int", "value"),
    (re.compile(r"^invalid float value: (.*)$", re.S), "argp.invalid_float", "value"),
)


def _localize_error(message: str) -> str:
    """Translate argparse's fixed error sentences (the Korean screen only)."""
    if current_lang() == "en":
        return message
    m = re.match(r"^argument (\S+): (.*)$", message, re.S)
    if m:
        return t("argp.argument", name=m.group(1), message=_localize_error(m.group(2)))
    m = re.match(r"^invalid choice: (.*) \(choose from (.*)\)$", message, re.S)
    if m:
        return t("argp.invalid_choice", value=m.group(1), choices=m.group(2))
    if message == "expected one argument":
        return t("argp.expected_one")
    for pattern, code, name in _ERROR_PATTERNS:
        m = pattern.match(message)
        if m:
            return t(code, **{name: m.group(1)})
    return message


class _Parser(argparse.ArgumentParser):
    """ArgumentParser with its fixed sentences (usage, headings, errors, -h) in the screen language."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", _Formatter)
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = t("argp.positional")
        self._optionals.title = t("argp.options")
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help=t("argp.help"))

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {t('argp.error')}: {_localize_error(message)}\n")


def _prescan_lang(argv):
    """Read --lang from argv before real parsing so --help and parse errors use that language."""
    for i, a in enumerate(argv):
        if a == "--":
            break
        value = argv[i + 1] if a == "--lang" and i + 1 < len(argv) else a[7:] if a.startswith("--lang=") else None
        if value in LANGS:
            return value
    return None


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="llmbench", description=t("app.description"))
    p.add_argument("--version", action="version", version=f"llmbench {__version__}", help=t("argp.version"))
    p.add_argument("--lang", choices=LANGS, default=None, help=t("argp.lang"))
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help=t("cmd.run"))
    r.add_argument("--lang", choices=LANGS, default=argparse.SUPPRESS, help=t("argp.lang"))  # also allowed after `run`
    r.add_argument("--mock", action="store_true", help=t("opt.mock"))
    r.add_argument("--mock-speed", type=float, default=10.0, help=t("opt.mock_speed"))
    r.add_argument("--host", default=None, help=t("opt.host"))
    r.add_argument("--models", default=None, help=t("opt.models"))
    r.add_argument("--concurrency", default="1,2,4", help=t("opt.concurrency"))
    r.add_argument("--prompt-sizes", default="short,medium,long", help=t("opt.prompt_sizes", sizes=",".join(SIZES)))
    r.add_argument("--repeat", type=int, default=2, help=t("opt.repeat"))
    r.add_argument("--num-ctx", default="4096", help=t("opt.num_ctx"))
    r.add_argument("--num-predict", type=int, default=64, help=t("opt.num_predict"))
    r.add_argument("--no-nonce", action="store_true", help=t("opt.no_nonce"))
    r.add_argument("--out", default=".", help=t("opt.out"))
    r.add_argument("--run-id", default=None, help=t("opt.run_id"))
    r.add_argument("--fresh", action="store_true", help=t("opt.fresh"))
    r.add_argument("--max-cells", type=int, default=None, help=t("opt.max_cells"))
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
    """Bad input ends with a friendly CodedError before any server starts or measuring begins."""
    try:
        conc, ctxs = _ints(args.concurrency), _ints(args.num_ctx)
    except ValueError:
        raise CodedError("err.ints")
    if not conc or any(n < 1 for n in conc):
        raise CodedError("err.concurrency")
    if not ctxs or any(n < 1 for n in ctxs):
        raise CodedError("err.num_ctx")
    sizes = _strs(args.prompt_sizes)
    bad = [s for s in sizes if s not in SIZES]
    if not sizes or bad:
        raise CodedError("err.prompt_sizes", bad=bad or [t("err.empty")], sizes=", ".join(SIZES))
    if args.repeat < 1:
        raise CodedError("err.repeat_min")
    if args.num_predict < 1:
        raise CodedError("err.num_predict_min")
    if args.mock_speed <= 0:
        raise CodedError("err.mock_speed_min")


def cmd_run(args) -> int:
    try:
        validate_args(args)
    except ValueError as e:
        print(t("err.prefix", message=e), file=sys.stderr)
        return 2
    mock = args.mock or os.environ.get("LLMBENCH_MOCK") == "1"
    fake = None
    try:
        if mock:
            print(t("mock.banner"))
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
        print(t("err.unreachable", host=client_host(args), reason=e), file=sys.stderr)
        return 2
    except OllamaError as e:
        print(t("err.rejected", reason=e), file=sys.stderr)
        return 2
    except ValueError as e:
        print(t("err.prefix", message=e), file=sys.stderr)
        return 2
    except OSError as e:  # e.g. --out is a file, or no permission: one line, no traceback
        print(t("err.os", path=e.filename or args.out, reason=e.strerror or e), file=sys.stderr)
        return 2
    finally:
        if fake:
            fake.stop()


def client_host(args) -> str:
    return normalize_host(args.host or os.environ.get("OLLAMA_HOST", "http://localhost:11434"))


def _norm_tag(tag: str) -> str:
    """'qwen3' 와 'qwen3:latest' 를 같게 본다(':' 가 없으면 ':latest')."""
    return tag if ":" in tag else tag + ":latest"


def _check_models(client: OllamaClient, models: list) -> int | None:
    """측정 전에 모델이 서버에 있는지 확인. 없으면 안내 후 2, 통과·건너뜀이면 None."""
    try:
        have = client.tags()
    except OllamaError:  # /api/tags 미지원 등 -> 경고만 하고 기존 흐름대로
        have = None
    except ValueError:  # 응답 형식이 다름
        have = None
    if have is None:
        print(t("warn.no_tags"))
        return None
    have_norm = {_norm_tag(h) for h in have}
    missing = [m for m in models if _norm_tag(m) not in have_norm]
    if not missing:
        return None
    lines = [t("err.missing_models", models=", ".join(missing))]
    lines += [t("err.pull", model=m) for m in missing]
    lines.append(t("err.have", models=", ".join(have) if have else t("err.have_none")))
    print("\n".join(lines), file=sys.stderr)
    return 2


def _run(args, cfg: Config, client: OllamaClient, mock: bool) -> int:
    version = client.version()  # 여기서 연결 실패가 먼저 드러난다
    ps_before = client.ps()
    names = [m.get("name") for m in ps_before]
    code = _check_models(client, cfg.models)
    if code is not None:
        return code
    mode = "MOCK" if mock else "REAL"
    print(f"[{mode}] ollama {version} @ {client.host}")
    others = [n for n in names if n not in cfg.models]
    if others:
        print(t("warn.other_models", names=", ".join(others)))
    cells, requests = cfg.total_cells(), cfg.total_requests()
    plan = "run.plan_one" if cells == 1 and requests == 1 else "run.plan_one_cell" if cells == 1 else "run.plan"
    print(t(plan, cells=cells, requests=requests, tokens=cfg.num_predict))

    out = os.path.join(args.out, "results")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, _run_id(args, cfg, mock) + ".jsonl")
    _append(path, {"type": "meta", "mode": mode, "ollama_version": version, "time_scale": client.time_scale,
                   "host": client.host, "ps_before": ps_before, "config": cfg.__dict__,
                   "started": time.strftime("%Y-%m-%dT%H:%M:%S")})
    done = len(read_jsonl(path))
    if done > 1:
        print(t("run.resume", path=path))
    try:
        res = run_matrix(client, cfg, path, max_cells=args.max_cells)
    except KeyboardInterrupt:
        print(t("run.interrupted", path=path))
        return 130
    one_s, one_d = res["skipped"] == 1, res["done"] == 1
    summary = "run.summary" + ("_one_both" if one_s and one_d else "_one_skipped" if one_s else "_one_done" if one_d else "")
    print(t(summary, skipped=res["skipped"], done=res["done"], stopped=t("run.stopped") if res["stopped"] else ""))
    _print_table(summarize(read_jsonl(path)))
    print(t("run.result", path=path))
    return 0


def _print_table(rows) -> None:
    if not rows:
        return
    # pad by display width so Korean headers line up with the ASCII ones
    heads = [("model", 24, False), ("ctx", 6, True), (t("tbl.conc"), 5, True), (t("tbl.size"), 8, True),
             ("TTFT p50", 10, True), ("p95", 9, True), (t("tbl.decode"), 8, True), (t("tbl.agg"), 10, True),
             (t("tbl.mem"), 9, True)]
    print("\n" + "".join(pad(text, w, right) for text, w, right in heads))
    for r in rows:
        mb = f"{r['ps_size'] / 1e6:.0f}" if r["ps_size"] else "-"
        print(f"{r['model']:<24}{r['num_ctx']:>6}{r['concurrency']:>5}{r['size']:>8}"
              f"{r['ttft_p50']:>10.0f}{r['ttft_p95']:>9.0f}{r['decode_tps']:>8.1f}{r['agg_tps']:>10.1f}{mb:>9}")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    set_lang(resolve_lang(_prescan_lang(argv)))  # --lang > LLMBENCH_LANG > LC_ALL > LC_MESSAGES > LANG
    try:
        args = build_parser().parse_args(argv)
        return {"run": cmd_run}[args.cmd](args)
    finally:
        set_lang(None)  # do not leak the language into later calls (tests, embedding)


if __name__ == "__main__":
    sys.exit(main())
