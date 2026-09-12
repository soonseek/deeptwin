"""Pure example function. The framework never imports this control-plane-side."""


def transform_text(value):
    if type(value) is not str or len(value.encode("utf-8")) > 65_536:
        raise ValueError("value must be bounded text")
    return value.upper()
