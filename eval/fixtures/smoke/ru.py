"""Russian smoke fixtures: ``ru-smoke.jsonl`` (the Russian pack's). Built by
``eval/fixtures/build_smoke.py``; fictional values only (ADR 0005)."""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import BANK, DOB, IDD, ORG, PH, PLATE, A, E, P

from pii_guard.eval import Document, from_markup
from pii_guard.languages.ru.checksums import (
    account_key,
    inn10_check_digit,
    inn12_check_digits,
    ogrn_check_digit,
    ogrnip_check_digit,
    snils_check_number,
)


def inn10(payload9: str) -> str:
    return payload9 + str(inn10_check_digit(payload9))


def inn12(payload10: str) -> str:
    return payload10 + inn12_check_digits(payload10)


def snils(payload9: str, layout: str = "grouped") -> str:
    """A valid СНИЛС, ``XXX-XXX-XXX YY`` or compact."""
    digits = payload9 + snils_check_number(payload9)
    if layout == "compact":
        return digits
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:9]} {digits[9:]}"


def ogrn(payload12: str) -> str:
    return payload12 + str(ogrn_check_digit(payload12))


def ogrnip(payload14: str) -> str:
    return payload14 + str(ogrnip_check_digit(payload14))


def account(bik: str, account20: str, *, correspondent: bool = False) -> str:
    """A 20-digit account whose key (9th digit) fits ``bik``."""
    key = account_key(bik, account20, correspondent=correspondent)
    return account20[:8] + key + account20[9:]


def luhn_card(prefix15: str, grouped: bool = True) -> str:
    """A 16-digit card number with a valid Luhn digit."""
    total = 0
    for i, ch in enumerate(reversed(prefix15)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    digits = prefix15 + str((10 - total % 10) % 10)
    return " ".join(digits[i : i + 4] for i in range(0, 16, 4)) if grouped else digits


def ru_documents() -> list[Document]:
    bik_1, bik_2 = "044525999", "044030999"
    inn_person_1, inn_person_2 = inn12("7700000012"), inn12("5000123456")
    inn_org_1 = inn10("770000123")
    snils_1, snils_2 = snils("123456789"), snils("987654321", layout="compact")
    ogrn_1 = ogrn("102770000012")
    ogrnip_1 = ogrnip("31677000000012")
    acc_person = account(bik_1, "40817810000000012345")
    acc_org = account(bik_2, "40702810500000000001")
    acc_corr = account(bik_2, "30101810900000000999", correspondent=True)
    card_1 = luhn_card("220000000012345")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "ru-email-0001",
            "Тема: Возврат средств\n\nДобрый день!\n\nПрошу оформить возврат для "
            f"{P('Смирновой Ольги Петровны')} по заказу № 4510-77. Связаться можно по телефону "
            f"{PH('8 (916) 555-01-23')} или по почте {E('olga.smirnova@example.com')}.\n\n"
            f"С уважением,\n{P('Ольга Смирнова')}",
            {"kind": "email"},
        ),
        (
            "ru-contract-0002",
            "ДОГОВОР АРЕНДЫ № 17/26\n\n"
            f"{ORG('ООО «Полярный ветер»')}, именуемое в дальнейшем «Арендодатель», и гражданин "
            f"{P('Кузнецов Алексей Викторович')}, {DOB('14.03.1987')} года рождения, паспорт "
            f"серии {IDD('45 10 123456')}, зарегистрированный по адресу: "
            f"{A('г. Тверь, ул. Советская, д. 12, кв. 34')}, ИНН {IDD(inn_person_1)}, СНИЛС "
            f"{IDD(snils_1)}, именуемый в дальнейшем «Арендатор», заключили настоящий договор.\n"
            f"Арендная плата 45 000 руб. перечисляется на счёт {BANK(acc_person)}, БИК {bik_1}.",
            {"kind": "contract"},
        ),
        (
            "ru-invoice-0003",
            "Счёт на оплату № 512 от 03.11.2026\n"
            f"Поставщик: {ORG('ООО «Северная звезда»')}, ИНН {IDD(inn_org_1)}, "
            f"ОГРН {IDD(ogrn_1)}\n"
            f"р/с {BANK(acc_org)}, к/с {BANK(acc_corr)}, БИК {bik_2}\n"
            f"Покупатель: ИП {P('Гусейнова Лейла Рашидовна')}, ИНН {IDD(inn_person_2)}, "
            f"ОГРНИП {IDD(ogrnip_1)}\n"
            "Итого к оплате: 128 400,00 руб., в т. ч. НДС 20 %.",
            {"kind": "invoice"},
        ),
        (
            "ru-chat-0004",
            f"привет, скинь номер {P('тимура ахметова')}, он обещал перезвонить "
            f"{P('насте')}. у меня только старый {PH('89165550147')}",
            {"kind": "chat", "tags": ["informal", "lowercase"]},
        ),
        (
            "ru-inflection-0005",
            f"{P('Марина Белова')} переезжает в другой офис. Ключи передали "
            f"{P('Беловой')}, договор подписали с {P('Мариной Беловой')} в понедельник. "
            f"Коробки для {P('Марины Сергеевны')} стоят у {P('Игоря Валентиновича')}, "
            f"а {P('Игорь Валентинович')} просил напомнить {P('Белову')} про пропуск.",
            {"kind": "note", "tags": ["inflected"]},
        ),
        (
            "ru-form-0006",
            "АНКЕТА СОИСКАТЕЛЯ\n"
            f"ФИО: {P('ПЕТРОВА АННА СЕРГЕЕВНА')}\n"
            f"Дата рождения: {DOB('03.02.1991')}\nМесто рождения: г. Самара\n"
            f"Паспорт: серия {IDD('36 15')} № {IDD('654321')}\n"
            "Адрес: "
            + A("620014, Свердловская обл., г. Екатеринбург, пр-т Ленина, д. 5, корп. 2, кв. 118")
            + "\n"
            f"Телефон: {PH('+7 903 555-44-33')}\nE-mail: {E('anna.petrova@example.org')}",
            {"kind": "form"},
        ),
        (
            "ru-tool-0007",
            '{"tool": "crm.get_contact", "result": {"name": "'
            f"{P('Пётр Васильев')}"
            '", "phone": "'
            f"{PH('+7 (495) 555-01-99')}"
            '", "email": "'
            f"{E('p.vasiliev@example.org')}"
            '", "snils": "'
            f"{IDD(snils_2)}"
            '", "segment": "B2B", "orders": 14}}',
            {"kind": "tool_output", "tags": ["json"]},
        ),
        (
            "ru-letter-0008",
            f"Уважаемая {P('Наталья Юрьевна')}!\n\nСообщаем, что водительское удостоверение "
            f"{IDD('77 15 654321')} готово к выдаче. Автомобиль с государственным номером "
            f"{PLATE('А123ВС777')} можно забрать со штрафстоянки по адресу "
            f"{A('ул. Промышленная, д. 3, стр. 1')}.\n\n"
            f"Инспектор {P('Сидоренко В. П.')}",
            {"kind": "letter"},
        ),
        (
            "ru-medical-0009",
            f"Пациент: {P('Хабибуллина Гульнара Ринатовна')}, дата рождения "
            f"{DOB('3 февраля 1991 года')}.\n"
            f"Полис ОМС {IDD('7700000012345678')}, СНИЛС {IDD(snils('111222333'))}.\n"
            f"Направлена на консультацию к {P('Геворкяну Арсену Ашотовичу')}.",
            {"kind": "medical"},
        ),
        (
            "ru-delivery-0010",
            f"Курьер {P('Бахтиёр Юлдашев')}: заказ привезти на {A('Садовую 14, квартира 7')}, "
            f"домофон не работает, звонить {P('Зареме')} на {PH('+7 926 555-12-34')}.",
            {"kind": "message", "tags": ["informal"]},
        ),
        (
            "ru-minutes-0011",
            "Протокол совещания 12.11.2026\n"
            f"Присутствовали: {P('Иванов И.И.')}, {P('Н. А. Власова')}, {P('Рустам Алиев')}.\n"
            f"Решили: {P('Власовой')} подготовить отчёт к пятнице, {P('Алиеву')} согласовать "
            f"смету с {P('Ивановым')}. Копию направить {P('Сидоренко В. П.')}",
            {"kind": "minutes"},
        ),
        (
            "ru-bank-0012",
            f"Выписка по счёту {BANK(acc_person)}\nВладелец: {P('Орлов Максим Андреевич')}\n"
            f"Карта {BANK(card_1)}, БИК {bik_1}.\n"
            "Остаток на 01.11.2026: 56 780,45 руб.",
            {"kind": "statement"},
        ),
        (
            "ru-negative-0013",
            "Протокол приёмки от 01.02.2026\n"
            "Заказ № 89165550123 отгружен со склада на улице Ленина во Владимир и Орёл. "
            "Артикул 4510-123456, партия 770-001, счёт-фактура 112233 на сумму 1 987 000 руб. "
            "В испытании участвовали 20000 пользователей в течение 18 месяцев.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "ru-negative-0014",
            "Вера в лучшее и надежда на успех — вот что нужно команде. Роман о войне выйдет "
            "весной, тираж 15 000 экземпляров. Любовь к порядку помогла закрыть проект "
            "«Надежда» к 14.03.2027. Модель ответила за 420 мс, версия 2.14.",
            {"kind": "note", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="ru", meta=meta) for doc_id, text, meta in docs]


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "ru-smoke.jsonl": ru_documents,
}
