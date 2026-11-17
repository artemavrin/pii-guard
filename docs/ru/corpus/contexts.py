"""Контекст находок сверки: id, тип, значение и ±40 символов вокруг (для ручного решения).

    uv run python docs/ru/corpus/contexts.py <audit.txt> <raw.jsonl>...
"""

from __future__ import annotations

import json
import re
import sys

from pii_guard.eval import from_markup

audit, raws = sys.argv[1], sys.argv[2:]
docs = {}
for path in raws:
    for line in open(path, encoding="utf-8"):
        row = json.loads(line)
        docs[row["id"]] = from_markup(row["id"], row["markup"], language="ru").text
current = None
for line in open(audit, encoding="utf-8"):
    if not line.startswith(" "):
        current = line.strip()
        continue
    m = re.match(r"\s+НЕ РАЗМЕЧЕНО (\w+)\s+'(.*)'$", line.rstrip("\n"))
    if m and current in docs:
        text, value = docs[current], m.group(2)
        i = text.find(value)
        ctx = text[max(0, i - 40) : i + len(value) + 30].replace("\n", " ⏎ ")
        print(f"{current}\t{m.group(1)}\t{value}\t…{ctx}…")
