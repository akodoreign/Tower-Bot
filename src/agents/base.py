"""
src/agents/base.py — Base agent class for Pi/OpenClaw integration.

Provides the foundation for all Tower bot agents. Uses the OpenAI-compatible
API endpoint provided by Ollama's Pi integration.

Key differences from old direct Ollama calls:
    - Uses OpenAI-compatible API: http://localhost:11434/v1/chat/completions
    - Supports the configured local Qwen model through Ollama
    - Structured response handling with AgentResponse dataclass
    - Built-in retry logic and error handling
    - Respects ollama_busy.py busy flag for graceful degradation
"""

from __future__ import annotations

import os
import re
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class ModelType(Enum):
    """Types of models available in the Pi/OpenClaw stack."""
    LOCAL = "local"      # Runs entirely on local hardware (qwen)
    CLOUD = "cloud"      # Reserved for optional cloud-hosted models


@dataclass
class AgentConfig:
    """Configuration for an agent instance."""
    model_name: str
    model_type: ModelType
    base_url: str = "http://localhost:11434"
    timeout: float = 120.0
    max_retries: int = 2
    temperature: float = 0.7
    max_tokens: int = 4096
    ollama_track: str = "primary"
    
    # Subagent configuration (for kimi)
    enable_subagents: bool = False
    max_concurrent_subagents: int = 4
    
    # Pi-specific options
    pi_workspace: Optional[str] = None
    pi_tools_enabled: bool = False


@dataclass
class AgentResponse:
    """Structured response from an agent call."""
    content: str
    model: str
    success: bool = True
    error: Optional[str] = None
    usage: Dict[str, int] = field(default_factory=dict)
    subagent_results: List[Dict] = field(default_factory=list)
    
    @property
    def text(self) -> str:
        """Alias for content, for compatibility with existing code."""
        return self.content


class BaseAgent(ABC):
    """
    Abstract base class for all Tower bot agents.
    
    Subclasses must implement:
        - _get_config(): Return AgentConfig with model-specific settings
        - _build_system_prompt(): Return the system prompt for this agent type
    
    Provides:
        - complete(): Send a prompt and get a response
        - chat(): Multi-turn conversation support
        - _strip_preamble(): Clean AI response of common prefixes
    """
    
    def __init__(self):
        self.config = self._get_config()
        self._client: Optional[httpx.AsyncClient] = None
    
    @abstractmethod
    def _get_config(self) -> AgentConfig:
        """Return the configuration for this agent type."""
        pass
    
    @abstractmethod
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        """Build the system prompt for this agent type."""
        pass
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    def _strip_preamble(self, text: str) -> str:
        """
        Strip common AI preamble phrases from the response.
        Same logic as existing Tower bot code for consistency.
        """
        lines = text.splitlines()
        skip_prefixes = (
            "sure", "here's", "here is", "certainly", 
            "of course", "below is", "great question",
            "i'd be happy to", "absolutely", "let me"
        )
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip_prefixes):
            lines.pop(0)
        return "\n".join(lines).strip()
    
    async def complete(
        self,
        prompt: str,
        context: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        strip_preamble: bool = True,
        force: bool = False,
    ) -> AgentResponse:
        """
        Send a single prompt and get a response.
        
        Args:
            prompt: The user prompt to send
            context: Optional additional context to include in system prompt
            temperature: Override default temperature
            max_tokens: Override default max tokens
            strip_preamble: Whether to strip common AI preamble phrases
            force: If True, bypass the busy check (for internal compilation use)
            
        Returns:
            AgentResponse with the model's response
        """
        from src.ollama_busy import is_available, get_busy_reason
        
        # Check busy flag (skip if force=True, e.g., when called from mission_compiler)
        if not force and not is_available():
            reason = get_busy_reason()
            logger.info(f"🤖 Agent {self.__class__.__name__} skipping — Ollama busy ({reason})")
            return AgentResponse(
                content="",
                model=self.config.model_name,
                success=False,
                error=f"Ollama busy: {reason}"
            )
        
        messages = [
            {"role": "system", "content": self._build_system_prompt(context)},
            {"role": "user", "content": prompt},
        ]
        
        return await self._call_api(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            strip_preamble=strip_preamble,
            force=force,
        )
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        context: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        strip_preamble: bool = True,
    ) -> AgentResponse:
        """
        Send a multi-turn conversation and get a response.
        
        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."} dicts
            context: Optional additional context to include in system prompt
            temperature: Override default temperature
            max_tokens: Override default max tokens
            strip_preamble: Whether to strip common AI preamble phrases
            
        Returns:
            AgentResponse with the model's response
        """
        from src.ollama_busy import is_available, get_busy_reason
        
        if not is_available():
            reason = get_busy_reason()
            logger.info(f"🤖 Agent {self.__class__.__name__} skipping — Ollama busy ({reason})")
            return AgentResponse(
                content="",
                model=self.config.model_name,
                success=False,
                error=f"Ollama busy: {reason}"
            )
        
        # Prepend system prompt
        full_messages = [
            {"role": "system", "content": self._build_system_prompt(context)},
            *messages,
        ]
        
        return await self._call_api(
            messages=full_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            strip_preamble=strip_preamble,
        )
    
    async def _call_api(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        strip_preamble: bool = True,
        force: bool = False,
    ) -> AgentResponse:
        """
        Make the actual API call to the OpenAI-compatible endpoint.

        Args:
            force: If True, bypass the busy check (use when the caller already
                   holds the busy flag itself, e.g. inside a mission pipeline).
        """
        client = await self._get_client()

        num_ctx  = int(os.getenv("OLLAMA_AGENT_CTX", os.getenv("OLLAMA_NUM_CTX", "8192")))
        num_pred = max_tokens or self.config.max_tokens
        think_enabled = os.getenv("OLLAMA_AGENT_THINK", "false").lower() in ("1", "true", "yes", "on")
        options = {
            "temperature": temperature or self.config.temperature,
            "num_predict": num_pred,
            "num_ctx": num_ctx,
            "think": think_enabled,
        }
        # Only override num_gpu if explicitly set to non-zero — otherwise let Modelfile control it
        _num_gpu = int(os.getenv("OLLAMA_NUM_GPU", "0"))
        if _num_gpu > 0:
            options["num_gpu"] = _num_gpu

        payload = {
            "model": self.config.model_name,
            "messages": messages,
            "stream": False,
            "options": options,
        }

        url = f"{self.config.base_url.rstrip('/')}/api/chat"

        from src.ollama_queue import _lock as _ollama_lock
        from src.ollama_busy import is_available, get_busy_reason

        agent_name = self.__class__.__name__
        prompt_words = sum(len(m.get("content", "").split()) for m in messages)
        logger.info(
            f"🤖 [{agent_name}] → {self.config.model_name} | "
            f"ctx={num_ctx} predict={num_pred} | "
            f"prompt={prompt_words}w | timeout={self.config.timeout}s"
        )

        for attempt in range(self.config.max_retries + 1):
            try:
                if not force and not is_available():
                    logger.info(f"🔀 [{agent_name}] skipping — busy: {get_busy_reason()}")
                    return AgentResponse(content="", model=self.config.model_name, success=False,
                                         error="Ollama busy")
                if not force:
                    from src.resource_cop import wait_for_ollama_turn

                    decision = await wait_for_ollama_turn(
                        f"agent:{agent_name}",
                        track=self.config.ollama_track,
                        max_wait_seconds=60,
                    )
                    if not decision.run_now:
                        logger.info(f"[{agent_name}] skipping - dispatcher busy: {decision.reason}")
                        return AgentResponse(
                            content="",
                            model=self.config.model_name,
                            success=False,
                            error=f"Ollama busy: {decision.reason}",
                        )
                if attempt > 0:
                    logger.info(f"🤖 [{agent_name}] retry {attempt}/{self.config.max_retries} ...")
                logger.info(f"🤖 [{agent_name}] → sending to {url} (waiting for response...)")
                _t0 = time.monotonic()
                async with _ollama_lock:
                    resp = await client.post(url, json=payload)
                _elapsed = time.monotonic() - _t0
                resp.raise_for_status()
                data = resp.json()
                logger.info(f"🤖 [{agent_name}] ← response received in {_elapsed:.1f}s")

                # Parse native Ollama /api/chat response
                content = ""
                usage = {}

                if "message" in data:
                    content = data["message"].get("content", "")
                elif "choices" in data and data["choices"]:
                    content = data["choices"][0].get("message", {}).get("content", "")

                if data.get("eval_count") or data.get("prompt_eval_count"):
                    usage = {
                        "completion_tokens": data.get("eval_count", 0),
                        "prompt_tokens": data.get("prompt_eval_count", 0),
                        "total_tokens": data.get("eval_count", 0) + data.get("prompt_eval_count", 0),
                    }

                # Strip qwen3 thinking blocks unconditionally
                raw_len = len(content)
                _think_matches = re.findall(r"<think>(.*?)</think>", content, flags=re.DOTALL)
                _think_chars = sum(len(t) for t in _think_matches)
                if _think_chars:
                    logger.info(f"🤖 [{agent_name}] thinking block: {_think_chars} chars")
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                if strip_preamble:
                    content = self._strip_preamble(content)

                resp_words = len(content.split())
                resp_chars = len(content)
                tok_in  = usage.get("prompt_tokens", 0)
                tok_out = usage.get("completion_tokens", 0)
                logger.info(
                    f"🤖 [{agent_name}] ✓ {resp_words}w / {resp_chars} chars generated | "
                    f"tokens in={tok_in} out={tok_out} | "
                    f"raw={raw_len}ch | elapsed={_elapsed:.1f}s"
                )
                # Log first 120 chars of response as preview
                preview = content[:120].replace("\n", " ")
                logger.info(f"🤖 [{agent_name}] preview: {preview!r}")

                return AgentResponse(
                    content=content,
                    model=self.config.model_name,
                    success=True,
                    usage=usage,
                )

            except httpx.TimeoutException as e:
                logger.warning(f"🤖 [{agent_name}] TIMEOUT attempt {attempt + 1} after {self.config.timeout}s")
                if attempt == self.config.max_retries:
                    return AgentResponse(
                        content="",
                        model=self.config.model_name,
                        success=False,
                        error=f"Timeout after {self.config.max_retries + 1} attempts",
                    )
                # Before burning another full timeout, give Ollama 30s to settle then do a
                # quick cop check. If the queue is still occupied, abort rather than retry.
                import asyncio as _asyncio
                logger.info(f"🤖 [{agent_name}] sleeping 30s after timeout before retry check ...")
                await _asyncio.sleep(30)
                from src.resource_cop import ask_ollama as _ask_ollama
                _cop = await _ask_ollama(f"agent:{agent_name}:retry", track=self.config.ollama_track)
                if not _cop.run_now:
                    logger.info(
                        f"🤖 [{agent_name}] aborting remaining retries — Ollama still busy: {_cop.reason}"
                    )
                    return AgentResponse(
                        content="",
                        model=self.config.model_name,
                        success=False,
                        error=f"Timeout + Ollama busy on retry check: {_cop.reason}",
                    )
            except httpx.HTTPStatusError as e:
                logger.error(f"🤖 [{agent_name}] HTTP {e.response.status_code}: {e.response.text[:200]}")
                return AgentResponse(
                    content="",
                    model=self.config.model_name,
                    success=False,
                    error=f"HTTP {e.response.status_code}: {e.response.text}",
                )
            except Exception as e:
                logger.error(f"🤖 [{agent_name}] error: {type(e).__name__}: {e}")
                return AgentResponse(
                    content="",
                    model=self.config.model_name,
                    success=False,
                    error=f"{type(e).__name__}: {e}",
                )
        
        # Should never reach here, but just in case
        return AgentResponse(
            content="",
            model=self.config.model_name,
            success=False,
            error="Unknown error",
        )


# ---------------------------------------------------------------------------
# Convenience function for quick one-off completions
# ---------------------------------------------------------------------------

async def quick_complete(
    prompt: str,
    model: str = "qwen3-8b-slim:latest",
    timeout: float = 90.0,
) -> str:
    """
    Quick one-off completion without creating an agent instance.
    Uses the native Ollama API for simplicity and backward compatibility.
    
    For repeated calls, prefer creating a QwenAgent or KimiAgent instance.
    """
    from src.ollama_busy import is_available, get_busy_reason
    if not is_available():
        logger.info(f"🔀 quick_complete skipping — busy: {get_busy_reason()}")
        return ""

    from src.resource_cop import wait_for_ollama_turn
    decision = await wait_for_ollama_turn("agent:quick_complete", track="quick", max_wait_seconds=45)
    if not decision.run_now:
        logger.info(f"quick_complete skipping - dispatcher busy: {decision.reason}")
        return ""

    url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    num_gpu = int(os.getenv("OLLAMA_NUM_GPU", "0"))
    num_ctx = int(os.getenv("OLLAMA_AGENT_CTX", os.getenv("OLLAMA_NUM_CTX", "12288")))

    try:
        from src.ollama_queue import _lock as _ollama_lock
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with _ollama_lock:
                resp = await client.post(url, json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_gpu": num_gpu, "num_ctx": num_ctx},
                })
            resp.raise_for_status()
            data = resp.json()
            if "message" in data:
                return data["message"].get("content", "").strip()
            elif "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"].strip()
            return ""
    except Exception as e:
        logger.error(f"quick_complete error: {e}")
        return ""
