"""입력 길이(short/medium/long)별 프롬프트 만들기.

토큰 수는 '글자 4개 = 토큰 1개'로 어림한다(영어 기준 대략값).
실제 토큰 수는 Ollama가 돌려주는 prompt_eval_count 로 확인한다.
"""
import math
import os

from .i18n import CodedError

# 크기 이름 -> 목표 토큰 수 (약 20 / 500 / 1,500)
SIZES = {"short": 20, "medium": 500, "long": 1500}

PASSAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "passage.txt"
)


def estimate_tokens(text: str) -> int:
    """글자 수 / 4 (올림). 가짜 서버도 같은 식을 써서 입력 길이 효과를 만든다."""
    return math.ceil(len(text) / 4)


def _passage(chars: int) -> str:
    with open(PASSAGE_PATH, encoding="utf-8") as f:
        base = f.read().strip()
    out, n = "", 1
    while len(out) < chars:  # 본문이 모자라면 구간 번호를 붙여 반복한다
        out += f"[part {n}] {base}\n"
        n += 1
    return out[:chars]


def make_prompt(size: str, nonce: str = "") -> str:
    """nonce 가 있으면 맨 앞에 붙인다 -> 프롬프트 캐시(접두어 일치)를 피한다."""
    if size not in SIZES:
        raise CodedError("err.unknown_size", size=size, sizes=", ".join(SIZES))
    head = f"[run {nonce}] " if nonce else ""
    if size == "short":
        body = "Explain what a KV cache is in one sentence."
    else:
        body = "Summarize the following text in two sentences.\n\n" + _passage(SIZES[size] * 4)
    return head + body
