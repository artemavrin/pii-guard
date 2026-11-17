"""Сверка разметки корпуса с правилами и текущей NER: показать расхождения.

    uv run python docs/ru/corpus/audit.py <raw.jsonl>...

Для каждого документа: «НЕ РАЗМЕЧЕНО» — детектор нашёл персональные данные вне разметки
(кандидат в пропуск автора), «НЕ НАЙДЕНО» — размеченное, что детекторы не видят (то, чему
модель и должна научиться, или лишняя метка автора). Организации детекторов не учитываются.
"""

from __future__ import annotations

import json
import sys

from pii_guard.detect.ner import NerDetector
from pii_guard.detect.rules import RuleDetector
from pii_guard.eval import from_markup

SKIP = {"ORGANIZATION"}


def main(paths: list[str]) -> None:
    rules, ner = RuleDetector(), NerDetector()
    missed = unseen = 0
    for path in paths:
        for line in open(path, encoding="utf-8"):
            row = json.loads(line)
            doc = from_markup(row["id"], row["markup"], language="ru")
            found = [
                s
                for s in rules.detect(doc.text, "ru") + ner.detect(doc.text, "ru")
                if s.entity_type.value not in SKIP
            ]
            gold = list(doc.spans)
            out = []
            for s in found:
                if not any(g.start < s.end and s.start < g.end for g in gold):
                    out.append(f"  НЕ РАЗМЕЧЕНО {s.entity_type.value:13} {doc.text[s.start:s.end]!r}")
                    missed += 1
            for g in gold:
                if g.entity_type.value in SKIP:
                    continue
                if not any(g.start < s.end and s.start < g.end for s in found):
                    out.append(f"  не найдено   {g.entity_type.value:13} {doc.text[g.start:g.end]!r}")
                    unseen += 1
            if out:
                print(row["id"])
                print("\n".join(dict.fromkeys(out)))
    print(f"\nвне разметки {missed}, размечено-но-не-найдено {unseen}")


if __name__ == "__main__":
    main(sys.argv[1:])
