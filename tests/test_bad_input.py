"""회귀: 잘못된 인자는 Traceback·무한 대기 없이 오류 메시지와 종료코드 2 로 끝난다."""
import contextlib
import io
import tempfile
import types
import unittest

import llmbench.matrix as mx
from llmbench.__main__ import main
from llmbench.matrix import Config, _run_batch


class BadInput(unittest.TestCase):
    def _run(self, *extra):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = main(["run", "--mock", "--out", tempfile.mkdtemp(), *extra])
        return code, err.getvalue()

    def test_unknown_prompt_size(self):
        code, msg = self._run("--prompt-sizes", "huge")
        self.assertEqual(code, 2)
        self.assertIn("huge", msg)
        self.assertNotIn("Traceback", msg)

    def test_zero_or_bad_concurrency(self):
        for v in ("0", "-1", "a", ""):
            code, msg = self._run("--concurrency", v)
            self.assertEqual(code, 2, v)
            self.assertIn("--concurrency", msg)
            self.assertNotIn("Traceback", msg)

    def test_worker_failure_does_not_hang(self):
        # worker 가 barrier 전에 예외를 만나도 배치가 멈추지 않고 오류를 메인으로 올린다
        orig = mx.make_prompt
        mx.make_prompt = lambda *a, **k: (_ for _ in ()).throw(KeyError("boom"))
        try:
            with self.assertRaises(KeyError):
                _run_batch(types.SimpleNamespace(time_scale=1.0), Config(models=["m"]), "m", 4096, "short", 2)
        finally:
            mx.make_prompt = orig


if __name__ == "__main__":
    unittest.main()
