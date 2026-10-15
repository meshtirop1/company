from django.urls import path

from . import views

app_name = 'cutting'

urlpatterns = [
    path('', views.hub, name='hub'),

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
