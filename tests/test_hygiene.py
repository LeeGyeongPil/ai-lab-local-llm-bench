"""AC-5: 측정 위생 — 워밍업 제외, nonce 로 캐시 회피, 캐시 적중 표시, 대기 추정."""
import unittest

from llmbench.matrix import Config
from llmbench.stats import measured, summarize
from tests.helpers import measure

MODEL = "qwen3:4b"


class Hygiene(unittest.TestCase):
    def test_warmup_nonce_and_queue_estimate(self):
        cfg = Config(models=[MODEL], concurrencies=[1, 2], sizes=["short", "medium"], repeat=2, num_predict=8)
        rows, _ = measure(cfg, speed=20)
        warm = [r for r in rows if r.get("phase") == "warmup"]
        self.assertEqual(len(warm), 1)
        self.assertGreater(warm[0]["load_ms"], 0)  # 워밍업이 콜드 로드를 흡수
        meas = measured(rows)
        self.assertTrue(all(r["load_ms"] == 0 for r in meas))  # 측정 행에는 로드가 없다
        self.assertEqual(len(meas), cfg.total_requests())  # 워밍업 행은 집계에서 빠짐
        # nonce 기본 켬 -> 캐시 적중 0
        self.assertTrue(all(r["prompt_eval_cached_count"] == 0 for r in meas))
        # 대기 추정은 항상 0 이상, 동시 2 의 두 번째 요청은 실제로 기다렸다
        self.assertTrue(all(r["queue_ms"] >= 0 for r in meas))
        c2 = [r for r in meas if r["concurrency"] == 2 and r["rep"] == 0 and r["size"] == "medium"]
        self.assertGreater(max(r["queue_ms"] for r in c2), min(r["queue_ms"] for r in c2) + 100)

    def test_no_nonce_shows_cache_hits(self):
        cfg = Config(models=[MODEL], concurrencies=[1], sizes=["medium"], repeat=3, num_predict=8, nonce=False)
        rows, _ = measure(cfg, speed=20)
        hits = [r for r in measured(rows) if r["prompt_eval_cached_count"] > 0]
        self.assertGreaterEqual(len(hits), 2)  # 둘째 반복부터 같은 프롬프트
        self.assertGreater(summarize(rows)[0]["cache_hits"], 0)  # 요약 표에도 적중 수가 보인다


if __name__ == "__main__":
    unittest.main()
