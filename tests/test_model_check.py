"""측정 전 모델 존재 확인(/api/tags): 없는 태그는 측정 전에 안내하고 종료코드 2."""
import contextlib
import copy
import io
import os
import tempfile
import unittest

from llmbench.__main__ import _check_models, main
from llmbench.client import OllamaClient
from llmbench.fake_ollama import FakeOllama, load_profiles

COMMON = ["run", "--concurrency", "1", "--prompt-sizes", "short", "--repeat", "1", "--num-predict", "4"]


def run_cli(argv, fake):
    out_dir = tempfile.mkdtemp()
    so, se = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
        code = main(COMMON + ["--host", fake.url, "--out", out_dir] + argv)
    res = os.path.join(out_dir, "results")
    files = os.listdir(res) if os.path.isdir(res) else []
    lines = []
    for f in files:
        with open(os.path.join(res, f), encoding="utf-8") as fh:
            lines += fh.read().splitlines()
    return code, so.getvalue(), se.getvalue(), files, lines


class ModelCheck(unittest.TestCase):
    def test_missing_model_stops_before_measuring(self):
        with FakeOllama(speed=50) as fake:
            code, out, err, files, _ = run_cli(["--models", "nosuch:1b"], fake)
        self.assertEqual(code, 2)
        self.assertIn("서버에 없는 모델 태그: nosuch:1b", err)
        self.assertIn("ollama pull nosuch:1b", err)
        self.assertIn("qwen3:4b", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(files, [])
        self.assertNotIn("[warmup]", out)

    def test_second_model_missing_does_not_measure_first(self):
        with FakeOllama(speed=50) as fake:
            code, out, err, files, lines = run_cli(["--models", "qwen3:4b,nosuch:1b"], fake)
        self.assertEqual(code, 2)
        self.assertIn("nosuch:1b", err)
        self.assertEqual(files, [])
        self.assertFalse([ln for ln in lines if '"measure"' in ln])
        self.assertNotIn("[warmup]", out)

    def test_default_tags_missing_listed(self):
        with FakeOllama(speed=50) as fake:
            code, out, err, files, _ = run_cli([], fake)
        self.assertEqual(code, 2)
        self.assertIn("서버에 없는 모델 태그:", err)
        self.assertIn("qwen3:0.6b", err)
        self.assertEqual(files, [])

    def test_latest_suffix_normalized(self):
        # 서버 목록이 'qwen3:latest' 이면 --models qwen3 은 통과(확인 함수만 직접 호출)
        profiles = copy.deepcopy(load_profiles())
        profiles["models"] = {"qwen3:latest": profiles["models"]["qwen3:4b"]}
        with FakeOllama(profiles, speed=50) as fake:
            client = OllamaClient(fake.url)
            self.assertIsNone(_check_models(client, ["qwen3"]))
            self.assertIsNone(_check_models(client, ["qwen3:latest"]))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(_check_models(client, ["qwen3:4b"]), 2)

    def test_tags_unsupported_warns_and_continues(self):
        with FakeOllama(speed=50, tags=False) as fake:
            code, out, err, files, _ = run_cli(["--models", "qwen3:4b"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("경고: 모델 목록(/api/tags)을 확인할 수 없어 존재 확인을 건너뜁니다"), 1)

    def test_existing_model_output_has_no_new_lines(self):
        with FakeOllama(speed=50) as fake:
            code, out, err, files, _ = run_cli(["--models", "qwen3:4b"], fake)
        self.assertEqual(code, 0)
        self.assertNotIn("경고", out)
        self.assertEqual(err, "")

    def test_mock_missing_model(self):
        so, se = io.StringIO(), io.StringIO()
        d = tempfile.mkdtemp()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = main(COMMON + ["--mock", "--models", "nosuch:1b", "--out", d])
        self.assertEqual(code, 2)
        self.assertIn("서버에 없는 모델 태그: nosuch:1b", se.getvalue())
        self.assertFalse(os.path.isdir(os.path.join(d, "results")))


if __name__ == "__main__":
    unittest.main()
