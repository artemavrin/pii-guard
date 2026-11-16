"""Per-document diagnosis of a smoke set against a running ``pii-guard serve``.

Prints, per document, the gold values that reached the model (leaks) and the masks that
cover no gold value (over-masking). Fictional fixtures only.

    uv run python docs/ru/diagnose.py eval/fixtures/ru-smoke.jsonl
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

URL = os.environ.get("PII_GUARD_URL", "http://127.0.0.1:8797")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(route: str, text: str, language: str) -> dict:
    body = json.dumps({"text": text, "language": language}).encode()
    req = urllib.request.Request(URL + route, body, {"Content-Type": "application/json"})
    with _OPENER.open(req) as r:
        return json.load(r)


def main(path: str) -> None:
    leaks = extra = gold_total = 0
    for line in open(path, encoding="utf-8"):
        doc = json.loads(line)
        text, gold = doc["text"], doc.get("spans") or doc.get("entities") or []
        language = doc.get("language", "ru")
        masked = call("/v1/mask", text, language)["masked_text"]
        spans = call("/v1/analyze", text, language)["spans"]
        found = [(s["start"], s["end"], s["entity_type"]) for s in spans if s["policy"] == "mask"]
        rows = []
        for g in gold:
            value = text[g["start"] : g["end"]]
            if g["entity_type"] == "ORGANIZATION":
                continue
            gold_total += 1
            if value in masked:
                leaks += 1
                rows.append(f"  УТЕЧКА   {g['entity_type']:14} {value!r}")
        for start, end, etype in found:
            if not any(start < g["end"] and g["start"] < end for g in gold):
                extra += 1
                rows.append(f"  ЛИШНЕЕ   {etype:14} {text[start:end]!r}")
        if rows:
            print(doc["id"])
            print("\n".join(rows))
    print(f"\nутечек {leaks} из {gold_total}, лишних масок {extra}")


if __name__ == "__main__":
    main(sys.argv[1])
