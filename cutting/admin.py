from django.contrib import admin

from .models import AuditEntry, CutBatch, CutRecord, Cutter, MonthLock, PriceItem, PriceRate


@admin.register(Cutter)
class CutterAdmin(admin.ModelAdmin):
    list_display = ['name', 'note', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'note']
    readonly_fields = ['created_at', 'updated_at']


class ViewOnly:
    """Work records and prices change only on the supervisor pages — where the month lock,
    the change log and the price-list rules (e.g. a size keeps at least one rate) apply.
    Here they can be looked at, not changed."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PriceRateInline(ViewOnly, admin.TabularInline):
    model = PriceRate
    extra = 0
    fields = ['effective_from', 'unit_price', 'created_by', 'created_at']
    readonly_fields = fields
    ordering = ['-effective_from']


@admin.register(PriceItem)
class PriceItemAdmin(ViewOnly, admin.ModelAdmin):
    list_display = ['style', 'size', 'sort_order', 'is_active']
    list_filter = ['style', 'is_active']
    ordering = ['style', 'sort_order']
    readonly_fields = ['style', 'size', 'sort_order', 'is_active', 'created_at', 'updated_at']
    inlines = [PriceRateInline]


class CutRecordInline(ViewOnly, admin.TabularInline):
    model = CutRecord
    extra = 0
    fields = ['cutter', 'style', 'size', 'boxes', 'unit_price', 'total']
    readonly_fields = fields


@admin.register(CutBatch)
class CutBatchAdmin(ViewOnly, admin.ModelAdmin):
    list_display = ['work_date', 'created_at', 'entered_by_name']
    date_hierarchy = 'work_date'
    readonly_fields = ['work_date', 'token', 'entered_by', 'entered_by_name', 'created_at']
    inlines = [CutRecordInline]


@admin.register(CutRecord)
class CutRecordAdmin(ViewOnly, admin.ModelAdmin):
    list_display = ['work_date', 'cutter', 'style', 'size', 'boxes', 'unit_price', 'total']
    list_filter = ['style', 'work_date']
    search_fields = ['cutter__name']
    date_hierarchy = 'work_date'
    readonly_fields = ['batch', 'cutter', 'item', 'work_date', 'style', 'size', 'boxes', 'unit_price', 'total',
                       'created_at', 'updated_at']


@admin.register(MonthLock)
class MonthLockAdmin(ViewOnly, admin.ModelAdmin):
    """Locking and unlocking happen on the monthly pay page, where they are logged."""
    list_display = ['month', 'locked_by_name', 'locked_at']
    readonly_fields = ['month', 'locked_by', 'locked_by_name', 'locked_at']


@admin.register(AuditEntry)
class AuditEntryAdmin(ViewOnly, admin.ModelAdmin):
    list_display = ['at', 'action', 'month', 'work_date', 'cutter_name', 'user_name', 'reason']
    list_filter = ['action', 'month']
    search_fields = ['cutter_name', 'user_name', 'reason']
    date_hierarchy = 'at'
    readonly_fields = ['action', 'month', 'work_date', 'cutter_name', 'record_id', 'batch_id', 'before', 'after',
                       'reason', 'user', 'user_name', 'at']
