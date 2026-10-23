"""LLM provider boundary.

``LLMProvider`` is the only thing the LLM agents know about a model vendor. ``AnthropicProvider`` is
the one real implementation (Anthropic Messages API via the official ``anthropic`` SDK, imported
lazily so the core install never needs it). ``ScriptedProvider`` is an offline test double - it is
NOT a model and its output is never reported as a model result.

API facts honoured here (checked against the Claude API skill bundled with this session, 2026-10):
  * no ``temperature`` / ``top_p`` / ``top_k``: rejected with HTTP 400 on current API versions;
  * no forced ``tool_choice`` (``any`` / ``tool``): rejected by newer models; we send ``auto``;
  * ``stop_reason == "refusal"`` is surfaced, never silently treated as an answer;
  * thinking blocks in assistant turns are echoed back unchanged (``raw_content``).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from robot_eval.domain.models import Usage
from robot_eval.observability.sanitize import sanitize_text


class ProviderError(RuntimeError):
    """A sanitized provider failure. ``kind`` is one of: timeout, rate_limit, connection, server,
    bad_request, auth, refusal, other."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {sanitize_text(message, 300)}")
        self.kind = kind


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[LLMToolCall]
    raw_content: Any  # echoed back verbatim as the assistant turn
    stop_reason: str | None
    usage: Usage
    model: str | None = None
    refusal_category: str | None = None


class LLMProvider(Protocol):
    model_id: str
    provider_name: str

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        timeout_s: float | None = None,
    ) -> LLMResponse: ...


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local ``$ref``/``$defs`` so the schema is self-contained (portable across providers)."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if (
                "$ref" in node
                and isinstance(node["$ref"], str)
                and node["$ref"].startswith("#/$defs/")
            ):
                target = copy.deepcopy(defs[node["$ref"].split("/")[-1]])
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return walk({**target, **extra})
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    out: dict[str, Any] = walk(schema)
    return out


def to_provider_tools(descriptors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": d["name"],
            "description": d["description"],
            "input_schema": inline_refs(d["input_schema"]),
        }
        for d in descriptors
    ]


# --------------------------------------------------------------------------------- Anthropic
class AnthropicProvider:
    provider_name = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        client: Any | None = None,
        max_retries: int = 2,
        timeout_s: float = 60.0,
        effort: str | None = None,
        pricing: dict[str, float] | None = None,
    ) -> None:
        import anthropic  # lazy: optional extra

        self._sdk = anthropic
        self.model_id = model
        self.effort = effort
        self.pricing = pricing
        self.client = client or anthropic.Anthropic(max_retries=max_retries, timeout=timeout_s)

    def _cost(self, inp: int | None, out: int | None) -> float | None:
        """Estimate only when the operator configured prices; otherwise None (never 0)."""
        if not self.pricing or inp is None or out is None:
            return None
        return (inp * self.pricing["input_per_mtok"] + out * self.pricing["output_per_mtok"]) / 1e6

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        timeout_s: float | None = None,
    ) -> LLMResponse:
        sdk = self._sdk
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
            "tool_choice": {"type": "auto"},
        }
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        client = self.client.with_options(timeout=timeout_s) if timeout_s else self.client
        try:
            resp = client.messages.create(**kwargs)
        except sdk.APITimeoutError as exc:
            raise ProviderError("timeout", str(exc)) from exc
        except sdk.RateLimitError as exc:
            raise ProviderError("rate_limit", str(exc)) from exc
        except (sdk.AuthenticationError, sdk.PermissionDeniedError) as exc:
            raise ProviderError("auth", str(exc)) from exc
        except sdk.BadRequestError as exc:
            raise ProviderError("bad_request", getattr(exc, "message", str(exc))) from exc
        except sdk.APIConnectionError as exc:
            raise ProviderError("connection", str(exc)) from exc
        except sdk.APIStatusError as exc:
            raise ProviderError(
                "server" if exc.status_code >= 500 else "other",
                f"HTTP {exc.status_code}: {getattr(exc, 'message', '')}",
            ) from exc
        text_parts: list[str] = []
        calls: list[LLMToolCall] = []
        for b in resp.content:
            if b.type == "text":
                text_parts.append(b.text)
            elif b.type == "tool_use":
                calls.append(
                    LLMToolCall(id=b.id, name=b.name, arguments=dict(b.input) if b.input else {})
                )
        u = resp.usage
        parts = [
            getattr(u, "input_tokens", None),
            getattr(u, "cache_creation_input_tokens", None),
            getattr(u, "cache_read_input_tokens", None),
        ]
        inp = (
            sum(p for p in parts if isinstance(p, int))
            if any(isinstance(p, int) for p in parts)
            else None
        )
        out_t = getattr(u, "output_tokens", None)
        sd = getattr(resp, "stop_details", None)
        rid = getattr(resp, "_request_id", None)
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=calls,
            raw_content=resp.content,
            stop_reason=resp.stop_reason,
            usage=Usage(
                input_tokens=inp,
                output_tokens=out_t if isinstance(out_t, int) else None,
                cost_usd=self._cost(inp, out_t if isinstance(out_t, int) else None),
                request_ids=[rid] if rid else [],
            ),
            model=getattr(resp, "model", None),
            refusal_category=getattr(sd, "category", None) if sd else None,
        )


# ------------------------------------------------------------------------------------- mock
@dataclass
class ScriptedProvider:
    """Offline test double: replays a script of responses (or raises scripted errors)."""

    script: list[LLMResponse | ProviderError | Callable[[dict[str, Any]], LLMResponse]]
    model_id: str = "scripted-test-double"
    provider_name: str = "scripted"
    requests: list[dict[str, Any]] = field(default_factory=list)

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        timeout_s: float | None = None,
    ) -> LLMResponse:
        req = {
            "system": system,
            "messages": copy.deepcopy(messages),
            "tools": tools,
            "max_tokens": max_tokens,
            "timeout_s": timeout_s,
        }
        self.requests.append(req)
        if not self.script:
            raise ProviderError("other", "scripted provider exhausted")
        item = self.script.pop(0)
        if isinstance(item, ProviderError):
            raise item
        if callable(item):
            return item(req)
        return item


def tool_call_response(
    *calls: tuple[str, str, dict[str, Any]],
    inp: int | None = 10,
    out: int | None = 5,
    text: str = "",
) -> LLMResponse:
    """Build a scripted assistant turn containing tool_use blocks: (id, name, arguments)."""
    raw: list[dict[str, Any]] = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "id": i, "name": n, "input": a} for i, n, a in calls
    ]
    return LLMResponse(
        text=text,
        tool_calls=[LLMToolCall(i, n, a) for i, n, a in calls],
        raw_content=raw,
        stop_reason="tool_use",
        usage=Usage(input_tokens=inp, output_tokens=out),
    )
