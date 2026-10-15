from django import template

register = template.Library()


@register.filter
def won(amount):
    """4500 → '4,500', the same in every language (floatformat's grouping follows the locale)."""
    if amount in (None, ''):
        return ''
    return f'{int(amount):,}'
