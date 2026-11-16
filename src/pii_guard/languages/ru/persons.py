"""The Russian person layer: one person = one vault entry, ``Персона`` labels upstream.

Gateway side (docs/ru/README.md):

1. :func:`prepare` (before the vault masks a request). Every ``PERSON`` span is parsed
   (:mod:`.names`) and resolved to a person of the session: the persons the vault already
   has (their lemmas) and those earlier in this request, richest mentions first. A mention
   whose known parts agree with exactly one person joins it (``Ольге Петровне`` joins
   ``Смирнова Ольга Петровна``); otherwise it is a new person. The span gets the person's
   key as its ``lemma``, so the vault keys every form on one entry. Then the other written
   forms of each person (every case of the full name, the name and patronymic, the
   surname; a given name alone only when capitalized and not a common word) are swept in
   all texts and added as spans: ``смирновой`` in chat is masked too.
2. :func:`render` (after the vault). Each ``[[PERSON_id]]`` that replaced a parsed
   mention becomes ``Персона_Женщина_id`` in the mention's case.
3. :class:`LabelSession` (response side) wraps the session: labels in the answer are
   restored to the real name in the label's case, with the parts the context needs (name
   and patronymic in an address, otherwise as the person was last named), and a
   preposition before it adjusted (``с``/``со``, ``о``/``об`` ...). It also tells a
   streaming unmasker to hold back a possible label at the end of a chunk.

The registry of a session (parts, gender, last form of each person) lives here, keyed by
the session id, rebuilt from the vault and the request on every request: the gateway
re-masks the whole history each time. Nothing here logs values.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pii_guard.languages.ru.names import (
    LABEL_RE,
    Mention,
    NameParts,
    case_before,
    inflect,
    label,
    parse,
    read_label,
)
from pii_guard.types import EntityType, Span
from pii_guard.vault.placeholders import PLACEHOLDER_RE

__all__ = ["NOTE", "LabelSession", "Registry", "has_labels", "prepare", "render"]

DETECTOR = "ru_person"
_PREFIX = "PERSON_"

#: The system note added when labels are in a request (measured: docs/ru/spikes/README.md).
NOTE = (
    "Ради защиты персональных данных настоящие имена людей в сообщениях заменены метками "
    "вида Персона_Женщина_1a2b или Персона_Мужчина_3c4d. За каждой меткой стоит настоящий "
    "человек с настоящими именем, фамилией и отчеством.\n"
    "Система подставит имя ровно в том падеже, в котором ты напишешь метку. Поэтому склоняй "
    "оба слова метки так же, как склонял бы имя, идентификатор оставляй как есть: «договор с "
    "Персоной_Мужчиной_3c4d», «задача для Персоны_Женщины_1a2b», «передай "
    "Персоне_Мужчине_3c4d». Как назвать человека — полностью, по имени и отчеству или по "
    "фамилии — система выберет сама.\n"
    "Не упоминай метки, не говори, что имя или отчество неизвестны, и не придумывай имён."
)


@dataclass(slots=True)
class Person:
    key: str
    parts: NameParts
    roles: tuple[str, ...] = ()  # how the person was last named (restore uses it)
    style: str = "title"

    def __repr__(self) -> str:
        return f"Person(parts={self.parts!r}, roles={self.roles})"


@dataclass(slots=True)
class Registry:
    persons: dict[str, Person] = field(default_factory=dict)  # by key (the vault lemma)
    by_id: dict[str, Person] = field(default_factory=dict)  # by placeholder id

    def __repr__(self) -> str:
        return f"Registry(persons={len(self.persons)})"


_REGISTRIES: OrderedDict[str, Registry] = OrderedDict()
_LOCK = threading.Lock()
_MAX_REGISTRIES = 4096


def _remember(session_id: str, registry: Registry) -> None:
    with _LOCK:
        _REGISTRIES[session_id] = registry
        _REGISTRIES.move_to_end(session_id)
        while len(_REGISTRIES) > _MAX_REGISTRIES:
            _REGISTRIES.popitem(last=False)


def registry_of(session_id: str) -> Registry | None:
    with _LOCK:
        return _REGISTRIES.get(session_id)


# --- 1. Resolution and sweep ---------------------------------------------------------


def _resolve(persons: dict[str, Person], mention: Mention) -> Person:
    candidates = [
        p
        for p in persons.values()
        if p.parts.compatible(mention.parts) and p.parts.shared(mention.parts) >= 1
    ]
    if candidates:
        best = max(p.parts.shared(mention.parts) for p in candidates)
        top = [p for p in candidates if p.parts.shared(mention.parts) == best]
        if len(top) == 1:
            person = top[0]
            person.parts = person.parts.merged(mention.parts)
            return person
    key = mention.parts.key()
    person = persons.get(key)
    if person is None:
        person = Person(key=key, parts=mention.parts)
        persons[key] = person
    return person


def _richness(mention: Mention) -> int:
    p = mention.parts
    return sum(1 for x in (p.last, p.first, p.middle) if x)


# Compositions swept for a person: (roles, needs every role known).
_SWEPT = (("f", "i", "o"), ("i", "o", "f"), ("i", "o"), ("i", "f"), ("f", "i"), ("f",))


def _common_word(word: str) -> bool:
    """A given name that is also an ordinary word ("Вера", "Роман", "Лев")."""
    from pii_guard.languages.ru.names import _morph

    best = _morph().parse(word.lower())[0]
    return "Name" not in best.tag and "Surn" not in best.tag


def _sweep_patterns(person: Person) -> list[tuple[re.Pattern[str], bool]]:
    """(pattern, case-sensitive) for every written form of the person to sweep."""
    p = person.parts
    known = {"f": p.last, "i": p.first, "o": p.middle}
    forms: set[str] = set()
    for roles in _SWEPT:
        if all(known[r] for r in roles):
            for case in ("nomn", "gent", "datv", "accs", "ablt", "loct"):
                forms.add(inflect(p, roles, case))
    patterns: list[tuple[re.Pattern[str], bool]] = []
    if forms:
        alternation = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
        patterns.append(
            (re.compile(rf"(?<![\w-])(?:{alternation})(?![\w-])", re.IGNORECASE), False)
        )
    if p.first and not _common_word(p.first):
        first = {inflect(p, ("i",), c) for c in ("nomn", "gent", "datv", "accs", "ablt", "loct")}
        alternation = "|".join(re.escape(f) for f in sorted(first, key=len, reverse=True))
        patterns.append((re.compile(rf"(?<![\w-])(?:{alternation})(?![\w-])"), True))
    return patterns


def _overlaps(start: int, end: int, spans: Sequence[Span]) -> bool:
    return any(s.start < end and start < s.end for s in spans)


def prepare(
    texts: Sequence[str],
    spans: Sequence[Sequence[Span]],
    known_lemmas: Sequence[str],
    session_id: str,
) -> list[list[Span]]:
    """Spans with person lemmas, plus swept forms of every person, per text."""
    registry = Registry()
    persons = registry.persons
    for lemma in known_lemmas:  # the vault's persons keep their keys
        mention = parse(lemma)
        if mention is not None:
            persons.setdefault(lemma, Person(key=lemma, parts=mention.parts))
    out = _resolved(spans, persons)
    for person in persons.values():
        _sweep(person, texts, out)
    for found in out:
        found.sort(key=lambda s: (s.start, s.end))
    _remember(session_id, registry)
    return out


def _resolved(spans: Sequence[Sequence[Span]], persons: dict[str, Person]) -> list[list[Span]]:
    """Each parsed PERSON span with its person's key as ``lemma`` (richest mentions first)."""
    mentions: list[tuple[int, int, Mention]] = []
    for t, found in enumerate(spans):
        for s_index, span in enumerate(found):
            if span.entity_type is EntityType.PERSON:
                mention = parse(span.text)
                if mention is not None:
                    mentions.append((t, s_index, mention))
    lemma_of: dict[tuple[int, int], str] = {}
    for t, s_index, mention in sorted(mentions, key=lambda m: -_richness(m[2])):
        lemma_of[(t, s_index)] = _resolve(persons, mention).key
    out: list[list[Span]] = []
    for t, found in enumerate(spans):
        new = [
            replace(span, lemma=lemma_of[(t, i)]) if (t, i) in lemma_of else span
            for i, span in enumerate(found)
        ]
        out.append(new)
    return out


def _sweep(person: Person, texts: Sequence[str], out: list[list[Span]]) -> None:
    """Add every other written form of ``person`` in ``texts`` as a span (in place)."""
    patterns = _sweep_patterns(person)
    for t, text in enumerate(texts):
        for pattern, _ in patterns:
            for m in pattern.finditer(text):
                # A known person's form wins over an organization the NER guessed
                # ("смирновой" in chat): an organization is kept, so it would leak.
                out[t] = [
                    s
                    for s in out[t]
                    if not (
                        s.entity_type is EntityType.ORGANIZATION
                        and s.start < m.end()
                        and m.start() < s.end
                    )
                ]
                if _overlaps(m.start(), m.end(), out[t]):
                    continue
                out[t].append(
                        Span(
                            m.start(), m.end(), EntityType.PERSON, m.group(0), 0.75, DETECTOR,
                            lemma=person.key,
                        )
                    )  # fmt: skip


# --- 2. Labels on the way out --------------------------------------------------------


def _occurrences(original: str, first: Any, second: Any) -> list[tuple[int, str, str, str]]:
    """(position in the final text, placeholder, surface, text before the surface).

    ``first`` is the vault's report on ``original``; ``second`` the report of the remask
    pass on ``first.text`` (offsets in that text).
    """
    items: list[tuple[int, str, str, str]] = []
    delta = 0
    for start, end, placeholder in sorted(first.replacements):
        items.append((start + delta, placeholder, original[start:end], original[:start]))
        delta += len(placeholder) - (end - start)
    shifted: list[tuple[int, str, str, str]] = []
    second_items = sorted(second.replacements) if second is not None else []
    for pos, placeholder, surface, before in items:
        shift = sum(len(ph) - (e - s) for s, e, ph in second_items if e <= pos)
        shifted.append((pos + shift, placeholder, surface, before))
    delta = 0
    for start, end, placeholder in second_items:
        shifted.append((start + delta, placeholder, first.text[start:end], first.text[:start]))
        delta += len(placeholder) - (end - start)
    return sorted(shifted)


def render(final: str, original: str, first: Any, second: Any, session_id: str) -> str:
    """``final`` with each ``[[PERSON_id]]`` of a parsed mention written as a label."""
    registry = registry_of(session_id)
    if registry is None:
        return final
    pieces: list[str] = []
    cursor = 0
    for pos, placeholder, surface, before in _occurrences(original, first, second):
        if (
            not placeholder.startswith("[[" + _PREFIX)
            or final[pos : pos + len(placeholder)] != placeholder
        ):
            continue
        mention = parse(surface)
        if mention is None:
            continue
        pid = placeholder[2 + len(_PREFIX) : -2]
        person = _person_for(registry, mention)
        if person is None:
            continue
        registry.by_id[pid] = person
        person.roles = mention.roles
        person.style = "title" if mention.style == "lower" else mention.style
        case = case_before(before, len(before), mention.cases)
        pieces.append(final[cursor:pos])
        pieces.append(label(pid, person.parts.gender or mention.parts.gender, case))
        cursor = pos + len(placeholder)
    pieces.append(final[cursor:])
    return "".join(pieces)


def _person_for(registry: Registry, mention: Mention) -> Person | None:
    exact = [
        p
        for p in registry.persons.values()
        if p.parts.compatible(mention.parts) and p.parts.shared(mention.parts) >= 1
    ]
    if len(exact) == 1:
        return exact[0]
    return registry.persons.get(mention.parts.key())


def has_labels(text: str) -> bool:
    return LABEL_RE.search(text) is not None


# --- 3. Restoring labels in the answer ----------------------------------------------

_GREETING_BEFORE = re.compile(
    r"(?:\b(?:Уважаем\w*|Дорог\w*|Милая|Милый)\s+|(?:Здравствуйте|Добрый\s+\w+|Доброе\s+\w+|Привет)\s*,\s*)$",
    re.IGNORECASE,
)
_LINE_START = re.compile(r"(?:^|\n)[ \t*«\"]*$")
_PREPOSITION_BEFORE = re.compile(r"(?<![\w])(с|со|к|ко|в|во|о|об|обо)(\s+)$", re.IGNORECASE)
_VOWELS = "аеёиоуыэюя"


def _roles_for(person: Person, text: str, start: int, end: int) -> tuple[str, ...]:
    p = person.parts
    greeting = _GREETING_BEFORE.search(text[:start]) or (
        re.match(r"\s*!", text[end:]) and _LINE_START.search(text[:start])
    )
    if greeting and p.first:
        return ("i", "o") if p.middle else ("i",)
    known = {"f": p.last, "i": p.first, "o": p.middle, "IO": p.first_initial}
    roles = tuple(r for r in person.roles if known.get(r))
    if roles:
        return roles
    return tuple(r for r in ("f", "i", "o") if known[r])


def _preposition(word: str, name: str) -> str:
    """``с`` -> ``со`` before ``Смирновой``, ``о`` -> ``об`` before ``Ольге`` (and back)."""
    lower = word.lower()
    first = name[:1].lower()
    second = name[1:2].lower()
    base = {"со": "с", "ко": "к", "во": "в", "об": "о", "обо": "о"}.get(lower, lower)
    if base == "о":
        new = "об" if first in _VOWELS else "о"
    elif base in ("с", "к", "в"):
        heavy = {"с": "сзшжщ", "к": "кг", "в": "вф"}[base]
        new = base + "о" if first in heavy and second and second not in _VOWELS else base
    else:
        return word
    return new.capitalize() if word[:1].isupper() else new


def restore_labels(text: str, session: Any, registry: Registry | None) -> str:
    """Every label in ``text`` written as the person's name in the label's case."""
    pieces: list[str] = []
    cursor = 0
    for m in LABEL_RE.finditer(text):
        pid = m.group("id")
        person = registry.by_id.get(pid) if registry is not None else None
        if person is None:
            lemma = session.unmask(f"[[{_PREFIX}{pid}]]")
            if PLACEHOLDER_RE.fullmatch(lemma):
                continue  # not a value of this session: leave the label as written
            mention = parse(lemma)
            if mention is None:
                continue
            person = Person(key=lemma, parts=mention.parts, roles=mention.roles)
        case = read_label(m, text)
        roles = _roles_for(person, text, m.start(), m.end())
        name = inflect(person.parts, roles, case, person.style)
        head = text[cursor : m.start()]
        prep = _PREPOSITION_BEFORE.search(head)
        if prep is not None:
            head = head[: prep.start(1)] + _preposition(prep.group(1), name) + prep.group(2)
        pieces.append(head)
        pieces.append(name)
        cursor = m.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


_LABEL_PREFIX_RE = re.compile(
    r"(?:(?<![\w])(?:с|со|к|ко|в|во|о|об|обо)\s+)?"
    r"(?<![\w])[Пп](?:е(?:р(?:с(?:о(?:н[а-яё]{0,2}(?:[_\s-]?(?:[МмЖж][а-яё]{0,8})?(?:[_\s-]?[0-9a-f]{0,64})?)?)?)?)?)?)?$",
    re.IGNORECASE,
)


_TRAILING_PREPOSITION_RE = re.compile(r"(?<![\w])(?:с|со|к|ко|в|во|о|об|обо)\s*$", re.IGNORECASE)


def hold_from(buffer: str) -> int:
    """Index of a trailing part that may still become a label (with its preposition)."""
    window = max(0, len(buffer) - 100)
    m = _LABEL_PREFIX_RE.search(buffer, window)
    if m is not None:
        return m.start()
    # A preposition at the very end may still be followed by a label it must agree with.
    m = _TRAILING_PREPOSITION_RE.search(buffer, window)
    if m is not None:
        return m.start()
    # A complete label right at the end: its id may still grow.
    last = None
    for match in LABEL_RE.finditer(buffer, window):
        last = match
    if last is not None and last.end() == len(buffer):
        start = last.start()
        prep = _PREPOSITION_BEFORE.search(buffer[:start])
        return prep.start(1) if prep is not None else start
    return len(buffer)


class LabelSession:
    """A vault session that also restores ``Персона`` labels (the gateway's restore side)."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._registry = registry_of(session.session_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def __repr__(self) -> str:
        return f"LabelSession({self._session!r})"

    def restore_labels(self, text: str) -> str:
        return restore_labels(text, self._session, self._registry)

    def unmask(self, text: str, **kwargs: Any) -> str:
        return self._session.unmask(self.restore_labels(text), **kwargs)

    def unmask_with_report(self, text: str, **kwargs: Any) -> Any:
        return self._session.unmask_with_report(self.restore_labels(text), **kwargs)

    def hold_from(self, buffer: str) -> int:
        return hold_from(buffer)
