from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('employee-calendar/<int:user_id>/', views.employee_calendar_view, name='employee_calendar'),
    path('admin-panel/', views.admin_panel, name='admin_panel'),
    path('bulk-hours/', views.bulk_hours_view, name='bulk_hours'),
    path('individual-hours/', views.individual_hours_view, name='individual_hours'),
    path('bulk-absence/', views.bulk_absence_view, name='bulk_absence'),
    path('superuser-dashboard/', views.superuser_dashboard, name='superuser_dashboard'),
    path('manage-users/', views.manage_users, name='manage_users'),
    path('register-employee/', views.register_employee, name='register_employee'),
    path('manage-holidays/', views.manage_holidays, name='manage_holidays'),

]