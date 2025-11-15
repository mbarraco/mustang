from django import template
from django.forms.boundfield import BoundField

register = template.Library()


@register.filter
def add_input_class(field, css_class):
    """
    Adds the provided class to a form field without mutating the original widget.
    """
    if not isinstance(field, BoundField):
        return field

    attrs = field.field.widget.attrs.copy()
    existing = attrs.get("class", "")
    if existing:
        attrs["class"] = f"{existing} {css_class}"
    else:
        attrs["class"] = css_class
    return field.as_widget(attrs=attrs)
