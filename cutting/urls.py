from datetime import date

from django.urls import path, register_converter

from . import peeling_views, views


class IsoDateConverter:
    """`2026-10-15` in a URL ⇄ a date. An impossible date (2026-02-30) is a 404, not a 500."""
    regex = r'\d{4}-\d{2}-\d{2}'

    def to_python(self, value):
        return date.fromisoformat(value)  # ValueError → the pattern doesn't match → 404

    def to_url(self, value):
        return value.isoformat() if isinstance(value, date) else value


class YearMonthConverter:
    """`2026-10` in a URL ⇄ the first day of that month. `2026-13` is a 404."""
    regex = r'\d{4}-\d{2}'

    def to_python(self, value):
        year, month = value.split('-')
        return date(int(year), int(month), 1)  # ValueError → no match → 404

    def to_url(self, value):
        return value.strftime('%Y-%m') if isinstance(value, date) else value


register_converter(IsoDateConverter, 'isodate')
register_converter(YearMonthConverter, 'yearmonth')

app_name = 'cutting'

urlpatterns = [
    path('', views.hub, name='hub'),
    path('help/', views.help_page, name='help'),

    path('entry/', views.entry, name='entry'),
    path('day/', views.day, name='day_today'),
    path('day/<isodate:day>/', views.day, name='day'),
    path('records/<int:pk>/edit/', views.record_edit, name='record_edit'),
    path('records/<int:pk>/delete/', views.record_delete, name='record_delete'),
    path('batches/<int:pk>/delete/', views.batch_delete, name='batch_delete'),

    path('month/', views.month_report, name='month_current'),
    path('month/<yearmonth:month>/', views.month_report, name='month'),
    path('month/<yearmonth:month>/export.xlsx', views.month_export, name='month_export'),
    path('month/<yearmonth:month>/payslips/', views.payslips, name='payslips'),
    path('month/<yearmonth:month>/cutters/<int:cutter_pk>/', views.cutter_report, name='cutter_month'),
    path('month/<yearmonth:month>/cutters/<int:cutter_pk>/payslip/', views.payslip, name='payslip'),
    path('month/<yearmonth:month>/lock/', views.month_lock, name='month_lock'),
    path('month/<yearmonth:month>/unlock/', views.month_unlock, name='month_unlock'),
    path('month/<yearmonth:month>/reprice/', views.reprice, name='reprice'),
    path('log/', views.audit_log, name='audit'),

    path('cutters/', views.cutters, name='cutters'),
    path('cutters/<int:pk>/edit/', views.cutter_edit, name='cutter_edit'),
    path('cutters/<int:pk>/active/', views.cutter_set_active, name='cutter_set_active'),
    path('cutters/<int:pk>/delete/', views.cutter_delete, name='cutter_delete'),
    path('cutters/<int:pk>/deductions/', views.cutter_deduction_set, name='cutter_deduction_set'),
    path('deductions/<int:pk>/delete/', views.cutter_deduction_delete, name='cutter_deduction_delete'),

    path('prices/', views.prices, name='prices'),
    path('prices/<int:pk>/edit/', views.item_edit, name='item_edit'),
    path('prices/<int:pk>/active/', views.item_set_active, name='item_set_active'),
    path('prices/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('prices/<int:item_pk>/rates/new/', views.rate_add, name='rate_add'),
    path('rates/<int:pk>/edit/', views.rate_edit, name='rate_edit'),
    path('rates/<int:pk>/delete/', views.rate_delete, name='rate_delete'),

    path('peeling/', peeling_views.peel_home, name='peel_home'),
    path('peeling/new/', peeling_views.peel_entry, name='peel_entry'),
    path('peeling/entries/<int:pk>/edit/', peeling_views.peel_entry_edit, name='peel_entry_edit'),
    path('peeling/entries/<int:pk>/delete/', peeling_views.peel_entry_delete, name='peel_entry_delete'),
    path('peeling/summary/', peeling_views.peel_summary, name='peel_summary_current'),
    path('peeling/summary/<yearmonth:month>/', peeling_views.peel_summary, name='peel_summary'),
    path('peeling/companies/new/', peeling_views.peel_company_new, name='peel_company_new'),
    path('peeling/companies/<int:pk>/', peeling_views.peel_company, name='peel_company'),
    path('peeling/companies/<int:pk>/edit/', peeling_views.peel_company_edit, name='peel_company_edit'),
    path('peeling/companies/<int:pk>/delete/', peeling_views.peel_company_delete, name='peel_company_delete'),
    path('peeling/companies/<int:pk>/prices/', peeling_views.peel_price_add, name='peel_price_add'),
    path('peeling/prices/<int:pk>/delete/', peeling_views.peel_price_delete, name='peel_price_delete'),
    path('peeling/companies/<int:pk>/<yearmonth:month>/', peeling_views.peel_statement, name='peel_statement'),
    path('peeling/companies/<int:pk>/<yearmonth:month>/paid/', peeling_views.peel_mark_paid,
         name='peel_mark_paid'),
    path('peeling/companies/<int:pk>/<yearmonth:month>/reopen/', peeling_views.peel_reopen, name='peel_reopen'),
]
