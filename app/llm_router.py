"""LLM providers + routing policy.
Internal message format = Anthropic-style blocks; providers translate.
"""

import json
from dataclasses import dataclass

import httpx

from . import config
from .observability import log


@dataclass
class LLMResult:
    text: str
    tool_uses: list
    input_tokens: int
    output_tokens: int
    provider: str
    model: str


class ThirdPartyProvider:
    """Groq cloud API using OpenAI-compatible chat completions."""

    name = "third_party"

    def __init__(self):
        self.model = config.MODEL
        self.base_url = config.GROQ_BASE_URL.rstrip("/")
        self.api_key = config.GROQ_API_KEY

    async def complete(self, system, tools, messages) -> LLMResult:
        # Convert internal Anthropic-style messages to OpenAI-compatible format
        converted_messages = SelfHostedProvider._convert(system, messages)

        payload = {
            "model": self.model,
            "messages": converted_messages,
            "temperature": 0,
            "max_tokens": 1024,
        }

        # Convert tools to OpenAI-compatible function calling format
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120) as http:
            response = await http.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

        data = response.json()
        message = data["choices"][0]["message"]

        # Extract tool calls
        tool_uses = [
            {
                "id": tc["id"],
                "name": tc["function"]["name"],
                "input": json.loads(tc["function"].get("arguments") or "{}"),
            }
            for tc in (message.get("tool_calls") or [])
        ]

        # Extract only user-facing text (not reasoning)
        text = message.get("content") or ""

        usage = data.get("usage") or {}

        return LLMResult(
            text=text,
            tool_uses=tool_uses,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            provider=self.name,
            model=self.model,
        )


class SelfHostedProvider:
    """OpenAI-compatible self-hosted server (Ollama, vLLM, TGI, etc.)."""

    name = "self_hosted"

    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.base = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    @staticmethod
    def _convert(system, messages):
        """Convert internal Anthropic-style messages to OpenAI format."""

        out = [{"role": "system", "content": system}]

        for m in messages:
            c = m["content"]

            if isinstance(c, str):
                out.append({
                    "role": m["role"],
                    "content": c,
                })

            elif m["role"] == "assistant":
                calls = [
                    {
                        "id": b["id"],
                        "type": "function",
                        "function": {
                            "name": b["name"],
                            "arguments": json.dumps(b["input"]),
                        },
                    }
                    for b in c
                    if b["type"] == "tool_use"
                ]

                msg = {
                    "role": "assistant",
                    "content": "".join(
                        b["text"] for b in c if b["type"] == "text"
                    ) or None,
                }

                if calls:
                    msg["tool_calls"] = calls

                out.append(msg)

            else:
                # Convert tool results into OpenAI tool messages
                for b in c:
                    if b["type"] == "tool_result":
                        out.append({
                            "role": "tool",
                            "tool_call_id": b["tool_use_id"],
                            "content": b["content"],
                        })

        return out

    async def complete(self, system, tools, messages) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": self._convert(system, messages),
            "temperature": 0,
        }

        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]

        headers = (
            {"Authorization": f"Bearer {self.api_key}"}
            if self.api_key
            else {}
        )

        async with httpx.AsyncClient(timeout=120) as http:
            response = await http.post(
                f"{self.base}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

        data = response.json()
        message = data["choices"][0]["message"]

        tool_uses = [
            {
                "id": tc["id"],
                "name": tc["function"]["name"],
                "input": json.loads(
                    tc["function"].get("arguments") or "{}"
                ),
            }
            for tc in (message.get("tool_calls") or [])
        ]

        usage = data.get("usage") or {}

        return LLMResult(
            text=message.get("content") or "",
            tool_uses=tool_uses,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            provider=self.name,
            model=self.model,
        )


class LLMRouter:
    """Provider routing policy.

    - Subagents handling raw account/transaction data use self-hosted
      provider when configured.
    - Coordinator uses third-party provider unless PII was detected
      and self-hosted provider is configured.
    - If self-hosted is not configured, third-party is used.
    """

    def __init__(self, third_party=None, self_hosted=None):
        self.third_party = third_party or ThirdPartyProvider()

        if self_hosted is None and config.SELF_HOSTED_URL:
            self_hosted = SelfHostedProvider(
                config.SELF_HOSTED_URL,
                config.SELF_HOSTED_MODEL,
                config.SELF_HOSTED_API_KEY,
            )

        self.self_hosted = self_hosted

    def choose(self, role: str, pii_in_turn: bool):
        if self.self_hosted and (
            role == "subagent" or pii_in_turn
        ):
            provider = self.self_hosted
        else:
            provider = self.third_party

        log(
            "llm_route",
            role=role,
            pii=pii_in_turn,
            provider=provider.name,
        )

        return provider