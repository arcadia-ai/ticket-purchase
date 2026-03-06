"""Smart element detection: u2 native selectors + optional LLM fallback (Ollama / DeepSeek)."""
import json
import os

import uiautomator2 as u2
from loguru import logger

# LLM prompt template for element detection
_LLM_PROMPT = """Analyze this Android UI XML and find the best locator for: "{desc}"

Prioritize:
1. resourceId (most stable)
2. text or textContains
3. className with index

Output ONLY valid JSON:
{{"strategy": "resourceId"|"text"|"textContains"|"className", "value": "the value", "confidence": 0.0-1.0}}

If not found: {{"strategy": "NOT_FOUND", "value": "", "confidence": 0}}

XML:
{xml}"""


class LLMClient:
    """Unified LLM client supporting Ollama and DeepSeek (OpenAI-compatible) backends."""

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "").lower()  # "ollama" or "deepseek"
        self._client = None
        self._model = None

        if not self.provider:
            return

        if self.provider == "ollama":
            self._init_ollama()
        elif self.provider == "deepseek":
            self._init_deepseek()
        else:
            logger.warning("Unknown LLM_PROVIDER '{}', disabling LLM", self.provider)
            self.provider = ""

    def _init_ollama(self):
        try:
            import ollama
            host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            self._client = ollama.Client(host=host)
            self._model = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-cloud")
            logger.info("LLM: Ollama (host={}, model={})", host, self._model)
        except ImportError:
            logger.warning("ollama package not installed: pip install ollama")
            self.provider = ""
        except Exception as e:
            logger.warning("Ollama init failed: {}", e)
            self.provider = ""

    def _init_deepseek(self):
        try:
            from openai import OpenAI
            api_key = os.getenv("DEEPSEEK_API_KEY", "")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            if not api_key:
                logger.warning("DEEPSEEK_API_KEY not set, disabling LLM")
                self.provider = ""
                return
            self._client = OpenAI(api_key=api_key, base_url=base_url)
            self._model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            logger.info("LLM: DeepSeek (model={})", self._model)
        except ImportError:
            logger.warning("openai package not installed: pip install openai")
            self.provider = ""
        except Exception as e:
            logger.warning("DeepSeek init failed: {}", e)
            self.provider = ""

    @property
    def enabled(self) -> bool:
        return bool(self.provider and self._client)

    def chat(self, prompt: str) -> str | None:
        """Send prompt to LLM and return response text."""
        if not self.enabled:
            return None
        try:
            if self.provider == "ollama":
                resp = self._client.chat(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp["message"]["content"]
            elif self.provider == "deepseek":
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                )
                return resp.choices[0].message.content
        except Exception as e:
            logger.debug("LLM call failed: {}", e)
        return None


class Detector:
    """Unified element finder with multiple strategies."""

    def __init__(self, device: u2.Device):
        self.device = device
        self._llm = LLMClient()

    def find(self, desc: str, timeout: float = 3.0, **kwargs) -> u2.UiObject | None:
        """Find a single UI element using multiple strategies.

        Args:
            desc: Human-readable description (for logging and LLM)
            timeout: Max wait time in seconds
            **kwargs: u2 selector kwargs (resourceId, text, textContains, className, etc.)

        Returns:
            UiObject if found, None otherwise.
        """
        # Strategy 1: LLM priority (when enabled)
        if self._llm.enabled:
            element = self._find_with_llm(desc, timeout)
            if element:
                return element

        # Strategy 2: u2 native selectors (fallback)
        if kwargs:
            element = self.device(**kwargs)
            if element.wait(timeout=timeout):
                logger.debug("Found '{}' via native selector: {}", desc, kwargs)
                return element

        logger.warning("Element not found: '{}'", desc)
        return None

    def find_all(self, desc: str, **kwargs) -> list:
        """Find all matching UI elements."""
        if not kwargs:
            return []

        elements = self.device(**kwargs)
        count = elements.count
        if count > 0:
            logger.debug("Found {} elements for '{}': {}", count, desc, kwargs)
            return [elements[i] for i in range(count)]

        logger.warning("No elements found for '{}'", desc)
        return []

    def exists(self, timeout: float = 1.0, **kwargs) -> bool:
        """Check if an element exists without full wait."""
        return bool(self.device(**kwargs).wait(timeout=timeout))

    def _find_with_llm(self, desc: str, timeout: float = 5.0) -> u2.UiObject | None:
        """Use LLM to analyze page XML and find element."""
        try:
            xml = self.device.dump_hierarchy()[:15000]
            prompt = _LLM_PROMPT.format(desc=desc, xml=xml)

            response_text = self._llm.chat(prompt)
            if not response_text:
                logger.debug("LLM returned empty response for '{}'", desc)
                return None

            logger.debug("LLM raw response for '{}': {}", desc, response_text[:500])

            # Extract JSON from response (handle markdown code blocks)
            json_str = response_text.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            result = json.loads(json_str)

            if result["strategy"] == "NOT_FOUND" or result.get("confidence", 0) < 0.3:
                logger.debug("LLM couldn't find '{}' (confidence: {})", desc, result.get("confidence", 0))
                return None

            # Map strategy to u2 selector
            strategy = result["strategy"]
            value = result["value"]
            selector = {strategy: value}

            element = self.device(**selector)
            if element.wait(timeout=timeout):
                logger.info("LLM found '{}' via {}='{}' (confidence: {:.2f})",
                           desc, strategy, value, result["confidence"])
                return element

            logger.debug("LLM locator didn't match actual UI for '{}'", desc)
        except json.JSONDecodeError as e:
            logger.debug("LLM JSON parse failed: {}", e)
        except Exception as e:
            logger.debug("LLM query failed for '{}': {}", desc, e)

        return None
