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
from .resume import is_resume, join_wrapped, resume_fields
from .statement import is_bank_statement, statement_fields
from .receipt import is_receipt, receipt_fields
from .extract import candidate_spans, build_extract_questions, extract_by_verification, field_kind
from .form import is_form, form_fields
from .jev import CURRENCY_HINTS, JEV_PROVIDERS, JevError, answers_to_items, ask_jev, build_questions, check_fields, core_fields, discover_fields, option_key, vendor_candidates
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
    "is_bank_statement",
    "statement_fields",
    "is_receipt",
    "receipt_fields",
    "candidate_spans",
    "build_extract_questions",
    "extract_by_verification",
    "field_kind",
    "is_form",
    "form_fields",
    "is_resume",
    "resume_fields",
    "join_wrapped",
    "core_fields",
    "vendor_candidates",
    "option_key",
    "CURRENCY_HINTS",
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
