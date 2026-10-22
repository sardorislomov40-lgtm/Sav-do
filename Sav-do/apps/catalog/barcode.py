"""Shtrix-kod yordamchilari (Django'siz, sof Python).

Ichki kodlar EAN-13 formatida va "27" bilan boshlanadi:
27 + 10 xonali tartib raqami + nazorat raqami = 13 xona.
"27" tanlangan, chunki tarozi kodlari ko'pincha 20-26 bilan boshlanadi.
"""
import re

INTERNAL_PREFIX = "27"
_PLAIN_CODE = re.compile(r"^[A-Za-z0-9._\-]{3,32}$")


def gs1_check_digit(body: str) -> int:
    """EAN-8/UPC-A/EAN-13/GTIN-14 uchun nazorat raqami (kod oxirgi raqamsiz beriladi)."""
    if not body.isdigit():
        raise ValueError("Faqat raqamlar bo'lishi kerak")
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def is_valid_gs1(code: str) -> bool:
    return (
        code.isdigit()
        and len(code) in (8, 12, 13, 14)
        and int(code[-1]) == gs1_check_digit(code[:-1])
    )


def build_internal_ean13(number: int, prefix: str = INTERNAL_PREFIX) -> str:
    width = 12 - len(prefix)
    if number < 1 or number >= 10**width:
        raise ValueError("Ichki kod raqami diapazondan tashqarida")
    body = prefix + str(number).zfill(width)
    return body + str(gs1_check_digit(body))


def is_internal_code(code: str) -> bool:
    return len(code) == 13 and code.startswith(INTERNAL_PREFIX) and is_valid_gs1(code)


def normalize_code(raw: str) -> str:
    """Skaner ba'zan bo'shliq yoki Enter qoldiradi: tozalaymiz."""
    return "".join((raw or "").split())


def validate_factory_code(raw: str) -> str:
    """Zavod kodini tekshiradi va tozalangan kodni qaytaradi (xato bo'lsa ValueError)."""
    code = normalize_code(raw)
    if not _PLAIN_CODE.match(code):
        raise ValueError("Kod 3-32 belgidan iborat bo'lib, faqat harf, raqam, '-', '.', '_' bo'lishi mumkin")
    if code.isdigit() and len(code) in (8, 12, 13, 14) and not is_valid_gs1(code):
        raise ValueError("Nazorat raqami noto'g'ri: kodni qayta tekshiring")
    return code
