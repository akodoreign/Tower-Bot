"""
src/agents/base.py — Base agent class for Pi/OpenClaw integration.

Provides the foundation for all Tower bot agents. Uses the OpenAI-compatible
API endpoint provided by Ollama's Pi integration.

Key differences from old direct Ollama calls:
    - Uses OpenAI-compatible API: http://localhost:11434/v1/chat/completions
    - Supports both local models (qwen) and cloud models (kimi-k2.5:cloud)
    - Structured response handling with AgentResponse dataclass
    - Built-in retry logic and error handling
    - Respects ollama_busy.py busy flag for graceful degradation
"""

from __future__ import annotations

import os
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
    CLOUD = "cloud"      # Cloud-hosted model (kimi-k2.5:cloud)


@dataclass
class AgentConfig:
    """Configuration for an agent instance."""
    model_name: str
    model_type: ModelType
    base_url: str = "http://localhost:11434/v1"
    timeout: float = 120.0
    max_retries: int = 2
    temperature: float = 0.7
    max_tokens: int = 4096
    
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
    ) -> AgentResponse:
        """
        Send a single prompt and get a response.
        
        Args:
            prompt: The user prompt to send
            context: Optional additional context to include in system prompt
            temperature: Override default temperature
            max_tokens: Override default max tokens
            strip_preamble: Whether to strip common AI preamble phrases
            
        Returns:
            AgentResponse with the model's response
        """
        from src.ollama_busy import is_available, get_busy_reason
        
        # Check busy flag
        if not is_available():
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
    ) -> AgentResponse:
        """
        Make the actual API call to the OpenAI-compatible endpoint.
        """
        client = await self._get_client()
        
        payload = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": False,
        }
        
        url = f"{self.config.base_url}/chat/completions"
        
        for attempt in range(self.config.max_retries + 1):
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                
                # Parse OpenAI-format response
                content = ""
                usage = {}
                
                if "choices" in data and len(data["choices"]) > 0:
                    choice = data["choices"][0]
                    message = choice.get("message", {})
                    content = message.get("content", "")
                elif "message" in data:
                    # Fallback for native Ollama format
                    content = data["message"].get("content", "")
                
                if "usage" in data:
                    usage = data["usage"]
                
                if strip_preamble:
                    content = self._strip_preamble(content)
                
                return AgentResponse(
                    content=content,
                    model=self.config.model_name,
                    success=True,
                    usage=usage,
                )
                
            except httpx.TimeoutException as e:
                logger.warning(f"🤖 Agent timeout (attempt {attempt + 1}): {e}")
                if attempt == self.config.max_retries:
                    return AgentResponse(
                        content="",
                        model=self.config.model_name,
                        success=False,
                        error=f"Timeout after {self.config.max_retries + 1} attempts",
                    )
            except httpx.HTTPStatusError as e:
                logger.error(f"🤖 Agent HTTP error: {e.response.status_code} - {e.response.text}")
                return AgentResponse(
                    content="",
                    model=self.config.model_name,
                    success=False,
                    error=f"HTTP {e.response.status_code}: {e.response.text}",
                )
            except Exception as e:
                logger.error(f"🤖 Agent error: {type(e).__name__}: {e}")
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
    model: str = "qwen",
    timeout: float = 90.0,
) -> str:
    """
    Quick one-off completion without creating an agent instance.
    Uses the native Ollama API for simplicity and backward compatibility.
    
    For repeated calls, prefer creating a QwenAgent or KimiAgent instance.
    """
    from src.ollama_busy import is_available
    
    if not is_available():
        return ""
    
    # Use OpenAI-compatible API
    url = "http://localhost:11434/v1/chat/completions"
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()
            
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"].strip()
            elif "message" in data:
                return data["message"].get("content", "").strip()
            return ""
    except Exception as e:
        logger.error(f"quick_complete error: {e}")
        return ""
