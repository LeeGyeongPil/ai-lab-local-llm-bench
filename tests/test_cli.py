"""AC-9: 서버가 없을 때 친절하게 실패, 그리고 --mock 전체 실행."""
import contextlib
import io
import os
import socket
import tempfile
import unittest

from llmbench.__main__ import main


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Cli(unittest.TestCase):
    def test_unreachable_server_message(self):
        port = free_port()  # 아무도 듣지 않는 포트
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = main(["run", "--host", f"http://127.0.0.1:{port}", "--out", tempfile.mkdtemp()])
        self.assertEqual(code, 2)
        msg = err.getvalue()
        self.assertIn(f"Ollama 서버(http://127.0.0.1:{port})에 연결할 수 없습니다", msg)
        self.assertIn("--mock", msg)
        self.assertNotIn("Traceback", msg)

    def test_mock_run_prints_banner_and_writes_jsonl(self):
        out_dir, out = tempfile.mkdtemp(), io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["run", "--mock", "--mock-speed", "40", "--concurrency", "1,2", "--prompt-sizes", "short",
                         "--repeat", "1", "--num-predict", "8", "--out", out_dir])
        self.assertEqual(code, 0)
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("MOCK"))  # 첫 줄 배너
        self.assertTrue(any(f.endswith(".jsonl") for f in os.listdir(os.path.join(out_dir, "results"))))


if __name__ == "__main__":
    unittest.main()
