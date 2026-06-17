"""OpenAI 호환 LLM 클라이언트.

무료로 쓸 수 있는 곳들을 LLM_PROVIDER 프리셋으로 지원한다.
사용자는 키와 모델명만 넣으면 된다.

  gemini     - Google Gemini (무료 등급 넉넉, 한국어 좋음)
  groq       - Groq (무료, 빠름)
  openrouter - OpenRouter (무료 모델 일부 제공)
  ollama     - 로컬 (키 불필요, 모델 설치 필요)

표준 라이브러리만 쓴다(설치 불필요).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass


class LLMConfigurationError(RuntimeError):
    pass


class LLMRequestError(RuntimeError):
    pass


PROVIDER_PRESETS = {
    "gemini": {
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-flash",
        "needs_key": True,
    },
    "groq": {
        "api_base": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "needs_key": True,
    },
    "openrouter": {
        "api_base": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "needs_key": True,
    },
    "ollama": {
        "api_base": "http://127.0.0.1:11434/v1",
        "default_model": "exaone3.5:7.8b",
        "needs_key": False,
    },
}


@dataclass(frozen=True)
class LLMConfig:
    api_base: str
    model: str
    api_key: str = ""
    timeout: float = 60.0
    temperature: float = 0.5
    max_tokens: int = 768
    reasoning_effort: str = ""

    @classmethod
    def resolve(cls) -> tuple[str, str, str]:
        """환경변수 -> 프리셋 순으로 api_base, model, api_key 를 정한다."""
        provider = os.getenv("LLM_PROVIDER", "").strip().lower()
        preset = PROVIDER_PRESETS.get(provider, {})
        api_base = os.getenv("LLM_API_BASE", "").strip() or preset.get("api_base", "")
        model = os.getenv("LLM_MODEL", "").strip() or preset.get("default_model", "")
        api_key = os.getenv("LLM_API_KEY", "").strip()
        return api_base.rstrip("/"), model, api_key

    @classmethod
    def is_configured(cls) -> bool:
        api_base, model, _ = cls.resolve()
        return bool(api_base and model)

    @classmethod
    def from_env(cls) -> "LLMConfig":
        api_base, model, api_key = cls.resolve()
        if not api_base or not model:
            raise LLMConfigurationError(
                "LLM 설정이 없다. LLM_PROVIDER(gemini/groq/openrouter/ollama)와 "
                "LLM_API_KEY, 필요하면 LLM_MODEL 을 설정해라. llm.env.example 참고."
            )
        return cls(
            api_base=api_base,
            model=model,
            api_key=api_key,
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.5")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "384")),
            reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "").strip(),
        )


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()

    def chat(self, system_prompt: str, user_message: str) -> str:
        return "".join(self.chat_stream(system_prompt, user_message)).strip()

    def complete(self, system_prompt: str, user_message: str) -> str:
        """비스트리밍 호출. 스트리밍이 답을 중간에 끊는 모델(gemini-2.5-flash 등)에서도
        항상 완전한 답을 받기 위해 쓴다."""
        endpoint = f"{self.config.api_base}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.reasoning_effort:
            payload["reasoning_effort"] = self.config.reasoning_effort
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                body = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMRequestError(f"LLM API HTTP {exc.code}: {detail[:400]}") from exc
        except urllib.error.URLError as exc:
            raise LLMRequestError(f"LLM API 연결 실패: {exc}") from exc

        choices = body.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return str(message.get("content") or "").strip()

    def chat_stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        endpoint = f"{self.config.api_base}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        if self.config.reasoning_effort:
            payload["reasoning_effort"] = self.config.reasoning_effort
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    chunk = _parse_stream_line(line)
                    if chunk is None:
                        continue
                    if chunk == "[DONE]":
                        break
                    yield chunk
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMRequestError(f"LLM API HTTP {exc.code}: {detail[:400]}") from exc
        except urllib.error.URLError as exc:
            raise LLMRequestError(f"LLM API 연결 실패: {exc}") from exc


def _parse_stream_line(line: str) -> str | None:
    payload = line
    if line.startswith("data:"):
        payload = line.removeprefix("data:").strip()
    if payload == "[DONE]":
        return "[DONE]"
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None

    chunks: list[str] = []
    for choice in parsed.get("choices", []):
        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        content = delta.get("content")
        if content is None:
            content = message.get("content")
        if content:
            chunks.append(str(content))
    return "".join(chunks) if chunks else None
