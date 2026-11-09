"""AC-2, AC-3: mock 에서 README 가 가르칠 교훈이 '실제 측정'으로 재현되는가.
허용 오차는 비율·순서 기준이다(벽시계가 수 ms 흔들려도 통과하도록)."""
import unittest

from llmbench.matrix import Config
from llmbench.stats import measured, summarize
from tests.helpers import measure

MODEL = "qwen3:4b"


class MockLessons(unittest.TestCase):
    def test_concurrency_staircase(self):
        cfg = Config(models=[MODEL], concurrencies=[1, 4], sizes=["short"], repeat=3, num_predict=24)
        rows, _ = measure(cfg, speed=8)
        s = {r["concurrency"]: r for r in summarize(rows)}
        # 줄 서기: 동시 4의 p95 TTFT 는 동시 1 의 p50 보다 3배 이상 크다
        self.assertGreaterEqual(s[4]["ttft_p95"], 3 * s[1]["ttft_p50"])
        # 한 배치(동시 4)의 TTFT 를 정렬하면 계단: 각 칸이 앞 칸보다 뚜렷이 크다
        batch = sorted(r["ttft_ms"] for r in measured(rows) if r["concurrency"] == 4 and r["rep"] == 0)
        self.assertEqual(len(batch), 4)
        for a, b in zip(batch, batch[1:]):
            self.assertGreater(b, a)
        # 합계 처리량은 평평(단일 슬롯): 동시 1 대비 4 의 차이 15% 이내
        self.assertLess(abs(s[4]["agg_tps"] - s[1]["agg_tps"]) / s[1]["agg_tps"], 0.15)

    def test_prefill_scales_with_input(self):
        cfg = Config(models=[MODEL], concurrencies=[1], repeat=3, num_predict=24)
        rows, _ = measure(cfg, speed=5)
        s = {r["size"]: r for r in summarize(rows)}
        self.assertLess(s["short"]["ttft_p50"], s["medium"]["ttft_p50"])
        self.assertLess(s["medium"]["ttft_p50"], s["long"]["ttft_p50"])
        self.assertGreaterEqual(s["long"]["ttft_p50"], 5 * s["short"]["ttft_p50"])
        # 디코드 속도는 입력 길이와 무관: 클라이언트가 직접 잰 값이 크기별로 ±10% 이내
        tps = [s[k]["client_decode_tps"] for k in s]
        self.assertLess((max(tps) - min(tps)) / (sum(tps) / len(tps)), 0.10)


if __name__ == "__main__":
    unittest.main()
