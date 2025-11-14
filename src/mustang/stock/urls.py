from django.urls import path

from .views import (
    instrument_performance,
    portfolio_summary,
    user_operation_timeline,
)

app_name = "stock"

urlpatterns = [
    path(
        "users/<int:user_id>/timeline/",
        user_operation_timeline,
        name="user-operation-timeline",
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
