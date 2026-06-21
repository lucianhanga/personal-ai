"""OpenAI-compatible ModelProvider + Transcriber adapters for PersonalAI (remote)."""

from personalai_provider_openai.provider import DEFAULT_BASE_URL, OpenAICompatProvider
from personalai_provider_openai.transcribe import OpenAICompatTranscriber

__all__ = ["DEFAULT_BASE_URL", "OpenAICompatProvider", "OpenAICompatTranscriber"]
