from django.contrib import admin
from .models import CustomUser, WorkHours, Holiday, Settings


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ['email', 'first_name', 'last_name', 'is_employee', 'is_admin', 'hourly_wage']
    list_filter = ['is_employee', 'is_admin', 'is_contracted']
    search_fields = ['email', 'first_name', 'last_name']


@admin.register(WorkHours)
class WorkHoursAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'hours', 'is_absence', 'created_at', 'updated_at']
    list_filter = ['is_absence', 'date', 'created_at']
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    date_hierarchy = 'date'
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Work Information', {
            'fields': ('user', 'date', 'hours', 'is_absence')
        }),
        ('Tracking Information', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ['name', 'date', 'created_at']
    list_filter = ['date']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ['minimum_wage', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']