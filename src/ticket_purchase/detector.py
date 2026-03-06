"""Smart element detection: u2 native selectors + optional Ollama LLM fallback."""
import json
import os

import uiautomator2 as u2
from loguru import logger


class Detector:
    """Unified element finder with multiple strategies."""

    def __init__(self, device: u2.Device):
        self.device = device
        self._ollama_client = None
        self._ollama_enabled = os.getenv("OLLAMA_ENABLED", "false").lower() == "true"

        if self._ollama_enabled:
            self._init_ollama()

    def _init_ollama(self):
        """Initialize Ollama client if enabled."""
        try:
            import ollama
            host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            self._ollama_client = ollama.Client(host=host)
            self._ollama_model = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-cloud")
            logger.info("Ollama initialized: host={}, model={}", host, self._ollama_model)
        except ImportError:
            logger.warning("Ollama package not installed, disabling LLM fallback")
            self._ollama_enabled = False
        except Exception as e:
            logger.warning("Ollama init failed: {}, disabling", e)
            self._ollama_enabled = False

    def find(self, desc: str, timeout: float = 3.0, **kwargs) -> u2.UiObject | None:
        """Find a single UI element using multiple strategies.

        Args:
            desc: Human-readable description (for logging and Ollama)
            timeout: Max wait time in seconds
            **kwargs: u2 selector kwargs. Supports nested strategies:
                - resourceId, text, textContains, className, description, etc.
                - If multiple kwargs, they are combined as AND conditions.

        Returns:
            UiObject if found, None otherwise.
        """
        # Strategy 1: u2 native selectors
        if kwargs:
            element = self.device(**kwargs)
            if element.wait(timeout=timeout):
                logger.debug("Found '{}' via native selector: {}", desc, kwargs)
                return element

        # Strategy 2: Ollama LLM fallback
        if self._ollama_enabled and self._ollama_client:
            element = self._find_with_ollama(desc, timeout)
            if element:
                return element

        logger.warning("Element not found: '{}'", desc)
        return None

    def find_all(self, desc: str, **kwargs) -> list:
        """Find all matching UI elements.

        Returns list of UiObject elements.
        """
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

    def _find_with_ollama(self, desc: str, timeout: float = 5.0) -> u2.UiObject | None:
        """Use Ollama LLM to analyze page XML and find element."""
        try:
            xml = self.device.dump_hierarchy()[:15000]
            prompt = f"""Analyze this Android UI XML and find the best locator for: "{desc}"

Prioritize:
1. resourceId (most stable)
2. text or textContains
3. className with index

Output ONLY valid JSON:
{{"strategy": "resourceId"|"text"|"textContains"|"className", "value": "the value", "confidence": 0.0-1.0}}

If not found: {{"strategy": "NOT_FOUND", "value": "", "confidence": 0}}

XML:
{xml}"""

            response = self._ollama_client.chat(
                model=self._ollama_model,
                messages=[{"role": "user", "content": prompt}],
            )
            result = json.loads(response["message"]["content"])

            if result["strategy"] == "NOT_FOUND" or result["confidence"] < 0.3:
                logger.debug("Ollama couldn't find '{}' (confidence: {})", desc, result.get("confidence", 0))
                return None

            # Map strategy to u2 selector
            strategy = result["strategy"]
            value = result["value"]
            selector = {strategy: value}

            element = self.device(**selector)
            if element.wait(timeout=timeout):
                logger.info("Ollama found '{}' via {}='{}' (confidence: {:.2f})",
                           desc, strategy, value, result["confidence"])
                return element

            logger.debug("Ollama locator didn't match actual UI for '{}'", desc)
        except json.JSONDecodeError as e:
            logger.debug("Ollama JSON parse failed: {}", e)
        except Exception as e:
            logger.debug("Ollama query failed for '{}': {}", desc, e)

        return None
