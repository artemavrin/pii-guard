"""Замер: как модель упоминает замаскированного человека в нужном падеже.

Два варианта на одних заданиях:

- ``tag``: метка с полом, составом имени и падежом, ``[[PERSON_ab12|ж|фио|дат]]``;
  модель сама ставит состав и падеж, каких требует её фраза.
- ``sur``: подставное ФИО того же пола; модель склоняет его как обычное имя, падеж
  читается из формы.

Отвечает Claude Haiku чистым чатом (``claude -p``, без инструментов). Все имена выдуманы.

    uv run python docs/ru/spikes/case_protocol.py run   # вызвать модель, сохранить ответы
    uv run python docs/ru/spikes/case_protocol.py show  # восстановить имена и показать
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pytrovich.detector import PetrovichGenderDetector  # noqa: F401  (kept for parity checks)
from pytrovich.enums import Case, Gender, NamePart
from pytrovich.maker import PetrovichDeclinationMaker

OUT = Path(__file__).with_name("case_protocol_answers.json")
MODEL = sys.argv[2] if len(sys.argv) > 2 else "haiku"
_MAKER = PetrovichDeclinationMaker()

CASES = {
    "им": None,
    "род": Case.GENITIVE,
    "дат": Case.DATIVE,
    "вин": Case.ACCUSATIVE,
    "тв": Case.INSTRUMENTAL,
    "пр": Case.PREPOSITIONAL,
}
# Состав: какие части и в каком порядке.
COMPS = {
    "фио": ("f", "i", "o"),
    "ио": ("i", "o"),
    "фи": ("i", "f"),
    "ф": ("f",),
    "и": ("i",),
}
_PART = {"f": NamePart.LASTNAME, "i": NamePart.FIRSTNAME, "o": NamePart.MIDDLENAME}

# key: (настоящее ФИО, подставное ФИО, пол, id метки)
PEOPLE = {
    "A": (("Смирнова", "Ольга", "Петровна"), ("Иванова", "Анна", "Сергеевна"), "ж", "7f3a"),
    "B": (("Кузнецов", "Алексей", "Викторович"), ("Соколов", "Дмитрий", "Андреевич"), "м", "20c2"),
    "C": (("Белова", "Марина", "Игоревна"), ("Морозова", "Елена", "Павловна"), "ж", "9e41"),
    "D": (("Хабибуллин", "Рустам", "Ринатович"), ("Каримов", "Тимур", "Маратович"), "м", "b7d0"),
    "E": (("Орлов", "Максим", "Андреевич"), ("Лебедев", "Игорь", "Николаевич"), "м", "4a6c"),
    "F": (("Власова", "Наталья", "Юрьевна"), ("Новикова", "Татьяна", "Олеговна"), "ж", "e518"),
}

TASKS = [
    "{A:им:фио} просит вернуть деньги за заказ 4510. Напиши короткое подтверждение для отдела: кому и когда вернём деньги (в пятницу).",
    "Договор подписал {B:им:фи}. Напиши одну фразу: с кем заключён договор.",
    "Вчера звонила {A:им:ио}. Составь заметку для коллег: о ком идёт речь и кому нужно перезвонить.",
    "Письмо от {B:род:фио}: «Прошу перенести встречу на среду». Ответь мне: что сделать и кого предупредить о переносе.",
    "{C:им:фи} и {B:им:фи} спорят о сроках. Кому из них поручить отчёт, если {C:им:и} в отпуске? Ответь одной фразой.",
    "Передай {A:дат:ио}, что документы готовы. Напиши текст сообщения, обращаясь к ней по имени и отчеству.",
    "У {D:род:фио} день рождения в субботу. Напиши две фразы: кого поздравляем и что дарим от отдела.",
    "Заявку подала {C:им:фио}. Статус: одобрено. Сформулируй уведомление в третьем лице: чья заявка одобрена.",
    "{E:им:фи} отвечает за склад, {F:им:фи} — за доставку. Клиент жалуется на опоздание курьера. К кому обратиться и что сказать? Две фразы.",
    "Итог встречи. Присутствовали {A:им:фи}, {B:им:фи} и {D:им:фи}. Решили: отчёт готовит {B:им:ф}, смету согласует {D:им:ф} с {A:тв:ф}. Перескажи списком из трёх пунктов, каждый начни словами «Задача для».",
    "Напомни мне завтра позвонить {F:дат:ио}. Ответь подтверждением: когда и кому звоним.",
    "{B:им:фио} уволился. Кем его заменить, если свободен {E:им:фи}? Ответь одной фразой.",
    'Результат инструмента: {{"contact": "{D:им:фио}", "role": "закупки", "orders": 14}}. Расскажи в двух фразах, что известно об этом контакте.',
    "Нужно письмо-отказ. Получатель — {C:им:фио}. Начни с обращения «Уважаемая» и напиши две фразы.",
    "Получатель письма — {E:им:фио}. Начни с обращения «Уважаемый» и напиши две фразы о переносе поставки.",
    "{F:им:фи} закрыла проект раньше срока. Напиши одну фразу от лица отдела: кому мы благодарны и за что.",
    "Счёт выставлен на {B:вин:фио}. Кто плательщик? Ответь полным предложением.",
    "Вчера видел {A:вин:фи} с {B:тв:фи} на выставке. О чём мне спросить каждого из них? По одной фразе на человека.",
    "Доверенность оформляется на {D:вин:фио}. Напиши две фразы для договора: «Интересы компании представляет …» и «Доверенность выдана …».",
    "Клиентка {C:им:фи} недовольна сроками. Её менеджер — {E:им:фи}. Составь план из двух шагов: что сделать для клиентки и с кем это согласовать.",
    "{A:им:фи} — бухгалтер, {F:им:фи} — юрист. Напиши, к кому идти с вопросом про налоги, а к кому — про договор.",
    "От {E:род:фи} пришло три письма, от {D:род:фи} — ни одного. Напиши вывод одной фразой: кем я доволен, а кем нет.",
    "Запомни: {B:им:фио} предпочитает звонки, а не письма. Подтверди одной фразой, что запомнил, о ком и что.",
    "Составь поздравление с повышением для {F:род:ио}. Обращайся по имени и отчеству, две фразы.",
    "Пропуск заказан на {A:вин:фио} и {D:вин:фио}. Охрана спрашивает, кого пропускать. Ответь одной фразой.",
    "{C:им:фи} передала дела {E:дат:фи}. Напиши для отчёта две фразы в страдательном залоге: кем дела переданы и кому.",
    "Встреча с {B:тв:ио} перенесена. Напиши ему короткое сообщение с извинением, обращаясь по имени и отчеству.",
    "У {A:род:ф} срок до пятницы, у {C:род:ф} — до понедельника. Напиши одной фразой, кто сдаёт раньше, назвав обеих по фамилии.",
    "Переведи на деловой язык: «скажи {D:дат:и}, чтобы зашёл к {F:дат:ио}».",
    "Про {E:вин:фио} спрашивали из банка. Его руководитель — {A:им:фи}. Напиши записку: о ком спрашивали и кому передать информацию.",
]  # fmt: skip

BASE_SYSTEM = "Ты — помощник в рабочем чате. Отвечай по-русски, кратко и по делу, без markdown."
TAG_NOTE = """

В сообщениях имена людей заменены метками ради защиты персональных данных. Метка выглядит так:
[[PERSON_7f3a|ж|фио|дат]]
- 7f3a — идентификатор человека, он не меняется;
- пол: м или ж;
- состав имени: фио (фамилия, имя, отчество), ио (имя и отчество), фи (имя и фамилия), ф (только фамилия), и (только имя);
- падеж: им, род, дат, вин, тв, пр.

Когда упоминаешь человека, пиши метку с его идентификатором и полом, а состав и падеж ставь такие, каких требует твоя фраза, а не те, что были в сообщении. Сама метка не склоняется: ничего к ней не дописывай. Пример: «Передай [[PERSON_7f3a|ж|ио|дат]], что [[PERSON_20c2|м|ф|им]] согласен»."""


def inflect(fio: tuple[str, str, str], gender: str, comp: str, case: str) -> str:
    g = Gender.FEMALE if gender == "ж" else Gender.MALE
    parts = dict(zip("fio", fio, strict=True))
    words = []
    for key in COMPS[comp]:
        word = parts[key]
        if CASES[case] is not None:
            word = _MAKER.make(_PART[key], g, CASES[case], word)
        words.append(word)
    return " ".join(words)


_SLOT = re.compile(r"\{([A-F]):(\w+):(\w+)\}")


def render(task: str, arm: str) -> str:
    def repl(m: re.Match[str]) -> str:
        real, sur, gender, pid = PEOPLE[m.group(1)]
        case, comp = m.group(2), m.group(3)
        if arm == "real":
            return inflect(real, gender, comp, case)
        if arm == "sur":
            return inflect(sur, gender, comp, case)
        return f"[[PERSON_{pid}|{gender}|{comp}|{case}]]"

    return _SLOT.sub(repl, task).replace("{{", "{").replace("}}", "}")


def ask(system: str, user: str) -> str:
    cmd = [
        "claude", "-p", "--model", MODEL, "--system-prompt", system, "--tools", "",
        "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
        "--output-format", "json",
    ]  # fmt: skip
    out = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=180, check=False)
    return json.loads(out.stdout)["result"]


def run() -> None:
    jobs = [(i, arm) for i in range(len(TASKS)) for arm in ("tag", "sur")]

    def one(job: tuple[int, str]) -> dict:
        i, arm = job
        system = BASE_SYSTEM + (TAG_NOTE if arm == "tag" else "")
        user = render(TASKS[i], arm)
        return {"task": i, "arm": arm, "user": user, "answer": ask(system, user)}

    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(one, jobs))
    OUT.write_text(json.dumps({"model": MODEL, "rows": rows}, ensure_ascii=False, indent=1))
    print(f"saved {len(rows)} answers to {OUT.name}")


# --- Восстановление -----------------------------------------------------------------

_TAG = re.compile(r"\[\[PERSON_([0-9a-f]{4})\s*\|\s*([мж])\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\]\](\w*)")
_ANY_LABEL = re.compile(r"\[\[[^\]]*\]\]?")
BY_ID = {pid: key for key, (_, _, _, pid) in PEOPLE.items()}


def restore_tag(answer: str, user: str) -> tuple[str, list[str], list[str]]:
    seen = {(m.group(1), m.group(3), m.group(4)) for m in _TAG.finditer(user)}
    notes, problems = [], []

    def repl(m: re.Match[str]) -> str:
        pid, gender, comp, case, glued = m.groups()
        key = BY_ID.get(pid)
        if key is None or comp not in COMPS or case not in CASES:
            problems.append(f"битая метка {m.group(0)}")
            return m.group(0)
        real, _, real_gender, _ = PEOPLE[key]
        if gender != real_gender:
            problems.append(f"пол изменён в {m.group(0)}")
        if glued:
            problems.append(f"дописано «{glued}» после метки")
        copied = "=вход" if (pid, comp, case) in seen else ""
        notes.append(f"{comp}/{case}{copied}")
        return "⟦" + inflect(real, real_gender, comp, case) + "⟧" + glued

    text = _TAG.sub(repl, answer)
    problems += [f"остаток метки {x}" for x in _ANY_LABEL.findall(text)]
    return text, notes, problems


def surrogate_forms(key: str) -> list[tuple[str, str, str]]:
    """(подставная форма, состав, падеж) — длинные раньше; оба порядка для фи и фио."""
    _, sur, gender, _ = PEOPLE[key]
    forms = []
    for comp in COMPS:
        for case in CASES:
            words = inflect(sur, gender, comp, case).split()
            forms.append((" ".join(words), comp, case))
            if comp == "фи":
                forms.append((" ".join(reversed(words)), comp + "*", case))
            if comp == "фио":
                forms.append((" ".join([*words[1:], words[0]]), comp + "*", case))
    return sorted(forms, key=lambda f: -len(f[0]))


def restore_sur(answer: str) -> tuple[str, list[str], list[str]]:
    notes, problems = [], []
    text = answer
    for key, (real, sur, gender, _) in PEOPLE.items():
        for form, comp, case in surrogate_forms(key):
            pattern = re.compile(r"(?<![\w⟦])" + re.escape(form) + r"(?![\w⟧])", re.IGNORECASE)

            def repl(_m: re.Match[str], comp: str = comp, case: str = case) -> str:
                base = comp.rstrip("*")
                words = inflect(real, gender, base, case).split()
                if comp == "фи*":
                    words.reverse()
                elif comp == "фио*":
                    words = [*words[1:], words[0]]
                notes.append(f"{comp}/{case}")
                return "⟦" + " ".join(words) + "⟧"

            # Одна форма подходит нескольким падежам (Ивановой: род, дат, тв, пр): берём
            # первый; настоящее имя того же типа склоняется так же.
            text = pattern.sub(repl, text)
        # Остатки: слово с основой подставного имени вне восстановленного.
        plain = re.sub(r"⟦[^⟧]*⟧", "", text)
        for word in sur:
            stem = word[: max(3, len(word) - 2)]
            for m in re.finditer(r"\b" + stem + r"\w*", plain, re.IGNORECASE):
                problems.append(f"не восстановлено «{m.group(0)}»")
    return text, notes, problems


def show() -> None:
    data = json.loads(OUT.read_text())
    rows = sorted(data["rows"], key=lambda r: (r["task"], r["arm"]))
    stats = {"tag": [0, 0, 0], "sur": [0, 0, 0]}  # ответов, упоминаний, проблем
    print(f"модель: {data['model']}\n")
    for row in rows:
        arm = row["arm"]
        if arm == "tag":
            text, notes, problems = restore_tag(row["answer"], row["user"])
        else:
            text, notes, problems = restore_sur(row["answer"])
        stats[arm][0] += 1
        stats[arm][1] += len(notes)
        stats[arm][2] += len(problems)
        if arm == "sur":
            print(f"#{row['task'] + 1:02d} ЗАДАНИЕ: {render(TASKS[row['task']], 'real')}")
        print(f"   [{arm}] {text.strip()}")
        print(
            f"         формы: {', '.join(notes) or '—'}"
            + (f"   ПРОБЛЕМЫ: {problems}" if problems else "")
        )
        if arm == "tag":
            print()
    for arm, (n, mentions, problems) in stats.items():
        print(f"{arm}: ответов {n}, упоминаний {mentions}, технических проблем {problems}")


if __name__ == "__main__":
    {"run": run, "show": show}[sys.argv[1]]()
