from django import forms

from .models import StockInstrument, StockOperation
from .utils import to_major_units, to_minor_units


class StockInstrumentForm(forms.ModelForm):
    class Meta:
        model = StockInstrument
        fields = [
            "symbol",
            "name",
            "yahoo_symbol",
            "google_symbol",
            "instrument_type",
            "currency",
            "exchange",
        ]
        help_texts = {
            "symbol": "Primary ticker symbol that uniquely identifies the instrument.",
            "yahoo_symbol": "Optional override for Yahoo Finance.",
            "google_symbol": "Optional override for Google Finance.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs["class"] = (
                    f"{field.widget.attrs.get('class', '')} form-select"
                ).strip()
                continue
            css_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"form-control {css_class}".strip()
            field.widget.attrs.setdefault("placeholder", field.label)


class StockOperationForm(forms.ModelForm):
    price = forms.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=0,
        localize=False,
        widget=forms.NumberInput(attrs={"step": "0.01"}),
        help_text="Enter the unit price in major currency units (e.g., dollars).",
    )
    class Meta:
        model = StockOperation
        exclude = ["user"]
        widgets = {
            "timestamp": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}
            ),
            "operation_type": forms.Select(attrs={"class": "form-select"}),
            "instrument": forms.Select(attrs={"class": "form-select"}),
            "currency": forms.Select(attrs={"class": "form-select"}),
        }
        help_texts = {
            "fees": "Fees in minor units (defaults to 0).",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                continue
            if "class" not in field.widget.attrs:
                field.widget.attrs["class"] = "form-control"
        if self.instance and self.instance.price is not None:
            self.initial.setdefault("price", to_major_units(self.instance.price))

    def clean_price(self):
        price_value = self.cleaned_data.get("price")
        return to_minor_units(price_value)


class ExchangeRateSnapshotForm(forms.Form):
    official = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        label="Official USD/ARS",
    )
    mep = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        label="MEP USD/ARS",
    )
    blue = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        label="Blue USD/ARS",
    )
    custom = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        label="Custom USD/ARS",
        required=False,
        help_text="Optional override; defaults to the average of official, MEP, and blue.",
    )

    def __init__(self, *args, **kwargs):
        initial = kwargs.get("initial")
        if initial:
            transformed = {}
            for key, value in initial.items():
                if key == "custom" and value is None:
                    transformed[key] = None
                else:
                    transformed[key] = to_major_units(value) if value is not None else value
            kwargs["initial"] = transformed
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
