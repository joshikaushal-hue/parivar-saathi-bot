"""
Twilio ASR hint words — improve recognition accuracy per state.
Hints are free-form comma-separated tokens Twilio biases the ASR toward.
"""
from app.state_machine.states import State


_HINTS = {
    State.ASK_AGE: (
        "age, saal, years, twenty, thirty, forty, fifty, "
        "बीस, पच्चीस, तीस, पैंतीस, चालीस, पैंतालीस, पचास"
    ),
    State.ASK_DURATION: (
        "year, years, month, months, saal, mahina, mahine, trying, "
        "एक साल, दो साल, तीन साल, चार साल, पाँच साल, महीने"
    ),
    State.ASK_TREATMENT: (
        "IVF, IUI, yes, no, haan, nahi, haan ji, nahi ki, done, "
        "आईवीएफ, आईयूआई, किया है, नहीं किया, हाँ, नहीं"
    ),
}


def hints_for(state: State) -> str:
    return _HINTS.get(state, "")
