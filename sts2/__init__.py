"""Spirescope package; importing it does not resolve personal filesystem paths."""


def __getattr__(name: str):
    if name == "__version__":
        from sts2.config import VERSION
        return VERSION
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
