"""JevAPI: decide, field by field, whether an extracted value is safe to auto-fill
or should go to a human. Zero dependencies.

A model's stated confidence is a claim. JevAPI turns it into a measured
probability using your own labelled examples, then applies a cost rule: what a
wrong fill costs versus what a human check costs.

Profiles are plain JSON and identical to the npm package's, so you can calibrate
in Python and decide in the browser (or the other way round). Option keys use the
same camelCase names in both languages for that reason.
"""

from .certainty import correctness_probability, normalize
from .jev import JEV_PROVIDERS, JevError, answers_to_items, ask_jev, build_questions, check_fields, discover_fields
from .core import (
    PROFILE_VERSION,
    apply_isotonic,
    calibrate,
    cost_threshold,
    decide,
    decide_all,
    ece,
    evaluate,
    fit_isotonic,
    validate_profile,
    wilson_lower,
)

__all__ = [
    "JEV_PROVIDERS",
    "JevError",
    "answers_to_items",
    "ask_jev",
    "build_questions",
    "check_fields",
    "correctness_probability",
    "discover_fields",
    "normalize",
    "PROFILE_VERSION",
    "apply_isotonic",
    "calibrate",
    "cost_threshold",
    "decide",
    "decide_all",
    "ece",
    "evaluate",
    "fit_isotonic",
    "validate_profile",
    "wilson_lower",
]
__version__ = "0.1.0"
