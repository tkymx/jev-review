"""Minimal client for TypeSafe's System One API (Jev). Standard library only."""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.13.0"      # pin the model: thresholds were measured on this version
PRICE_PER_MTOK_USD = 0.042        # input tokens only; output is free
MAX_TOTAL_TOKENS = 64_000         # state + all questions
MAX_SINGLE_TOKENS = 32_000        # state + the longest question
SAFETY = 0.9


class JevError(RuntimeError):
    pass


def estimate_tokens(obj) -> int:
    """Conservative estimate: ~3 ASCII characters per token, 1 token per non-ASCII character."""
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    ascii_chars = sum(1 for c in s if ord(c) < 128)
    return ascii_chars // 3 + (len(s) - ascii_chars) + 1


def plan_calls(state, questions: dict) -> list[dict]:
    """Pack questions into as few calls as the token limits allow.

    One call is preferred: splitting 24 questions into 4 or 6 parallel calls did not
    change accuracy but cost 1.8-2.4x the tokens.
    """
    s = estimate_tokens(state)
    batches: list[dict] = []
    cur: dict = {}
    used = s
    for qid, q in questions.items():
        t = estimate_tokens(q)
        if s + t > MAX_SINGLE_TOKENS * SAFETY:
            raise JevError(f"hunk too large for one question ({s + t} estimated tokens)")
        if cur and used + t > MAX_TOTAL_TOKENS * SAFETY:
            batches.append(cur)
            cur, used = {}, s
        cur[qid] = q
        used += t
    if cur:
        batches.append(cur)
    return batches


def load_env_file(path: str) -> None:
    """Read KEY=VALUE lines into os.environ without overriding existing values."""
    for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


class JevClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, endpoint: str = ENDPOINT,
                 timeout: float = 60, retries: int = 4):
        if not api_key:
            raise JevError("TYPESAFE_API_KEY is not set (get one at https://console.typesafe.ai/)")
        self.api_key, self.model, self.endpoint = api_key, model, endpoint
        self.timeout, self.retries = timeout, retries

    def ask(self, state, questions: dict) -> dict:
        body = json.dumps({"model": self.model, "state": state, "questions": questions},
                          ensure_ascii=False).encode("utf-8")
        last = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.endpoint, data=body, method="POST", headers={
                "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code in (429, 500, 502, 503, 504, 529) and attempt < self.retries:
                    last = f"HTTP {e.code}"
                else:
                    raise JevError(f"HTTP {e.code}: {detail}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                last = str(e)
                if attempt >= self.retries:
                    raise JevError(f"network error: {e}") from e
            time.sleep(min(2 ** attempt, 20) * (0.5 + random.random()))
        raise JevError(f"giving up after retries: {last}")
