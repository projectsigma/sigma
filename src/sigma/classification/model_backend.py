from __future__ import annotations

import os
from abc import ABC, abstractmethod

from sigma.config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL


class ChatBackend(ABC):
    model_name: str

    @property
    def cache_identity(self) -> str:
        return self.model_name

    @abstractmethod
    def complete(self, system: str, user: str, temperature: float = 0.0) -> str:
        raise NotImplementedError


class OpenAICompatibleBackend(ChatBackend):
    """OpenAI-compatible chat backend using the existing Sigma LLM environment variables."""

    def __init__(self, *, base_url: str, api_key: str, model: str):
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "model-assisted PSIC classification requires the openai package"
            ) from exc
        self.base_url = base_url.rstrip("/")
        self.client = OpenAI(base_url=self.base_url, api_key=api_key)
        self.model_name = model

    @property
    def cache_identity(self) -> str:
        return f"{self.base_url}|{self.model_name}"

    @classmethod
    def configuration_from_environment(cls) -> tuple[str, str]:
        """Return normalized endpoint/model identity without reading or exposing the API key."""
        base_url = (
            os.getenv("SIGMA_LLM_BASE_URL", DEFAULT_LLM_BASE_URL).strip()
            or DEFAULT_LLM_BASE_URL
        ).rstrip("/")
        model = os.getenv("SIGMA_LLM_MODEL", DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL
        return base_url, model

    @classmethod
    def from_environment(cls) -> OpenAICompatibleBackend:
        api_key = os.getenv("SIGMA_LLM_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "SIGMA_LLM_API_KEY is required when --llm is enabled. "
                "SIGMA_LLM_BASE_URL and SIGMA_LLM_MODEL are optional."
            )
        base_url, model = cls.configuration_from_environment()
        return cls(base_url=base_url, api_key=api_key, model=model)

    def complete(self, system: str, user: str, temperature: float = 0.0) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
        except Exception as exc:
            raise RuntimeError(
                "PSIC traversal request failed. Check the LLM endpoint, API key, quota, "
                f"and model access. Provider error: {type(exc).__name__}: {exc}"
            ) from exc
        return response.choices[0].message.content or ""
