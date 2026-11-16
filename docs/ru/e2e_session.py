import json, re, urllib.request
import os

URL = os.environ.get("PII_GUARD_URL", "http://127.0.0.1:8797")


def post(path, body):
    req = urllib.request.Request(
        URL + path, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req) as r:
        return json.load(r)


turns = [
    "Оформи возврат для Смирновой Ольги Петровны, паспорт 4510 123456, телефон 8 916 555-01-23.",
    "Ольга Петровна Смирнова живёт по адресу: г. Тверь, ул. Советская, д. 12, кв. 34.",
    "Передай Ольге Петровне, что деньги придут до пятницы. И напиши Кузнецову из бухгалтерии.",
    "Договор с Ольгой Смирновой подписывал Алексей Кузнецов, его СНИЛС 112-233-445 95.",
    "насть, скинь контакты смирновой и кузнецова",
]
sid = None
for t in turns:
    body = {"text": t, "language": "ru"}
    if sid:
        body["session_id"] = sid
    r = post("/v1/mask", body)
    sid = r["session_id"]
    print("ВХОД :", t)
    print("МОДЕЛЬ:", r["masked_text"])
    print()

ph = sorted(
    set(
        re.findall(
            r"\[\[[A-Z_]+_[0-9a-f]+\]\]",
            " ".join(
                post("/v1/mask", {"text": t, "language": "ru", "session_id": sid})["masked_text"]
                for t in turns
            ),
        )
    )
)
print("Разных меток за сессию:", len(ph), ph)

persons = [p for p in ph if p.startswith("[[PERSON")]
if persons:
    a = f"Готово: оформил возврат для {persons[0]}, письмо отправил {persons[0]} и {persons[-1]}у."
    r = post("/v1/unmask", {"text": a, "session_id": sid})
    print("\nОТВЕТ МОДЕЛИ:", a)
    print("ПОСЛЕ ВОССТАНОВЛЕНИЯ:", r)
