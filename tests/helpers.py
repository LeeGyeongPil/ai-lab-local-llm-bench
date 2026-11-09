"""테스트 공용: 가짜 Ollama 를 띄우고 작은 매트릭스를 임시 JSONL 로 측정한다."""
import os
import tempfile

from llmbench.client import OllamaClient
from llmbench.fake_ollama import FakeOllama
from llmbench.matrix import Config, read_jsonl, run_matrix


def measure(cfg: Config, speed: float = 8.0, path: str | None = None, max_cells=None, fake=None):
    """가짜 서버를 띄워 측정하고 (rows, path) 를 돌려준다. 서버는 항상 정리한다."""
    path = path or os.path.join(tempfile.mkdtemp(), "run.jsonl")
    own = fake is None
    fake = fake or FakeOllama(speed=speed).start()
    try:
        client = OllamaClient(fake.url, time_scale=fake.speed)
        run_matrix(client, cfg, path, log=lambda *_: None, max_cells=max_cells)
    finally:
        if own:
            fake.stop()
    return read_jsonl(path), path
