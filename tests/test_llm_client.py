import json
import os
import unittest
from unittest.mock import patch

from llm_client import LLMConfig, OpenAICompatibleClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class LlmClientTests(unittest.TestCase):
    def test_default_max_tokens_is_not_tiny(self):
        old_base = os.environ.get("LLM_API_BASE")
        old_model = os.environ.get("LLM_MODEL")
        old_tokens = os.environ.get("LLM_MAX_TOKENS")
        try:
            os.environ["LLM_API_BASE"] = "http://example.invalid/v1"
            os.environ["LLM_MODEL"] = "fake"
            os.environ.pop("LLM_MAX_TOKENS", None)
            self.assertEqual(LLMConfig.from_env().max_tokens, 2048)
        finally:
            _restore_env("LLM_API_BASE", old_base)
            _restore_env("LLM_MODEL", old_model)
            _restore_env("LLM_MAX_TOKENS", old_tokens)

    def test_complete_continues_when_finish_reason_is_length(self):
        responses = [
            FakeResponse({
                "choices": [{
                    "message": {"content": "앞부분이다."},
                    "finish_reason": "length",
                }]
            }),
            FakeResponse({
                "choices": [{
                    "message": {"content": "뒷부분이다."},
                    "finish_reason": "stop",
                }]
            }),
        ]
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return responses.pop(0)

        config = LLMConfig(
            api_base="http://example.invalid/v1",
            model="fake",
            max_tokens=12,
            max_continuations=1,
        )
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            text = OpenAICompatibleClient(config).complete("system", "user")

        self.assertEqual(text, "앞부분이다.\n뒷부분이다.")
        self.assertEqual(len(requests), 2)
        self.assertIn("길이 제한", requests[1]["messages"][-1]["content"])


def _restore_env(key, value):
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
