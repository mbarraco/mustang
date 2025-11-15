from django.urls import path

from .views import (
    create_stock_instrument,
    create_stock_operation,
    exchange_rate_snapshot_wizard,
    instrument_performance,
    lookup_stock_instrument,
    portfolio_summary,
    user_operation_timeline,
)

app_name = "stock"

urlpatterns = [
    path(
        "instruments/new/",
        create_stock_instrument,
        name="instrument-create",
    ),
    path(
        "instruments/lookup/",
        lookup_stock_instrument,
        name="instrument-lookup",
    ),
    path(
        "exchange-rates/",
        exchange_rate_snapshot_wizard,
        name="exchange-rate-wizard",
    ),
    path(
        "users/<int:user_id>/timeline/",
        user_operation_timeline,
        name="user-operation-timeline",
    ),
    path(
        "operations/new/",
        create_stock_operation,
        name="operation-create",
    ),
    path(
        "users/<int:user_id>/portfolio/",
        portfolio_summary,
        name="portfolio-summary",
    ),
    path(
        "users/<int:user_id>/instruments/<int:instrument_id>/performance/",
        instrument_performance,
        name="instrument-performance",
    ),
]
