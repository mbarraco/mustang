from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone

from .enums import InstrumentType
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

ALPHA_ASSET_TYPE_MAP = {
    "COMMON STOCK": InstrumentType.STOCK,
    "PREFERRED STOCK": InstrumentType.STOCK,
    "STOCK": InstrumentType.STOCK,
    "EQUITY": InstrumentType.STOCK,
    "ADR": InstrumentType.ADR,
    "AMERICAN DEPOSITARY RECEIPT": InstrumentType.ADR,
    "ETF": InstrumentType.ETF,
    "EXCHANGE TRADED FUND": InstrumentType.ETF,
    "BOND": InstrumentType.BOND,
}

logger = logging.getLogger(__name__)


class AlphaVantageRateLimitError(ValidationError):
    """Raised when Alpha Vantage signals a rate limit event."""


def _get_alpha_api_keys(overridden: Optional[str]) -> List[str]:
    if overridden:
        return [overridden]
    configured_keys: List[str] = list(getattr(settings, "ALPHAVANTAGE_API_KEYS", []))
    if not configured_keys:
        fallback = getattr(settings, "ALPHAVANTAGE_API_KEY", None)
        if fallback:
            configured_keys = [fallback]
    keys: List[str] = []
    for candidate in configured_keys:
        candidate = (candidate or "").strip()
        if candidate and candidate not in keys:
            keys.append(candidate)
    if not keys:
        raise ImproperlyConfigured(
            "Alpha Vantage API key is missing. "
            "Set ALPHAVANTAGE_API_KEY in Django settings or the environment."
        )
    return keys


def _extract_alpha_diagnostic(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key in ("Note", "Information", "Error Message"):
            message = payload.get(key)
            if message:
                return message
    return None


def _is_alpha_rate_limit_message(message: Optional[str]) -> bool:
    if not message:
        return False
    lowered = message.lower()
    rate_limit_signals = [
        "standard api rate limit",
        "please visit https://www.alphavantage.co/premium",
        "premium plan",
        "call frequency",
        "rate limit",
    ]
    return any(signal in lowered for signal in rate_limit_signals)


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
    timeout_value = timeout or getattr(settings, "MARKET_DATA_HTTP_TIMEOUT", 10)
    last_rate_limit_error: Optional[AlphaVantageRateLimitError] = None
    for idx, key in enumerate(_get_alpha_api_keys(api_key), start=1):
        try:
            return _fetch_alpha_vantage_quote_with_key(
                symbol,
                api_key=key,
                timeout=timeout_value,
                key_position=idx,
            )
        except AlphaVantageRateLimitError as exc:
            last_rate_limit_error = exc
            logger.info(
                "Alpha Vantage GLOBAL_QUOTE rate limit for symbol=%s using key #%s; trying fallback.",
                symbol,
                idx,
            )
            continue
    if last_rate_limit_error:
        raise last_rate_limit_error
    raise ValidationError(f"Alpha Vantage request failed for symbol '{symbol}'.")


def fetch_alpha_vantage_overview(
    symbol: str,
    *,
    api_key: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Call Alpha Vantage's OVERVIEW endpoint and return the payload."""

    timeout_value = timeout or getattr(settings, "MARKET_DATA_HTTP_TIMEOUT", 10)
    last_rate_limit_error: Optional[AlphaVantageRateLimitError] = None
    for idx, key in enumerate(_get_alpha_api_keys(api_key), start=1):
        try:
            return _fetch_alpha_vantage_overview_with_key(
                symbol,
                api_key=key,
                timeout=timeout_value,
                key_position=idx,
            )
        except AlphaVantageRateLimitError as exc:
            last_rate_limit_error = exc
            logger.info(
                "Alpha Vantage OVERVIEW rate limit for symbol=%s using key #%s; trying fallback.",
                symbol,
                idx,
            )
            continue
    if last_rate_limit_error:
        raise last_rate_limit_error
    raise ValidationError(f"Alpha Vantage returned no overview data for symbol '{symbol}'.")


def _fetch_alpha_vantage_quote_with_key(
    symbol: str,
    *,
    api_key: str,
    timeout: int,
    key_position: int,
) -> Dict[str, Any]:
    logger.info(
        "Alpha Vantage GLOBAL_QUOTE request for symbol=%s (key #%s)",
        symbol,
        key_position,
    )
    response = requests.get(
        ALPHAVANTAGE_URL,
        params={
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": api_key,
        },
        timeout=timeout,
    )
    logger.info(
        "Alpha Vantage GLOBAL_QUOTE response status=%s for symbol=%s (key #%s)",
        response.status_code,
        symbol,
        key_position,
    )
    response.raise_for_status()
    raw_payload = response.json()
    diagnostic = _extract_alpha_diagnostic(raw_payload)
    if diagnostic:
        logger.info(
            "Alpha Vantage GLOBAL_QUOTE diagnostic for symbol=%s (key #%s): %s",
            symbol,
            key_position,
            diagnostic,
        )
    if _is_alpha_rate_limit_message(diagnostic):
        logger.info(
            "Alpha Vantage GLOBAL_QUOTE rate limit detected for symbol=%s (key #%s)",
            symbol,
            key_position,
        )
        raise AlphaVantageRateLimitError(diagnostic)
    payload_data = raw_payload if isinstance(raw_payload, dict) else {}
    payload = payload_data.get("Global Quote") or {}
    if not payload:
        message = diagnostic or f"Alpha Vantage returned an empty payload for symbol '{symbol}'."
        raise ValidationError(message)
    logger.info(
        "Alpha Vantage GLOBAL_QUOTE success for symbol=%s (price=%s, volume=%s)",
        symbol,
        payload.get("05. price"),
        payload.get("06. volume"),
    )
    return payload


def _fetch_alpha_vantage_overview_with_key(
    symbol: str,
    *,
    api_key: str,
    timeout: int,
    key_position: int,
) -> Dict[str, Any]:
    logger.info(
        "Alpha Vantage OVERVIEW request for symbol=%s (key #%s)",
        symbol,
        key_position,
    )
    response = requests.get(
        ALPHAVANTAGE_URL,
        params={
            "function": "OVERVIEW",
            "symbol": symbol,
            "apikey": api_key,
        },
        timeout=timeout,
    )
    logger.info(
        "Alpha Vantage OVERVIEW response status=%s for symbol=%s (key #%s)",
        response.status_code,
        symbol,
        key_position,
    )
    response.raise_for_status()
    raw_payload = response.json()
    diagnostic = _extract_alpha_diagnostic(raw_payload)
    if diagnostic:
        logger.info(
            "Alpha Vantage OVERVIEW diagnostic for symbol=%s (key #%s): %s",
            symbol,
            key_position,
            diagnostic,
        )
    if _is_alpha_rate_limit_message(diagnostic):
        logger.info(
            "Alpha Vantage OVERVIEW rate limit detected for symbol=%s (key #%s)",
            symbol,
            key_position,
        )
        raise AlphaVantageRateLimitError(diagnostic)
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    payload_keys = list(payload.keys())
    if not payload or not payload.get("Symbol"):
        message = diagnostic or f"Alpha Vantage returned no overview data for symbol '{symbol}'."
        logger.info(
            "Alpha Vantage OVERVIEW missing data for symbol=%s (key #%s, keys=%s)",
            symbol,
            key_position,
            payload_keys,
        )
        raise ValidationError(message)
    logger.info(
        "Alpha Vantage OVERVIEW success for symbol=%s (name=%s, exchange=%s, currency=%s)",
        symbol,
        payload.get("Name"),
        payload.get("Exchange"),
        payload.get("Currency"),
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


def map_alpha_asset_type(asset_type: Optional[str]) -> Optional[str]:
    """Translate Alpha Vantage asset types to internal instrument categories."""

    if not asset_type:
        return None
    normalized = asset_type.strip().upper()
    if normalized in ALPHA_ASSET_TYPE_MAP:
        return ALPHA_ASSET_TYPE_MAP[normalized]
    for key, mapped in ALPHA_ASSET_TYPE_MAP.items():
        if key in normalized:
            return mapped
    return None


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
