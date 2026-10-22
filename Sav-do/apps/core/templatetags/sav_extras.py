from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value):
    """12500 -> '12 500'"""
    try:
        return f"{int(Decimal(value).quantize(Decimal('1'))):,}".replace(",", " ")
    except (InvalidOperation, TypeError, ValueError):
        return ""


@register.filter
def qty(value):
    """Miqdor: 5.000 -> '5', 1.250 -> '1,25'"""
    if value is None or value == "":
        return ""
    try:
        text = format(Decimal(value).normalize(), "f")
    except (InvalidOperation, TypeError, ValueError):
        return ""
    return text.replace(".", ",")


@register.filter
def plain_number(value):
    """Input maydoniga: 1.250 -> '1.25' (nuqta bilan, brauzer number inputi uchun)."""
    if value is None or value == "":
        return ""
    return format(Decimal(value).normalize(), "f")


@register.simple_tag(takes_context=True)
def page_url(context, number):
    """Joriy filtrlarni saqlagan holda sahifa havolasi."""
    query = context["request"].GET.copy()
    query["page"] = number
    return "?" + query.urlencode()
