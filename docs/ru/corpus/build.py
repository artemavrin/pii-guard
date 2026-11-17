"""Русский корпус: пулы имён для авторов, проверка и сборка JSONL для обучения.

    uv run python docs/ru/corpus/build.py pool <seed> <n>      # пул выдуманных имён
    uv run python docs/ru/corpus/build.py check <raw.jsonl>...  # проверить разметку
    uv run python docs/ru/corpus/build.py build <out.jsonl> <raw.jsonl>...  # собрать

Сырые файлы пишут авторы (docs/ru/corpus/SPEC.md); собранный — формат eval-документов
(``pii_guard.eval.Document``), его читает training/ner/train.py. Всё выдумано.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

from pii_guard.eval import from_markup

TYPES = {
    "PERSON", "ORGANIZATION", "ADDRESS", "DATE_OF_BIRTH", "EMAIL", "PHONE", "ID_DOCUMENT",
    "BANK_ACCOUNT",
}  # fmt: skip
_LABEL = re.compile(r"\{\{([A-Z_]+)\|([^{}|]+)\}\}")

FIRST_M = (
    "Алексей Андрей Артём Борис Вадим Виктор Владимир Глеб Григорий Даниил Денис Дмитрий Егор "
    "Иван Игорь Илья Кирилл Константин Леонид Максим Михаил Никита Николай Олег Павел Роман "
    "Руслан Святослав Сергей Станислав Степан Тимофей Фёдор Юрий Ярослав Тимур Рустам Марат "
    "Ильдар Арсен Давид Бахтиёр Азамат Эльдар Ринат Айдар Аслан Георгий Лев Семён Матвей"
).split()
FIRST_F = (
    "Алина Алёна Анастасия Анна Валентина Валерия Вера Виктория Галина Дарья Евгения Екатерина "
    "Елена Елизавета Жанна Зоя Ирина Карина Ксения Лариса Любовь Людмила Маргарита Марина "
    "Мария Надежда Наталья Нина Оксана Олеся Ольга Полина Светлана София Таисия Татьяна Ульяна "
    "Юлия Яна Гульнара Лейла Зарема Диляра Эльмира Камила Асель Алсу Регина Майя Милана"
).split()
PATRON_M = (
    "Александрович Алексеевич Андреевич Борисович Викторович Владимирович Дмитриевич "
    "Евгеньевич Иванович Игоревич Константинович Михайлович Николаевич Олегович Павлович "
    "Петрович Романович Сергеевич Юрьевич Ринатович Маратович Ашотович Тимурович Рашидович"
).split()
SURNAMES = (
    "Смирнов Кузнецов Попов Васильев Петров Соколов Михайлов Новиков Фёдоров Морозов Волков "
    "Алексеев Лебедев Семёнов Егоров Павлов Козлов Степанов Николаев Орлов Андреев Макаров "
    "Никитин Захаров Зайцев Соловьёв Борисов Яковлев Григорьев Романов Воробьёв Сергеев "
    "Кудрявцев Беляев Тарасов Белов Комаров Фролов Медведев Журавлёв Гусев Титов Широков "
    "Хабибуллин Галиев Садыков Гусейнов Алиев Мамедов Геворкян Арутюнян Юлдашев Каримов "
    "Ахметов Шевчук Бондаренко Ковальчук Сидоренко Мельник Белых Седых Цой Ким Дюма "
    "Тавренов Кеслов Мирзубов Ровдин Зельтов Бранцев Палдеев Рудмеев Тисканов Чевалин"
).split()


def _feminine_surname(s: str) -> str:
    if s.endswith(("ов", "ев", "ёв", "ин", "ын")):
        return s + "а"
    if s.endswith("ский"):
        return s[:-2] + "ая"
    return s  # Шевчук, Белых, Цой, Ким, Бондаренко, Геворкян


def _feminine_patronymic(p: str) -> str:
    return p[:-3] + "вна" if p.endswith("ович") else p[:-3] + "вна" if p.endswith("евич") else p


def pool(seed: int, n: int) -> list[str]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        surname = rng.choice(SURNAMES)
        patron = rng.choice(PATRON_M)
        if rng.random() < 0.5:
            out.append(f"{surname} {rng.choice(FIRST_M)} {patron}")
        else:
            fem = _feminine_patronymic(patron)
            out.append(f"{_feminine_surname(surname)} {rng.choice(FIRST_F)} {fem}")
    return out


def _rows(paths: list[str]) -> list[dict]:
    rows = []
    for path in paths:
        for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    rows.append({"id": f"{path}:{n}", "markup": None})
    return rows


def problems(row: dict) -> list[str]:
    markup = row.get("markup")
    if not isinstance(markup, str) or not markup.strip():
        return ["нет markup"]
    out = []
    for m in _LABEL.finditer(markup):
        if m.group(1) not in TYPES:
            out.append(f"неизвестный тип {m.group(1)}")
        if m.group(2) != m.group(2).strip():
            out.append("пробел на краю значения")
    rest = _LABEL.sub("", markup)
    if "{{" in rest or "}}" in rest:
        out.append("сломанная разметка")
    for email in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", _LABEL.sub(r"\2", markup)):
        if not re.search(r"@example\.(com|org|net|ru)$", email):
            out.append("почта не на example.*")
    try:
        from_markup(row.get("id", "x"), markup, language="ru")
    except Exception as e:  # noqa: BLE001
        out.append(f"from_markup: {type(e).__name__}")
    return out


def check(paths: list[str]) -> None:
    rows = _rows(paths)
    bad = 0
    types: dict[str, int] = {}
    for row in rows:
        p = problems(row)
        if p:
            bad += 1
            print(row.get("id"), p)
        for m in _LABEL.finditer(row.get("markup") or ""):
            types[m.group(1)] = types.get(m.group(1), 0) + 1
    print(f"документов {len(rows)}, с ошибками {bad}; метки: {dict(sorted(types.items()))}")


# Structured values the rules validate: an author's miss of one is filled in from the rules.
FILLED = {"PHONE", "EMAIL", "ID_DOCUMENT", "BANK_ACCOUNT", "PAYMENT_CARD"}


def _filled(doc):  # type: ignore[no-untyped-def]
    """``doc`` plus rule-validated values the author left unlabelled (see :data:`FILLED`)."""
    from dataclasses import replace

    from pii_guard.detect.rules import RuleDetector
    from pii_guard.eval.fixtures import GoldSpan
    from pii_guard.types import EntityType

    added = []
    for s in RuleDetector().detect(doc.text, "ru"):
        if s.entity_type.value not in FILLED:
            continue
        if any(g.start < s.end and s.start < g.end for g in doc.spans):
            continue
        kind = EntityType.BANK_ACCOUNT if s.entity_type.value == "PAYMENT_CARD" else s.entity_type
        added.append(GoldSpan(start=s.start, end=s.end, entity_type=kind, text=s.text))
    if not added:
        return doc, 0
    spans = sorted([*doc.spans, *added], key=lambda x: x.start)
    return replace(doc, spans=tuple(spans)), len(added)


def build(out: str, paths: list[str]) -> None:
    rows = [r for r in _rows(paths) if not problems(r)]
    seen: set[str] = set()
    filled = 0
    with open(out, "w", encoding="utf-8") as f:
        for row in rows:
            if row["markup"] in seen:
                continue
            seen.add(row["markup"])
            meta = {"slice": row.get("slice")}
            doc, n = _filled(from_markup(row["id"], row["markup"], language="ru", meta=meta))
            filled += n
            f.write(json.dumps(doc.to_dict(), ensure_ascii=False) + "\n")
    print(f"собрано {len(seen)} документов в {out}; дописано по правилам меток: {filled}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "pool":
        print("\n".join(pool(int(sys.argv[2]), int(sys.argv[3]))))
    elif cmd == "check":
        check(sys.argv[2:])
    elif cmd == "build":
        build(sys.argv[2], sys.argv[3:])
