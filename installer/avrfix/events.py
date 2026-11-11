"""Event types the flasher emits and the prompts it asks. CLI and GUI subscribe to these,
so there is one source of truth for steps, progress, and the human decisions."""
from dataclasses import dataclass


@dataclass
class Step:
    """A phase begins. `human` is a plain-language line for the UI."""
    name: str
    human: str


@dataclass
class Progress:
    """Progress within a step (e.g. TFTP block n of total)."""
    step: str
    done: int
    total: int
    note: str = ""


@dataclass
class Info:
    """A neutral status line for the UI (not a step boundary)."""
    human: str


@dataclass
class Result:
    """The outcome of a phase. ok=False carries a plain-language `detail`."""
    phase: str
    ok: bool
    detail: str = ""


@dataclass
class Prompt:
    """A human decision the core needs. The UI's `ask` returns True/False.
    kind: "ack_risk" | "confirm_write" | "power_cycle_retry" | "choose".
    """
    kind: str
    human: str
