"""측정 매트릭스 실행: 워밍업 -> (크기 x 동시성 x 반복) 배치, 결과는 JSONL 한 줄씩 append.

칸(cell) = 배치 하나 = (model, num_ctx, concurrency, size, rep). 배치 안에서 동시 N개가
같이 출발하고, 행 하나가 slot 하나다. 행 키 = (model, num_ctx, concurrency, size, rep, slot).
JSONL에 이미 있는 칸은 다시 재지 않는다 -> Ctrl+C 후 같은 명령으로 이어하기.
"""
import json
import secrets
import threading
import time
from dataclasses import dataclass, field

from .client import OllamaClient
from .i18n import t
from .prompts import make_prompt


@dataclass
class Config:
    models: list
    num_ctxs: list = field(default_factory=lambda: [4096])
    concurrencies: list = field(default_factory=lambda: [1, 2, 4])
    sizes: list = field(default_factory=lambda: ["short", "medium", "long"])
    repeat: int = 2
    num_predict: int = 64
    nonce: bool = True  # False 면 같은 프롬프트를 반복 -> 캐시 적중 관찰용
    seed: int = 1

    def cells(self):
        """(model, num_ctx, size, concurrency, rep) 순서대로 모든 칸."""
        for m in self.models:
            for c in self.num_ctxs:
                for s in self.sizes:
                    for n in self.concurrencies:
                        for r in range(self.repeat):
                            yield (m, c, n, s, r)

    def total_cells(self) -> int:
        return len(self.models) * len(self.num_ctxs) * len(self.sizes) * len(self.concurrencies) * self.repeat

    def total_requests(self) -> int:
        return len(self.models) * len(self.num_ctxs) * len(self.sizes) * self.repeat * sum(self.concurrencies)


def read_jsonl(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def done_cells(rows) -> set:
    """이미 끝난 칸 = 배치의 slot 이 모두 기록된 칸."""
    slots = {}
    for r in rows:
        if r.get("type") == "row" and r.get("phase") == "measure":
            key = (r["model"], r["num_ctx"], r["concurrency"], r["size"], r["rep"])
            slots.setdefault(key, set()).add(r["slot"])
    return {k for k, v in slots.items() if len(v) == k[2]}


def _append(path: str, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:  # 한 줄씩 열고 닫아 중단돼도 앞부분은 남는다
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _prompt(cfg: Config, size: str) -> str:
    return make_prompt(size, secrets.token_hex(4) if cfg.nonce else "")


def _run_batch(client, cfg, model, num_ctx, size, n):
    """동시 n개를 한꺼번에 출발시켜 결과 리스트와 배치 벽시계(ms)를 돌려준다."""
    results = [None] * n
    errors = []
    barrier = threading.Barrier(n + 1)

    def worker(i):
        try:
            prompt = _prompt(cfg, size)
        except Exception as e:  # 준비 중 실패해도 barrier 는 반드시 거쳐야 모두가 멈추지 않는다
            prompt = None
            errors.append(e)
        try:
            barrier.wait(timeout=30)  # 모두 준비되면 동시에 출발
        except threading.BrokenBarrierError:
            return
        if prompt is None:
            return
        try:
            results[i] = client.chat(model, prompt, num_ctx, cfg.num_predict, cfg.seed)
        except Exception as e:  # 스레드 안 오류는 메인에서 다시 던진다
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    try:
        barrier.wait(timeout=30)
    except threading.BrokenBarrierError:
        pass
    t0 = time.perf_counter()
    for t in threads:
        t.join()
    wall_ms = (time.perf_counter() - t0) * client.time_scale * 1000
    if errors:
        raise errors[0]
    return results, round(wall_ms, 1)


def run_matrix(client: OllamaClient, cfg: Config, path: str, log=print, max_cells=None) -> dict:
    """매트릭스를 돌리고 {'done','skipped','stopped'} 를 돌려준다. max_cells: 이번 실행에서 잴 칸 상한."""
    rows = read_jsonl(path)
    finished = done_cells(rows)
    skipped = measured_now = 0
    stopped = False
    for model in cfg.models:
        for num_ctx in cfg.num_ctxs:
            todo = [c for c in cfg.cells() if c[0] == model and c[1] == num_ctx and c not in finished]
            skipped += sum(1 for c in cfg.cells() if c[0] == model and c[1] == num_ctx) - len(todo)
            if not todo:
                continue
            if max_cells is not None and measured_now >= max_cells:
                stopped = True
                break
            # 워밍업 1회: 모델을 올리고 결과는 버린다(phase=warmup, 집계에서 제외)
            log(t("run.warmup", model=model, num_ctx=num_ctx))
            wres, wwall = _run_batch(client, cfg, model, num_ctx, "short", 1)
            _append(path, {"type": "row", "phase": "warmup", "model": model, "num_ctx": num_ctx,
                           "concurrency": 1, "size": "short", "rep": 0, "slot": 0,
                           "batch_wall_ms": wwall, **wres[0]})
            for (m, c, n, size, rep) in todo:
                if max_cells is not None and measured_now >= max_cells:
                    stopped = True
                    break
                results, wall = _run_batch(client, cfg, m, c, size, n)
                info = client.ps_info(m)  # 배치 직후 메모리 추정치
                for slot, res in enumerate(results):
                    _append(path, {"type": "row", "phase": "measure", "model": m, "num_ctx": c,
                                   "concurrency": n, "size": size, "rep": rep, "slot": slot,
                                   "nonce": cfg.nonce, "time_scale": client.time_scale,
                                   "batch_wall_ms": wall, **res, **info})
                measured_now += 1
                tt = sorted(r["ttft_ms"] for r in results)
                log(t("run.progress", index=measured_now + skipped, total=cfg.total_cells(), model=m, ctx=c, conc=n,
                      size=size, rep=rep + 1, lo=tt[0], hi=tt[-1], tps=results[0]["decode_tps"]))
            if stopped:
                break
    return {"done": measured_now, "skipped": skipped, "stopped": stopped}
