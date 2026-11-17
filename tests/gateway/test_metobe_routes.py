"""The masking service for an app that calls the model itself (``routes/metobe.py``, Metobe).

``/s/<session>/v1/chat/mask`` masks a chat-completions body as the gateway would forward it;
``/s/<session>/v1/chat/restore`` restores the model's text, tool arguments and stream tails.
All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import FakeLlm, make_app

NAMES = ("Смирновой Ольги Петровны", "Ольге Петровне", "Кузнецову")
PHONE = "8 916 555-01-23"
EMAIL = "olga.smirnova@example.com"
RU = {"X-PII-Guard-Language": "ru"}
LABEL = re.compile(r"Персон\w*_(?:Женщин|Мужчин)\w*_([0-9a-f]+)")


@pytest.fixture
def client() -> TestClient:
    with TestClient(make_app(llm=FakeLlm(NAMES)), raise_server_exceptions=False) as http:
        yield http


def _mask(client: TestClient, session: str, messages: list[dict]) -> dict:
    response = client.post(f"/s/{session}/v1/chat/mask", json={"messages": messages}, headers=RU)
    assert response.status_code == 200, response.text
    return response.json()


def _restore(client: TestClient, session: str, items: list[dict]) -> list[dict]:
    response = client.post(f"/s/{session}/v1/chat/restore", json={"items": items}, headers=RU)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _person_id(out: dict) -> str:
    """The id of the masked person, from ``entities`` (the system note holds example labels)."""
    label = next(e["placeholder"] for e in out["entities"] if e["type"] == "PERSON")
    match = LABEL.fullmatch(label)
    assert match is not None
    return match.group(1)


def test_mask_returns_the_body_and_entities(client: TestClient) -> None:
    out = _mask(
        client,
        "metobe_m1",
        [
            {"role": "user", "content": f"Оформи возврат для Смирновой Ольги Петровны, {PHONE}."},
            {"role": "user", "content": f"Передай Ольге Петровне, почта {EMAIL}."},
        ],
    )
    text = json.dumps(out["body"], ensure_ascii=False)
    for value in ("Смирнов", "Ольг", PHONE, EMAIL):
        assert value not in text
    users = [m["content"] for m in out["body"]["messages"] if m["role"] == "user"]
    ids = {m.group(1) for u in users for m in LABEL.finditer(u)}
    assert len(ids) == 1  # one person in two case forms
    types = {e["type"] for e in out["entities"]}
    assert {"PERSON", "PHONE", "EMAIL"} <= types
    person = next(e for e in out["entities"] if e["type"] == "PERSON")
    assert person["value"] == "Смирнова Ольга Петровна"
    assert out["session_id"]


def test_restore_text_in_the_case_the_model_wrote(client: TestClient) -> None:
    out = _mask(
        client,
        "metobe_m2",
        [{"role": "user", "content": "Оформи возврат для Смирновой Ольги Петровны."}],
    )
    pid = _person_id(out)
    items = _restore(
        client,
        "metobe_m2",
        [{"kind": "text", "text": f"Письмо отправлено Персоне_Женщине_{pid}."}],
    )
    assert items[0]["text"] == "Письмо отправлено Смирновой Ольге Петровне."


def test_restore_tool_arguments(client: TestClient) -> None:
    out = _mask(client, "metobe_m3", [{"role": "user", "content": f"Напиши на {EMAIL}."}])
    token = next(e["placeholder"] for e in out["entities"] if e["type"] == "EMAIL")
    arguments = json.dumps({"to": token})[1:-1]  # inside a JSON string, as the model writes it
    items = _restore(client, "metobe_m3", [{"kind": "arguments", "text": arguments}])
    assert EMAIL in items[0]["text"]


def test_restore_stream_holds_a_split_label(client: TestClient) -> None:
    out = _mask(
        client, "metobe_m4", [{"role": "user", "content": "Передай Ольге Петровне привет."}]
    )
    pid = _person_id(out)
    head = "Передал Персоне_Жен"
    first = _restore(client, "metobe_m4", [{"kind": "stream", "text": head}])[0]
    assert "Персон" not in first["text"]
    assert first["held"].startswith("Персоне")
    tail = first["held"] + f"щине_{pid}."
    last = _restore(client, "metobe_m4", [{"kind": "stream", "text": tail, "final": True}])[0]
    assert first["text"] + last["text"] == "Передал Ольге Петровне."
    assert last["held"] == ""


def test_unknown_session_label_is_left_as_written(client: TestClient) -> None:
    items = _restore(
        client, "metobe_m5", [{"kind": "text", "text": "Привет, Персона_Женщина_1a2b3c."}]
    )
    assert items[0]["text"] == "Привет, Персона_Женщина_1a2b3c."


def test_dry_run_prints_the_send_labels_and_registers_nothing(client: TestClient) -> None:
    draft = [{"role": "user", "content": f"Передай Ольге Петровне, почта {EMAIL}."}]
    response = client.post(
        "/s/metobe_m6/v1/chat/mask", json={"messages": draft, "dry": True}, headers=RU
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    email = next(e["placeholder"] for e in preview["entities"] if e["type"] == "EMAIL")
    # Nothing was registered: the session cannot restore the draft's placeholder yet.
    assert _restore(client, "metobe_m6", [{"kind": "text", "text": email}])[0]["text"] == email
    sent = _mask(client, "metobe_m6", draft)
    assert {e["placeholder"] for e in sent["entities"]} == {
        e["placeholder"] for e in preview["entities"]
    }
    assert _restore(client, "metobe_m6", [{"kind": "text", "text": email}])[0]["text"] == EMAIL


def test_keep_and_block_types_for_one_request(client: TestClient) -> None:
    messages = [{"role": "user", "content": f"Передай Ольге Петровне, почта {EMAIL}."}]
    response = client.post(
        "/s/metobe_m7/v1/chat/mask", json={"messages": messages, "keep": ["EMAIL"]}, headers=RU
    )
    assert response.status_code == 200, response.text
    out = response.json()
    assert EMAIL in json.dumps(out["body"], ensure_ascii=False)
    assert {e["type"] for e in out["entities"]} == {"PERSON"}
    blocked = client.post(
        "/s/metobe_m8/v1/chat/mask", json={"messages": messages, "block": ["EMAIL"]}, headers=RU
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "blocked_by_policy"
    assert EMAIL not in blocked.text
    bad = client.post(
        "/s/metobe_m9/v1/chat/mask", json={"messages": messages, "keep": ["NOPE"]}, headers=RU
    )
    assert bad.status_code == 400
