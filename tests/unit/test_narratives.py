"""Unit tests for narrative briefing generation."""

import json
import time
import pytest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from trendscope.narratives import (
    NarrativeGenerator,
    EXECUTIVE_PROMPTS,
    DEFAULT_PROMPT,
)


SAMPLE_REPORT = {
    "executive": "CMO",
    "focus": "Marketing & Growth",
    "key_trends": [{"name": "AI Tools", "score": 85}],
}


# =============================================================================
# NarrativeGenerator init
# =============================================================================


class TestNarrativeGeneratorInit:

    def test_init_sets_defaults(self):
        gen = NarrativeGenerator()
        assert gen.ollama_host == "http://localhost:11434"
        assert gen.ollama_model == "qwen2.5:7b"
        assert gen.cache_ttl == 3600
        assert gen._cache == {}

    def test_custom_host_and_model(self):
        gen = NarrativeGenerator(ollama_host="http://custom:1234", ollama_model="llama3:8b")
        assert gen.ollama_host == "http://custom:1234"
        assert gen.ollama_model == "llama3:8b"


# =============================================================================
# generate_briefing
# =============================================================================


class TestGenerateBriefing:

    @pytest.fixture
    def gen(self):
        return NarrativeGenerator()

    def test_calls_ollama_with_correct_executive_prompt(self, gen):
        with patch.object(gen, "_call_ollama", return_value="briefing text") as mock_call:
            gen.generate_briefing("CMO", SAMPLE_REPORT)
            args = mock_call.call_args[0]
            assert args[0] == EXECUTIVE_PROMPTS["CMO"]

    def test_uses_cmo_prompt_for_cmo(self, gen):
        with patch.object(gen, "_call_ollama", return_value="ok") as mock_call:
            gen.generate_briefing("CMO", SAMPLE_REPORT)
            assert EXECUTIVE_PROMPTS["CMO"] in mock_call.call_args[0][0]

    def test_uses_ceo_prompt_for_ceo(self, gen):
        with patch.object(gen, "_call_ollama", return_value="ok") as mock_call:
            gen.generate_briefing("CEO", SAMPLE_REPORT)
            assert EXECUTIVE_PROMPTS["CEO"] in mock_call.call_args[0][0]

    def test_uses_cpo_prompt_for_cpo(self, gen):
        with patch.object(gen, "_call_ollama", return_value="ok") as mock_call:
            gen.generate_briefing("CPO", SAMPLE_REPORT)
            assert EXECUTIVE_PROMPTS["CPO"] in mock_call.call_args[0][0]

    def test_uses_cro_prompt_for_cro(self, gen):
        with patch.object(gen, "_call_ollama", return_value="ok") as mock_call:
            gen.generate_briefing("CRO", SAMPLE_REPORT)
            assert EXECUTIVE_PROMPTS["CRO"] in mock_call.call_args[0][0]

    def test_uses_default_prompt_for_unknown_code(self, gen):
        with patch.object(gen, "_call_ollama", return_value="ok") as mock_call:
            gen.generate_briefing("UNKNOWN", SAMPLE_REPORT)
            assert DEFAULT_PROMPT in mock_call.call_args[0][0]

    def test_returns_none_when_ollama_unavailable(self, gen):
        with patch.object(gen, "_call_ollama", return_value=None):
            result = gen.generate_briefing("CMO", SAMPLE_REPORT)
            assert result is None

    def test_returns_cached_result_within_ttl(self, gen):
        with patch.object(gen, "_call_ollama", return_value="cached text") as mock_call:
            # First call populates cache
            result1 = gen.generate_briefing("CMO", SAMPLE_REPORT)
            assert result1 == "cached text"

            # Second call should use cache, not call Ollama again
            result2 = gen.generate_briefing("CMO", SAMPLE_REPORT)
            assert result2 == "cached text"
            assert mock_call.call_count == 1

    def test_refreshes_cache_after_ttl_expires(self, gen):
        gen.cache_ttl = 0  # Expire immediately
        with patch.object(gen, "_call_ollama", return_value="fresh text") as mock_call:
            gen.generate_briefing("CMO", SAMPLE_REPORT)
            # Wait for TTL to expire (it's 0 so immediate)
            gen.generate_briefing("CMO", SAMPLE_REPORT)
            assert mock_call.call_count == 2

    def test_different_data_produces_different_cache_keys(self, gen):
        data_a = {"key": "value_a"}
        data_b = {"key": "value_b"}
        with patch.object(gen, "_call_ollama", return_value="response") as mock_call:
            gen.generate_briefing("CMO", data_a)
            gen.generate_briefing("CMO", data_b)
            # Should call Ollama twice since data differs
            assert mock_call.call_count == 2


# =============================================================================
# _call_ollama
# =============================================================================


class TestCallOllama:

    @pytest.fixture
    def gen(self):
        return NarrativeGenerator()

    def test_successful_call_returns_content(self, gen):
        response_data = json.dumps({
            "message": {"role": "assistant", "content": "The market is bullish."},
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("trendscope.narratives.urlopen", return_value=mock_resp):
            result = gen._call_ollama("system", "user")
            assert result == "The market is bullish."

    def test_returns_none_on_urlerror(self, gen):
        with patch("trendscope.narratives.urlopen", side_effect=URLError("connection refused")):
            result = gen._call_ollama("system", "user")
            assert result is None

    def test_returns_none_on_timeout(self, gen):
        with patch("trendscope.narratives.urlopen", side_effect=OSError("timed out")):
            result = gen._call_ollama("system", "user")
            assert result is None

    def test_returns_none_on_invalid_json_response(self, gen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("trendscope.narratives.urlopen", return_value=mock_resp):
            result = gen._call_ollama("system", "user")
            assert result is None

    def test_handles_empty_message_content(self, gen):
        response_data = json.dumps({
            "message": {"role": "assistant", "content": ""},
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("trendscope.narratives.urlopen", return_value=mock_resp):
            result = gen._call_ollama("system", "user")
            assert result == ""


# =============================================================================
# _hash_data
# =============================================================================


class TestHashData:

    def test_same_data_produces_same_hash(self):
        gen = NarrativeGenerator()
        h1 = gen._hash_data({"a": 1, "b": 2})
        h2 = gen._hash_data({"a": 1, "b": 2})
        assert h1 == h2

    def test_different_data_produces_different_hash(self):
        gen = NarrativeGenerator()
        h1 = gen._hash_data({"a": 1})
        h2 = gen._hash_data({"a": 2})
        assert h1 != h2


# =============================================================================
# clear_cache
# =============================================================================


class TestClearCache:

    def test_empties_the_cache(self):
        gen = NarrativeGenerator()
        gen._cache[("CMO", "abc")] = ("text", time.time())
        assert len(gen._cache) == 1
        gen.clear_cache()
        assert len(gen._cache) == 0
