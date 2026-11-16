"""Russian person names: parse a written mention, inflect it, read and write ``Персона`` labels.

A mention is how a name is written in the text: which parts it has (surname ``f``, given
name ``i``, patronymic ``o``; initials ``I``/``O``), in which order, and in which grammatical
case. ``parse`` reads it with pymorphy3 (names, surnames, patronymics in its dictionary) and
falls back to pytrovich for surnames and given names the dictionary lacks: a candidate
nominative is accepted only if pytrovich inflects it back to the written form.

``inflect`` writes known parts in a case (pytrovich). ``label`` / ``read_labels`` write and
read the word labels the upstream model sees instead of ``[[PERSON_id]]``:
``Персона_Женщина_7f3a`` declines like a name (``Персоне_Женщине_7f3a``), so the case of
every mention the model writes can be read back (docs/ru/README.md).

Nothing here logs or raises with a name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from itertools import product

__all__ = [
    "CASES",
    "LABEL_RE",
    "Mention",
    "NameParts",
    "case_before",
    "inflect",
    "label",
    "parse",
    "read_label",
]

#: pymorphy case tags, in the order a tie is resolved.
CASES = ("nomn", "gent", "datv", "accs", "ablt", "loct")
_ROLE_TAG = {"Surn": "f", "Name": "i", "Patr": "o"}
_INITIALS_RE = re.compile(r"^([А-ЯЁ])\.(?:\s*([А-ЯЁ])\.)?$")
_WORD_RE = re.compile(r"[А-ЯЁа-яё]+(?:-[А-ЯЁа-яё]+)?")
_TOKEN_RE = re.compile(r"[А-ЯЁ]\.\s*(?:[А-ЯЁ]\.)?|[А-ЯЁа-яё]+(?:-[А-ЯЁа-яё]+)?")
# Word orders a written name takes (initials as I/O).
_PATTERNS: dict[int, tuple[tuple[str, ...], ...]] = {
    1: (("f",), ("i",)),
    2: (("i", "o"), ("i", "f"), ("f", "i"), ("f", "IO"), ("IO", "f")),
    3: (("f", "i", "o"), ("i", "o", "f")),
}


@dataclass(frozen=True, slots=True)
class NameParts:
    """What is known of a person's name, in the nominative. Never repr'd with values."""

    last: str | None = None
    first: str | None = None
    middle: str | None = None
    first_initial: str | None = None
    middle_initial: str | None = None
    gender: str | None = None  # "m", "f" or None (unknown)

    def __repr__(self) -> str:
        known = [k for k in ("last", "first", "middle") if getattr(self, k)]
        return f"NameParts(known={known}, gender={self.gender!r})"

    def key(self) -> str:
        """The vault lemma: the known full parts, surname first, in the nominative."""
        words = [w for w in (self.last, self.first, self.middle) if w]
        if self.first is None and self.first_initial:
            words.append(self.first_initial + ".")
        if self.middle is None and self.middle_initial:
            words.append(self.middle_initial + ".")
        return " ".join(words)

    def merged(self, other: NameParts) -> NameParts:
        return NameParts(
            last=self.last or other.last,
            first=self.first or other.first,
            middle=self.middle or other.middle,
            first_initial=self.first_initial or other.first_initial,
            middle_initial=self.middle_initial or other.middle_initial,
            gender=self.gender or other.gender,
        )

    def compatible(self, other: NameParts) -> bool:
        """No known part contradicts the other's (initials match their full names)."""
        if self.gender and other.gender and self.gender != other.gender:
            return False
        for a, b in (
            (self.last, other.last),
            (self.first, other.first),
            (self.middle, other.middle),
        ):
            if a and b and _fold(a) != _fold(b):
                return False
        pairs = (
            (self.first or self.first_initial, other.first or other.first_initial),
            (self.middle or self.middle_initial, other.middle or other.middle_initial),
        )
        return all(not (a and b) or _fold(a)[0] == _fold(b)[0] for a, b in pairs)

    def shared(self, other: NameParts) -> int:
        """How many full parts both know and agree on."""
        return sum(
            1
            for a, b in (
                (self.last, other.last),
                (self.first, other.first),
                (self.middle, other.middle),
            )
            if a and b and _fold(a) == _fold(b)
        )


@dataclass(frozen=True, slots=True)
class Mention:
    """One written name: its parts, the order they were written in, and its case(s)."""

    parts: NameParts
    roles: tuple[str, ...]  # e.g. ("f", "i", "o"), ("i", "o"), ("f", "IO")
    cases: tuple[str, ...]  # every case the written form can be, most likely first
    style: str = "title"  # "title", "upper" or "lower"
    score: float = field(default=0.0, compare=False)

    def __repr__(self) -> str:
        return f"Mention(roles={self.roles}, cases={self.cases}, style={self.style!r})"


def _fold(word: str) -> str:
    return word.casefold().replace("ё", "е")


def _style(surface: str) -> str:
    letters = [c for c in surface if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) > 2:
        return "upper"
    if letters and all(c.islower() for c in letters):
        return "lower"
    return "title"


def _styled(text: str, style: str) -> str:
    if style == "upper":
        return text.upper()
    if style == "lower":
        return text.lower()
    return text


def _title(word: str) -> str:
    return "-".join(p[:1].upper() + p[1:].lower() for p in word.split("-"))


@lru_cache(maxsize=1)
def _morph():  # type: ignore[no-untyped-def]
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=1)
def _petrovich():  # type: ignore[no-untyped-def]
    from pytrovich.maker import PetrovichDeclinationMaker

    return PetrovichDeclinationMaker()


def _pt_case(case: str):  # type: ignore[no-untyped-def]
    from pytrovich.enums import Case

    return {
        "gent": Case.GENITIVE,
        "datv": Case.DATIVE,
        "accs": Case.ACCUSATIVE,
        "ablt": Case.INSTRUMENTAL,
        "loct": Case.PREPOSITIONAL,
    }.get(case)


def _pt_make(role: str, gender: str, case: str, word: str) -> str:
    from pytrovich.enums import Gender, NamePart

    pt_case = _pt_case(case)
    if pt_case is None:
        return word
    part = {"f": NamePart.LASTNAME, "i": NamePart.FIRSTNAME, "o": NamePart.MIDDLENAME}[role]
    g = Gender.FEMALE if gender == "f" else Gender.MALE
    try:
        return str(_petrovich().make(part, g, pt_case, word))
    except Exception:
        return word


# A token's readings: (role, case, gender, nominative, score).
_Reading = tuple[str, str, str | None, str, float]
_SURNAME_ENDINGS = (
    "ов", "ев", "ёв", "ин", "ын", "ова", "ева", "ёва", "ина", "ына", "ский", "ская", "цкий", "цкая",
)  # fmt: skip
_MIN_SCORE = 0.02
# Nominative endings tried for words the dictionary lacks (pytrovich then checks the guess).
_NOM_ENDINGS = ("", "а", "я", "й", "ь", "ий", "ой", "ая", "ов", "ев", "ин", "ова", "ева", "ина")


@lru_cache(maxsize=4096)
def _readings(word: str) -> tuple[_Reading, ...]:
    out: list[_Reading] = []
    seen_roles: set[str] = set()
    parses = _morph().parse(word)
    # Roles the word can take in a declinable reading ("Анне" from "Анна"): an indeclinable
    # reading of that role ("Анне" as a foreign name) then yields to it. A surname that only
    # has indeclinable readings ("Белых") keeps its full weight.
    declinable = {
        r for p in parses for t, r in _ROLE_TAG.items() if t in p.tag and "Fixd" not in p.tag
    }
    for p in parses:
        tag = p.tag
        role = next((r for t, r in _ROLE_TAG.items() if t in tag), None)
        if role is None or tag.case not in CASES or tag.number == "plur":
            continue
        gender = {"masc": "m", "femn": "f"}.get(str(tag.gender))  # "ms-f" and None: unknown
        nominative = p.inflect({"nomn"})
        nom = nominative.word if nominative is not None else p.normal_form
        # A dictionary reading always outweighs a guess (below); an indeclinable reading
        # ("Анне" as a foreign name) yields to a declinable one ("Анне" from "Анна").
        score = 0.2 + 0.8 * float(p.score)
        if "Fixd" in tag and role in declinable:
            score *= 0.3
        out.append((role, str(tag.case), gender, _title(nom), score))
        seen_roles.add(role)
    # Surnames and given names the dictionary lacks: guess a nominative, keep it only if
    # pytrovich writes it back exactly (in the nominative the word is its own guess).
    for role in ("f", "i"):
        if role in seen_roles or not word[:1].isupper():
            continue
        folded = word.lower()
        for gender, case in product(("m", "f"), CASES):
            if case == "nomn":
                # The word as its own nominative: the weakest guess, below any form
                # pytrovich confirms.
                typical = role == "f" and folded.endswith(_SURNAME_ENDINGS)
                out.append((role, case, gender, _title(word), 0.03 if typical else 0.01))
                continue
            for cut in range(0, min(3, len(folded) - 2) + 1):
                stem = folded[: len(folded) - cut] if cut else folded
                for ending in _NOM_ENDINGS:
                    guess = _title(stem + ending)
                    if _pt_make(role, gender, case, guess).lower() == folded:
                        typical = role == "f" and guess.lower().endswith(_SURNAME_ENDINGS)
                        # Unchanged: read as indeclinable, the weakest confirmed guess.
                        weight = 0.005 if guess.lower() == folded else 0.06 if typical else 0.04
                        out.append((role, case, gender, guess, weight))
    return tuple(out)


def parse(surface: str) -> Mention | None:
    """Read a written name; ``None`` if it does not look like one."""
    tokens = _TOKEN_RE.findall(surface)
    if not tokens or len(tokens) > 3:
        return None
    style = _style(surface)
    best: Mention | None = None
    for pattern in _PATTERNS.get(len(tokens), ()):
        mention = _fit(tokens, pattern, style)
        if mention is not None and (best is None or mention.score > best.score):
            best = mention
    # Only the weakest guess ("the word is its own nominative"): not evidence of a name.
    return best if best is not None and best.score >= _MIN_SCORE else None


def _fit(tokens: list[str], pattern: tuple[str, ...], style: str) -> Mention | None:
    options: list[list[_Reading]] = []
    initials: tuple[str | None, str | None] = (None, None)
    for token, role in zip(tokens, pattern, strict=True):
        if role == "IO":
            m = _INITIALS_RE.match(token.replace(" ", ""))
            if m is None:
                return None
            initials = (m.group(1), m.group(2))
            options.append([("IO", "*", None, token, 1.0)])
            continue
        if not _WORD_RE.fullmatch(token):
            return None
        word = _title(token) if style != "title" else token
        found = [r for r in _readings(word) if r[0] == role]
        if not found:
            return None
        options.append(found)
    best = _best_combo(options, pattern, initials, style)
    if best is None:
        return None
    # Every case the same written form can be in ("Смирновой": gent, datv, ablt, loct).
    first = inflect(best.parts, best.roles, best.cases[0])
    same = [c for c in CASES if c != best.cases[0] and inflect(best.parts, best.roles, c) == first]
    return replace(best, cases=(best.cases[0], *same))


def _best_combo(
    options: list[list[_Reading]],
    pattern: tuple[str, ...],
    initials: tuple[str | None, str | None],
    style: str,
) -> Mention | None:
    best: Mention | None = None
    for combo in product(*options):
        cases = {r[1] for r in combo if r[1] != "*"}
        if len(cases) > 1:
            continue
        genders = {r[2] for r in combo if r[2] is not None}
        if len(genders) > 1:
            continue
        score = 1.0
        for r in combo:
            score *= r[4]
        if best is not None and score <= best.score:
            continue
        parts = {"f": None, "i": None, "o": None}
        for r in combo:
            if r[0] in parts:
                parts[r[0]] = r[3]
        case = next(iter(cases)) if cases else "nomn"
        best = Mention(
            parts=NameParts(
                last=parts["f"],
                first=parts["i"],
                middle=parts["o"],
                first_initial=initials[0],
                middle_initial=initials[1],
                gender=next(iter(genders)) if genders else None,
            ),
            roles=pattern,
            cases=(case,),
            style=style,
            score=score,
        )
    return best


def inflect(parts: NameParts, roles: tuple[str, ...], case: str, style: str = "title") -> str:
    """The known parts in ``roles`` order, in ``case`` (initials stay as written)."""
    gender = parts.gender or "m"
    words: list[str] = []
    for role in roles:
        if role == "IO":
            words.append(
                " ".join(f"{x}." for x in (parts.first_initial, parts.middle_initial) if x)
            )
            continue
        word = {"f": parts.last, "i": parts.first, "o": parts.middle}[role]
        if word is None:
            initial = {"i": parts.first_initial, "o": parts.middle_initial}.get(role)
            if initial:
                words.append(initial + ".")
            continue
        words.append(_pt_make(role, gender, case, word))
    return _styled(" ".join(w for w in words if w), style)


# --- Labels ----------------------------------------------------------------------------

_PERSONA = {
    "nomn": "Персона",
    "gent": "Персоны",
    "datv": "Персоне",
    "accs": "Персону",
    "ablt": "Персоной",
    "loct": "Персоне",
}
_MAN = {
    "nomn": "Мужчина",
    "gent": "Мужчины",
    "datv": "Мужчине",
    "accs": "Мужчину",
    "ablt": "Мужчиной",
    "loct": "Мужчине",
}
_WOMAN = {
    "nomn": "Женщина",
    "gent": "Женщины",
    "datv": "Женщине",
    "accs": "Женщину",
    "ablt": "Женщиной",
    "loct": "Женщине",
}
_READ: dict[str, tuple[str, ...]] = {}
for _table in (_PERSONA, _MAN, _WOMAN):
    for _case, _form in _table.items():
        _READ[_fold(_form)] = (*_READ.get(_fold(_form), ()), _case)
for _stem in ("персон", "мужчин", "женщин"):
    _READ[_stem + "ою"] = ("ablt",)

#: A label as the model may write it: words joined by ``_``, a space or a hyphen.
LABEL_RE = re.compile(
    r"(?<![\w])(?P<first>[Пп]ерсон[а-яё]{0,2})[_\s-]?"
    r"(?:(?P<gender>[МмЖж](?:ужчин|енщин)[а-яё]{0,2})[_\s-]?)?"
    r"(?P<id>[0-9a-f]{4,64})(?![0-9a-zA-Z_])"
)
# Prepositions that take the prepositional case (to tell it from the dative: "Персоне").
_LOCATIVE_BEFORE = re.compile(r"(?:^|[\s(«\"'])(?:о|об|обо|при|в|во|на)\s+$", re.IGNORECASE)


def label(placeholder_id: str, gender: str | None, case: str) -> str:
    """``Персона_Женщина_7f3a`` in ``case``; ``Персона_7f3a`` when the gender is unknown."""
    case = case if case in _PERSONA else "nomn"
    if gender == "m":
        return f"{_PERSONA[case]}_{_MAN[case]}_{placeholder_id}"
    if gender == "f":
        return f"{_PERSONA[case]}_{_WOMAN[case]}_{placeholder_id}"
    return f"{_PERSONA[case]}_{placeholder_id}"


def read_label(match: re.Match[str], text: str) -> str:
    """The case a label match is written in (the dative and prepositional by the word before)."""
    first = _READ.get(_fold(match.group("first")), ())
    second = _READ.get(_fold(match.group("gender") or ""), ()) if match.group("gender") else ()
    cases = [c for c in first if not second or c in second] or list(first or second or ("nomn",))
    if set(cases) >= {"datv", "loct"}:
        return "loct" if _LOCATIVE_BEFORE.search(text[: match.start()]) else "datv"
    return cases[0]


# --- Case of a mention from the words before it ----------------------------------------

_GOVERNS = {
    "gent": (
        "у", "для", "от", "до", "без", "из", "около", "возле", "кроме", "против", "вместо",
        "среди",
    ),
    "datv": ("к", "ко", "по", "благодаря", "согласно"),
    "ablt": ("с", "со", "над", "под", "перед", "между"),
    "loct": ("о", "об", "обо", "при"),
}  # fmt: skip
_WORD_BEFORE = re.compile(r"([А-ЯЁа-яё]+)\s*$")


def case_before(text: str, start: int, cases: tuple[str, ...]) -> str:
    """Pick one of ``cases`` for a mention at ``start`` from the preposition before it."""
    if len(cases) == 1:
        return cases[0]
    m = _WORD_BEFORE.search(text[max(0, start - 20) : start])
    if m is not None:
        word = m.group(1).casefold()
        for case, words in _GOVERNS.items():
            if word in words and case in cases:
                return case
    return cases[0]
