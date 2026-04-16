from enum import Enum


class State(str, Enum):
    GREETING = "GREETING"
    ASK_AGE = "ASK_AGE"
    ASK_DURATION = "ASK_DURATION"
    ASK_TREATMENT = "ASK_TREATMENT"
    QUALIFY = "QUALIFY"
    CLOSE = "CLOSE"
    END = "END"


# Fixed forward order — used for "give up retrying, move on" behavior
FORWARD_ORDER = [
    State.GREETING,
    State.ASK_AGE,
    State.ASK_DURATION,
    State.ASK_TREATMENT,
    State.QUALIFY,
    State.CLOSE,
    State.END,
]


def next_state_of(current: State) -> State:
    idx = FORWARD_ORDER.index(current)
    return FORWARD_ORDER[min(idx + 1, len(FORWARD_ORDER) - 1)]
