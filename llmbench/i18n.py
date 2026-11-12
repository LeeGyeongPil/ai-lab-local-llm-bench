"""Screen language (English / Korean) for the llmbench CLI.

All user-visible text lives in MESSAGES below. Call sites pass only a message code plus
parameters; the text is chosen when it is printed. Machine output (JSONL keys and values,
exit codes, option names) is never translated.

Language order: --lang en|ko > LLMBENCH_LANG > LC_ALL > LC_MESSAGES > LANG. A value that
starts with "ko" means Korean; anything else (unset, C, POSIX, fr_FR ...) means English.
"""
import os
import unicodedata

LANGS = ("en", "ko")
ENV_ORDER = ("LLMBENCH_LANG", "LC_ALL", "LC_MESSAGES", "LANG")

MESSAGES = {
    "en": {
        "app.description": "Local LLM (Ollama) speed anatomy tool",
        "cmd.run": "run the measurement matrix",
        "argp.usage": "usage:",
        "argp.options": "options",
        "argp.positional": "positional arguments",
        "argp.error": "error",
        "argp.help": "show this help message and exit",
        "argp.version": "show the program's version number and exit",
        "argp.lang": "screen language: en or ko (default: $LLMBENCH_LANG, then the locale, else en)",
        "argp.unrecognized": "unrecognized arguments: {args}",
        "argp.required": "the following arguments are required: {args}",
        "argp.invalid_int": "invalid int value: {value}",
        "argp.invalid_float": "invalid float value: {value}",
        "argp.invalid_choice": "invalid choice: {value} (choose from {choices})",
        "argp.expected_one": "expected one argument",
        "argp.argument": "argument {name}: {message}",
        "opt.mock": "measure with a fake Ollama (recorded profile) - practice mode. LLMBENCH_MOCK=1 does the same",
        "opt.mock_speed": "mock time multiplier (default: 10x faster)",
        "opt.host": "Ollama address (default: $OLLAMA_HOST or http://localhost:11434)",
        "opt.models": "comma-separated model tags",
        "opt.concurrency": "list of concurrent request counts",
        "opt.prompt_sizes": "list of input lengths ({sizes})",
        "opt.repeat": "repetitions per cell",
        "opt.num_ctx": "list of context lengths (default: just 4096)",
        "opt.num_predict": "generated-token limit",
        "opt.no_nonce": "turn off the prompt prefix (nonce) -> observe cache hits",
        "opt.out": "result folder (JSONL goes under results/)",
        "opt.run_id": "result file name (default: config hash -> the same command resumes)",
        "opt.fresh": "do not resume; measure under a new run-id (timestamp)",
        "opt.max_cells": "cell limit for this run (for trying out resume)",
        "mock.banner": "MOCK - practice (mock) mode replaying a recorded measurement profile. These are not real model speeds.",
        "run.plan": "{cells} cells to measure, about {requests} requests (+ warm-up), {tokens} tokens generated",
        "run.plan_one": "{cells} cell to measure, about {requests} request (+ warm-up), {tokens} tokens generated",
        "run.plan_one_cell": "{cells} cell to measure, about {requests} requests (+ warm-up), {tokens} tokens generated",
        "run.resume": "resuming: {path}",
        "run.interrupted": "\nInterrupted. Run the same command again to resume: {path}",
        "run.summary": "skipped {skipped} cells, measured {done} new cells{stopped}",
        "run.summary_one_skipped": "skipped 1 cell, measured {done} new cells{stopped}",
        "run.summary_one_done": "skipped {skipped} cells, measured 1 new cell{stopped}",
        "run.summary_one_both": "skipped 1 cell, measured 1 new cell{stopped}",
        "run.stopped": " (stopped at the limit)",
        "run.result": "result: {path}",
        "run.warmup": "[warmup] {model} num_ctx={num_ctx} (excluded from stats)",
        "run.progress": "[{index}/{total}] {model} ctx={ctx} conc={conc} size={size} rep={rep}  TTFT {lo:.0f}~{hi:.0f}ms  decode {tps:.1f} tok/s",
        "warn.other_models": "warning: other models are already in memory ({names}) - memory and speed may be affected.",
        "warn.no_tags": "warning: cannot read the model list (/api/tags); skipping the existence check",
        "tbl.conc": "conc",
        "tbl.size": "size",
        "tbl.decode": "decode",
        "tbl.agg": "agg tok/s",
        "tbl.mem": "mem MB",
        "err.prefix": "error: {message}",
        "err.ints": "--concurrency / --num-ctx must be comma-separated integers (e.g. 1,2,4)",
        "err.concurrency": "--concurrency must be a list of integers >= 1 (e.g. 1,2,4)",
        "err.num_ctx": "--num-ctx must be a list of integers >= 1 (e.g. 4096)",
        "err.prompt_sizes": "--prompt-sizes has unknown value(s) {bad}: allowed values are {sizes}",
        "err.empty": "(empty)",
        "err.repeat_min": "--repeat must be 1 or more",
        "err.num_predict_min": "--num-predict must be 1 or more",
        "err.mock_speed_min": "--mock-speed must be greater than 0",
        "err.unreachable": (
            "error: cannot connect to the Ollama server ({host}) ({reason}).\n"
            "  - start the server: `ollama serve`  (for another address use --host or OLLAMA_HOST)\n"
            "  - to try it without a server or models: python3 -m llmbench run --mock"
        ),
        "err.rejected": (
            "error: Ollama rejected the request: {reason}\n"
            "  if the model is missing, fetch it with `ollama pull <tag>`."
        ),
        "err.missing_models": "error: models not on the server: {models}",
        "err.pull": "  to fetch: ollama pull {model}",
        "err.have": "  models you have: {models}",
        "err.have_none": "(none)",
        "err.os": "error: cannot write {path} ({reason})",
        "err.tags_shape": "the /api/tags response has no models list",
        "err.unknown_size": "unknown input size: {size} (choose from {sizes})",
    },
    "ko": {
        "app.description": "로컬 LLM(Ollama) 속도 해부 도구",
        "cmd.run": "측정 매트릭스 실행",
        "argp.usage": "사용법:",
        "argp.options": "옵션",
        "argp.positional": "위치 인자",
        "argp.error": "오류",
        "argp.help": "이 도움말을 보이고 종료합니다",
        "argp.version": "프로그램 버전을 보이고 종료합니다",
        "argp.lang": "화면 언어: en 또는 ko (기본: $LLMBENCH_LANG, 그다음 로케일, 없으면 en)",
        "argp.unrecognized": "알 수 없는 인자: {args}",
        "argp.required": "다음 인자가 필요합니다: {args}",
        "argp.invalid_int": "정수가 아닌 값: {value}",
        "argp.invalid_float": "숫자가 아닌 값: {value}",
        "argp.invalid_choice": "잘못된 선택: {value} (가능한 값: {choices})",
        "argp.expected_one": "값이 하나 필요합니다",
        "argp.argument": "인자 {name}: {message}",
        "opt.mock": "가짜 Ollama(녹화 프로필)로 측정 — 연습용. LLMBENCH_MOCK=1 도 같음",
        "opt.mock_speed": "mock 시간 배율(기본 10배 빠르게)",
        "opt.host": "Ollama 주소(기본: $OLLAMA_HOST 또는 http://localhost:11434)",
        "opt.models": "쉼표로 구분한 모델 태그",
        "opt.concurrency": "동시 요청 수 목록",
        "opt.prompt_sizes": "입력 길이 목록({sizes})",
        "opt.repeat": "칸마다 반복 횟수",
        "opt.num_ctx": "컨텍스트 길이 목록(기본 4096 하나로 고정)",
        "opt.num_predict": "생성 토큰 상한",
        "opt.no_nonce": "프롬프트 접두어(nonce)를 끈다 -> 캐시 적중 관찰",
        "opt.out": "결과 폴더(results/ 아래에 JSONL)",
        "opt.run_id": "결과 파일 이름(기본: 설정 해시 -> 같은 명령이면 이어하기)",
        "opt.fresh": "이어하지 않고 새 run-id(시각)로 측정",
        "opt.max_cells": "이번 실행에서 잴 칸 상한(이어하기 시험용)",
        "mock.banner": "MOCK — 녹화된 측정 프로필을 재생하는 연습용(mock) 모드입니다. 실제 모델 속도가 아닙니다.",
        "run.plan": "측정 칸 {cells}개, 요청 약 {requests}개 (+워밍업), 생성 {tokens}토큰",
        "run.plan_one": "측정 칸 {cells}개, 요청 약 {requests}개 (+워밍업), 생성 {tokens}토큰",
        "run.plan_one_cell": "측정 칸 {cells}개, 요청 약 {requests}개 (+워밍업), 생성 {tokens}토큰",
        "run.resume": "이어하기: {path}",
        "run.interrupted": "\n중단했습니다. 같은 명령을 다시 실행하면 이어서 측정합니다: {path}",
        "run.summary": "건너뜀 {skipped}칸, 새로 측정 {done}칸{stopped}",
        "run.summary_one_skipped": "건너뜀 1칸, 새로 측정 {done}칸{stopped}",
        "run.summary_one_done": "건너뜀 {skipped}칸, 새로 측정 1칸{stopped}",
        "run.summary_one_both": "건너뜀 1칸, 새로 측정 1칸{stopped}",
        "run.stopped": " (상한에서 멈춤)",
        "run.result": "결과: {path}",
        "run.warmup": "[warmup] {model} num_ctx={num_ctx} (집계 제외)",
        "run.progress": "[{index}/{total}] {model} ctx={ctx} 동시={conc} 입력={size} 반복={rep}  TTFT {lo:.0f}~{hi:.0f}ms  디코드 {tps:.1f} tok/s",
        "warn.other_models": "경고: 다른 모델이 이미 메모리에 있습니다({names}) — 메모리·속도에 영향을 줄 수 있습니다.",
        "warn.no_tags": "경고: 모델 목록(/api/tags)을 확인할 수 없어 존재 확인을 건너뜁니다",
        "tbl.conc": "동시",
        "tbl.size": "입력",
        "tbl.decode": "디코드",
        "tbl.agg": "합계tok/s",
        "tbl.mem": "메모리MB",
        "err.prefix": "오류: {message}",
        "err.ints": "--concurrency / --num-ctx 는 쉼표로 구분한 정수여야 합니다 (예: 1,2,4)",
        "err.concurrency": "--concurrency 는 1 이상의 정수 목록이어야 합니다 (예: 1,2,4)",
        "err.num_ctx": "--num-ctx 는 1 이상의 정수 목록이어야 합니다 (예: 4096)",
        "err.prompt_sizes": "--prompt-sizes 에 알 수 없는 값 {bad}: 가능한 값은 {sizes}",
        "err.empty": "(빈 값)",
        "err.repeat_min": "--repeat 는 1 이상이어야 합니다",
        "err.num_predict_min": "--num-predict 는 1 이상이어야 합니다",
        "err.mock_speed_min": "--mock-speed 는 0 보다 커야 합니다",
        "err.unreachable": (
            "오류: Ollama 서버({host})에 연결할 수 없습니다 ({reason}).\n"
            "  - 서버를 켜세요: `ollama serve`  (다른 주소면 --host 또는 OLLAMA_HOST)\n"
            "  - 서버·모델 없이 먼저 해 보려면: python3 -m llmbench run --mock"
        ),
        "err.rejected": (
            "오류: Ollama 가 요청을 거절했습니다: {reason}\n"
            "  모델이 없다면 `ollama pull <태그>` 로 받으세요."
        ),
        "err.missing_models": "오류: 서버에 없는 모델 태그: {models}",
        "err.pull": "  받으려면: ollama pull {model}",
        "err.have": "  받아 둔 모델: {models}",
        "err.have_none": "(없음)",
        "err.os": "오류: {path} 에 쓸 수 없습니다 ({reason})",
        "err.tags_shape": "/api/tags 응답에 models 목록이 없습니다",
        "err.unknown_size": "알 수 없는 입력 크기: {size} (선택: {sizes})",
    },
}

_current = None  # set by main(); None -> resolve from the environment on every call


def lang_from_value(value):
    """'ko', 'ko_KR.UTF-8' -> 'ko'; an empty value -> None; anything else -> 'en'."""
    if not value:
        return None
    return "ko" if value.strip().lower().startswith("ko") else "en"


def resolve_lang(cli_value=None, environ=None) -> str:
    """Apply the priority order and return 'en' or 'ko'."""
    environ = os.environ if environ is None else environ
    if cli_value in LANGS:
        return cli_value
    for name in ENV_ORDER:
        found = lang_from_value(environ.get(name))
        if found:
            return found
    return "en"


def set_lang(lang) -> None:
    global _current
    _current = lang if lang in LANGS else None


def current_lang() -> str:
    return _current or resolve_lang()


def t(code: str, **params) -> str:
    """Look up a message in the current language and fill in its parameters."""
    return MESSAGES[current_lang()][code].format(**params)


class CodedError(ValueError):
    """An error that carries a message code; its text is translated when it is shown."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params

    def __str__(self) -> str:
        return t(self.code, **self.params)


def display_width(s: str) -> int:
    """Terminal cell width (wide East Asian characters count as 2)."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, width: int, right: bool = True) -> str:
    """Pad to a display width so Korean and ASCII headers line up."""
    gap = max(0, width - display_width(s))
    return " " * gap + s if right else s + " " * gap
