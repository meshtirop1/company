from django.contrib import admin

from .models import CutBatch, CutRecord, Cutter, PriceItem, PriceRate


@admin.register(Cutter)
class CutterAdmin(admin.ModelAdmin):
    list_display = ['name', 'note', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'note']
    readonly_fields = ['created_at', 'updated_at']


class PriceRateInline(admin.TabularInline):
    model = PriceRate
    extra = 0
    fields = ['effective_from', 'unit_price', 'created_by', 'created_at']
    readonly_fields = ['created_by', 'created_at']
    ordering = ['-effective_from']


@admin.register(PriceItem)
class PriceItemAdmin(admin.ModelAdmin):
    list_display = ['style', 'size', 'sort_order', 'is_active']
    list_filter = ['style', 'is_active']
    ordering = ['style', 'sort_order']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [PriceRateInline]


class CutRecordInline(admin.TabularInline):
    model = CutRecord
    extra = 0
    fields = ['cutter', 'style', 'size', 'boxes', 'unit_price', 'total']
    readonly_fields = fields  # priced at save time; correct records on the Entries page


@admin.register(CutBatch)
class CutBatchAdmin(admin.ModelAdmin):
    list_display = ['work_date', 'created_at', 'entered_by']
    date_hierarchy = 'work_date'
    readonly_fields = ['work_date', 'token', 'entered_by', 'created_at']
    inlines = [CutRecordInline]


@admin.register(CutRecord)
class CutRecordAdmin(admin.ModelAdmin):
    list_display = ['work_date', 'cutter', 'style', 'size', 'boxes', 'unit_price', 'total']
    list_filter = ['style', 'work_date']
    search_fields = ['cutter__name']
    date_hierarchy = 'work_date'
    readonly_fields = ['batch', 'cutter', 'item', 'work_date', 'style', 'size', 'boxes', 'unit_price', 'total',
                       'created_at', 'updated_at']
