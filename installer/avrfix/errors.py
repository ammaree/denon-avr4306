"""Typed errors for avrfix. The UI layers map these to plain-language messages."""


class AvrfixError(Exception):
    """Base for everything this tool raises on purpose."""


class NotReachable(AvrfixError):
    """The unit did not answer on the expected port(s)."""


class WrongModel(AvrfixError):
    """The target does not look like an AVR-4306 DM850 (OUI / shell / version guard)."""


class ShaMismatch(AvrfixError):
    """An image did not match its expected sha256 (wrong original, or a bad patch result)."""


class AcquireError(AvrfixError):
    """Could not obtain/extract the owner's original DM850I image."""


class PatchError(AvrfixError):
    """The byte-diff did not apply cleanly to the supplied original image."""


class HungModule(AvrfixError):
    """The module stopped answering — recoverable by an AC power-cycle (not a brick)."""


class WriteAborted(AvrfixError):
    """A guarded step did not confirm; nothing was written past that point."""
