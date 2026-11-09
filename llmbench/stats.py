"""집계: p50/p95, 시간 쪼개기, 합계 처리량. 워밍업 행은 여기서 항상 빠진다."""
import statistics


def percentile(values, q: float) -> float:
    """선형 보간 백분위수 (q: 0~100)."""
    xs = sorted(values)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * q / 100
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def measured(rows):
    """측정 행만(워밍업·meta 제외)."""
    return [r for r in rows if r.get("type") == "row" and r.get("phase") == "measure"]


def breakdown(row: dict) -> dict:
    """요청 하나의 시간을 대기·로드·프리필·디코드로 쪼갠다(ms)."""
    return {
        "queue": row["queue_ms"],
        "load": row["load_ms"],
        "prefill": row["prompt_eval_ms"],
        "decode": row["eval_ms"],
    }


def aggregate_throughput(batch_rows) -> float:
    """한 배치(동시 N개)의 합계 처리량 = 전체 생성 토큰 / 배치 벽시계(초)."""
    wall = max(r["batch_wall_ms"] for r in batch_rows) / 1000
    return sum(r["eval_count"] for r in batch_rows) / wall if wall else 0.0


def summarize(rows):
    """(model, num_ctx, concurrency, size) 칸마다 p50/p95 표 행을 만든다."""
    groups, batches = {}, {}
    for r in measured(rows):
        key = (r["model"], r["num_ctx"], r["concurrency"], r["size"])
        groups.setdefault(key, []).append(r)
        batches.setdefault(key + (r["rep"],), []).append(r)
    out = []
    for key in sorted(groups):
        rs = groups[key]
        ttft = [r["ttft_ms"] for r in rs]
        agg = [aggregate_throughput(b) for k, b in batches.items() if k[:4] == key]
        out.append({
            "model": key[0], "num_ctx": key[1], "concurrency": key[2], "size": key[3],
            "n": len(rs),
            "ttft_p50": percentile(ttft, 50), "ttft_p95": percentile(ttft, 95),
            "decode_tps": statistics.median(r["decode_tps"] for r in rs),
            "client_decode_tps": statistics.median(r["client_decode_tps"] for r in rs),
            "prefill_tps": statistics.median(r["prefill_tps"] for r in rs),
            "agg_tps": statistics.median(agg),
            "queue_p50": percentile([r["queue_ms"] for r in rs], 50),
            "ps_size": rs[-1].get("ps_size"),
            "cache_hits": sum(1 for r in rs if r["prompt_eval_cached_count"] > 0),
        })
    return out
