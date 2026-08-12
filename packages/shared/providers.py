"""Provider abstractions so no business logic is hardwired to one AI vendor.

Implementations are selected via env config (packages/shared/config.py), never
hardcoded into agent/retrieval code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...


class FastEmbedProvider(EmbeddingProvider):
    """Local, no-API-key embeddings via ONNX runtime (BAAI/bge-small-en-v1.5)."""

    _MODEL_DIM = 384

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [vec.tolist() for vec in self._model.embed(texts)]

    @property
    def dimensions(self) -> int:
        return self._MODEL_DIM


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Hosted embeddings; requires OPENAI_API_KEY. Higher quality, has cost."""

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        from openai import OpenAI

        self._client = OpenAI()
        self._model = model
        self._dim = 1536

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in resp.data]

    @property
    def dimensions(self) -> int:
        return self._dim


def get_embedding_provider(name: str) -> EmbeddingProvider:
    if name == "fastembed":
        return FastEmbedProvider()
    if name == "openai":
        return OpenAIEmbeddingProvider()
    raise ValueError(f"Unknown embedding provider: {name}")


@dataclass
class LLMMessage:
    role: str  # "user" | "assistant" | "system"
    # str for plain turns. For an assistant turn that made tool calls: the provider's
    # own raw_content from LLMResponse (round-tripped back into the same provider
    # unchanged). For a user turn carrying tool results: a generic
    # list[{"tool_call_id": str, "content": str}] that every provider translates into
    # its own wire format in complete() — this keeps the agent loop provider-agnostic.
    content: str | list[dict]


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Anthropic-style {name, description, input_schema} -> OpenAI/Ollama {type:
    function, function: {name, description, parameters}}."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[LLMToolCall]
    stop_reason: str
    raw_content: list[dict] | None = None  # provider-native blocks, for round-tripping


class LLMProvider(ABC):
    @abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse: ...


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        wire_messages = []
        for m in messages:
            if m.role == "user" and isinstance(m.content, list) and m.content and "tool_call_id" in m.content[0]:
                wire_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": d["tool_call_id"], "content": d["content"]}
                            for d in m.content
                        ],
                    }
                )
            else:
                wire_messages.append({"role": m.role, "content": m.content})

        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=wire_messages,
            tools=tools or [],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        tool_calls = [
            LLMToolCall(id=b.id, name=b.name, arguments=b.input)
            for b in resp.content
            if b.type == "tool_use"
        ]
        raw_content = [b.model_dump() for b in resp.content]
        return LLMResponse(
            text=text, tool_calls=tool_calls, stop_reason=resp.stop_reason or "", raw_content=raw_content
        )


def _build_chat_style_messages(system: str, messages: list[LLMMessage]) -> list[dict]:
    """Shared OpenAI/Ollama-style wire format: assistant tool_calls + separate
    role:"tool" messages per result (as opposed to Anthropic's content-block style)."""
    wire: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        if m.role == "assistant" and isinstance(m.content, list):
            wire.append({"role": "assistant", "content": "", "tool_calls": m.content})
        elif m.role == "user" and isinstance(m.content, list) and m.content and "tool_call_id" in m.content[0]:
            for d in m.content:
                wire.append({"role": "tool", "tool_call_id": d["tool_call_id"], "content": d["content"]})
        else:
            wire.append({"role": m.role, "content": m.content})
    return wire


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        chat_messages = _build_chat_style_messages(system, messages)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=chat_messages,
            max_tokens=max_tokens,
            tools=_to_openai_tools(tools) if tools else None,
        )
        choice = resp.choices[0]
        raw_tool_calls = choice.message.tool_calls or []
        tool_calls = [
            LLMToolCall(id=tc.id, name=tc.function.name, arguments=_safe_json(tc.function.arguments))
            for tc in raw_tool_calls
        ]
        raw_content = [tc.model_dump() for tc in raw_tool_calls] if raw_tool_calls else None
        return LLMResponse(
            text=choice.message.content or "",
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason or "",
            raw_content=raw_content,
        )


class OllamaProvider(LLMProvider):
    """Local LLM via Ollama's OpenAI-compatible /api/chat. No API key required —
    this is the default development provider (docs/OLLAMA.md)."""

    def __init__(self, base_url: str, model: str) -> None:
        import httpx

        self._base_url = base_url.rstrip("/")
        self._model = model
        # CPU inference on a small local model can be slow for multi-tool-call turns;
        # generous timeout documented in docs/OLLAMA.md rather than silently truncated.
        self._client = httpx.Client(timeout=300.0)

    def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        chat_messages = _build_chat_style_messages(system, messages)
        payload = {
            "model": self._model,
            "messages": chat_messages,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = _to_openai_tools(tools)
        resp = self._client.post(f"{self._base_url}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        message = data.get("message", {})
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = []
        for i, tc in enumerate(raw_tool_calls):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = _safe_json(args)
            tool_calls.append(
                LLMToolCall(id=tc.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=args)
            )
        raw_content = raw_tool_calls or None
        return LLMResponse(
            text=message.get("content", "") or "",
            tool_calls=tool_calls,
            stop_reason=data.get("done_reason", ""),
            raw_content=raw_content,
        )

    def health_check(self, ping: bool = True) -> dict:
        """Readiness probe: server up, model present, and (if ping=True) model
        actually responds. ping=False skips the ~1-3s inference round-trip for use
        on the hot chat path; the dedicated /api/v1/health/llm endpoint uses ping=True
        so the UI can show real connected/latency status without waiting for a chat."""
        import time

        result = {"provider": "ollama", "base_url": self._base_url, "model": self._model}
        try:
            tags = self._client.get(f"{self._base_url}/api/tags", timeout=5.0)
            tags.raise_for_status()
            models = [m["name"] for m in tags.json().get("models", [])]
            result["server_reachable"] = True
            result["model_available"] = self._model in models or f"{self._model}:latest" in models
            result["available_models"] = models
        except Exception as e:  # noqa: BLE001
            return {**result, "status": "unreachable", "server_reachable": False, "model_available": False, "error": str(e)}

        if not result["model_available"]:
            result["status"] = "model_not_pulled"
            return result

        if not ping:
            result["status"] = "connected"
            return result

        try:
            t0 = time.monotonic()
            r = self._client.post(
                f"{self._base_url}/api/chat",
                json={"model": self._model, "messages": [{"role": "user", "content": "ping"}], "stream": False},
                timeout=30.0,
            )
            r.raise_for_status()
            result["latency_ms"] = int((time.monotonic() - t0) * 1000)
            result["status"] = "connected"
        except Exception as e:  # noqa: BLE001
            result["status"] = "unresponsive"
            result["error"] = str(e)
        return result


def _safe_json(s):
    import json

    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return {}


class ProviderNotConfiguredError(RuntimeError):
    pass


def get_llm_provider(settings) -> LLMProvider:
    """Dispatches on settings.llm_provider. Never silently falls back to a different
    (possibly paid) provider — an unconfigured provider raises, it doesn't fall
    through (spec module 6: "never silently switch to a paid provider")."""
    name = settings.llm_provider
    if name == "ollama":
        provider = OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_model)
        health = provider.health_check(ping=False)
        if health["status"] != "connected":
            raise ProviderNotConfiguredError(
                f"Ollama is configured (LLM_PROVIDER=ollama) but not usable: "
                f"{health.get('status')} — {health.get('error', '')}. "
                f"Run `ollama serve` and `ollama pull {settings.ollama_model}`, "
                f"or check docs/OLLAMA.md."
            )
        return provider
    if name == "anthropic":
        if not settings.anthropic_api_key:
            raise ProviderNotConfiguredError(
                "ANTHROPIC_API_KEY is not set. Add it to .env to enable the reasoning "
                "agent (see .env.example)."
            )
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    if name == "openai":
        if not settings.openai_api_key:
            raise ProviderNotConfiguredError("OPENAI_API_KEY is not set.")
        return OpenAIProvider(api_key=settings.openai_api_key)
    raise ValueError(f"Unknown LLM provider: {name}")
