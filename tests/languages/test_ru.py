"""The Russian language pack (``ru``): check digits, rules, inflection."""

from __future__ import annotations

import pytest

from pii_guard.languages.ru.checksums import (
    account_key,
    inn10_check_digit,
    inn12_check_digits,
    is_valid_account,
    is_valid_inn,
    is_valid_ogrn,
    is_valid_ogrnip,
    is_valid_snils,
    snils_check_number,
)

# --- Check digits: published values ------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["7707083893", "500100732259"],  # a large bank's ИНН; the textbook example of a person's
)
def test_inn_published(value: str) -> None:
    assert is_valid_inn(value)


def test_snils_published() -> None:
    assert is_valid_snils("11223344595")


def test_ogrn_published() -> None:
    assert is_valid_ogrn("1027700132195")


def test_ogrnip_published() -> None:
    assert is_valid_ogrnip("304500116000157")


def test_correspondent_account_published() -> None:
    assert is_valid_account("044525225", "30101810400000000225")


# --- Check digits: any changed digit fails -----------------------------------------------


@pytest.mark.parametrize(
    ("check", "value"),
    [
        (is_valid_inn, "7707083893"),
        (is_valid_inn, "500100732259"),
        (is_valid_snils, "11223344595"),
        (is_valid_ogrn, "1027700132195"),
        (is_valid_ogrnip, "304500116000157"),
    ],
)
def test_changed_last_digit_fails(check, value: str) -> None:  # type: ignore[no-untyped-def]
    broken = value[:-1] + str((int(value[-1]) + 1) % 10)
    assert not check(broken)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "770708389",
        "77070838930",
        "770708389a",
        "0000000000",
        "000000000000",
        "".join(chr(0xFF10 + int(d)) for d in "7707083893"),  # full-width digits
    ],
)
def test_inn_rejects_malformed(value: str) -> None:
    assert not is_valid_inn(value)


def test_snils_without_check_number_range() -> None:
    # Numbers up to 001-001-998 carry no check number: never valid, whatever the tail.
    assert not is_valid_snils("00100199800")
    assert not is_valid_snils("00000000100")


@pytest.mark.parametrize("payload", ["123456789", "999999999", "001002003", "500100732"])
def test_snils_generated_round_trip(payload: str) -> None:
    value = payload + snils_check_number(payload)
    assert is_valid_snils(value) == (int(payload) > 1001998)


@pytest.mark.parametrize("payload", ["123456789", "770000001", "990000123"])
def test_inn10_generated_round_trip(payload: str) -> None:
    assert is_valid_inn(payload + str(inn10_check_digit(payload)))


@pytest.mark.parametrize("payload", ["1234567890", "7700000012", "9900001234"])
def test_inn12_generated_round_trip(payload: str) -> None:
    assert is_valid_inn(payload + inn12_check_digits(payload))


@pytest.mark.parametrize("correspondent", [False, True])
@pytest.mark.parametrize("account", ["40817810000000012345", "40702810500000000001"])
def test_account_key_round_trip(account: str, correspondent: bool) -> None:
    bik = "044525999"
    keyed = account[:8] + account_key(bik, account, correspondent=correspondent) + account[9:]
    assert is_valid_account(bik, keyed)


@pytest.mark.parametrize("bik", ["044535226", "044599111", "044511300"])
def test_account_rejects_wrong_bik(bik: str) -> None:
    # A correspondent account is keyed on БИК digits 5-6, a bank account on its last three:
    # these differ in both.
    assert not is_valid_account(bik, "30101810400000000225")


# --- Rules -------------------------------------------------------------------------------

from pii_guard.detect.rules import RuleDetector  # noqa: E402

# Made-up payloads with computed check digits (issued to nobody).
INN_PERSON = "7700000012" + inn12_check_digits("7700000012")
INN_ORG = "770000123" + str(inn10_check_digit("770000123"))
SNILS = "123456789" + snils_check_number("123456789")
SNILS_GROUPED = f"{SNILS[:3]}-{SNILS[3:6]}-{SNILS[6:9]} {SNILS[9:]}"
BIK = "044525999"
ACCOUNT = "40817810000000012345"
ACCOUNT = ACCOUNT[:8] + account_key(BIK, ACCOUNT) + ACCOUNT[9:]


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def _found(detector: RuleDetector, text: str, language: str = "ru") -> list[tuple[str, str]]:
    return [(s.entity_type.value, s.text) for s in detector.detect(text, language)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"ИНН {INN_PERSON}", ("ID_DOCUMENT", INN_PERSON)),
        (f"ИНН: {INN_ORG}", ("ID_DOCUMENT", INN_ORG)),
        (f"Покупатель {INN_PERSON} оплатил", ("ID_DOCUMENT", INN_PERSON)),
        (f"СНИЛС {SNILS}", ("ID_DOCUMENT", SNILS)),
        (f"номер {SNILS_GROUPED} в анкете", ("ID_DOCUMENT", SNILS_GROUPED)),
        (f"р/с {ACCOUNT}, БИК {BIK}", ("BANK_ACCOUNT", ACCOUNT)),
        ("Звоните 8 (916) 555-01-23 вечером", ("PHONE", "8 (916) 555-01-23")),
        ("тел 89165550147", ("PHONE", "89165550147")),
        ("офис (495) 555-01-99", ("PHONE", "(495) 555-01-99")),
        ("Звоните +7 916 555-01-23", ("PHONE", "+7 916 555-01-23")),
        ("Звоните 79165550147 вечером", ("PHONE", "79165550147")),
        ("Звоните 7 916 555-01-23 вечером", ("PHONE", "7 916 555-01-23")),
        ("Звоните 916 555-01-23 вечером", ("PHONE", "916 555-01-23")),
        ("паспорт серии 45 10 123456 выдан", ("ID_DOCUMENT", "45 10 123456")),
        ("Паспорт: серия 36 15 № 654321", ("ID_DOCUMENT", "36 15 № 654321")),
        ("водительское удостоверение 77 15 654321", ("ID_DOCUMENT", "77 15 654321")),
        ("загранпаспорт 75 1234567", ("ID_DOCUMENT", "75 1234567")),
        ("Полис ОМС 7700000012345678", ("ID_DOCUMENT", "7700000012345678")),
        ("госномер А123ВС777", ("VEHICLE_PLATE", "А123ВС777")),
        (
            "по адресу: г. Тверь, ул. Советская, д. 12, кв. 34.",
            ("ADDRESS", "г. Тверь, ул. Советская, д. 12, кв. 34"),
        ),
        (
            "Адрес: 620014, Свердловская обл., г. Екатеринбург, пр-т Ленина, д. 5, корп. 2, "
            "кв. 118",
            (
                "ADDRESS",
                "620014, Свердловская обл., г. Екатеринбург, пр-т Ленина, д. 5, корп. 2, кв. 118",
            ),
        ),
        (
            "Московская область, Одинцовский район, деревня Жуковка, улица Лесная, дом 3",
            (
                "ADDRESS",
                "Московская область, Одинцовский район, деревня Жуковка, улица Лесная, дом 3",
            ),
        ),
        ("адрес ул. Промышленная, д. 3, стр. 1.", ("ADDRESS", "ул. Промышленная, д. 3, стр. 1")),
        ("привезти на Садовую 14, квартира 7, домофон", ("ADDRESS", "Садовую 14, квартира 7")),
        ("живёт на Советской улице, 8", ("ADDRESS", "Советской улице, 8")),
    ],
)
def test_rule_finds(detector: RuleDetector, text: str, expected: tuple[str, str]) -> None:
    assert expected in _found(detector, text)


@pytest.mark.parametrize(
    "text",
    [
        "Заказ № 89165550123 отгружен со склада.",
        "Артикул 4510-123456, партия 770-001.",
        "склад на улице Ленина закрыт на ремонт",
        "Отправили из Владимира в Орёл.",
        "Итого 1 987 000 руб., НДС 20 %.",
        f"длинный список {INN_ORG} позиций",  # 10-digit ИНН: masked only after its label
        f"БИК {BIK}",
        "Счёт на оплату № 512 от 03.11.2026",
        "Версия 2.14, ответ за 420 мс, 15 000 экземпляров.",
        "Глава 14, квартал 3.",
        "Заказ № 79165550123 отгружен.",
        "Звоните 555-01-23 вечером.",  # a seven-digit local number: only after its cue
        "Накладная 916 555-01-23 оформлена.",
        "Вес 916 555 кг, объём 01 23.",
    ],
)
def test_rule_leaves_alone(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


def test_snils_grouped_runs_for_other_languages(detector: RuleDetector) -> None:
    assert ("ID_DOCUMENT", SNILS_GROUPED) in _found(detector, f"SNILS {SNILS_GROUPED}", "en")


def test_unlabelled_inn_is_russian_only(detector: RuleDetector) -> None:
    assert _found(detector, f"Customer {INN_PERSON} paid", "en") == []
