from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import CustomUser, WorkHours, Holiday, Settings


# CustomUser Admin
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = (
    'email', 'first_name', 'last_name', 'is_employee', 'is_admin', 'is_superuser', 'is_contracted', 'hourly_wage',
    'account_number', 'visa_type', 'bank_name')
    list_filter = ('is_employee', 'is_admin', 'is_superuser', 'is_contracted')
    search_fields = ('email', 'first_name', 'last_name', 'account_number', 'visa_type', 'bank_name')
    ordering = ('email',)

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal Info'), {'fields': ('first_name', 'last_name', 'account_number', 'visa_type', 'bank_name')}),
        (_('Permissions'), {'fields': ('is_employee', 'is_admin', 'is_superuser', 'is_active', 'is_staff')}),
        (_('Employment Info'), {'fields': ('is_contracted', 'hourly_wage')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
            'email', 'password1', 'password2', 'first_name', 'last_name', 'account_number', 'visa_type', 'bank_name',
            'is_employee', 'is_admin', 'is_contracted', 'hourly_wage'),
        }),
    )


# WorkHours Admin
class WorkHoursAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'hours', 'is_absence')
    list_filter = ('is_absence', 'date')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')
    ordering = ('-date',)


# Holiday Admin
class HolidayAdmin(admin.ModelAdmin):
    list_display = ('date', 'name')
    search_fields = ('name',)
    ordering = ('date',)


# Settings Admin
class SettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'minimum_wage')

    # Only one instance should exist, so restrict adding/deleting
    def has_add_permission(self, request):
        return not Settings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# Register models with admin site
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(WorkHours, WorkHoursAdmin)
admin.site.register(Holiday, HolidayAdmin)
admin.site.register(Settings, SettingsAdmin)