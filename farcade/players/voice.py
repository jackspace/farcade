"""The voice adapter: OpenAI-compatible chat completions, unwired by
default.

Speaks the /v1/chat/completions shape that Ollama, llama.cpp's server,
LM Studio and the hosted APIs all expose, so "connect inference" is a
config change (base_url + model), never a refactor.

Failure discipline is absolute: ANY problem - timeout, refusal, HTTP
error, garbage JSON, unresolvable host - degrades to None, which the
caller renders as silence. A chess game must never stall because a GPU
is busy. The black-hole test in tests/test_players.py holds this to
account.
"""

from __future__ import annotations

import httpx


class OpenAICompatVoice:
    def __init__(
        self,
        base_url: str,
        model: str,
        persona: str = "You are a correspondence-game companion. One or two short sentences.",
        timeout: float = 10.0,
        max_tokens: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.persona = persona
        self.timeout = timeout
        self.max_tokens = max_tokens

    def comment(self, context: dict) -> str | None:
        prompt = (
            f"Game: {context.get('game', '?')}. Ply {context.get('ply', '?')}. "
            f"Position: {context.get('position', '?')}. "
            f"Last move: {context.get('last_move', '?')}. "
            f"Recent chat: {context.get('chat', '')!r}. "
            "React in character, briefly. Never suggest or choose moves."
        )
        try:
            resp = httpx.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": self.persona},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": self.max_tokens,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            return text or None
        except Exception:
            return None  # silence, by design; never an exception upward
