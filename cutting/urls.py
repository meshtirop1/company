from datetime import date

from django.urls import path, register_converter

from . import views


class IsoDateConverter:
    """`2026-10-15` in a URL ⇄ a date. An impossible date (2026-02-30) is a 404, not a 500."""
    regex = r'\d{4}-\d{2}-\d{2}'

    def to_python(self, value):
        return date.fromisoformat(value)  # ValueError → the pattern doesn't match → 404

    def to_url(self, value):
        return value.isoformat() if isinstance(value, date) else value


register_converter(IsoDateConverter, 'isodate')

app_name = 'cutting'

urlpatterns = [
    path('', views.hub, name='hub'),

    path('entry/', views.entry, name='entry'),
    path('day/', views.day, name='day_today'),
    path('day/<isodate:day>/', views.day, name='day'),
    path('records/<int:pk>/edit/', views.record_edit, name='record_edit'),
    path('records/<int:pk>/delete/', views.record_delete, name='record_delete'),
    path('batches/<int:pk>/delete/', views.batch_delete, name='batch_delete'),

    path('cutters/', views.cutters, name='cutters'),
    path('cutters/<int:pk>/edit/', views.cutter_edit, name='cutter_edit'),
    path('cutters/<int:pk>/active/', views.cutter_set_active, name='cutter_set_active'),
    path('cutters/<int:pk>/delete/', views.cutter_delete, name='cutter_delete'),

    path('prices/', views.prices, name='prices'),
    path('prices/<int:pk>/edit/', views.item_edit, name='item_edit'),
    path('prices/<int:pk>/active/', views.item_set_active, name='item_set_active'),
    path('prices/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('prices/<int:item_pk>/rates/new/', views.rate_add, name='rate_add'),
    path('rates/<int:pk>/edit/', views.rate_edit, name='rate_edit'),
    path('rates/<int:pk>/delete/', views.rate_delete, name='rate_delete'),
]
