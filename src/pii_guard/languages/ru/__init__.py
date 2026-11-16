"""The Russian language pack (``ru``, our fork; see ``docs/ru/README.md``).

- rules (:mod:`.rules`): ИНН, СНИЛС, ОГРН, ОГРНИП (check digits), bank accounts (validated
  against a БИК in the text), national phone numbers, passport / foreign passport / driving
  licence / ОМС numbers next to their label, vehicle plates and postal addresses;
- checksums (:mod:`.checksums`);
- cue words (``cues.tsv``) and reference words (``references.tsv``);
- LLM prompt notes (``prompt.md``), eval stopwords (:data:`SURFACE_FORMS`) and the
  hand-written smoke set ``eval/fixtures/ru-smoke.jsonl``.

Names decline in every word (``Смирнова Ольга Петровна`` -> ``Смирновой Ольге Петровне``):
the vault's "stem + suffix" model does not cover that; the person layer is described in
``docs/ru/README.md``.
"""

from __future__ import annotations

from importlib.resources import files

from pii_guard.languages import LanguagePack, SurfaceForms

__all__ = ["SURFACE_FORMS", "pack"]

# Words that may stay readable next to a masked value without identifying anyone: street
# and settlement types, months, legal forms (the partial-leak check ignores them).
SURFACE_FORMS = SurfaceForms(
    stopwords=frozenset(
        {
            "ул", "улица", "улице", "улицы", "пр", "проспект", "пер", "переулок", "б-р",
            "бульвар", "ш", "шоссе", "наб", "набережная", "пл", "площадь", "д", "дом", "корп",
            "корпус", "стр", "строение", "кв", "квартира", "офис", "г", "город", "обл",
            "область", "край", "район", "р-н", "пос", "поселок", "с", "село", "деревня",
            "мкр", "россия", "рф",
            "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
            "сентября", "октября", "ноября", "декабря", "года", "г.",
            "ооо", "оао", "зао", "пао", "ао", "ип", "нко", "ано",
        }
    )
)  # fmt: skip


def pack() -> LanguagePack:
    from pii_guard.languages.ru import rules

    return LanguagePack(
        code="ru",
        name="Russian",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("ru-smoke.jsonl",),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        surface_forms=SURFACE_FORMS,
        allow_suffix=True,  # "Кузнецову": a name runs on into its case ending
        cues=files(__name__).joinpath("cues.tsv"),
        references=files(__name__).joinpath("references.tsv"),
    )
