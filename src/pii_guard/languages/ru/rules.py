"""Russian rules (our fork; see ``docs/ru/README.md``).

``EVERYWHERE`` (validated, run for every language): ИНН, ОГРН, ОГРНИП and a compact СНИЛС
next to their label; a СНИЛС in its printed layout ``XXX-XXX-XXX YY``, which no other
identifier shares.

``RULES`` (Russian text only): unlabelled ИНН (12 digits), ОГРНИП and ОГРН; bank accounts
(20 digits with a balance-account prefix and a currency code, validated against a БИК in the
text when there is one); national phone numbers (``8 (916) 555-01-23``, ``89165550123``,
``(495) 555-01-99``); passport, foreign passport, driving licence and ОМС policy numbers next
to their label (none has a check digit); vehicle plates; postal addresses with a house number.

Every identifier is ``ID_DOCUMENT``, as for the other packs. Labels are matched as whole
words (``инн`` is not found inside ``длинный``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from pii_guard.detect.rules._base import (
    VALIDATED_ID_DOCUMENT,
    Rule,
    _Hit,
    reference_or_amount_before,
)
from pii_guard.languages.ru.checksums import (
    is_valid_account,
    is_valid_inn,
    is_valid_ogrn,
    is_valid_ogrnip,
    is_valid_snils,
)
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES"]

_UP = "А-ЯЁ"
_LO = "а-яё"
# A Russian amount: a currency word or sign right after the number.
_NOT_AMOUNT = r"(?![ \t]?(?:руб\w*|₽|RUB|р\.|коп\w*|USD|EUR|€|\$)(?!\w))"
# Digit-run boundaries: no digit (or a digit and a separator) on either side.
_NUM_START = r"(?<!\d)(?<!\d[-./ ])"
_NUM_END = r"(?!\d)(?![-./ ]\d)"
_LABEL_WINDOW = 40


def _compact(value: str) -> str:
    return re.sub(r"[\s\-№]", "", value)


def _label_re(*words: str) -> re.Pattern[str]:
    """A whole-word label: ``инн`` but not ``длинный``; a trailing ``*`` takes endings."""
    parts = [re.escape(w[:-1]) + r"\w*" if w.endswith("*") else re.escape(w) for w in words]
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


def _labelled_by(text: str, start: int, label: re.Pattern[str]) -> bool:
    """Whether ``label`` ends within :data:`_LABEL_WINDOW` characters before ``start``,
    on the same line."""
    window = text[max(0, start - _LABEL_WINDOW) : start]
    window = window.rsplit("\n", 1)[-1]
    return label.search(window) is not None


def _reference_before(text: str, start: int) -> bool:
    return reference_or_amount_before(text, start)


# --- Tax and registration numbers ------------------------------------------------------

_INN_LABEL = _label_re("инн", "inn", "идентификационный номер налогоплательщика")
_SNILS_LABEL = _label_re("снилс", "snils", "страховой номер*", "страхового номера")
_OGRN_LABEL = _label_re("огрн", "огрнип", "ogrn", "ogrnip")

_INN_RE = re.compile(_NUM_START + r"(?P<value>\d{12}|\d{10})" + _NUM_END + _NOT_AMOUNT)
_SNILS_GROUPED_RE = re.compile(
    r"(?<![\d-])(?P<value>\d{3}-\d{3}-\d{3}[ \t-]\d{2})(?![\d-])(?![ \t]\d)"
)
_SNILS_COMPACT_RE = re.compile(_NUM_START + r"(?P<value>\d{11})" + _NUM_END)
_OGRN_RE = re.compile(_NUM_START + r"(?P<value>\d{15}|\d{13})" + _NUM_END)


def _id_rule(
    pattern: re.Pattern[str],
    valid: Callable[[str], bool],
    label: re.Pattern[str] | None,
    score: float,
    *,
    labelled: bool,
) -> Rule:
    """A validated number with (``labelled``) or without its label before it."""

    def rule(text: str) -> Iterator[_Hit]:
        for m in pattern.finditer(text):
            value = _compact(m.group("value"))
            if not valid(value):
                continue
            has_label = label is not None and _labelled_by(text, m.start("value"), label)
            if labelled != has_label:
                continue
            if not labelled and _reference_before(text, m.start("value")):
                continue
            yield _Hit(
                m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, score,
                VALIDATED_ID_DOCUMENT,
            )  # fmt: skip

    return rule


def _is_person_inn(value: str) -> bool:
    return len(value) == 12 and is_valid_inn(value)


_find_labelled_inn = _id_rule(_INN_RE, is_valid_inn, _INN_LABEL, 0.97, labelled=True)
_find_inn = _id_rule(_INN_RE, _is_person_inn, _INN_LABEL, 0.85, labelled=False)
_find_labelled_snils = _id_rule(
    _SNILS_COMPACT_RE, is_valid_snils, _SNILS_LABEL, 0.97, labelled=True
)
_find_labelled_ogrn = _id_rule(
    _OGRN_RE, lambda v: is_valid_ogrn(v) or is_valid_ogrnip(v), _OGRN_LABEL, 0.97, labelled=True
)
_find_ogrnip = _id_rule(_OGRN_RE, is_valid_ogrnip, _OGRN_LABEL, 0.85, labelled=False)
_find_ogrn = _id_rule(_OGRN_RE, is_valid_ogrn, _OGRN_LABEL, 0.75, labelled=False)


def _find_snils_grouped(text: str) -> Iterator[_Hit]:
    for m in _SNILS_GROUPED_RE.finditer(text):
        if is_valid_snils(_compact(m.group("value"))):
            yield _Hit(
                m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, 0.95,
                VALIDATED_ID_DOCUMENT,
            )  # fmt: skip


# --- Bank accounts ---------------------------------------------------------------------

# 20 digits, optionally in groups. The balance-account prefix (301xx-302xx for banks'
# accounts, 401xx-408xx for organizations and people, 420xx-426xx for deposits) and the
# currency code in digits 6-8 make a 20-digit run an account; a БИК in the text validates its
# key.
_ACCOUNT_RE = re.compile(
    r"(?<!\d)(?<!\d[ \t])(?P<value>\d(?:[ \t]?\d){19})(?![ \t]?\d)" + _NOT_AMOUNT
)
_ACCOUNT_PREFIX = re.compile(r"(?:30[12]|40[1-8]|42[0-6])\d\d(?:810|643|840|978|156|826|756)")
_BIK_RE = re.compile(r"(?<!\w)БИК[ \t:№]*(\d{9})(?!\d)", re.IGNORECASE)


def _find_account(text: str) -> Iterator[_Hit]:
    biks = [m.group(1) for m in _BIK_RE.finditer(text)]
    for m in _ACCOUNT_RE.finditer(text):
        value = _compact(m.group("value"))
        if not _ACCOUNT_PREFIX.match(value):
            continue
        if _reference_before(text, m.start("value")):
            continue
        score = 0.95 if any(is_valid_account(bik, value) for bik in biks) else 0.8
        yield _Hit(m.start("value"), m.end("value"), EntityType.BANK_ACCOUNT, score)


# --- Phone numbers ---------------------------------------------------------------------

# ``8``/``+7`` and a ten-digit number whose code starts 3, 4, 8 or 9 (geographic codes and
# mobile networks), in the usual groupings; or a code in parentheses without the prefix.
_PHONE_RE = re.compile(
    r"(?<![\w+(])(?<!\d[-./ ])"
    r"(?P<value>(?:(?:\+7|8)[ \t-]?\(?[3489]\d{2}\)?|\([3489]\d{2}\))"
    r"[ \t-]?\d{3}[ \t-]?\d{2}[ \t-]?\d{2})"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT
)
# A mobile number (code 9xx) without ``+`` or ``8``: ``79165550147`` compact, or in groups
# with or without the country code (``7 916 555-01-23``, ``916 555-01-23``). A compact
# ten-digit run and a seven-digit local number are left to their cue (cues.tsv).
_MOBILE_RE = re.compile(
    r"(?<![\w+(])(?<!\d[-./ ])"
    r"(?P<value>79\d{9}|(?:7[ \t-])?\(?9\d{2}\)?[ \t-]\d{3}[ \t-]\d{2}[ \t-]?\d{2})"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT
)


def _find_phone(text: str) -> Iterator[_Hit]:
    for m in _PHONE_RE.finditer(text):
        if not _reference_before(text, m.start("value")):
            yield _Hit(m.start("value"), m.end("value"), EntityType.PHONE, 0.85)
    for m in _MOBILE_RE.finditer(text):
        if not _reference_before(text, m.start("value")):
            yield _Hit(m.start("value"), m.end("value"), EntityType.PHONE, 0.75)


# --- Documents without a check digit: masked next to their label ----------------------

_PASSPORT_LABEL = _label_re("паспорт*", "серия", "серии", "серию")
_FOREIGN_LABEL = _label_re(
    "загранпаспорт*", "заграничный паспорт", "заграничного паспорта", "загран"
)
_LICENCE_LABEL = _label_re(
    "водительское удостоверение", "водительского удостоверения", "водительские права",
    "водительских прав", "права", "ву", "в/у",
)  # fmt: skip
_OMS_LABEL = _label_re("омс", "полис*", "енп")

_PASSPORT_RE = re.compile(
    _NUM_START + r"(?P<value>\d{2}[ \t]?\d{2}[ \t]*(?:№[ \t]*)?\d{6})" + _NUM_END
)
_FOREIGN_RE = re.compile(_NUM_START + r"(?P<value>\d{2}[ \t]*(?:№[ \t]*)?\d{7})" + _NUM_END)
_LICENCE_RE = re.compile(
    r"(?<![\w-])(?P<value>\d{2}[ \t]?(?:\d{2}|[" + _UP + r"]{2})[ \t]*(?:№[ \t]*)?\d{6})" + _NUM_END
)
_OMS_RE = re.compile(_NUM_START + r"(?P<value>\d{4}(?:[ \t]?\d{4}){3})" + _NUM_END)


def _labelled_document(pattern: re.Pattern[str], label: re.Pattern[str]) -> Rule:
    def rule(text: str) -> Iterator[_Hit]:
        for m in pattern.finditer(text):
            if _labelled_by(text, m.start("value"), label) and not _reference_before(
                text, m.start("value")
            ):
                yield _Hit(m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, 0.9)

    return rule


_find_passport = _labelled_document(_PASSPORT_RE, _PASSPORT_LABEL)
_find_foreign_passport = _labelled_document(_FOREIGN_RE, _FOREIGN_LABEL)
_find_driving_licence = _labelled_document(_LICENCE_RE, _LICENCE_LABEL)
_find_oms = _labelled_document(_OMS_RE, _OMS_LABEL)


# --- Vehicle plates --------------------------------------------------------------------

# ``А123ВС777``: a letter, three digits, two letters and a two- or three-digit region, in
# the twelve letters plates use (Cyrillic, or their Latin look-alikes; at least one letter
# must be Cyrillic, so a code in Latin text is left alone).
_PLATE_LETTER = "АВЕКМНОРСТУХABEKMHOPCTYX"
_PLATE_RE = re.compile(
    rf"(?<![\w-])(?P<value>[{_PLATE_LETTER}][ \t]?\d{{3}}[ \t]?[{_PLATE_LETTER}]{{2}}"
    rf"[ \t]?\d{{2,3}})(?![\w-])"
)


def _find_plate(text: str) -> Iterator[_Hit]:
    for m in _PLATE_RE.finditer(text):
        if re.search(f"[{_UP}]", m.group("value")):
            yield _Hit(m.start("value"), m.end("value"), EntityType.VEHICLE_PLATE, 0.85)


# --- Addresses -------------------------------------------------------------------------

# A street (a type word before or after its name) and a house number, optionally preceded
# by a chain of postcode, region, district and locality, each followed by a comma. A street
# without a house number is not an address ("склад на улице Ленина").
_NAME_WORD = (
    rf"(?:[{_UP}][{_LO}]+(?:-[{_UP}]?[{_LO}]+)?|\d{{1,3}}-?(?:я|й|е|го|ая|ой|ий)|[{_UP}]\.)"
)
_STREET_NAME = rf"(?:\d{{1,2}}[ \t]+)?{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,3}}"
_TYPE_BEFORE = (
    r"(?:ул\.|ул(?=[ \t])|улиц[аеыуй]|улицей|пр-кт|пр-т|просп\.|проспект\w*|пер\.|переул\w+"
    r"|б-р|бульвар\w*|ш\.|шоссе|наб\.|набережн\w+|пл\.|площад\w+|пр-д|проезд\w*|туп\.|тупик\w*"
    r"|мкр\.?|микрорайон\w*|алле[яиюей]|линия|линии|тракт\w*)"
)
_TYPE_AFTER = (
    r"(?:ул\.|улиц[аеыуй]|улицей|проспект\w*|пр-т|переул\w+|пер\.|бульвар\w*|шоссе"
    r"|набережн\w+|площад\w+|проезд\w*|тупик\w*)"
)
_HOUSE_MARK = r"(?:д\.|дом|дома|доме|вл\.|владение)"
_HOUSE_NO = rf"\d{{1,4}}(?:[ \t]?[{_UP}{_LO}](?![{_LO}]))?(?:/\d{{1,4}}[{_UP}{_LO}]?)?"
_BUILDING = (
    rf"(?:,?[ \t]*(?:корп\.|корпус|к\.|стр\.|строение|лит\.|литера)[ \t]*[\d{_UP}{_LO}]{{1,4}}"
    rf"(?![{_LO}]))"
)
_FLAT = r"(?:,?[ \t]*(?:кв\.|квартира|кв|оф\.|офис|пом\.|помещение|комн\.|комната)[ \t]*\d{1,5})"
_HOUSE = rf"(?:(?i:{_HOUSE_MARK})[ \t]*)?{_HOUSE_NO}(?:{_BUILDING})*(?:{_FLAT})?"
_STREET = rf"(?:(?i:{_TYPE_BEFORE})[ \t]*{_STREET_NAME}|{_STREET_NAME}[ \t]+(?i:{_TYPE_AFTER}))"
_LOCALITY = (
    r"(?:г\.|гор\.|город|пос\.|пос[её]лок|пгт|с\.|село|д\.|дер\.|деревня|ст-ца|станица|х\.|хутор)"
    rf"[ \t]*{_NAME_WORD}(?:[- ]{_NAME_WORD})?"
)
_REGION = (
    rf"(?:{_NAME_WORD}(?:[ \t]+{_NAME_WORD})?[ \t]+(?:обл\.|область|край|р-н|район|АО)"
    rf"|(?:респ\.|Республика)[ \t]+{_NAME_WORD}(?:[ \t]+{_NAME_WORD})?)"
)
_PREFIX = rf"(?:(?:\d{{6}}|{_REGION}|{_LOCALITY}|Россия|РФ)[ \t]*,[ \t]*)*"
_ADDRESS_RE = re.compile(
    rf"(?<![\w.]){_PREFIX}(?:{_STREET},?[ \t]*{_HOUSE}"
    rf"|{_LOCALITY},?[ \t]*(?i:{_HOUSE_MARK})[ \t]*{_HOUSE_NO}(?:{_BUILDING})*(?:{_FLAT})?)"
    r"(?![\w/])"
)
# Informal, no street type: "на Садовую 14, квартира 7". Needs a flat or office number.
_INFORMAL_ADDRESS_RE = re.compile(
    rf"(?:(?<=на )|(?<=по )|(?<=в ))(?P<value>{_NAME_WORD}[ \t]+{_HOUSE_NO}(?:{_BUILDING})*"
    rf"(?i:{_FLAT}))(?![\w/])"
)


def _find_address(text: str) -> Iterator[_Hit]:
    for m in _ADDRESS_RE.finditer(text):
        yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.85)
    for m in _INFORMAL_ADDRESS_RE.finditer(text):
        yield _Hit(m.start("value"), m.end("value"), EntityType.ADDRESS, 0.75)


EVERYWHERE: tuple[Rule, ...] = (
    _find_labelled_inn,
    _find_labelled_snils,
    _find_snils_grouped,
    _find_labelled_ogrn,
)
RULES: tuple[Rule, ...] = (
    _find_inn,
    _find_ogrnip,
    _find_ogrn,
    _find_account,
    _find_phone,
    _find_passport,
    _find_foreign_passport,
    _find_driving_licence,
    _find_oms,
    _find_plate,
    _find_address,
)
