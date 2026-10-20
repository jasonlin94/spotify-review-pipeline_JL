"""Model clients for the classify/verify/memo roles.

Provider-agnostic: a client exposes `.generate(prompt) -> GenResult` with usage.
Two implementations:
  - GeminiClient : Google AI Studio free tier (key from GEMINI_API_KEY, starts AIza)
  - OllamaClient : local, no key, http://localhost:11434 (fallback)

Only stdlib (urllib) so requirements stay light and reproducible. Keys are read
from the environment at call time and NEVER logged.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class GenResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    model: str = ""
    raw_usage: dict = field(default_factory=dict)


class ModelError(Exception):
    pass


class GeminiClient:
    """Google Gemini via REST. Default model is a cheap/fast flash-lite tier."""

    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, model: str = "gemini-2.0-flash-lite",
                 output_token_cap: int = 1024, temperature: float = 0.0):
        self.model = model
        self.output_token_cap = output_token_cap
        self.temperature = temperature

    def _key(self) -> str:
        k = os.environ.get("GEMINI_API_KEY", "").strip()
        if not k:
            raise ModelError("GEMINI_API_KEY not set in environment (.env)")
        return k

    def generate(self, prompt: str, max_retries: int = 2) -> GenResult:
        url = f"{self.BASE}/{self.model}:generateContent"
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.output_token_cap,
            },
        }).encode()
        last_err = None
        for attempt in range(max_retries + 1):
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json",
                         "x-goog-api-key": self._key()},
            )
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    out = json.loads(r.read())
                dt = time.time() - t0
                text = _gemini_text(out)
                usage = out.get("usageMetadata", {})
                return GenResult(
                    text=text,
                    input_tokens=usage.get("promptTokenCount", 0),
                    output_tokens=usage.get("candidatesTokenCount", 0),
                    latency_s=dt, model=self.model, raw_usage=usage,
                )
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
                if e.code in (429, 500, 503) and attempt < max_retries:
                    time.sleep(min(2 ** attempt + 0.5, 10))  # bounded backoff
                    continue
                raise ModelError(last_err)
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = str(e)
                if attempt < max_retries:
                    time.sleep(min(2 ** attempt + 0.5, 10))
                    continue
                raise ModelError(last_err)
        raise ModelError(last_err or "unknown error")


class OllamaClient:
    """Local Ollama (no key). Kept as a fallback / offline option."""

    def __init__(self, model: str = "gemma4:e2b",
                 output_token_cap: int = 512, temperature: float = 0.0,
                 host: str = "http://localhost:11434"):
        self.model = model
        self.output_token_cap = output_token_cap
        self.temperature = temperature
        self.host = host

    def generate(self, prompt: str, max_retries: int = 1) -> GenResult:
        body = json.dumps({
            "model": self.model, "prompt": prompt, "stream": False,
            "options": {"temperature": self.temperature,
                        "num_predict": self.output_token_cap},
        }).encode()
        last_err = None
        for attempt in range(max_retries + 1):
            req = urllib.request.Request(
                f"{self.host}/api/generate", data=body,
                headers={"Content-Type": "application/json"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    out = json.loads(r.read())
                dt = time.time() - t0
                return GenResult(
                    text=out.get("response", ""),
                    input_tokens=out.get("prompt_eval_count", 0),
                    output_tokens=out.get("eval_count", 0),
                    latency_s=dt, model=self.model, raw_usage=out,
                )
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = str(e)
                if attempt < max_retries:
                    time.sleep(1.0)
                    continue
                raise ModelError(last_err)
        raise ModelError(last_err or "unknown error")


def _gemini_text(out: dict) -> str:
    try:
        cands = out.get("candidates", [])
        if not cands:
            return ""
        parts = cands[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError):
        return ""


def make_client(provider: str | None = None, **kw):
    provider = (provider or os.environ.get("MODEL_PROVIDER") or "gemini").lower()
    if provider == "gemini":
        return GeminiClient(**kw)
    if provider == "ollama":
        return OllamaClient(**kw)
    raise ModelError(f"unknown provider: {provider}")
