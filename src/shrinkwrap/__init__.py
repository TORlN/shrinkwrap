try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("shrinkwrap")
except Exception:
    __version__ = "0.0.0"

from .parser import ParsedDocument, Section, ShrinkWrapClassificationWarning, parse
from .schema import VerifyResult, serialize, verify

__all__ = [
    "__version__",
    "ParsedDocument",
    "Section",
    "ShrinkWrapClassificationWarning",
    "parse",
    "VerifyResult",
    "serialize",
    "verify",
]
