"""Прогон русского слоя без шлюза: хранилище + prepare/render + восстановление.

Детекторы — правила и NER, как в быстром режиме. Все имена выдуманы.

    uv run python docs/ru/layer_check.py
"""

from __future__ import annotations

import re

from pii_guard.detect.ner import NerDetector
from pii_guard.detect.rules import RuleDetector
from pii_guard.languages.ru import persons
from pii_guard.types import EntityType
from pii_guard.vault import Vault

TURNS = [
    "Оформи возврат для Смирновой Ольги Петровны, паспорт 4510 123456, телефон 8 916 555-01-23.",
    "Ольга Петровна Смирнова живёт по адресу: г. Тверь, ул. Советская, д. 12, кв. 34.",
    "Передай Ольге Петровне, что деньги придут до пятницы. И напиши Кузнецову из бухгалтерии.",
    "Договор с Ольгой Смирновой подписывал Алексей Кузнецов, его СНИЛС 112-233-445 95.",
    "насть, скинь контакты смирновой и кузнецова",
]
ANSWER = (
    "Готово: возврат оформлен для Персоны_Женщины_{a}. Письмо отправил Персоне_Мужчине_{b}, "
    "договор с Персоной_Мужчиной_{b} в силе. Уважаемая Персона_Женщина_{a}! Думаю о "
    "Персоне_Женщине_{a}. Встречался с Персоной_Женщиной_{a}."
)


def main() -> None:
    vault = Vault(tenant_key=b"k" * 32)
    session, _ = vault.session_or_create("s_layer_check")
    rules, ner = RuleDetector(), NerDetector()
    history: list[str] = []
    for turn in TURNS:
        history.append(turn)
        spans = []
        for text in history:
            found = rules.detect(text, "ru") + ner.detect(text, "ru")
            found.sort(key=lambda s: (s.start, -s.end))
            kept, last_end = [], -1
            for s in found:  # crude overlap resolution: first, longest
                if s.start >= last_end:
                    kept.append(s)
                    last_end = s.end
            spans.append(kept)
        spans = persons.prepare(
            history, spans, session.confirmed_values((EntityType.PERSON,)), session.session_id
        )
        out = []
        for text, found in zip(history, spans, strict=True):
            r = session.mask_with_report(text, found, language="ru")
            f = session.mask_with_report(r.text, [], language="ru", remask=True, since=r.generation)
            out.append(persons.render(f.text, text, r, f, session.session_id))
    print("Модель видит последний запрос:")
    for line in out:
        print("  ", line)
    ids = {}
    for m in re.finditer(r"Персон\w*_(Мужчин|Женщин)\w*_([0-9a-f]+)", " ".join(out)):
        ids.setdefault(m.group(1), m.group(2))
    labels = sorted(
        {
            m.group(0)
            for m in re.finditer(
                r"\[\[PERSON_[0-9a-f]+\]\]|Персона_\w+?_[0-9a-f]{6,}", " ".join(out)
            )
        }
    )
    print(
        "\nРазных меток людей:",
        len({re.sub(r"^.*_", "", x).strip("[]") for x in labels if "Персон" in x or "PERSON" in x}),
    )
    answer = ANSWER.format(a=ids.get("Женщин", "?"), b=ids.get("Мужчин", "?"))
    print("\nОтвет модели:", answer)
    print("Восстановлено:", persons.LabelSession(session).unmask(answer))


if __name__ == "__main__":
    main()
