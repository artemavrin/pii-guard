"""Второй замер: подставное имя с придуманной фамилией, без пометки и в скобках.

- ``syn``: фамилии, которых нет в словаре настоящих (182 тыс. фамилий), имена и отчества
  обычные;
- ``brk``: то же, но имя взято в двойные квадратные скобки, ``[[Анна Тавренова]]``.

Оценка автоматическая: упоминание засчитано, если его форма совпала с одной из форм, которые
строит pytrovich; всё остальное с основой подставного имени — «не восстановлено».

    uv run python docs/ru/spikes/case_protocol_synthetic.py run
    uv run python docs/ru/spikes/case_protocol_synthetic.py show
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import case_protocol as base

OUT = Path(__file__).with_name("case_protocol_synthetic_answers.json")

SYNTHETIC = {
    "A": ("Тавренова", "Анна", "Сергеевна"),
    "B": ("Кеслов", "Дмитрий", "Андреевич"),
    "C": ("Мирзубова", "Елена", "Павловна"),
    "D": ("Ровдин", "Тимур", "Маратович"),
    "E": ("Зельтов", "Игорь", "Николаевич"),
    "F": ("Бранцева", "Татьяна", "Олеговна"),
}
for key, fio in SYNTHETIC.items():
    real, _, gender, pid = base.PEOPLE[key]
    base.PEOPLE[key] = (real, fio, gender, pid)

BRK_NOTE = """

В сообщениях имена людей заменены условными ради защиты персональных данных и взяты в двойные квадратные скобки: [[Анна Тавренова]]. Обращайся с ними как с обычными именами: склоняй по правилам русского языка, сокращай до имени и отчества или до фамилии, где это уместно. Скобки сохраняй: «Передай [[Анне Сергеевне]], что [[Кеслов]] согласен»."""

_BRACKETED = re.compile(r"\[\[([^\[\]]+)\]\]")


def render(task: str, arm: str) -> str:
    def repl(m: re.Match[str]) -> str:
        _, sur, gender, _ = base.PEOPLE[m.group(1)]
        form = base.inflect(sur, gender, m.group(3), m.group(2))
        return f"[[{form}]]" if arm == "brk" else form

    return base._SLOT.sub(repl, task).replace("{{", "{").replace("}}", "}")


def run() -> None:
    jobs = [(i, arm) for i in range(len(base.TASKS)) for arm in ("syn", "brk")]

    def one(job: tuple[int, str]) -> dict:
        i, arm = job
        system = base.BASE_SYSTEM + (BRK_NOTE if arm == "brk" else "")
        user = render(base.TASKS[i], arm)
        return {"task": i, "arm": arm, "user": user, "answer": base.ask(system, user)}

    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(one, jobs))
    OUT.write_text(json.dumps({"model": base.MODEL, "rows": rows}, ensure_ascii=False, indent=1))
    print(f"saved {len(rows)} answers to {OUT.name}")


def show() -> None:
    data = json.loads(OUT.read_text())
    stats = {"syn": [0, 0, 0], "brk": [0, 0, 0]}  # ответов, упоминаний, не восстановлено
    brackets = [0, 0, 0]  # в скобках, без скобок, в скобках не имя
    verbose = "-v" in sys.argv
    for row in sorted(data["rows"], key=lambda r: (r["task"], r["arm"])):
        arm, answer = row["arm"], row["answer"]
        if arm == "brk":
            marked = "".join(f"\x00{m}\x01" for m in _BRACKETED.findall(answer))
            _, inside, bad = base.restore_sur(marked.replace("\x00", " ").replace("\x01", " ."))
            brackets[0] += len(inside)
            brackets[2] += len(_BRACKETED.findall(answer)) - len(inside)
            answer = _BRACKETED.sub(r"\1", answer)
        text, notes, problems = base.restore_sur(answer)
        if arm == "brk":
            brackets[1] += len(notes) - len(inside)
        stats[arm][0] += 1
        stats[arm][1] += len(notes)
        stats[arm][2] += len(problems)
        if problems or verbose:
            print(f"#{row['task'] + 1:02d} [{arm}] {text.strip()}")
            print(f"      формы: {', '.join(notes) or '—'}   ПРОБЛЕМЫ: {problems}\n")
    for arm, (n, mentions, problems) in stats.items():
        print(f"{arm}: ответов {n}, упоминаний {mentions}, не восстановлено {problems}")
    print(f"brk: в скобках {brackets[0]}, без скобок {brackets[1]}, в скобках не имя {brackets[2]}")


if __name__ == "__main__":
    {"run": run, "show": show}[sys.argv[1]]()
