from django import forms


def style_widget(widget):
    """Barcha maydonlarga bir xil ko'rinish beradi (stillar base.html ichida)."""
    if isinstance(widget, forms.HiddenInput):
        return
    if isinstance(widget, forms.CheckboxInput):
        css = "h-5 w-5 rounded border-line accent-brand"
    else:
        css = "input"
    widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            style_widget(field.widget)
