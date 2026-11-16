"""Check digits of Russian identifiers (pure functions, no I/O).

- **ИНН** (taxpayer number): 10 digits for an organization, 12 for a person or an
  individual entrepreneur. Each check digit is a weighted sum modulo 11, then modulo 10:
  weights ``2 4 10 3 5 9 4 6 8`` for the 10th digit of a 10-digit ИНН; ``7 2 4 10 3 5 9 4 6
  8`` for the 11th and ``3 7 2 4 10 3 5 9 4 6 8`` for the 12th digit of a 12-digit one.
- **СНИЛС** (pension insurance number): 11 digits ``XXX-XXX-XXX YY``. The first nine digits
  weighted ``9 8 7 ... 1`` give a sum S: below 100 the check number is S, 100 and 101 give
  ``00``, above 101 it is S mod 101 (and 100 again gives ``00``). Numbers up to
  ``001-001-998`` were issued without a check number and never validate here.
- **ОГРН** (company registration number): 13 digits; the last is the first twelve as a
  number modulo 11, then modulo 10. **ОГРНИП** (individual entrepreneur): 15 digits; the
  first fourteen modulo 13, then modulo 10.
- **Bank account** (20 digits) with its bank's **БИК** (9 digits): three digits from the БИК
  (its last three for an account at a bank, ``0`` and digits 5-6 for a correspondent account
  at the central bank) followed by the account, weighted ``7 1 3`` repeated; the sum of the
  last digits of the products is a multiple of 10. The account's 9th digit is the key.

Verified against published values: ИНН ``7707083893`` and ОГРН ``1027700132195`` of a large
bank, its correspondent account ``30101810400000000225`` with БИК ``044525225``, and the
textbook examples ИНН ``500100732259``, СНИЛС ``112-233-445 95``, ОГРНИП
``304500116000157`` (``tests/languages/test_ru.py``).

Every function takes the value without separators and never raises on bad input.
"""

from __future__ import annotations

__all__ = [
    "account_key",
    "inn10_check_digit",
    "inn12_check_digits",
    "is_valid_account",
    "is_valid_inn",
    "is_valid_ogrn",
    "is_valid_ogrnip",
    "is_valid_snils",
    "ogrn_check_digit",
    "ogrnip_check_digit",
    "snils_check_number",
]

_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN11_WEIGHTS = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
# Three digits from the БИК plus the 20-digit account.
_ACCOUNT_WEIGHTS = ((7, 1, 3) * 8)[:23]
# The last СНИЛС issued without a check number.
_SNILS_UNCHECKED = 1001998


def _digits(value: str, n: int) -> bool:
    return len(value) == n and value.isascii() and value.isdigit()


def _weighted(weights: tuple[int, ...], digits: str) -> int:
    return sum(w * int(d) for w, d in zip(weights, digits, strict=False))


def inn10_check_digit(payload9: str) -> int:
    """The check digit for the first nine digits of an organization's ИНН."""
    return _weighted(_INN10_WEIGHTS, payload9) % 11 % 10


def inn12_check_digits(payload10: str) -> str:
    """The two check digits for the first ten digits of a person's ИНН."""
    first = _weighted(_INN11_WEIGHTS, payload10) % 11 % 10
    second = _weighted(_INN12_WEIGHTS, payload10 + str(first)) % 11 % 10
    return f"{first}{second}"


def is_valid_inn(value: str) -> bool:
    """A 10- or 12-digit ИНН with valid check digits (not all zeros)."""
    if _digits(value, 10):
        return value != "0" * 10 and inn10_check_digit(value[:9]) == int(value[9])
    if _digits(value, 12):
        return value != "0" * 12 and inn12_check_digits(value[:10]) == value[10:]
    return False


def snils_check_number(payload9: str) -> str:
    """The two-digit check number for the first nine digits of a СНИЛС."""
    total = sum(int(d) * (9 - i) for i, d in enumerate(payload9))
    if total > 101:
        total %= 101
    return "00" if total in (100, 101) else f"{total:02d}"


def is_valid_snils(value: str) -> bool:
    """An 11-digit СНИЛС issued with a check number, and that number valid."""
    if not _digits(value, 11) or int(value[:9]) <= _SNILS_UNCHECKED:
        return False
    return snils_check_number(value[:9]) == value[9:]


def ogrn_check_digit(payload12: str) -> int:
    return int(payload12) % 11 % 10


def ogrnip_check_digit(payload14: str) -> int:
    return int(payload14) % 13 % 10


def is_valid_ogrn(value: str) -> bool:
    """A 13-digit ОГРН (first digit 1 or 5) with a valid check digit."""
    return (
        _digits(value, 13) and value[0] in "15" and ogrn_check_digit(value[:12]) == int(value[12])
    )


def is_valid_ogrnip(value: str) -> bool:
    """A 15-digit ОГРНИП (first digit 3) with a valid check digit."""
    return (
        _digits(value, 15) and value[0] == "3" and ogrnip_check_digit(value[:14]) == int(value[14])
    )


def _bik_prefix(bik: str, correspondent: bool) -> str:
    return "0" + bik[4:6] if correspondent else bik[6:]


def _account_sum(prefix3: str, account: str) -> int:
    return sum((int(d) * w) % 10 for d, w in zip(prefix3 + account, _ACCOUNT_WEIGHTS, strict=True))


def account_key(bik: str, account_without_key: str, *, correspondent: bool = False) -> str:
    """The key digit (the 9th) for a 20-digit account whose 9th digit is ``0``.

    ``account_without_key`` is the account with any digit in 9th place; the key is chosen so
    the weighted sum is a multiple of 10.
    """
    if not (_digits(bik, 9) and _digits(account_without_key, 20)):
        raise ValueError("expected a 9-digit БИК and a 20-digit account")
    zeroed = account_without_key[:8] + "0" + account_without_key[9:]
    total = _account_sum(_bik_prefix(bik, correspondent), zeroed)
    # The key's weight (9th account digit = 12th of 23) is 3; 3 * k mod 10 must make the sum
    # a multiple of 10, and 3 has the inverse 7 modulo 10.
    return str(((10 - total % 10) % 10) * 7 % 10)


def is_valid_account(bik: str, account: str) -> bool:
    """A 20-digit account whose key fits ``bik`` as a bank or a correspondent account."""
    if not (_digits(bik, 9) and _digits(account, 20)):
        return False
    return any(
        _account_sum(_bik_prefix(bik, correspondent), account) % 10 == 0
        for correspondent in (False, True)
    )
