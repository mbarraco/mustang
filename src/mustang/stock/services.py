from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone

from .models import StockInstrument, StockInstrumentSnapshot
from .utils import to_minor_units

ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"
YAHOO_FINANCE_QUOTE_PAGE = "https://finance.yahoo.com/quote/{symbol}/"
YAHOO_PAGE_DATA_PATTERN = re.compile(
    r"root\.App\.main\s*=\s*(\{.*?\});\s*window\.YAHOO", re.DOTALL
)
DEFAULT_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
}
SNAPSHOT_REFRESH_INTERVAL = timedelta(minutes=15)
AMBITO_BASE_URL = "https://mercados.ambito.com"
AMBITO_EXCHANGE_ENDPOINTS = {
    "official": "/dolar/oficial/variacion",
    "blue": "/dolar/informal/variacion",
    "mep": "/dolarrava/mep/variacion",
}

logger = logging.getLogger(__name__)


def fetch_alpha_vantage_quote(
    symbol: str,
    *,
    api_key: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Call Alpha Vantage's GLOBAL_QUOTE endpoint and return the parsed payload.

    Raises
    ------
    ImproperlyConfigured
        When an API key is not configured.
    ValidationError
        When the API returns a successful HTTP status but no quote payload.
    requests.RequestException
        When the underlying HTTP request fails.
    """
    key = api_key or getattr(settings, "ALPHAVANTAGE_API_KEY", None)
    if not key:
        raise ImproperlyConfigured(
            "Alpha Vantage API key is missing. "
            "Set ALPHAVANTAGE_API_KEY in Django settings or the environment."
        )

    response = requests.get(
        ALPHAVANTAGE_URL,
        params={
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": key,
        },
        timeout=timeout or getattr(settings, "MARKET_DATA_HTTP_TIMEOUT", 10),
    )
    response.raise_for_status()
    payload = response.json().get("Global Quote") or {}
    if not payload:
        raise ValidationError(
            f"Alpha Vantage returned an empty payload for symbol '{symbol}'."
        )
    return payload


def fetch_yahoo_finance_quote(
    symbols: Iterable[str],
    *,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Scrape Yahoo Finance quote pages for the first symbol that returns data.
    """
    checked = []
    last_error: Optional[Exception] = None
    for symbol in symbols:
        checked.append(symbol)
        try:
            response = requests.get(
                YAHOO_FINANCE_QUOTE_PAGE.format(symbol=symbol),
                timeout=timeout or getattr(settings, "MARKET_DATA_HTTP_TIMEOUT", 10),
                headers=DEFAULT_HTTP_HEADERS,
            )
            response.raise_for_status()
            payload = _extract_yahoo_payload(response.text)
            price_block = payload.get("price") or {}
            if price_block.get("regularMarketPrice"):
                price_block["_symbol_used"] = symbol
                return price_block
        except Exception as exc:  # pragma: no cover
            last_error = exc
            logger.info("Yahoo Finance scrape failed for %s (%s)", symbol, exc)

    raise ValidationError(
        last_error
        or f"Yahoo Finance returned no data for symbols: {', '.join(checked)}"
    )


def sync_stock_instrument_snapshot(
    instrument: StockInstrument,
    *,
    api_key: Optional[str] = None,
) -> StockInstrumentSnapshot:
    """
    Fetch market data for the given instrument.symbol and persist a snapshot.
    """
    existing_snapshot = (
        StockInstrumentSnapshot.objects.filter(instrument=instrument).first()
    )
    if existing_snapshot:
        age = timezone.now() - existing_snapshot.date_updated
        if age < SNAPSHOT_REFRESH_INTERVAL:
            logger.info(
                "Skipping refresh for %s; snapshot age %s < %s",
                instrument.symbol,
                age,
                SNAPSHOT_REFRESH_INTERVAL,
            )
            return existing_snapshot

    try:
        quote = fetch_alpha_vantage_quote(instrument.symbol, api_key=api_key)
        snapshot_kwargs = _build_snapshot_kwargs_from_alpha(instrument, quote)
    except ValidationError as alpha_error:
        logger.info(
            "Alpha Vantage payload missing for %s, falling back to Yahoo Finance (%s)",
            instrument.symbol,
            alpha_error,
        )
        yahoo_quote = fetch_yahoo_finance_quote(_yahoo_symbol_candidates(instrument))
        snapshot_kwargs = _build_snapshot_kwargs_from_yahoo(instrument, yahoo_quote)

    if existing_snapshot:
        for field, value in snapshot_kwargs.items():
            setattr(existing_snapshot, field, value)
        existing_snapshot.save(
            update_fields=[
                "as_of",
                "price",
                "open_price",
                "day_high",
                "day_low",
                "volume",
                "data_source",
                "date_updated",
            ]
        )
        return existing_snapshot

    return StockInstrumentSnapshot.objects.create(**snapshot_kwargs)


def fetch_ambito_exchange_rates(timeout: Optional[int] = None) -> Dict[str, Any]:
    """
    Scrape exchange rate data from Ámbito's JSON endpoints.
    """
    rates: Dict[str, Decimal] = {}
    as_of_str: Optional[str] = None
    http_timeout = timeout or getattr(settings, "MARKET_DATA_HTTP_TIMEOUT", 10)

    for key, path in AMBITO_EXCHANGE_ENDPOINTS.items():
        response = requests.get(
            f"{AMBITO_BASE_URL.rstrip('/')}{path}",
            timeout=http_timeout,
            headers=DEFAULT_HTTP_HEADERS,
        )
        response.raise_for_status()
        payload = response.json()
        rate_value = payload.get("venta") or payload.get("valor") or payload.get("ultimo")
        if not rate_value:
            raise ValidationError(f"Ámbito response missing a '{key}' rate.")
        rates[key] = _parse_ambito_decimal(rate_value)
        if not as_of_str and payload.get("fecha"):
            as_of_str = payload["fecha"]

    return {
        "official": rates["official"],
        "blue": rates["blue"],
        "mep": rates["mep"],
        "as_of": as_of_str,
    }


def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
    if value in (None, "", "None"):
        return None
    return Decimal(str(value))


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value in (None, "", "None"):
        return None
    return int(value)


def _parse_alpha_as_of(quote: Dict[str, Any]) -> timezone.datetime:
    """
    Alpha Vantage only returns the trading day (no time of day). We align it with
    the current UTC time so the timestamp reflects roughly when the snapshot was taken.
    """
    now_utc = timezone.now().astimezone(dt_timezone.utc)
    date_str = quote.get("07. latest trading day")
    if not date_str:
        return now_utc
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return now_utc
    combined = datetime(
        parsed.year,
        parsed.month,
        parsed.day,
        now_utc.hour,
        now_utc.minute,
        now_utc.second,
        now_utc.microsecond,
        tzinfo=dt_timezone.utc,
    )
    return combined


def _parse_epoch_seconds(value: Optional[int]) -> timezone.datetime:
    if not value:
        return timezone.now()
    return timezone.make_aware(
        datetime.fromtimestamp(value, tz=dt_timezone.utc),
        timezone=dt_timezone.utc,
    )


def _extract_raw(field: Any) -> Any:
    if isinstance(field, dict):
        return field.get("raw")
    return field


def _build_snapshot_kwargs_from_alpha(
    instrument: StockInstrument, quote: Dict[str, Any]
) -> Dict[str, Any]:
    price = to_minor_units(_parse_decimal(quote.get("05. price"))) or 0
    return {
        "instrument": instrument,
        "as_of": _parse_alpha_as_of(quote),
        "price": price,
        "open_price": to_minor_units(_parse_decimal(quote.get("02. open"))),
        "day_high": to_minor_units(_parse_decimal(quote.get("03. high"))),
        "day_low": to_minor_units(_parse_decimal(quote.get("04. low"))),
        "volume": _parse_int(quote.get("06. volume")),
        "data_source": "alpha_vantage",
    }


def _build_snapshot_kwargs_from_yahoo(
    instrument: StockInstrument, quote: Dict[str, Any]
) -> Dict[str, Any]:
    price = (
        to_minor_units(_parse_decimal(_extract_raw(quote.get("regularMarketPrice"))))
        or 0
    )
    return {
        "instrument": instrument,
        "as_of": _parse_epoch_seconds(_extract_raw(quote.get("regularMarketTime"))),
        "price": price,
        "open_price": to_minor_units(
            _parse_decimal(_extract_raw(quote.get("regularMarketOpen")))
        ),
        "day_high": to_minor_units(
            _parse_decimal(_extract_raw(quote.get("regularMarketDayHigh")))
        ),
        "day_low": to_minor_units(
            _parse_decimal(_extract_raw(quote.get("regularMarketDayLow")))
        ),
        "volume": _parse_int(_extract_raw(quote.get("regularMarketVolume"))),
        "data_source": "yahoo_finance",
    }


def _yahoo_symbol_candidates(instrument: StockInstrument) -> Iterable[str]:
    """
    Try instrument.symbol plus exchange-specific suffixed versions (e.g., .BA).
    """
    if instrument.yahoo_symbol:
        return [instrument.yahoo_symbol]
    # Fallback to the canonical symbol only when overrides are missing; callers
    # should ideally guard against this and show a user-facing message.
    return [instrument.symbol]


def _extract_yahoo_payload(page_html: str) -> Dict[str, Any]:
    match = YAHOO_PAGE_DATA_PATTERN.search(page_html)
    if not match:
        raise ValidationError("Yahoo Finance page structure not recognized.")
    json_blob = match.group(1)
    data = json.loads(json_blob)
    return (
        data.get("context", {})
        .get("dispatcher", {})
        .get("stores", {})
        .get("QuoteSummaryStore", {})
    )


def _parse_ambito_decimal(value: str) -> Decimal:
    normalized = value.replace(".", "").replace(",", ".")
    return Decimal(normalized)
