from django.contrib import admin
from .models import CustomUser, WorkHours, Holiday, Settings, EmployeeDeduction, EmployeeWage
from .wages import this_month, wage_for


class EmployeeWageInline(admin.TabularInline):
    model = EmployeeWage
    extra = 0
    fields = ['effective_from', 'hourly_wage', 'updated_at']
    readonly_fields = ['updated_at']


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ['email', 'first_name', 'last_name', 'is_employee', 'is_admin', 'current_wage']
    list_filter = ['is_employee', 'is_admin', 'is_contracted']
    search_fields = ['email', 'first_name', 'last_name']
    # Pay uses the dated wages below; hourly_wage is only the fallback for someone with none.
    readonly_fields = ['hourly_wage']
    inlines = [EmployeeWageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('wages')

    @admin.display(description='Hourly wage (this month)')
    def current_wage(self, user):
        return wage_for(user, this_month())


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


@admin.register(EmployeeDeduction)
class EmployeeDeductionAdmin(admin.ModelAdmin):
    list_display = ['user', 'effective_from', 'tax_percent', 'insurance_mode', 'insurance_value', 'updated_at']
    list_filter = ['insurance_mode']
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['created_at', 'updated_at']
