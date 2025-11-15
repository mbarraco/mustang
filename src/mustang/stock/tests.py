from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    ExchangeRateSnapshot,
    StockExchange,
    StockInstrument,
    StockOperation,
)
from .services import fetch_alpha_vantage_overview
from .utils import to_minor_units


class CreateInstrumentViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="trader",
            password="testpass123",
        )
        self.exchange, _ = StockExchange.objects.get_or_create(
            code="NYSE",
            defaults={
                "name": "New York Stock Exchange",
                "country": "US",
            },
        )

    def test_login_required(self):
        url = reverse("stock:instrument-create")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_authenticated_user_can_create_instrument(self):
        self.client.force_login(self.user)
        url = reverse("stock:instrument-create")
        response = self.client.post(
            url,
            {
                "symbol": "TEST",
                "name": "Test Instrument",
                "yahoo_symbol": "",
                "google_symbol": "",
                "instrument_type": "STOCK",
                "currency": "USD",
                "exchange": self.exchange.id,
            },
            follow=True,
        )
        self.assertContains(response, "TEST was added successfully.")
        self.assertTrue(StockInstrument.objects.filter(symbol="TEST").exists())

    def test_redirects_to_next_when_safe(self):
        self.client.force_login(self.user)
        url = reverse("stock:instrument-create")
        response = self.client.post(
            url,
            {
                "symbol": "SAFE",
                "name": "Safe Redirect",
                "yahoo_symbol": "",
                "google_symbol": "",
                "instrument_type": "STOCK",
                "currency": "USD",
                "exchange": self.exchange.id,
                "next": "/dashboard/",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/dashboard/")


class InstrumentLookupApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="lookup",
            password="secret123",
        )
        self.exchange, _ = StockExchange.objects.get_or_create(
            code="NASDAQ",
            defaults={
                "name": "Nasdaq Stock Market",
                "country": "US",
            },
        )
        self.url = reverse("stock:instrument-lookup")
        cache.clear()

    def test_login_required(self):
        response = self.client.get(self.url, {"symbol": "AAPL"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    @patch("stock.views.fetch_alpha_vantage_overview")
    def test_returns_basic_metadata(self, mock_fetch):
        mock_fetch.return_value = {
            "Symbol": "AAPL",
            "Name": "Apple Inc.",
            "AssetType": "Common Stock",
            "Currency": "USD",
            "Exchange": "NASDAQ",
        }
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"symbol": "aapl"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["symbol"], "AAPL")
        self.assertEqual(data["name"], "Apple Inc.")
        self.assertEqual(data["instrument_type"], "STOCK")
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(data["exchange"]["id"], self.exchange.id)

    @patch("stock.views.fetch_alpha_vantage_overview")
    def test_returns_hint_when_exchange_not_found(self, mock_fetch):
        mock_fetch.return_value = {
            "Symbol": "AAA",
            "Name": "Unknown Corp",
            "AssetType": "ETF",
            "Currency": "USD",
            "Exchange": "MOCK",
        }
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"symbol": "AAA"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data["exchange"])
        self.assertEqual(data["exchange_hint"], "MOCK")

    @patch("stock.views.fetch_alpha_vantage_overview")
    def test_selects_exchange_using_aliases(self, mock_fetch):
        target_exchange, _ = StockExchange.objects.get_or_create(
            code="BCBA",
            defaults={
                "name": "Bolsas y Mercados Argentinos (BYMA)",
                "country": "AR",
            },
        )
        mock_fetch.return_value = {
            "Symbol": "YPF",
            "Name": "YPF SA",
            "AssetType": "Common Stock",
            "Currency": "ARS",
            "Exchange": "Buenos Aires",
        }
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"symbol": "YPF"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["exchange"]["id"], target_exchange.id)

    @patch("stock.views.fetch_alpha_vantage_overview")
    def test_handles_validation_error(self, mock_fetch):
        mock_fetch.side_effect = ValidationError("Alpha returned nothing")
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"symbol": "bad"})
        self.assertEqual(response.status_code, 404)
        self.assertIn("Alpha returned nothing", response.json()["error"])

    @patch("stock.views.fetch_alpha_vantage_overview")
    def test_uses_cached_overview_for_repeat_symbol(self, mock_fetch):
        mock_fetch.return_value = {
            "Symbol": "AAPL",
            "Name": "Apple Inc.",
            "AssetType": "Common Stock",
            "Currency": "USD",
            "Exchange": "NASDAQ",
        }
        self.client.force_login(self.user)
        cache.clear()
        response = self.client.get(self.url, {"symbol": "AAPL"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_fetch.call_count, 1)

        mock_fetch.reset_mock()
        response = self.client.get(self.url, {"symbol": "AAPL"})
        self.assertEqual(response.status_code, 200)
        mock_fetch.assert_not_called()


class AlphaVantageServiceTests(TestCase):
    @override_settings(
        ALPHAVANTAGE_API_KEYS=["primary-key", "secondary-key"],
        MARKET_DATA_HTTP_TIMEOUT=5,
    )
    @patch("stock.services.requests.get")
    def test_fetch_overview_uses_fallback_key_when_rate_limited(self, mock_get):
        rate_limited_response = Mock()
        rate_limited_response.status_code = 200
        rate_limited_response.raise_for_status.return_value = None
        rate_limited_response.json.return_value = {
            "Note": (
                "We have detected your API key as PRIMARY and our standard API rate limit is 25 requests per day."
            )
        }

        success_response = Mock()
        success_response.status_code = 200
        success_response.raise_for_status.return_value = None
        success_response.json.return_value = {
            "Symbol": "YPF",
            "Name": "YPF SA",
            "Currency": "ARS",
            "Exchange": "Buenos Aires",
        }

        mock_get.side_effect = [rate_limited_response, success_response]

        payload = fetch_alpha_vantage_overview("YPF")
        self.assertEqual(payload["Symbol"], "YPF")
        self.assertEqual(mock_get.call_count, 2)
        first_params = mock_get.call_args_list[0].kwargs["params"]
        second_params = mock_get.call_args_list[1].kwargs["params"]
        self.assertEqual(first_params["apikey"], "primary-key")
        self.assertEqual(second_params["apikey"], "secondary-key")

class CreateOperationViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="operator",
            password="testpass123",
        )
        self.exchange, _ = StockExchange.objects.get_or_create(
            code="NYSE",
            defaults={
                "name": "New York Stock Exchange",
                "country": "US",
            },
        )
        self.instrument = StockInstrument.objects.create(
            symbol="ABC",
            name="ABC Corp",
            exchange=self.exchange,
        )

    def test_login_required(self):
        url = reverse("stock:operation-create")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_authenticated_user_can_create_operation(self):
        self.client.force_login(self.user)
        url = reverse("stock:operation-create")
        response = self.client.post(
            url,
            {
                "instrument": self.instrument.id,
                "timestamp": "2025-11-14T12:00",
                "operation_type": "BUY",
                "quantity": "10",
                "price": "1000",
                "currency": "ARS",
                "fees": "0",
            },
            follow=True,
        )
        self.assertContains(response, "recorded.")
        operation = StockOperation.objects.get(instrument=self.instrument)
        self.assertEqual(operation.user, self.user)


class ExchangeRateWizardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="fx",
            password="testpass123",
        )
        self.url = reverse("stock:exchange-rate-wizard")

    @patch("stock.views.fetch_ambito_exchange_rates")
    def test_auto_snapshot_created_on_first_visit(self, mock_fetch):
        mock_fetch.return_value = {
            "official": Decimal("100"),
            "mep": Decimal("150"),
            "blue": Decimal("200"),
            "custom": Decimal("125"),
            "as_of": "13/11/2025 - 12:00",
        }
        self.client.force_login(self.user)
        response = self.client.get(self.url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_fetch.call_count, 1)
        snapshot = ExchangeRateSnapshot.objects.get()
        self.assertEqual(snapshot.custom, 12500)
        self.assertEqual(snapshot.source, ExchangeRateSnapshot.Source.AUTOMATIC)

    @patch("stock.views.fetch_ambito_exchange_rates")
    def test_recent_snapshot_skips_auto_fetch(self, mock_fetch):
        ExchangeRateSnapshot.objects.create(
            timestamp=timezone.now(),
            currency="USD",
            official=10000,
            mep=15000,
            blue=20000,
            custom=15000,
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        mock_fetch.assert_not_called()

    def test_manual_entry_creates_snapshot(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"{self.url}?manual=1",
            {
                "action": "manual",
                "official": "123.45",
                "mep": "150.10",
                "blue": "160.10",
            },
        )
        self.assertEqual(response.status_code, 302)
        snapshot = ExchangeRateSnapshot.objects.get()
        expected = to_minor_units(
            (Decimal("123.45") + Decimal("150.10") + Decimal("160.10")) / 3
        )
        self.assertEqual(snapshot.custom, expected)
        self.assertEqual(snapshot.source, ExchangeRateSnapshot.Source.MANUAL)

    @patch("stock.views.fetch_ambito_exchange_rates")
    def test_refresh_action_forces_new_snapshot(self, mock_fetch):
        ExchangeRateSnapshot.objects.create(
            timestamp=timezone.now(),
            currency="USD",
            official=10000,
            mep=15000,
            blue=20000,
            custom=15000,
        )
        mock_fetch.return_value = {
            "official": Decimal("101"),
            "mep": Decimal("151"),
            "blue": Decimal("201"),
            "as_of": "timestamp",
        }
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            {"action": "refresh"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ExchangeRateSnapshot.objects.count(), 2)

    @patch("stock.views.fetch_ambito_exchange_rates")
    def test_auto_failure_prompts_manual_mode(self, mock_fetch):
        mock_fetch.side_effect = Exception("boom")
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manual entry")
        self.assertEqual(ExchangeRateSnapshot.objects.count(), 0)


class LandingViewTests(TestCase):
    def test_anonymous_user_can_access(self):
        url = reverse("landing")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome to Mustang")


class AuthFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="authuser",
            password="pass12345",
        )

    def test_login_page_loads(self):
        response = self.client.get(reverse("account_login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in")
        self.assertNotContains(response, "Continue with Google")

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="client",
        GOOGLE_OAUTH_CLIENT_SECRET="secret",
    )
    def test_google_button_visible_when_configured(self):
        response = self.client.get(reverse("account_login"))
        self.assertContains(response, "Continue with Google")

    def test_can_login_and_logout(self):
        response = self.client.post(
            reverse("account_login"),
            {"login": "authuser", "password": "pass12345"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["user"].is_authenticated)

        response = self.client.post(reverse("account_logout"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["user"].is_authenticated)
