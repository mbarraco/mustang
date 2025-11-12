from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    ExchangeRateSnapshot,
    StockExchange,
    StockInstrument,
    StockOperation,
)

User = get_user_model()


class UserAdmin(DjangoUserAdmin):
    pass


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass
admin.site.register(User, UserAdmin)


class StockInstrumentAdminForm(forms.ModelForm):
    exchange = forms.ModelChoiceField(
        queryset=StockExchange.objects.all().order_by("code"),
        widget=forms.Select,
    )

    class Meta:
        model = StockInstrument
        fields = "__all__"


class StockOperationInline(admin.TabularInline):
    model = StockOperation
    extra = 0
    fields = (
        "timestamp",
        "operation_type",
        "quantity",
        "price",
        "currency",
        "fees",
        "total_value_display",
    )
    readonly_fields = ("total_value_display",)
    ordering = ("-timestamp",)

    @staticmethod
    def total_value_display(obj: StockOperation) -> int:
        return obj.total_value

    total_value_display.short_description = "Total value"


@admin.register(StockInstrument)
class StockInstrumentAdmin(admin.ModelAdmin):
    form = StockInstrumentAdminForm
    list_display = (
        "symbol",
        "name",
        "instrument_type",
        "currency",
        "exchange",
        "date_created",
        "date_updated",
    )
    search_fields = ("symbol", "name", "exchange__code", "exchange__name")
    list_filter = ("instrument_type", "currency", "exchange")
    inlines = (StockOperationInline,)


@admin.register(StockOperation)
class StockOperationAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "instrument",
        "operation_type",
        "quantity",
        "price",
        "currency",
        "fees",
        "total_value_display",
    )
    list_filter = ("operation_type", "currency", "timestamp", "instrument")
    search_fields = (
        "instrument__symbol",
        "instrument__name",
    )
    date_hierarchy = "timestamp"

    @staticmethod
    def total_value_display(obj: StockOperation) -> int:
        return obj.total_value

    total_value_display.short_description = "Total value"


@admin.register(ExchangeRateSnapshot)
class ExchangeRateSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "currency",
        "official",
        "mep",
        "blue",
    )
    list_filter = ("currency",)
    date_hierarchy = "timestamp"
    search_fields = ("currency",)


@admin.register(StockExchange)
class StockExchangeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "country", "date_created", "date_updated")
    search_fields = ("code", "name", "country")
