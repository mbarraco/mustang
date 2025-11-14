import logging
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, render

from .enums import OperationType
from .models import StockInstrument, StockInstrumentSnapshot, StockOperation
from .services import sync_stock_instrument_snapshot

logger = logging.getLogger(__name__)


def user_operation_timeline(request, user_id: int):
    """Timeline-styled list of StockOperation entries for a given user."""
    user_model = get_user_model()
    subject_user = get_object_or_404(user_model, pk=user_id)
    base_operations = list(
        StockOperation.objects.filter(user=subject_user)
        .select_related("instrument", "instrument__exchange")
        .order_by("timestamp")
    )

    instrument_choices = {
        operation.instrument_id: operation.instrument.symbol
        for operation in base_operations
    }
    selected_instrument_id = request.GET.get("instrument") or ""

    refresh_status = None
    refresh_error = None
    if request.method == "POST":
        instrument_to_refresh_id = request.POST.get("refresh_instrument_id")
        if instrument_to_refresh_id:
            instrument = (
                StockInstrument.objects.filter(
                    pk=instrument_to_refresh_id,
                    operations__user=subject_user,
                )
                .distinct()
                .first()
            )
            if instrument is None:
                refresh_error = "Instrument not found for this user."
            else:
                try:
                    sync_stock_instrument_snapshot(instrument)
                    refresh_status = f"Synced latest price for {instrument.symbol}."
                except IntegrityError as exc:
                    logger.warning(
                        "Duplicate snapshot for %s ignored: %s",
                        instrument.symbol,
                        exc,
                    )
                    refresh_error = (
                        "Latest price already stored. Please try again later."
                    )
                except Exception as exc:  # pragma: no cover
                    logger.exception("Failed to refresh instrument %s", instrument.symbol)
                    refresh_error = f"Failed to refresh price: {exc}"

    if selected_instrument_id:
        operations = [
            operation
            for operation in base_operations
            if str(operation.instrument_id) == selected_instrument_id
        ]
    else:
        operations = base_operations

    instrument_ids = {operation.instrument_id for operation in operations}
    latest_snapshots = {}
    if instrument_ids:
        snapshots = (
            StockInstrumentSnapshot.objects.filter(instrument_id__in=instrument_ids)
            .select_related("instrument")
            .order_by("instrument_id", "-as_of")
        )
        for snapshot in snapshots:
            if snapshot.instrument_id not in latest_snapshots:
                latest_snapshots[snapshot.instrument_id] = snapshot

    running_quantity = Decimal("0")
    running_cost = Decimal("0")
    timeline_entries = []

    for operation in operations:
        quantity = operation.quantity or Decimal("0")
        price_minor = Decimal(operation.price or 0)

        if operation.operation_type == OperationType.BUY:
            running_cost += quantity * price_minor
            running_quantity += quantity
        elif operation.operation_type == OperationType.SELL:
            current_average = (
                running_cost / running_quantity if running_quantity > 0 else Decimal("0")
            )
            running_quantity -= quantity
            running_cost -= quantity * current_average
            if running_quantity < 0:
                running_quantity = Decimal("0")
            if running_cost < 0:
                running_cost = Decimal("0")

        weighted_average_price = None
        if running_quantity > 0:
            weighted_average_price = (running_cost / running_quantity).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )

        timeline_entries.append(
            {
                "operation": operation,
                "weighted_average_price": weighted_average_price,
                "running_quantity": running_quantity,
                "running_cost": running_cost,
                "latest_snapshot": latest_snapshots.get(operation.instrument_id),
            }
        )

    def format_decimal(value: Decimal | None, places: Decimal) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(places, rounding=ROUND_HALF_UP)

    for entry in timeline_entries:
        entry["running_quantity"] = format_decimal(entry["running_quantity"], Decimal("1"))
        entry["running_cost"] = format_decimal(entry["running_cost"], Decimal("0.01"))
        entry["weighted_average_price"] = format_decimal(
            entry["weighted_average_price"], Decimal("0.01")
        )

    context = {
        "subject_user": subject_user,
        "timeline_entries": timeline_entries,
        "instrument_choices": sorted(
            instrument_choices.items(),
            key=lambda item: item[1],
        ),
        "selected_instrument_id": selected_instrument_id,
        "refresh_status": refresh_status,
        "refresh_error": refresh_error,
    }
    return render(request, "stock/user_operation_timeline.html", context)


def instrument_performance(request, user_id: int, instrument_id: int):
    user_model = get_user_model()
    subject_user = get_object_or_404(user_model, pk=user_id)
    instrument = get_object_or_404(StockInstrument, pk=instrument_id)
    operations = (
        StockOperation.objects.filter(user=subject_user, instrument=instrument)
        .order_by("timestamp")
        .all()
    )
    latest_snapshot = (
        StockInstrumentSnapshot.objects.filter(instrument=instrument).first()
    )

    metrics = _compute_performance_metrics(operations, latest_snapshot)
    context = {
        "subject_user": subject_user,
        "instrument": instrument,
        **metrics,
    }
    return render(request, "stock/instrument_performance.html", context)


def portfolio_summary(request, user_id: int):
    user_model = get_user_model()
    subject_user = get_object_or_404(user_model, pk=user_id)
    operations = list(
        StockOperation.objects.filter(user=subject_user)
        .select_related("instrument", "instrument__exchange")
        .order_by("instrument_id", "timestamp")
    )
    instrument_ids = {op.instrument_id for op in operations}
    snapshots_map = {
        snap.instrument_id: snap
        for snap in StockInstrumentSnapshot.objects.filter(
            instrument_id__in=instrument_ids
        )
    }

    summaries = []
    instrument_groups = {}
    for op in operations:
        instrument_groups.setdefault(op.instrument_id, []).append(op)

    for instrument_id, ops in instrument_groups.items():
        instrument = ops[0].instrument
        metrics = _compute_performance_metrics(
            ops, snapshots_map.get(instrument_id)
        )
        summaries.append(
            {
                "instrument": instrument,
                **metrics,
            }
        )

    portfolio_totals = {
        "running_quantity": sum(
            (summary["running_quantity"] or Decimal("0")) for summary in summaries
        ),
        "running_cost": sum(
            (summary["running_cost"] or Decimal("0")) for summary in summaries
        ),
        "market_value": sum(
            (summary["market_value"] or Decimal("0")) for summary in summaries
        ),
        "unrealized_gain": sum(
            (summary["unrealized_gain"] or Decimal("0")) for summary in summaries
        ),
        "total_realized": sum(summary["total_realized"] for summary in summaries),
    }

    context = {
        "subject_user": subject_user,
        "summaries": summaries,
        "portfolio_totals": portfolio_totals,
    }
    return render(request, "stock/portfolio_summary.html", context)


def _compute_performance_metrics(
    operations, latest_snapshot: StockInstrumentSnapshot | None
) -> dict:
    running_quantity = Decimal("0")
    running_cost = Decimal("0")
    realized_entries = []
    total_realized = Decimal("0")

    for operation in operations:
        quantity = operation.quantity or Decimal("0")
        price_minor = Decimal(operation.price or 0)
        if operation.operation_type == OperationType.BUY:
            running_cost += quantity * price_minor
            running_quantity += quantity
        elif operation.operation_type == OperationType.SELL and running_quantity > 0:
            avg_cost = running_cost / running_quantity
            sell_quantity = min(quantity, running_quantity)
            running_quantity -= sell_quantity
            running_cost -= avg_cost * sell_quantity
            sale_proceeds = sell_quantity * price_minor
            realized = sale_proceeds - (avg_cost * sell_quantity)
            total_realized += realized
            realized_entries.append(
                {
                    "operation": operation,
                    "quantity": sell_quantity,
                    "avg_cost": avg_cost,
                    "sale_price": price_minor,
                    "realized": realized,
                }
            )

    market_value = None
    unrealized_gain = None
    weighted_average_price = None
    if latest_snapshot and running_quantity > 0:
        current_price = Decimal(latest_snapshot.price)
        market_value = current_price * running_quantity
        weighted_average_price = running_cost / running_quantity
        unrealized_gain = market_value - (weighted_average_price * running_quantity)

    return {
        "realized_entries": realized_entries,
        "total_realized": total_realized,
        "running_quantity": running_quantity,
        "running_cost": running_cost,
        "latest_snapshot": latest_snapshot,
        "market_value": market_value,
        "unrealized_gain": unrealized_gain,
        "weighted_average_price": weighted_average_price,
    }
