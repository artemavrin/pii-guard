"""The Russian person layer: names, Персона labels, one person = one vault entry, restore.

All names are fictional.
"""

from __future__ import annotations

import re

import pytest

from pii_guard.languages.ru import persons
from pii_guard.languages.ru.names import CASES, LABEL_RE, inflect, label, parse, read_label
from pii_guard.types import EntityType, Span
from pii_guard.vault import StreamUnmasker, Vault

# --- Names -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("surface", "key", "gender", "case"),
    [
        ("Смирновой Ольги Петровны", "Смирнова Ольга Петровна", "f", "gent"),
        ("Ольге Петровне", "Ольга Петровна", "f", "datv"),
        ("Кузнецову", "Кузнецов", "m", "datv"),
        ("Алексей Кузнецов", "Кузнецов Алексей", "m", "nomn"),
        ("Иванов И.И.", "Иванов И. И.", "m", "nomn"),
        ("ПЕТРОВА АННА СЕРГЕЕВНА", "Петрова Анна Сергеевна", "f", "nomn"),
        ("тимура ахметова", "Ахметов Тимур", "m", "gent"),
        ("Геворкяну Арсену Ашотовичу", "Геворкян Арсен Ашотович", "m", "datv"),
        ("Белых Анне", "Белых Анна", "f", "datv"),
        ("Цою Виктору", "Цой Виктор", "m", "datv"),
        ("Мариной Беловой", "Белова Марина", "f", "ablt"),
        ("Тавреновой", "Тавренова", "f", "gent"),  # not in any dictionary
        ("Хабибуллиной Гульнаре Ринатовне", "Хабибуллина Гульнара Ринатовна", "f", "datv"),
    ],
)
def test_parse(surface: str, key: str, gender: str, case: str) -> None:
    mention = parse(surface)
    assert mention is not None
    assert mention.parts.key() == key
    assert mention.parts.gender == gender
    assert case in mention.cases


@pytest.mark.parametrize("surface", ["", "договор", "ООО Ромашка и партнёры навсегда"])
def test_parse_rejects(surface: str) -> None:
    assert parse(surface) is None


def test_inflect_round_trip() -> None:
    mention = parse("Смирнова Ольга Петровна")
    assert mention is not None
    for case in CASES:
        written = inflect(mention.parts, mention.roles, case)
        again = parse(written)
        assert again is not None and again.parts.key() == "Смирнова Ольга Петровна"
        assert case in again.cases


@pytest.mark.parametrize("gender", ["m", "f", None])
@pytest.mark.parametrize("case", CASES)
def test_label_round_trip(gender: str | None, case: str) -> None:
    text = "Передай " + label("7f3a01", gender, case)
    m = LABEL_RE.search(text)
    assert m is not None and m.group("id") == "7f3a01"
    read = read_label(m, text)
    # The dative and prepositional share their forms; "Передай" reads as the dative.
    assert read == ("datv" if case == "loct" else case)


@pytest.mark.parametrize(
    ("written", "case"),
    [
        ("о Персоне_Женщине_7f3a01", "loct"),
        ("к Персоне_Женщине_7f3a01", "datv"),
        ("с Персоной-Мужчиной 7f3a01", "ablt"),  # the model may join the words otherwise
        ("для Персоны Женщины_7f3a01", "gent"),
    ],
)
def test_read_label_variants(written: str, case: str) -> None:
    m = LABEL_RE.search(written)
    assert m is not None and read_label(m, written) == case


# --- One person = one entry -------------------------------------------------------------

DIALOGUE = [
    "Оформи возврат для Смирновой Ольги Петровны, телефон 8 916 555-01-23.",
    "Ольга Петровна Смирнова живёт в Твери.",
    "Передай Ольге Петровне, что деньги придут до пятницы. И напиши Кузнецову.",
    "Договор с Ольгой Смирновой подписывал Алексей Кузнецов.",
    "насть, скинь контакты смирновой и кузнецова",
]


def _person_spans(text: str) -> list[Span]:
    """What the NER finds in DIALOGUE (the lowercase surnames it misses)."""
    names = [
        "Смирновой Ольги Петровны", "Ольга Петровна Смирнова", "Ольге Петровне", "Кузнецову",
        "Ольгой Смирновой", "Алексей Кузнецов",
    ]  # fmt: skip
    spans = []
    for name in names:
        for m in re.finditer(re.escape(name), text):
            spans.append(Span(m.start(), m.end(), EntityType.PERSON, name, 0.99, "ner"))
    return sorted(spans, key=lambda s: s.start)


def _mask(session, texts: list[str], spans=None) -> list[str]:  # type: ignore[no-untyped-def]
    spans = spans if spans is not None else [_person_spans(t) for t in texts]
    spans = persons.prepare(
        texts, spans, session.confirmed_values((EntityType.PERSON,)), session.session_id
    )
    out = []
    for text, found in zip(texts, spans, strict=True):
        r = session.mask_with_report(text, found, language="ru")
        f = session.mask_with_report(r.text, [], language="ru", remask=True, since=r.generation)
        out.append(persons.render(f.text, text, r, f, session.session_id))
    return out


@pytest.fixture
def session():  # type: ignore[no-untyped-def]
    vault = Vault(tenant_key=b"k" * 32)
    return vault.session_or_create("s_ru_persons")[0]


def _ids(texts: list[str]) -> set[str]:
    return {m.group("id") for t in texts for m in LABEL_RE.finditer(t)}


def test_one_person_one_label_across_forms_and_turns(session) -> None:  # type: ignore[no-untyped-def]
    history: list[str] = []
    for turn in DIALOGUE:
        history.append(turn)
        out = _mask(session, history)
    assert len(_ids(out)) == 2
    joined = " ".join(out)
    for leaked in ("Смирнов", "смирнов", "Ольг", "Кузнецов", "кузнецов"):
        assert leaked not in joined
    assert "Персоны_Женщины_" in out[0]  # «для Смирновой Ольги Петровны»: genitive
    assert "Персоне_Женщине_" in out[2]  # «Передай Ольге Петровне»: dative


def test_partial_mention_first_then_full(session) -> None:  # type: ignore[no-untyped-def]
    out = _mask(session, ["Позвони Ольге Петровне.", "Смирнова Ольга Петровна звонила."])
    assert len(_ids(out)) == 1


def test_two_people_with_one_given_name_stay_apart(session) -> None:  # type: ignore[no-untyped-def]
    texts = ["Смирнова Ольга и Белова Ольга пришли.", "Ольга опоздала."]
    spans = [
        [
            Span(0, 14, EntityType.PERSON, "Смирнова Ольга", 0.99, "ner"),
            Span(17, 29, EntityType.PERSON, "Белова Ольга", 0.99, "ner"),
        ],
        [Span(0, 5, EntityType.PERSON, "Ольга", 0.99, "ner")],
    ]
    out = _mask(session, texts, spans)
    first = {m.group("id") for m in LABEL_RE.finditer(out[0])}
    second = {m.group("id") for m in LABEL_RE.finditer(out[1])}
    assert len(first) == 2
    assert not second & first  # an ambiguous "Ольга" is not merged into either


def test_common_word_name_is_not_swept(session) -> None:  # type: ignore[no-untyped-def]
    texts = ["Позвони Вере Ивановой.", "Вера в лучшее помогает."]
    spans = [[Span(8, 21, EntityType.PERSON, "Вере Ивановой", 0.99, "ner")], []]
    out = _mask(session, texts, spans)
    assert out[1] == "Вера в лучшее помогает."


def test_person_form_wins_over_guessed_organization(session) -> None:  # type: ignore[no-untyped-def]
    texts = ["Договор подписал Алексей Кузнецов.", "спроси у кузнецова"]
    spans = [
        [Span(17, 33, EntityType.PERSON, "Алексей Кузнецов", 0.99, "ner")],
        [Span(9, 18, EntityType.ORGANIZATION, "кузнецова", 0.9, "ner")],
    ]
    out = _mask(session, texts, spans)
    assert "кузнецов" not in out[1]
    assert _ids(out[:1]) == _ids(out[1:])


# --- Restore ----------------------------------------------------------------------------


@pytest.fixture
def masked(session):  # type: ignore[no-untyped-def]
    out = _mask(session, DIALOGUE)
    ids: dict[str, str] = {}
    for m in LABEL_RE.finditer(" ".join(out)):
        ids.setdefault(m.group("gender")[:3].lower(), m.group("id"))
    return session, ids["жен"], ids["муж"]


@pytest.mark.parametrize(
    ("answer", "restored"),
    [
        ("Письмо отправил Персоне_Мужчине_{m}.", "Письмо отправил Кузнецову."),
        ("Договор с Персоной_Мужчиной_{m}.", "Договор с Кузнецовым."),
        ("Встречался с Персоной_Женщиной_{f}.", "Встречался со Смирновой."),
        ("Думаю о Персоне_Женщине_{f}.", "Думаю о Смирновой."),
        ("Уважаемая Персона_Женщина_{f}!", "Уважаемая Ольга Петровна!"),
        ("Здравствуйте, Персона_Женщина_{f}!", "Здравствуйте, Ольга Петровна!"),
    ],
)
def test_restore_labels(masked, answer: str, restored: str) -> None:  # type: ignore[no-untyped-def]
    session, f, m = masked
    text = answer.format(f=f, m=m)
    assert persons.LabelSession(session).unmask(text) == restored


def test_preposition_before_a_vowel(session) -> None:  # type: ignore[no-untyped-def]
    out = _mask(session, ["Позвони Ольге Петровне."])
    pid = next(LABEL_RE.finditer(out[0])).group("id")
    text = f"Думаю о Персоне_Женщине_{pid}."
    assert persons.LabelSession(session).unmask(text) == "Думаю об Ольге Петровне."


def test_unknown_label_is_left_as_written(session) -> None:  # type: ignore[no-untyped-def]
    text = "Передай Персоне_Женщине_1a2b3c привет."
    assert persons.LabelSession(session).unmask(text) == text


def test_stream_matches_whole_at_every_cut(masked) -> None:  # type: ignore[no-untyped-def]
    session, f, m = masked
    answer = (
        f"Встречался с Персоной_Женщиной_{f}, письмо отправил Персоне_Мужчине_{m}. "
        f"Думаю о Персоне_Женщине_{f}"
    )
    labels = persons.LabelSession(session)
    whole = labels.unmask(answer)
    for size in (1, 2, 3, 5, 7, 11):
        unmasker = StreamUnmasker(labels)
        out = "".join(unmasker.feed(answer[i : i + size]) for i in range(0, len(answer), size))
        out += unmasker.flush()
        assert out == whole, size
