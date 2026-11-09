"""AC-6: 중단 후 같은 설정으로 다시 실행하면 남은 칸만 잰다."""
import os
import tempfile
import unittest

from llmbench.matrix import Config, done_cells
from llmbench.stats import measured
from tests.helpers import measure


class Resume(unittest.TestCase):
    def test_interrupt_and_resume(self):
        cfg = Config(models=["qwen3:4b"], concurrencies=[1, 2], sizes=["short"], repeat=3, num_predict=4)
        path = os.path.join(tempfile.mkdtemp(), "run.jsonl")
        rows, _ = measure(cfg, speed=50, path=path, max_cells=5)  # 칸 5개에서 끊김
        self.assertEqual(len(done_cells(rows)), 5)
        rows, _ = measure(cfg, speed=50, path=path)  # 같은 명령으로 재실행
        meas = measured(rows)
        self.assertEqual(len(meas), cfg.total_requests())  # 최종 행 수 = 매트릭스 요청 수
        keys = [(r["model"], r["num_ctx"], r["concurrency"], r["size"], r["rep"], r["slot"]) for r in meas]
        self.assertEqual(len(keys), len(set(keys)))  # 중복 0
        self.assertEqual(len(done_cells(rows)), cfg.total_cells())


if __name__ == "__main__":
    unittest.main()
