class UtilityError(Exception):
    """Base class for errors that should be shown to the user as-is."""


class KernelsNotLoaded(UtilityError):
    pass


class NoIntercept(UtilityError):
    """The camera boresight does not hit the target body at the requested time."""


class TimeParseError(UtilityError):
    pass


def spice_message(exc: Exception) -> str:
    """Condense a (multi-line) SpiceyError into one readable line."""
    lines = [ln.strip() for ln in str(exc).splitlines() if ln.strip() and not set(ln.strip()) <= {"="}]
    keep = [ln for ln in lines if ln.startswith("SPICE(") or "Insufficient" in ln or "not" in ln.lower()]
    return " ".join(keep[:2]) if keep else (lines[0] if lines else exc.__class__.__name__)
