"""Connectivity + format smoke test for the Gemini client.

Run AFTER pasting your key into .env:
    python -m scripts.test_gemini

Makes ONE tiny call. Prints model, latency, token usage and the parsed
classification lines. Never prints the API key.
"""
from __future__ import annotations

from pipeline.config import load_env
from pipeline.model_client import GeminiClient, ModelError

load_env()

PROMPT = """Classify each Spotify review. Output ONE line per review, format: id|topic|intent|severity|sentiment
topic: access usability playback downloads catalog billing support other
intent: cancellation complaint request praise unclear
severity: integer 1-5
sentiment: one of -1 -0.5 0 0.5 1
No other text.

1: Can't log in after the update, keeps rejecting my password
2: Love the new design, so smooth and fast
3: Downloaded songs stop playing when I go offline
4: I was charged twice for premium this month
5: meh it's fine
"""

def main() -> None:
    client = GeminiClient()
    try:
        r = client.generate(PROMPT)
    except ModelError as e:
        print("[FAIL]", e)
        print("\nCheck: (1) key pasted into .env  (2) key starts with AIza  "
              "(3) internet reachable  (4) free-tier quota not exhausted.")
        return
    print(f"[OK] model={r.model}  latency={r.latency_s:.2f}s  "
          f"in_tok={r.input_tokens} out_tok={r.output_tokens}")
    print("--- parsed lines ---")
    print(r.text.strip())


if __name__ == "__main__":
    main()
