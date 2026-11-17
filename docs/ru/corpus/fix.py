"""Дописать в сырой корпус метки, пропущенные авторами (решение принято вручную по сверке).

    uv run python docs/ru/corpus/fix.py <fixes.tsv> <raw.jsonl>...

fixes.tsv: id <TAB> TYPE <TAB> значение — первое вхождение значения вне существующих меток
оборачивается в {{TYPE|значение}}. Файлы переписываются на месте.
"""

from __future__ import annotations

import json
import re
import sys

_LABEL = re.compile(r"\{\{[A-Z_]+\|[^{}|]+\}\}")


def wrap(markup: str, kind: str, value: str) -> str | None:
    labelled = [(m.start(), m.end()) for m in _LABEL.finditer(markup)]
    for m in re.finditer(re.escape(value), markup):
        if any(a <= m.start() < b for a, b in labelled):
            continue
        before = markup[m.start() - 1 : m.start()]
        after = markup[m.end() : m.end() + 1]
        if (before.isalnum()) or (after.isalnum() and value[-1:].isalnum()):
            continue  # inside a longer word
        return markup[: m.start()] + f"{{{{{kind}|{value}}}}}" + markup[m.end() :]
    return None


def main(fixes: str, paths: list[str]) -> None:
    todo: dict[str, list[tuple[str, str]]] = {}
    for line in open(fixes, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            doc_id, kind, value = line.rstrip("\n").split("\t")
            todo.setdefault(doc_id, []).append((kind, value))
    done = missing = 0
    for path in paths:
        rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
        for row in rows:
            for kind, value in todo.pop(row["id"], []):
                new = wrap(row["markup"], kind, value)
                if new is None:
                    print("не найдено:", row["id"], kind)
                    missing += 1
                else:
                    row["markup"] = new
                    done += 1
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    for doc_id in todo:
        print("нет документа:", doc_id)
    print(f"дописано {done}, не найдено {missing}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
