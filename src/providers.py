import os
import logging
import re
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import asyncio

from openai import AsyncOpenAI
import google.generativeai as genai
from anthropic import AsyncAnthropic
import aiohttp

logger = logging.getLogger(__name__)


class ProviderType(Enum):
    FREE = "free"
    OPENAI = "openai"
    CLAUDE = "claude"
    GEMINI = "gemini"
    GROK = "grok"


@dataclass
class ModelInfo:
    name: str
    provider: ProviderType
    description: str = ""
    supports_vision: bool = False
    supports_image_generation: bool = False


class BaseProvider(ABC):
    """Base class for all AI providers"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.models: List[ModelInfo] = []

    @abstractmethod
    async def chat_completion(
        self, messages: List[Dict[str, str]], model: str, **kwargs
    ) -> str:
        """Generate chat completion"""
        pass

    @abstractmethod
    async def generate_image(
        self, prompt: str, model: Optional[str] = None, **kwargs
    ) -> str:
        """Generate image from prompt"""
        pass

    @abstractmethod
    def get_available_models(self) -> List[ModelInfo]:
        """Get list of available models"""
        pass

    @abstractmethod
    def supports_image_generation(self) -> bool:
        """Check if provider supports image generation"""
        pass


class FreeProvider(BaseProvider):
    """
    Local provider using Ollama (mistral by default) as backend.

    This implements the BaseProvider interface so it can be used by
    the ProviderManager and the /provider command just like OpenAI, Claude, etc.
    It calls ONLY the local Ollama HTTP API at http://localhost:11434/api/chat.
    """

    def __init__(self):
        super().__init__(api_key=None)
        # Hard-lock to local mistral model
        self.default_model_name = "mistral"
        # If you ever want to allow changing the name via env var:
        # self.default_model_name = os.getenv("OLLAMA_MODEL", "mistral")

    async def _ollama_chat(
        self,
        messages: List[Dict[str, str]],
        model_name: Optional[str] = None,
        **kwargs,
    ) -> str:
        import httpx

        if model_name is None:
            model_name = self.default_model_name

        # NOTE: RAG context is injected upstream by aclient.handle_response().
        # Do NOT inject it again here — that would send the system prompt twice.

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "http://localhost:11434/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        content = None
        if isinstance(data, dict):
            msg = data.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
            elif "choices" in data:
                try:
                    content = data["choices"][0]["message"]["content"]
                except Exception:
                    content = None

        if not content:
            content = str(data)

        return content

    async def acreate(
        self,
        messages: List[Dict[str, str]],
        model_name: Optional[str] = None,
        **kwargs,
    ) -> str:
        # Convenience entrypoint (some older code may call this)
        return await self._ollama_chat(messages, model_name=model_name, **kwargs)

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Standard chat interface used by ProviderManager and Discord client.
        """
        return await self._ollama_chat(
            messages, model_name=model or self.default_model_name, **kwargs
        )

    async def generate_image(
        self, prompt: str, model: Optional[str] = None, **kwargs
    ) -> str:
        raise NotImplementedError(
            "FreeProvider (local Ollama) does not support image generation in this bot."
        )

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                name=self.default_model_name,
                provider=ProviderType.FREE,
                description="Local Ollama model (Tower Oracle with campaign_docs RAG)",
                supports_vision=False,
                supports_image_generation=False,
            )
        ]

    def supports_image_generation(self) -> bool:
        return False


class OpenAIProvider(BaseProvider):
    """Official OpenAI API provider"""

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = AsyncOpenAI(api_key=api_key)

    async def chat_completion(
        self, messages: List[Dict[str, str]], model: str, **kwargs
    ) -> str:
        try:
            if not model:
                model = "gpt-4o-mini"

            response = await self.client.chat.completions.create(
                model=model, messages=messages, **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI provider error: {e}")
            raise

    async def generate_image(
        self, prompt: str, model: Optional[str] = None, **kwargs
    ) -> str:
        try:
            response = await self.client.images.generate(
                model=model or "dall-e-3",
                prompt=prompt,
                size=kwargs.get("size", "1024x1024"),
                quality=kwargs.get("quality", "standard"),
                n=1,
            )
            return response.data[0].url
        except Exception as e:
            logger.error(f"OpenAI image generation error: {e}")
            raise

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                "gpt-4o",
                ProviderType.OPENAI,
                "Most capable GPT-4 model",
                supports_vision=True,
            ),
            ModelInfo(
                "gpt-4o-mini",
                ProviderType.OPENAI,
                "Affordable GPT-4 model",
                supports_vision=True,
            ),
            ModelInfo("o1", ProviderType.OPENAI, "Reasoning model"),
            ModelInfo("o1-mini", ProviderType.OPENAI, "Smaller reasoning model"),
            ModelInfo(
                "dall-e-3",
                ProviderType.OPENAI,
                "DALL-E 3 image generation",
                supports_image_generation=True,
            ),
            ModelInfo(
                "dall-e-2",
                ProviderType.OPENAI,
                "DALL-E 2 image generation",
                supports_image_generation=True,
            ),
        ]

    def supports_image_generation(self) -> bool:
        return True


class ClaudeProvider(BaseProvider):
    """Official Anthropic Claude API provider"""

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = AsyncAnthropic(api_key=api_key)

    async def chat_completion(
        self, messages: List[Dict[str, str]], model: str, **kwargs
    ) -> str:
        try:
            if not model:
                model = "claude-haiku-4-5"

            system_message = None
            claude_messages = []

            for msg in messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                else:
                    claude_messages.append(
                        {"role": msg["role"], "content": msg["content"]}
                    )

            response = await self.client.messages.create(
                model=model,
                messages=claude_messages,
                system=system_message,
                max_tokens=kwargs.get("max_tokens", 4096),
            )

            return response.content[0].text
        except Exception as e:
            logger.error(f"Claude provider error: {e}")
            raise

    async def generate_image(
        self, prompt: str, model: Optional[str] = None, **kwargs
    ) -> str:
        raise NotImplementedError("Claude does not support image generation")

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                "claude-sonnet-4-5",
                ProviderType.CLAUDE,
                "Claude 4.5 Sonnet — current flagship",
            ),
            ModelInfo(
                "claude-haiku-4-5",
                ProviderType.CLAUDE,
                "Claude 4.5 Haiku — fast and affordable",
            ),
            ModelInfo(
                "claude-opus-4-5",
                ProviderType.CLAUDE,
                "Claude 4.5 Opus — most powerful",
            ),
        ]

    def supports_image_generation(self) -> bool:
        return False


class GeminiProvider(BaseProvider):
    """Official Google Gemini API provider"""

    def __init__(self, api_key: str):
        super().__init__(api_key)
        genai.configure(api_key=api_key)

    async def chat_completion(
        self, messages: List[Dict[str, str]], model: str, **kwargs
    ) -> str:
        try:
            if not model:
                model = "gemini-2.0-flash-exp"

            gemini_model = genai.GenerativeModel(model)
            chat = gemini_model.start_chat(history=[])

            response = None
            for msg in messages:
                if msg["role"] == "user":
                    response = await asyncio.to_thread(
                        chat.send_message, msg["content"]
                    )
                elif msg["role"] == "assistant":
                    chat.history.append(
                        {"role": "model", "parts": [msg["content"]]}
                    )

            return response.text if response else ""
        except Exception as e:
            logger.error(f"Gemini provider error: {e}")
            raise

    async def generate_image(
        self, prompt: str, model: Optional[str] = None, **kwargs
    ) -> str:
        try:
            model_name = model or "imagen-3.0-generate-001"
            imagen = genai.ImageGenerationModel(model_name)

            response = await asyncio.to_thread(
                imagen.generate_images,
                prompt=prompt,
                number_of_images=1,
                aspect_ratio=kwargs.get("aspect_ratio", "1:1"),
            )

            return response.images[0]._image_bytes
        except Exception as e:
            logger.error(f"Gemini image generation error: {e}")
            raise

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                "gemini-2.0-flash-exp",
                ProviderType.GEMINI,
                "Latest experimental model",
                supports_vision=True,
            ),
            ModelInfo(
                "gemini-1.5-pro",
                ProviderType.GEMINI,
                "Advanced reasoning",
                supports_vision=True,
            ),
            ModelInfo(
                "gemini-1.5-flash",
                ProviderType.GEMINI,
                "Fast multimodal",
                supports_vision=True,
            ),
            ModelInfo(
                "imagen-3.0-generate-001",
                ProviderType.GEMINI,
                "Image generation",
                supports_image_generation=True,
            ),
        ]

    def supports_image_generation(self) -> bool:
        return True


class GrokProvider(BaseProvider):
    """xAI Grok API provider"""

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.api_key = api_key
        self.base_url = "https://api.x.ai/v1"

    async def chat_completion(
        self, messages: List[Dict[str, str]], model: str, **kwargs
    ) -> str:
        try:
            if not model:
                model = "grok-2-latest"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            data = {
                "model": model,
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 4096),
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=data,
                ) as response:
                    result = await response.json()

                    if response.status != 200:
                        raise Exception(f"Grok API error: {result}")

                    return result["choices"][0]["message"]["content"]

        except Exception as e:
            logger.error(f"Grok provider error: {e}")
            raise

    async def generate_image(
        self, prompt: str, model: Optional[str] = None, **kwargs
    ) -> str:
        raise NotImplementedError("Grok does not support image generation yet")

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                "grok-2-latest", ProviderType.GROK, "Latest Grok-2 model"
            ),
            ModelInfo(
                "grok-2-mini", ProviderType.GROK, "Smaller, faster Grok model"
            ),
        ]

    def supports_image_generation(self) -> bool:
        return False


class ProviderManager:
    """Manages all AI providers"""

    def __init__(self):
        self.providers: Dict[ProviderType, BaseProvider] = {}
        self.current_provider = ProviderType.FREE
        self._initialize_providers()

    def _validate_api_key(
        self, api_key: str, provider_name: str, pattern: Optional[str] = None
    ) -> bool:
        """Validate API key format"""
        if not api_key or len(api_key) < 10:
            logger.warning(
                f"Invalid {provider_name} API key: too short (length: {len(api_key)})"
            )
            return False

        if pattern and not re.match(pattern, api_key):
            logger.warning(
                f"API key format warning for {provider_name} (pattern: {pattern})"
            )
            logger.warning(
                f"Key format: {api_key[:15]}. (length: {len(api_key)})"
            )
            logger.info(
                f"Proceeding with {provider_name} despite format warning"
            )

        return True

    def _initialize_providers(self):
        """Initialize available providers based on API keys"""

        # Always add free provider (local Ollama)
        self.providers[ProviderType.FREE] = FreeProvider()
        logger.info("Initialized FREE provider (local Ollama)")

        # Optional: also init cloud providers if API keys are set in env.
        api_configs = [
            (
                "OPENAI_KEY",
                ProviderType.OPENAI,
                OpenAIProvider,
                r"^sk-[a-zA-Z0-9]{20,}$",
            ),
            (
                "CLAUDE_KEY",
                ProviderType.CLAUDE,
                ClaudeProvider,
                r"^sk-ant-[a-zA-Z0-9-]{50,}$",
            ),
            (
                "GEMINI_KEY",
                ProviderType.GEMINI,
                GeminiProvider,
                r"^[a-zA-Z0-9_-]{20,}$",
            ),
            (
                "GROK_KEY",
                ProviderType.GROK,
                GrokProvider,
                r"^xai-[a-zA-Z0-9-]{20,}$",
            ),
        ]

        for env_key, provider_type, provider_class, pattern in api_configs:
            api_key = os.getenv(env_key)
            if api_key:
                logger.info(
                    f"Found {env_key} with length {len(api_key)}, prefix: {api_key[:10]}."
                )
                if self._validate_api_key(
                    api_key, provider_type.value, pattern
                ):
                    try:
                        self.providers[provider_type] = provider_class(api_key)
                        logger.info(
                            f"✅ Successfully initialized {provider_type.value} provider"
                        )
                    except Exception as e:
                        logger.error(
                            f"❌ Failed to initialize {provider_type.value}: {e}"
                        )
                else:
                    logger.warning(
                        f"❌ Skipping {provider_type.value} due to invalid API key format"
                    )
            else:
                logger.debug(
                    f"No {env_key} provided - {provider_type.value} provider disabled"
                )

    def get_provider(
        self, provider_type: Optional[ProviderType] = None
    ) -> BaseProvider:
        """Get specific provider or current provider"""
        if provider_type:
            if provider_type not in self.providers:
                raise ValueError(
                    f"Provider {provider_type.value} not available"
                )
            return self.providers[provider_type]
        return self.providers[self.current_provider]

    def set_current_provider(self, provider_type: ProviderType):
        """Set current provider"""
        if provider_type not in self.providers:
            raise ValueError(
                f"Provider {provider_type.value} not available"
            )
        self.current_provider = provider_type

    def get_available_providers(self) -> List[ProviderType]:
        """Get list of available providers"""
        return list(self.providers.keys())

    def get_all_models(self) -> Dict[ProviderType, List[ModelInfo]]:
        """Get all models from all providers"""
        result: Dict[ProviderType, List[ModelInfo]] = {}
        for provider_type, provider in self.providers.items():
            result[provider_type] = provider.get_available_models()
        return result

    def get_provider_models(
        self, provider_type: ProviderType
    ) -> List[ModelInfo]:
        """Get models for specific provider"""
        if provider_type not in self.providers:
            return []
        return self.providers[provider_type].get_available_models()
