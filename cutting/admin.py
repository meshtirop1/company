from django.contrib import admin

from .models import Cutter, PriceItem, PriceRate


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
