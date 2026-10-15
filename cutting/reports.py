"""Pay figures built from work records: what each cutter did and earned, by day and by month.

Everything is summed from the prices and totals saved on the records, never recalculated
from today's price list, so a report always shows exactly what was recorded.
"""
import calendar

from django.db.models import Sum
from django.utils import timezone

from .models import CutRecord, Cutter, CuttingStyle

STYLE_RANK = {value: rank for rank, value in enumerate(CuttingStyle.values)}
STYLE_LABELS = dict(CuttingStyle.choices)
LINE_FIELDS = ('style', 'size', 'unit_price', 'item__sort_order')


def month_bounds(first_day):
    """The first and last day of the calendar month that starts on `first_day`."""
    return first_day, first_day.replace(day=calendar.monthrange(first_day.year, first_day.month)[1])


def month_status(first_day, today=None):
    """Whether a month's figures can still grow: until its last day has passed they are
    provisional, covering only the work recorded through `through`."""
    today = today or timezone.localdate()
    last = month_bounds(first_day)[1]
    return {'provisional': today <= last, 'through': min(today, last)}


def provisional_note(T, first_day, today=None):
    """'Provisional — up to <date>' while the month isn't over, so no one takes it as final pay."""
    status = month_status(first_day, today)
    return T['provisional_note'].format(date=status['through'].isoformat()) if status['provisional'] else ''


def by_name(cutter):
    return cutter.name.casefold()


def line_order(line):
    return STYLE_RANK.get(line['style'], len(STYLE_RANK)), line['item__sort_order'], line['size'], line['unit_price']


def grouped_lines(records, *by):
    """Boxes and pay grouped by style, size and rate — a mid-month price change gives two lines.

    `.order_by()` clears the model's default ordering so it can't split the groups.
    """
    rows = records.order_by().values(*by, *LINE_FIELDS).annotate(boxes=Sum('boxes'), amount=Sum('total'))
    return [{**row, 'style_label': STYLE_LABELS.get(row['style'], row['style'])} for row in rows]


def empty_style_totals():
    return {style: {'boxes': 0, 'amount': 0} for style in CuttingStyle.values}


def style_cells(totals):
    """Per-style totals in report column order (통포, then 통할복), for templates and Excel."""
    return [{'style': style, 'label': label, **totals[style]} for style, label in CuttingStyle.choices]


def summarise(lines):
    """Totals over a list of lines: per style, all boxes, all pay."""
    by_style = empty_style_totals()
    for line in lines:
        by_style[line['style']]['boxes'] += line['boxes']
        by_style[line['style']]['amount'] += line['amount']
    return {
        'style_cells': style_cells(by_style),
        'boxes': sum(line['boxes'] for line in lines),
        'total': sum(line['amount'] for line in lines),
    }


def day_summary(day):
    """Each cutter who worked on `day`, with their lines and the day's boxes and pay."""
    lines_by_cutter = {}
    for line in grouped_lines(CutRecord.objects.filter(work_date=day), 'cutter_id'):
        lines_by_cutter.setdefault(line['cutter_id'], []).append(line)
    cutters = Cutter.objects.in_bulk(lines_by_cutter)
    entries = []
    for cutter_id, lines in lines_by_cutter.items():
        lines.sort(key=line_order)
        entries.append({'cutter': cutters[cutter_id], 'lines': lines, **summarise(lines)})
    return sorted(entries, key=lambda entry: by_name(entry['cutter']))


def month_summary(first_day):
    """Every cutter's month (first to last day), split by style, plus the month's totals."""
    first, last = month_bounds(first_day)
    records = CutRecord.objects.filter(work_date__range=(first, last))
    rows = records.order_by().values('cutter_id', 'style').annotate(boxes=Sum('boxes'), amount=Sum('total'))

    totals_by_cutter, month_totals = {}, empty_style_totals()
    for row in rows:
        totals = totals_by_cutter.setdefault(row['cutter_id'], empty_style_totals())
        totals[row['style']] = {'boxes': row['boxes'], 'amount': row['amount']}
        month_totals[row['style']]['boxes'] += row['boxes']
        month_totals[row['style']]['amount'] += row['amount']

    cutters = Cutter.objects.in_bulk(totals_by_cutter)
    cutter_rows = sorted((
        {
            'cutter': cutters[cutter_id],
            'style_cells': style_cells(totals),
            'boxes': sum(cell['boxes'] for cell in totals.values()),
            'total': sum(cell['amount'] for cell in totals.values()),
        }
        for cutter_id, totals in totals_by_cutter.items()
    ), key=lambda row: by_name(row['cutter']))

    return {
        'first': first,
        'last': last,
        'rows': cutter_rows,
        'style_cells': style_cells(month_totals),
        'boxes': sum(cell['boxes'] for cell in month_totals.values()),
        'total': sum(cell['amount'] for cell in month_totals.values()),
    }


def cutter_month(cutter, first_day):
    """One cutter's month: lines for the payslip, a day-by-day breakdown, and the totals."""
    first, last = month_bounds(first_day)
    records = CutRecord.objects.filter(cutter=cutter, work_date__range=(first, last))

    lines_by_day = {}
    for line in grouped_lines(records, 'work_date'):
        lines_by_day.setdefault(line['work_date'], []).append(line)
    days = []
    for day in sorted(lines_by_day):
        lines = sorted(lines_by_day[day], key=line_order)
        days.append({'date': day, 'lines': lines, **summarise(lines)})

    lines = sorted(grouped_lines(records), key=line_order)
    style_groups = []
    for style, label in CuttingStyle.choices:
        members = [line for line in lines if line['style'] == style]
        if members:
            style_groups.append({
                'style': style, 'label': label, 'lines': members,
                'boxes': sum(line['boxes'] for line in members),
                'amount': sum(line['amount'] for line in members),
            })
    return {
        'cutter': cutter, 'first': first, 'last': last,
        'days': days, 'lines': lines, 'style_groups': style_groups, **summarise(lines),
    }


def cutters_paid_in(first_day):
    """Cutters with any work recorded in the month, by name — inactive ones included."""
    first, last = month_bounds(first_day)
    worked = CutRecord.objects.filter(work_date__range=(first, last)).values('cutter_id')
    return sorted(Cutter.objects.filter(pk__in=worked), key=by_name)
