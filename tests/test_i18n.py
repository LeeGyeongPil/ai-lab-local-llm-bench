"""Screen language (en/ko): message table, priority order, per-language regressions."""
import contextlib
import io
import json
import os
import re
import socket
import string
import tempfile

import pytest

from llmbench import i18n
from llmbench.__main__ import main
from llmbench.i18n import MESSAGES, resolve_lang, t

HANGUL = re.compile("[가-힣]")


def run_cli(argv, lang=None, monkeypatch=None):
    """Run main() and return (exit code, stdout, stderr); --help/usage exits are folded into the code."""
    out, err = io.StringIO(), io.StringIO()
    args = (["--lang", lang] if lang else []) + list(argv)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(args)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fields(text):
    return sorted(f for _, f, _, _ in string.Formatter().parse(text) if f)


# (a) message table ---------------------------------------------------------------------------

def test_keys_match_between_languages():
    assert set(MESSAGES["en"]) == set(MESSAGES["ko"])


def test_placeholders_match_between_languages():
    for code in MESSAGES["en"]:
        assert fields(MESSAGES["en"][code]) == fields(MESSAGES["ko"][code]), code


def test_english_table_has_no_hangul():
    assert not any(HANGUL.search(v) for v in MESSAGES["en"].values())


# (b) priority --------------------------------------------------------------------------------

def test_priority_order():
    env = {"LLMBENCH_LANG": "en", "LC_ALL": "ko_KR.UTF-8", "LC_MESSAGES": "ko", "LANG": "ko"}
    assert resolve_lang("ko", env) == "ko"  # --lang beats the environment
    assert resolve_lang("en", {"LLMBENCH_LANG": "ko"}) == "en"
    assert resolve_lang(None, env) == "en"  # LLMBENCH_LANG beats LC_ALL
    assert resolve_lang(None, {"LC_ALL": "en_US.UTF-8", "LC_MESSAGES": "ko", "LANG": "ko"}) == "en"
    assert resolve_lang(None, {"LC_MESSAGES": "ko", "LANG": "en_US.UTF-8"}) == "ko"
    assert resolve_lang(None, {"LANG": "ko_KR.UTF-8"}) == "ko"


def test_non_korean_and_unset_are_english():
    for value in ("fr_FR.UTF-8", "C", "POSIX", "en_US.UTF-8"):
        assert resolve_lang(None, {"LANG": value}) == "en", value
    assert resolve_lang(None, {}) == "en"


def test_cli_flag_beats_env_in_real_run(monkeypatch):
    monkeypatch.setenv("LLMBENCH_LANG", "ko")
    _, _, err = run_cli(["run", "--mock", "--repeat", "0"], lang="en")
    assert "error: --repeat must be 1 or more" in err
    monkeypatch.setenv("LLMBENCH_LANG", "en")
    _, _, err = run_cli(["run", "--mock", "--repeat", "0"], lang="ko")
    assert "오류: --repeat 는 1 이상" in err


def test_lang_flag_allowed_after_run(monkeypatch):
    monkeypatch.setenv("LLMBENCH_LANG", "ko")
    code, _, err = run_cli(["run", "--lang", "en", "--mock", "--repeat", "0"])
    assert code == 2 and "error: --repeat" in err


def test_language_does_not_leak_after_main():
    run_cli(["run", "--mock", "--repeat", "0"], lang="en")
    assert t("err.repeat_min").startswith("--repeat 는")  # conftest pins ko again


# (c) per-language regressions ----------------------------------------------------------------

@pytest.fixture
def en(monkeypatch):
    monkeypatch.setenv("LLMBENCH_LANG", "en")


def test_en_help_and_argparse_errors_have_no_hangul(en):
    for argv in (["--help"], ["run", "--help"], ["--version"], ["run", "--bogus"], ["run", "--repeat", "x"], []):
        _, out, err = run_cli(argv)
        assert not HANGUL.search(out + err), argv


def test_ko_help_and_argparse_errors_have_no_english_fixed_phrases():
    for argv in (["--help"], ["run", "--help"], ["run", "--bogus"], ["run", "--repeat", "x"], [], ["--lang", "fr"]):
        code, out, err = run_cli(argv)
        text = out + err
        for phrase in ("usage:", "options:", "positional arguments", "error:", "unrecognized arguments",
                       "invalid int value", "show this help", "required", "invalid choice"):
            assert phrase not in text, (argv, phrase)
        assert "사용법:" in text


def test_en_validate_errors(en):
    for argv, needle in ((["--repeat", "0"], "--repeat must be 1 or more"),
                         (["--concurrency", "a"], "comma-separated integers"),
                         (["--prompt-sizes", "huge"], "unknown value(s) ['huge']"),
                         (["--prompt-sizes", ","], "(empty)")):
        code, _, err = run_cli(["run", "--mock", *argv])
        assert code == 2 and needle in err and not HANGUL.search(err), argv


def test_en_unreachable_and_missing_model(en):
    port = free_port()
    code, _, err = run_cli(["run", "--host", f"http://127.0.0.1:{port}", "--out", tempfile.mkdtemp()])
    assert code == 2 and "cannot connect to the Ollama server" in err and not HANGUL.search(err)


def test_en_mock_run_output_has_no_hangul(en):
    out_dir = tempfile.mkdtemp()
    code, out, err = run_cli(["run", "--mock", "--mock-speed", "40", "--concurrency", "1,2",
                              "--prompt-sizes", "short", "--repeat", "1", "--num-predict", "8", "--out", out_dir])
    assert code == 0, err
    assert not HANGUL.search(out + err)
    assert out.startswith("MOCK - practice (mock) mode")
    assert "conc" in out and "agg tok/s" in out and "mem MB" in out
    assert "decode" in out and "[1/2]" in out


def test_ko_table_headers_line_up():
    from llmbench.__main__ import _print_table
    row = {"model": "m", "num_ctx": 4096, "concurrency": 1, "size": "short", "ttft_p50": 1.0, "ttft_p95": 2.0,
           "decode_tps": 3.0, "agg_tps": 4.0, "ps_size": 1e9}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        _print_table([row])
    head, line = out.getvalue().splitlines()[1:3]
    assert i18n.display_width(head) == i18n.display_width(line)


# (d) machine output is language independent ---------------------------------------------------

def _mock_run(lang):
    out_dir = tempfile.mkdtemp()
    code, _, _ = run_cli(["run", "--mock", "--mock-speed", "40", "--concurrency", "1", "--prompt-sizes", "short",
                          "--repeat", "1", "--num-predict", "8", "--out", out_dir], lang=lang)
    names = os.listdir(os.path.join(out_dir, "results"))
    with open(os.path.join(out_dir, "results", names[0]), encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    return code, names, rows


def test_jsonl_keys_run_id_and_exit_code_do_not_depend_on_language():
    code_en, names_en, rows_en = _mock_run("en")
    code_ko, names_ko, rows_ko = _mock_run("ko")
    assert code_en == code_ko == 0
    assert names_en == names_ko  # same run-<hash>.jsonl, so resume works across languages
    assert [sorted(r) for r in rows_en] == [sorted(r) for r in rows_ko]
    assert rows_en[0]["mode"] == "MOCK" and {r["phase"] for r in rows_en[1:]} == {"warmup", "measure"}


def test_exit_code_for_bad_input_is_language_independent():
    assert run_cli(["run", "--mock", "--repeat", "0"], lang="en")[0] == 2
    assert run_cli(["run", "--mock", "--repeat", "0"], lang="ko")[0] == 2


# (e) singular / plural -----------------------------------------------------------------------

def test_english_singular_sentences():
    i18n.set_lang("en")
    try:
        assert t("run.plan_one", cells=1, requests=1, tokens=8) == \
            "1 cell to measure, about 1 request (+ warm-up), 8 tokens generated"
        assert t("run.summary_one_both", done=1, skipped=1, stopped="") == "skipped 1 cell, measured 1 new cell"
        assert t("run.summary_one_skipped", done=2, skipped=1, stopped="").startswith("skipped 1 cell,")
    finally:
        i18n.set_lang(None)


def test_single_cell_run_prints_singular(en):
    code, out, _ = run_cli(["run", "--mock", "--mock-speed", "40", "--concurrency", "1", "--prompt-sizes", "short",
                            "--repeat", "1", "--num-predict", "8", "--out", tempfile.mkdtemp()])
    assert code == 0
    assert "1 cell to measure, about 1 request" in out
    assert "skipped 0 cells, measured 1 new cell" in out


# (f) --out is a file -------------------------------------------------------------------------

@pytest.mark.parametrize("lang,needle", [("en", "error: cannot write"), ("ko", "오류:")])
def test_out_is_a_file(lang, needle):
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "afile")
        open(target, "w").close()
        code, _, err = run_cli(["run", "--mock", "--mock-speed", "40", "--out", target], lang=lang)
    assert code == 2
    assert needle in err and "Traceback" not in err and "afile" in err and ".part" not in err
    assert (lang != "en") or not HANGUL.search(err)
