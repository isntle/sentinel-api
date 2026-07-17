import json
from typing import Protocol

import httpx
from groq import Groq


class LLMProvider(Protocol):
    name: str

    def complete_json(self, system_prompt: str, user_content: str) -> dict:
        """Devuelve el JSON sin validarlo como veredicto de negocio."""
        ...


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def complete_json(self, system_prompt: str, user_content: str) -> dict:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not configured")
        client = Groq(api_key=self.api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        return json.loads(response.choices[0].message.content)


class OpenRouterProvider:
    name = "openrouter"
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str | None, model: str, timeout_seconds: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def complete_json(self, system_prompt: str, user_content: str) -> dict:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        return json.loads(body["choices"][0]["message"]["content"])
