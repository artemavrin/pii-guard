"""Masking service for an app that calls the model itself (Metobe, docs/ru/README.md).

The app keeps its own provider client and runs the gateway's pipeline in two halves:

- ``POST /s/<session>/v1/chat/mask``: a chat-completions body (``messages``, optional ``tools``)
  masked exactly as ``/v1/chat/completions`` would forward it — the same detection, Russian
  person layer, JSON tool results, outbound re-check and placeholder note — but returned
  instead of sent. ``entities`` lists every placeholder in the masked body with its type and
  original value, for the app's "what the model saw" view.
  ``"keep"`` and ``"block"`` (lists of entity types) are the app's policy for this request: kept
  types go as they are, a blocked type refuses the request (``blocked_by_policy``, 422).
  With ``"dry": true`` the body is masked in a fork of the session (a draft's preview): the
  same placeholders a send would print, nothing registered.
- ``POST /s/<session>/v1/chat/restore``: the model's answer back to original values —
  ``text`` (answer text), ``arguments`` (a tool call's JSON arguments, JSON-escaped), or
  ``stream`` (a streamed text tail: restores what is safe now and returns the tail to hold
  until the next chunk; ``final`` flushes it).

The session comes from the URL (``/s/<session>/v1/...``), language and mode from the gateway
headers. Values are returned to the caller: the app already holds the original text.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import Request
from pydantic import BaseModel, Field

from pii_guard.api.deps import get_max_text_chars
from pii_guard.api.routes._common import ensure_connected, log_extra, v1_router
from pii_guard.api.routes.chat import GatewayRoute, get_gateway
from pii_guard.gateway import InvalidChatRequestError
from pii_guard.gateway.chat import RequestStats, mask_chat_request
from pii_guard.gateway.request import collect_texts
from pii_guard.gateway.restore import RestoreReport, restore_arguments, restore_text
from pii_guard.gateway.sessions import path_session
from pii_guard.gateway.trace import CallTrace, new_request_id
from pii_guard.languages.ru.names import LABEL_RE
from pii_guard.observability import RequestTimer
from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE, StreamUnmasker

__all__ = ["router"]

router = v1_router(GatewayRoute)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    return []


def _types(value: Any) -> frozenset[EntityType]:
    """Entity type names from the app; anything unknown is a bad request, never ignored."""
    if value is None:
        return frozenset()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise InvalidChatRequestError("keep and block must be lists of entity types")
    try:
        return frozenset(EntityType(v) for v in value)
    except ValueError:
        raise InvalidChatRequestError("unknown entity type in keep or block") from None


def _call_ids(body: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for message in body.get("messages") or []:
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict) and isinstance(call.get("id"), str):
                ids.append(call["id"])
        if isinstance(message.get("tool_call_id"), str):
            ids.append(message["tool_call_id"])
    return ids


def _entities(body: dict[str, Any], session: Any) -> list[dict[str, str]]:
    """Each placeholder or ``Персона`` label in the masked body, once, in order of appearance."""
    seen: dict[str, dict[str, str]] = {}
    for text in _strings(body.get("messages", [])):
        for m in PLACEHOLDER_RE.finditer(text):
            token = m.group(0)
            if token not in seen:
                value = session.unmask(token)
                if value != token:
                    seen[token] = {"placeholder": token, "type": m.group(1), "value": value}
        for m in LABEL_RE.finditer(text):
            token = m.group(0)
            if token not in seen:
                value = session.unmask(f"[[PERSON_{m.group('id')}]]")
                if not PLACEHOLDER_RE.fullmatch(value):
                    seen[token] = {"placeholder": token, "type": "PERSON", "value": value}
    return list(seen.values())


@router.post("/v1/chat/mask", tags=["gateway"])
async def chat_mask(request: Request) -> dict[str, Any]:
    await ensure_connected(request)
    gateway = get_gateway(request)
    raw = await request.body()
    received_at = time.perf_counter()
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise InvalidChatRequestError("request body is not valid JSON") from None
    if not isinstance(body, dict):
        raise InvalidChatRequestError("request body must be a JSON object")
    # A preview of a draft: masked in a fork of the session, so the placeholders are the ones a
    # send would print, and nothing is registered unless the message is sent.
    dry = bool(body.pop("dry", False))
    # The app's settings for this request: types to leave as they are, types that stop it.
    keep = _types(body.pop("keep", None))
    block = _types(body.pop("block", None))
    body.setdefault("model", "gpt-4o")
    request.state.pii_guard_request_id = new_request_id()
    timer = RequestTimer(received_at)
    trace = CallTrace(
        gateway.observability, timer, body, request_id=request.state.pii_guard_request_id
    )
    headers = request.headers
    mode, language = gateway.mode(headers), gateway.language(headers)
    stats = RequestStats(mode=mode, mode_alias=gateway.mode_alias(headers))
    collected = collect_texts(body)
    gateway.validate_limits(collected, get_max_text_chars(request))
    # Tool-call ids here are the app's own (not the model's), so they never carry personal data;
    # left to the detectors, a short id like ``call_1`` can score as a phone and refuse the call.
    sid = path_session(request.scope)
    if sid is not None:
        gateway.issued_ids.add(sid, _call_ids(body))

    async def run() -> tuple[Any, RequestStats]:
        session, payload, _kept, _ = await mask_chat_request(
            gateway,
            body,
            collected,
            headers,
            detector=gateway.detectors[mode],
            language=language,
            path_session=path_session(request.scope),
            timer=timer,
            trace=trace,
            stats=stats,
            check_payload=lambda _payload, _images: None,
            dry=dry,
            keep=keep,
            block=block,
        )
        return (session, payload), stats

    (session, payload), _ = await gateway.with_session_lease(run())
    masked = json.loads(payload)
    masked.pop("model", None)
    entities = _entities(masked, session)
    log_extra(request, **stats.log_fields())
    return {
        "session_id": session.session_id,
        "body": masked,
        "entities": entities,
        "ms": round((time.perf_counter() - received_at) * 1000, 1),
    }


class RestoreItem(BaseModel):
    """One piece of the model's answer to restore."""

    kind: str = Field(
        pattern="^(text|arguments|stream)$",
        description=(
            "`text`: answer text; `arguments`: a tool call's JSON arguments (values come back "
            "JSON-escaped); `stream`: a streamed text tail — the safe part is restored now, the "
            "rest returned as `held` for the next call."
        ),
    )
    text: str = Field(description="The masked text as the model wrote it (with `held` prepended).")
    final: bool = Field(
        default=False, description="Last tail of a stream: restore everything, hold nothing."
    )


class RestoreRequest(BaseModel):
    """The pieces of one model answer to restore, in order."""

    items: list[RestoreItem] = Field(description="Pieces to restore; one result per piece.")


@router.post("/v1/chat/restore", tags=["gateway"])
async def chat_restore(body: RestoreRequest, request: Request) -> dict[str, Any]:
    gateway = get_gateway(request)
    headers = request.headers
    stats = RequestStats(mode=gateway.mode(headers), mode_alias=gateway.mode_alias(headers))
    trace = CallTrace(
        gateway.observability, RequestTimer(time.perf_counter()), {}, request_id=new_request_id()
    )

    async def run() -> tuple[list[dict[str, Any]], RequestStats]:
        found, created = gateway.session(headers, {}, path_session(request.scope), stats, trace)
        try:
            session = gateway.restoring(found, gateway.language(headers))
            out: list[dict[str, Any]] = []
            for item in body.items:
                if item.kind == "text":
                    out.append({"text": restore_text(session, item.text)[0]})
                elif item.kind == "arguments":
                    out.append({"text": restore_arguments(session, item.text, RestoreReport())})
                else:
                    unmasker = StreamUnmasker(session)
                    ready = unmasker.feed(item.text)
                    held = unmasker._buffer  # the tail more input may still change  # noqa: SLF001
                    if item.final:
                        ready, held = ready + unmasker.flush(), ""
                    out.append({"text": ready, "held": held})
        finally:
            gateway.release_session(found, created, masked=False)
        return out, stats

    items, _ = await gateway.with_session_lease(run())
    return {"items": items}
