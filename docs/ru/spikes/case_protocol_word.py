"""Третий замер: метка-слово, которую модель склоняет сама.

- ``pm``: ``Персона_Мужчина_20c2`` / ``Персона_Женщина_7f3a``, склоняются оба слова;
- ``gg``: ``Господин_20c2`` / ``Госпожа_7f3a``.

Падеж читается из формы слова. Состав имени (ФИО, имя-отчество, фамилия) метка не несёт:
при восстановлении берётся состав первого упоминания человека в сообщении.

    uv run python docs/ru/spikes/case_protocol_word.py run
    uv run python docs/ru/spikes/case_protocol_word.py show
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import case_protocol as base

base.MODEL = "haiku"  # второй аргумент здесь — список вариантов, а не модель

OUT = Path(__file__).with_name(
    "case_protocol_word3_answers.json"
    if "pm3" in " ".join(sys.argv)
    else "case_protocol_word2_answers.json"
    if "pm2" in " ".join(sys.argv)
    else "case_protocol_word_answers.json"
)

FORMS = {
    "персона": {"им": "Персона", "род": "Персоны", "дат": "Персоне", "вин": "Персону", "тв": "Персоной", "пр": "Персоне"},
    "мужчина": {"им": "Мужчина", "род": "Мужчины", "дат": "Мужчине", "вин": "Мужчину", "тв": "Мужчиной", "пр": "Мужчине"},
    "женщина": {"им": "Женщина", "род": "Женщины", "дат": "Женщине", "вин": "Женщину", "тв": "Женщиной", "пр": "Женщине"},
    "господин": {"им": "Господин", "род": "Господина", "дат": "Господину", "вин": "Господина", "тв": "Господином", "пр": "Господине"},
    "госпожа": {"им": "Госпожа", "род": "Госпожи", "дат": "Госпоже", "вин": "Госпожу", "тв": "Госпожой", "пр": "Госпоже"},
}  # fmt: skip
# Форма -> возможные падежи (одна форма бывает у нескольких).
READ: dict[str, list[str]] = {}
for table in FORMS.values():
    for case, form in table.items():
        READ.setdefault(form.casefold(), []).append(case)
READ["персоною"] = ["тв"]
READ["госпожою"] = ["тв"]
READ["мужчиною"] = ["тв"]
READ["женщиною"] = ["тв"]

NOTES = {
    "pm3": """

Ради защиты персональных данных настоящие имена людей в сообщениях заменены метками вида Персона_Женщина_1a2b или Персона_Мужчина_3c4d. За каждой меткой стоит настоящий человек с настоящими именем, фамилией и отчеством.
Система подставит имя ровно в том падеже, в котором ты напишешь метку. Поэтому склоняй оба слова метки так же, как склонял бы имя, идентификатор оставляй как есть: «договор с Персоной_Мужчиной_3c4d», «задача для Персоны_Женщины_1a2b», «передай Персоне_Мужчине_3c4d». Как назвать человека — полностью, по имени и отчеству или по фамилии — система выберет сама.
Не упоминай метки, не говори, что имя или отчество неизвестны, и не придумывай имён.""",
    "pm2": """

Ради защиты персональных данных настоящие имена людей в сообщениях заменены метками вида Персона_Женщина_1a2b или Персона_Мужчина_3c4d. За каждой меткой стоит настоящий человек с настоящими именем, фамилией и отчеством; система сама подставит их в твой ответ в нужной форме — полностью, по имени и отчеству или по фамилии, как уместно.
Поэтому пиши так, будто метка и есть имя человека: склоняй оба слова по падежам, идентификатор оставляй как есть. Обращайся к человеку по метке («Здравствуйте, Персона_Женщина_1a2b!»). Не упоминай метки, не говори, что имя или отчество неизвестны, и не придумывай имён.""",
    "pm": """

В сообщениях имена людей заменены условными обозначениями ради защиты персональных данных: Персона_Женщина_7f3a, Персона_Мужчина_20c2. Последняя часть — идентификатор человека, он не меняется. Обращайся с обозначением как с обычным именем: склоняй оба слова по падежам, идентификатор оставляй как есть. Пример: «Передай Персоне_Женщине_7f3a, что договор с Персоной_Мужчиной_20c2 подписан».""",
    "gg": """

В сообщениях имена людей заменены условными обозначениями ради защиты персональных данных: Госпожа_7f3a, Господин_20c2. Часть после подчёркивания — идентификатор человека, он не меняется. Обращайся с обозначением как с обычным именем: склоняй слово по падежам, идентификатор оставляй как есть. Пример: «Передай Госпоже_7f3a, что договор с Господином_20c2 подписан».""",
}


def label(arm: str, gender: str, pid: str, case: str) -> str:
    if arm in ("pm", "pm2", "pm3"):
        word = "мужчина" if gender == "м" else "женщина"
        return f"{FORMS['персона'][case]}_{FORMS[word][case]}_{pid}"
    word = "господин" if gender == "м" else "госпожа"
    return f"{FORMS[word][case]}_{pid}"


def render(task: str, arm: str) -> str:
    def repl(m: re.Match[str]) -> str:
        _, _, gender, pid = base.PEOPLE[m.group(1)]
        return label(arm, gender, pid, m.group(2))

    return base._SLOT.sub(repl, task).replace("{{", "{").replace("}}", "}")


def run() -> None:
    arms = sys.argv[2].split(",") if len(sys.argv) > 2 else ["pm", "gg"]
    jobs = [(i, arm) for i in range(len(base.TASKS)) for arm in arms]

    def one(job: tuple[int, str]) -> dict:
        i, arm = job
        user = render(base.TASKS[i], arm)
        return {
            "task": i,
            "arm": arm,
            "user": user,
            "answer": base.ask(base.BASE_SYSTEM + NOTES[arm], user),
        }

    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(one, jobs))
    OUT.write_text(json.dumps({"model": base.MODEL, "rows": rows}, ensure_ascii=False, indent=1))
    print(f"saved {len(rows)} answers to {OUT.name}")


_SEP = r"[_\s\-]?"
_PM = re.compile(
    rf"(Персон[а-яё]*){_SEP}(Мужчин[а-яё]*|Женщин[а-яё]*){_SEP}([0-9a-f]{{4}})([а-яё]*)",
    re.IGNORECASE,
)
_GG = re.compile(rf"(Господин[а-яё]*|Госпож[а-яё]*){_SEP}([0-9a-f]{{4}})([а-яё]*)", re.IGNORECASE)
# Обращение: «Уважаемая …», «Дорогой …», «Здравствуйте, …», «Добрый день, …», или метка в
# начале строки, за которой идёт запятая или «!».
_ADDRESS_BEFORE = re.compile(
    r"(?:\b(?:Уважаем\w*|Дорог\w*)\s+|(?:Здравствуйте|Добрый\s+\w+|Привет)\s*,\s*)$", re.IGNORECASE
)
_ADDRESS_AFTER = re.compile(r"\s*[,!]")
_LINE_START = re.compile(r"(?:^|\n)\s*(?:\*\*)?$")
_PREP = re.compile(r"(?:\bоб?|\bобо|\bв|\bво|\bна|\bпри)\s+$", re.IGNORECASE)
_LEFTOVER = re.compile(
    r"Персон\w*|Мужчин\w*|Женщин\w*|Господин\w*|Госпож\w*|\b(?=\d*[a-f])[0-9a-f]{4}\b",
    re.IGNORECASE,
)


def restore(answer: str, arm: str, task: int) -> tuple[str, list[str], list[str]]:
    comps = {}
    for m in base._SLOT.finditer(base.TASKS[task]):
        comps.setdefault(m.group(1), m.group(3))
    notes, problems = [], []

    def repl(m: re.Match[str]) -> str:
        if arm in ("pm", "pm2", "pm3"):
            first, word, pid, glued = m.groups()
            first_cases = READ.get(first.casefold())
        else:
            word, pid, glued = m.groups()
            first_cases = None
        key = base.BY_ID.get(pid)
        cases = READ.get(word.casefold())
        if key is None or cases is None:
            problems.append(f"не разобрано «{m.group(0)}»")
            return m.group(0)
        real, _, gender, _ = base.PEOPLE[key]
        expected = ("мужчин", "господин") if gender == "м" else ("женщин", "госпож")
        if not word.casefold().startswith(expected):
            problems.append(f"пол изменён в «{m.group(0)}»")
        if first_cases is not None and not set(first_cases) & set(cases):
            problems.append(f"слова в разных падежах «{m.group(0)}»")
        if glued:
            problems.append(f"дописано «{glued}»")
        if first_cases is not None and not set(first_cases) & set(cases):
            cases = first_cases  # «Персоне_Женщина»: первое слово склонено, второе нет
        elif first_cases is not None:
            cases = [c for c in cases if c in first_cases]
        case = cases[0]
        if set(cases) == {"род", "вин"}:  # «Господина»: у мужских имён эти формы совпадают
            case = "род"
        elif len(cases) > 1:  # дат или пр: по предлогу перед меткой
            case = "пр" if _PREP.search(answer[: m.start()]) else "дат"
        comp = comps.get(key, "фи")
        known = {
            c
            for k, c in ((mm.group(1), mm.group(3)) for mm in base._SLOT.finditer(base.TASKS[task]))
            if k == key
        }
        greeting = _ADDRESS_BEFORE.search(answer[: m.start()]) or (
            re.match(r"\s*!", answer[m.end() :]) and _LINE_START.search(answer[: m.start()])
        )
        if arm == "pm2" and (
            _ADDRESS_BEFORE.search(answer[: m.start()])
            or (_ADDRESS_AFTER.match(answer, m.end()) and _LINE_START.search(answer[: m.start()]))
        ):
            comp = "ио"
            notes.append(case + "+обращение")
        elif arm == "pm3" and greeting:
            comp = "ио" if any("о" in c for c in known) else "и"
            notes.append(case + "+обращение")
        else:
            notes.append(case)
        return "⟦" + base.inflect(real, gender, comp, case) + "⟧" + glued

    text = (_PM if arm in ("pm", "pm2", "pm3") else _GG).sub(repl, answer)
    problems += [f"остаток «{x}»" for x in _LEFTOVER.findall(re.sub(r"⟦[^⟧]*⟧", "", text))]
    return text, notes, problems


def show() -> None:
    data = json.loads(OUT.read_text())
    stats: dict[str, list[int]] = {}
    for row in sorted(data["rows"], key=lambda r: (r["task"], r["arm"])):
        arm = row["arm"]
        text, notes, problems = restore(row["answer"], arm, row["task"])
        stats.setdefault(arm, [0, 0, 0])
        stats[arm][0] += 1
        stats[arm][1] += len(notes)
        stats[arm][2] += len(problems)
        sents = [x.strip() for x in re.split(r"(?<=[.!?:])\s+|\n+", text) if "⟦" in x or "_" in x]
        if arm == sorted({r["arm"] for r in data["rows"]})[0]:
            print(f"#{row['task'] + 1:02d} ЗАДАНИЕ: {base.render(base.TASKS[row['task']], 'real')}")
        shown = " | ".join(sents)[:420] or text.strip()[:200]
        print(f"   [{arm}] {shown}")
        print(
            f"        падежи: {', '.join(notes) or '—'}"
            + (f"   ПРОБЛЕМЫ: {problems}" if problems else "")
        )
    for arm, (n, mentions, problems) in stats.items():
        print(f"{arm}: ответов {n}, упоминаний {mentions}, технических проблем {problems}")


if __name__ == "__main__":
    {"run": run, "show": show}[sys.argv[1]]()
