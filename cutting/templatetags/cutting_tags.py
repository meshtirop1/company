from django import template

register = template.Library()


@register.filter
def won(amount):
    """4500 → '4,500', the same in every language (floatformat's grouping follows the locale)."""
    if amount in (None, ''):
        return ''
    return f'{int(amount):,}'


@register.filter
def signed_won(amount):
    """A change in pay: 12000 → '+₩12,000', -3000 → '−₩3,000'."""
    if amount in (None, ''):
        return ''
    return f"{'−' if amount < 0 else '+'}₩{abs(int(amount)):,}"
