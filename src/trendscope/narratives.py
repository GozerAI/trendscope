"""LLM-driven narrative briefings for executive reports."""

import hashlib
import json
import logging
import os
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# Per-executive system prompts
EXECUTIVE_PROMPTS = {
    "CMO": (
        "You are a Chief Marketing Officer. Analyze these trends from a marketing "
        "perspective. Focus on brand opportunities, content marketing angles, social "
        "media implications, and audience engagement strategies. Be concise and actionable."
    ),
    "CEO": (
        "You are a Chief Executive Officer. Provide a strategic overview of these trends. "
        "Focus on market positioning, competitive threats, growth opportunities, and "
        "strategic recommendations. Be direct and business-focused."
    ),
    "CPO": (
        "You are a Chief Product Officer. Analyze these trends from a product development "
        "perspective. Focus on feature opportunities, technical feasibility, user experience "
        "implications, and product-market fit. Be specific and technical."
    ),
    "CRO": (
        "You are a Chief Revenue Officer. Analyze these trends from a revenue perspective. "
        "Focus on monetization opportunities, pricing signals, market demand, and commercial "
        "viability. Be data-driven and revenue-focused."
    ),
}

DEFAULT_PROMPT = (
    "You are a business analyst. Provide a concise analysis of these trends, "
    "focusing on key insights and recommended actions."
)


class NarrativeGenerator:
    """Generates natural-language briefings via Nexus gateway (preferred) or Ollama (fallback)."""

    def __init__(
        self,
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:7b",
        nexus_url=None,
    ):
        self.ollama_host = ollama_host
        self.ollama_model = ollama_model
        self.nexus_url = (nexus_url or os.environ.get("NEXUS_BASE_URL", "")).rstrip("/")
        self._cache = {}  # key: (executive_code, data_hash) -> (narrative, timestamp)
        self.cache_ttl = 3600  # 1 hour
        self._nexus_failures = 0

    def generate_briefing(self, executive_code, report_data):
        """Generate a narrative briefing for an executive report.

        Args:
            executive_code: Executive code (CEO, CMO, CPO, CRO)
            report_data: Dict with report data to narrativize

        Returns:
            str or None: The narrative text, or None if Ollama unavailable.
        """
        # Check cache
        data_hash = self._hash_data(report_data)
        cache_key = (executive_code, data_hash)
        cached = self._cache.get(cache_key)
        if cached:
            narrative, timestamp = cached
            if time.time() - timestamp < self.cache_ttl:
                return narrative

        # Build prompt
        system_prompt = EXECUTIVE_PROMPTS.get(executive_code.upper(), DEFAULT_PROMPT)
        user_content = (
            f"Here is the latest trend report data:\n\n"
            f"{json.dumps(report_data, indent=2, default=str)}\n\n"
            f"Provide a concise executive briefing based on this data."
        )

        # Try Nexus gateway first (multi-provider, cost-tracked)
        narrative = None
        if self.nexus_url and self._nexus_failures < 3:
            narrative = self._call_nexus(system_prompt, user_content)
            if narrative:
                self._nexus_failures = 0
            else:
                self._nexus_failures += 1

        # Fall back to direct Ollama
        if narrative is None:
            narrative = self._call_ollama(system_prompt, user_content)

        # Cache result (even None to avoid hammering a down Ollama)
        if narrative is not None:
            self._cache[cache_key] = (narrative, time.time())

        return narrative

    def _call_nexus(self, system_prompt, user_content):
        """Call Nexus LLM gateway. Returns response text or None on failure."""
        try:
            url = f"{self.nexus_url}/api/generate"
            body = json.dumps({
                "prompt": user_content,
                "system_prompt": system_prompt,
                "max_tokens": 2000,
                "source": "trendscope",
            }).encode("utf-8")

            req = Request(url, data=body, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data.get("content", "")
                if content:
                    logger.debug(
                        "Nexus LLM: model=%s latency=%.0fms",
                        data.get("model", "?"), data.get("latency_ms", 0),
                    )
                    return content
        except Exception as e:
            logger.debug("Nexus gateway unavailable: %s", e)
        return None

    def _call_ollama(self, system_prompt, user_content):
        """Call Ollama chat API. Returns response text or None on failure."""
        try:
            url = f"{self.ollama_host}/api/chat"
            body = json.dumps({
                "model": self.ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "stream": False,
            }).encode("utf-8")

            req = Request(url, data=body, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("message", {}).get("content", "")
        except (URLError, json.JSONDecodeError, OSError) as e:
            logger.warning(f"Ollama narrative generation failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error in narrative generation: {e}")
            return None

    def _hash_data(self, data):
        """Create a simple hash of report data for cache key."""
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.md5(serialized.encode()).hexdigest()

    def clear_cache(self):
        """Clear the narrative cache."""
        self._cache.clear()
