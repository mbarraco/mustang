import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .enums import Currency, OperationType
from .forms import (
    ExchangeRateSnapshotForm,
    StockInstrumentForm,
    StockOperationForm,
)
from .models import (
    ExchangeRateSnapshot,
    StockInstrument,
    StockInstrumentSnapshot,
    StockOperation,
)
from .services import fetch_ambito_exchange_rates, sync_stock_instrument_snapshot
from .utils import to_minor_units

logger = logging.getLogger(__name__)
EXCHANGE_RATE_STALE_AFTER = timedelta(minutes=30)


def landing(request):
    context = {
        "subject_user": request.user if request.user.is_authenticated else None,
        "cta_links": [
            {
                "title": "Track your trades",
                "description": "Visualize a timeline of buys and sells plus profit metrics.",
                "url": (
                    reverse("stock:user-operation-timeline", args=[request.user.id])
                    if request.user.is_authenticated
                    else reverse("stock:operation-create")
                ),
                "label": "View operations" if request.user.is_authenticated else "Log an operation",
            },
            {
                "title": "Manage instruments",
                "description": "Add new tickers for tracking without waiting on admins.",
                "url": reverse("stock:instrument-create"),
                "label": "Add instrument",
            },
            {
                "title": "Monitor FX rates",
                "description": "Capture official, MEP, and blue USD/ARS quotes from ámbito.com.",
                "url": reverse("stock:exchange-rate-wizard"),
                "label": "Open FX wizard",
            },
        ],
    }
    return render(request, "stock/landing.html", context)


@login_required
def create_stock_instrument(request):
    """Allow authenticated users to register additional instruments."""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if request.method == "POST":
        form = StockInstrumentForm(request.POST)
        if form.is_valid():
            instrument = form.save()
            messages.success(
                request,
                f"{instrument.symbol} was added successfully.",
            )
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
            ):
                return redirect(next_url)
            return redirect("stock:instrument-create")
    else:
        form = StockInstrumentForm()

    context = {
        "form": form,
        "next": next_url,
    }
    return render(request, "stock/instrument_form.html", context)


@login_required
def create_stock_operation(request):
    """Allow authenticated users to log a new stock operation."""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    fx_snapshot = ExchangeRateSnapshot.objects.order_by("-timestamp").first()
    if request.method == "POST":
        form = StockOperationForm(request.POST)
        if form.is_valid():
            operation = form.save(commit=False)
            operation.user = request.user
            operation.save()
            messages.success(
                request,
                f"{operation.get_operation_type_display()} {operation.quantity} {operation.instrument.symbol} recorded.",
            )
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
            ):
                return redirect(next_url)
            return redirect("stock:operation-create")
    else:
        form = StockOperationForm()

    context = {
        "form": form,
        "next": next_url,
        "fx_snapshot": fx_snapshot,
    }
    return render(request, "stock/operation_form.html", context)


@login_required
def exchange_rate_snapshot_wizard(request):
    """
    Auto-fetch exchange rates when stale, fallback to manual entry when scraping fails.
    """
    latest_snapshot = ExchangeRateSnapshot.objects.order_by("-timestamp").first()
    manual_mode = request.GET.get("manual") == "1"
    auto_error = None
    created_snapshot = None
    form: ExchangeRateSnapshotForm | None = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "refresh":
            created_snapshot, auto_error = _attempt_exchange_rate_refresh(request)
            if created_snapshot:
                return redirect("stock:exchange-rate-wizard")
            manual_mode = True
        elif action == "manual":
            manual_mode = True
            form = ExchangeRateSnapshotForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                custom_value = data.get("custom")
                if custom_value in (None, ""):
                    custom_value = _average_rates(
                        {
                            "official": data["official"],
                            "mep": data["mep"],
                            "blue": data["blue"],
                        }
                    )
                ExchangeRateSnapshot.objects.create(
                    timestamp=timezone.now(),
                    currency=Currency.USD,
                    official=to_minor_units(data["official"]),
                    mep=to_minor_units(data["mep"]),
                    blue=to_minor_units(data["blue"]),
                    custom=to_minor_units(custom_value),
                    source=ExchangeRateSnapshot.Source.MANUAL,
                )
                messages.success(
                    request,
                    "Exchange rate snapshot saved manually.",
                )
                return redirect("stock:exchange-rate-wizard")
    else:
        form = ExchangeRateSnapshotForm(
            initial=_snapshot_initial(latest_snapshot),
        )

    if manual_mode and form is None:
        form = ExchangeRateSnapshotForm(
            initial=_snapshot_initial(latest_snapshot),
        )

    should_auto_fetch = (
        request.method == "GET"
        and not manual_mode
        and (
            not latest_snapshot
            or latest_snapshot.timestamp < timezone.now() - EXCHANGE_RATE_STALE_AFTER
        )
    )
    if should_auto_fetch:
        created_snapshot, auto_error = _attempt_exchange_rate_refresh(
            request, show_errors=False
        )
        if created_snapshot:
            return redirect("stock:exchange-rate-wizard")
        manual_mode = True

    if created_snapshot:
        latest_snapshot = ExchangeRateSnapshot.objects.order_by("-timestamp").first()
    context = {
        "latest_snapshot": latest_snapshot,
        "manual_mode": manual_mode,
        "auto_fetch_error": auto_error,
        "form": form,
        "snapshot_is_recent": bool(
            latest_snapshot
            and latest_snapshot.timestamp >= timezone.now() - EXCHANGE_RATE_STALE_AFTER
        ),
        "custom_tooltip": (
            "Custom rate defaults to the average of official, MEP, and blue quotes. "
            "Override it if you need a blended or adjusted rate."
        ),
    }
    return render(request, "stock/exchange_rate_wizard.html", context)


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


def _attempt_exchange_rate_refresh(request, show_errors: bool = True):
    try:
        rates = fetch_ambito_exchange_rates()
        snapshot = ExchangeRateSnapshot.objects.create(
            timestamp=timezone.now(),
            currency=Currency.USD,
            official=to_minor_units(rates["official"]),
            mep=to_minor_units(rates["mep"]),
            blue=to_minor_units(rates["blue"]),
            custom=to_minor_units(rates.get("custom") or _average_rates(rates)),
            source=ExchangeRateSnapshot.Source.AUTOMATIC,
        )
        as_of = rates.get("as_of")
        if show_errors:
            message_suffix = f" ({as_of})" if as_of else ""
            messages.success(
                request,
                f"Exchange rate snapshot created from Ámbito{message_suffix}.",
            )
        return snapshot, None
    except (ValidationError, Exception) as exc:
        logger.exception("Failed to refresh exchange rate snapshot: %s", exc)
        if show_errors:
            messages.error(
                request,
                "Automatic refresh failed. Please try again or enter values manually.",
            )
        return None, str(exc)


def _snapshot_initial(snapshot: ExchangeRateSnapshot | None):
    if not snapshot:
        return None
    return {
        "official": snapshot.official,
        "mep": snapshot.mep,
        "blue": snapshot.blue,
        "custom": snapshot.custom,
    }


def _average_rates(rates: dict) -> Decimal:
    values = [
        Decimal(str(rates.get("official", 0))),
        Decimal(str(rates.get("mep", 0))),
        Decimal(str(rates.get("blue", 0))),
    ]
    values = [value for value in values if value]
    if not values:
        return Decimal("0")
    return sum(values) / len(values)


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
    if running_quantity > 0:
        weighted_average_price = running_cost / running_quantity
    if latest_snapshot and running_quantity > 0:
        current_price = Decimal(latest_snapshot.price or 0)
        market_value = current_price * running_quantity
        if weighted_average_price is not None:
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
