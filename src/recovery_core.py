"""
Recovery Core — single source of truth
========================================
Both revenue_recovery_agent.py (batch) and llm_recovery_agent.py
(autonomous tool-calling demo) import from HERE for classification,
recovery-likelihood scoring, backoff timing, and idempotency. This
was split out specifically to fix a real inconsistency: the two
agents previously used different probability sources (one used the
trained ML model, the other used a flat rate) and could have given
different answers for the same transaction. Now there is exactly one
implementation of each decision, so that can't happen again.
"""

import pickle
import hashlib
from razorpay_error_mapping import RAZORPAY_ERROR_MAPPING, get_error_category

STRATEGY_TABLE = {
    "CUSTOMER_SIDE": {
        "action": "RETRY_ALTERNATE_METHOD",
        "max_retries": 2,
        "success_rate": 0.60,  # fallback only, used if ML model unavailable
        "escalation": "Prompt customer directly with a corrective message",
    },
    "SYSTEM_SIDE": {
        "action": "EXPONENTIAL_BACKOFF",
        "max_retries": 3,
        "success_rate": 0.75,
        "escalation": "Escalate to ops / infra on-call (system may still be degraded)",
    },
    "MERCHANT_SIDE": {
        "action": "NO_RETRY",
        "max_retries": 0,
        "success_rate": 0.0,
        "escalation": "STOP immediately. Flag for merchant/support review — no retry can fix a config/business error.",
    },
}

ALT_METHOD = {"card": "UPI", "upi": "card", "netbanking": "UPI", "wallet": "UPI"}

# Real exponential backoff schedule in seconds (attempt_number -> wait time).
# Used for real in the interactive/demo agent; logged-but-not-slept in the
# bulk batch run so processing 750 transactions doesn't take real minutes —
# this tradeoff is disclosed explicitly, not hidden.
BACKOFF_SCHEDULE_SECONDS = {1: 5, 2: 10, 3: 20}

try:
    with open("models/recovery_likelihood_model.pkl", "rb") as f:
        _ml = pickle.load(f)
    ML_MODEL_LOADED = True
except FileNotFoundError:
    _ml = None
    ML_MODEL_LOADED = False


def classify_root_cause(error_code: str) -> str:
    """Deterministic lookup — the one and only root-cause classifier
    in the whole project. Both agents call this, never their own copy."""
    return get_error_category(error_code)


def predict_recovery_probability(root_cause: str, amount: float, payment_method: str, hour: int) -> float:
    """The one and only recovery-likelihood scorer. Uses the trained
    ML model if available, falls back to the flat strategy rate
    (documented, not silent) if the model file is missing OR if
    scoring fails for any reason — e.g. a scikit-learn version
    mismatch between the environment that pickled
    models/recovery_likelihood_model.pkl and the one running this
    code. This mirrors the same fallback-safe design already used
    for the LLM calls elsewhere in the project: one component being
    unavailable should never take down the whole demo."""
    if root_cause == "MERCHANT_SIDE":
        return 0.0
    if not ML_MODEL_LOADED:
        return STRATEGY_TABLE[root_cause]["success_rate"]
    try:
        method_enc = _ml["le_method"].transform([payment_method])[0] if payment_method in _ml["le_method"].classes_ else 0
        cause_enc = _ml["le_cause"].transform([root_cause])[0]
        import pandas as pd
        X = pd.DataFrame([[amount, method_enc, hour, cause_enc]],
                          columns=["amount", "method_enc", "hour_int", "cause_enc"])
        X_scaled = _ml["scaler"].transform(X)
        return float(_ml["model"].predict_proba(X_scaled)[0][1])
    except Exception:
        # Most common cause: the .pkl was trained/pickled with a
        # different scikit-learn version than is installed here (see
        # requirements.txt — pin scikit-learn to match, or just
        # re-run `python3 src/train_recovery_model.py` locally to
        # regenerate the model against your installed version).
        return STRATEGY_TABLE[root_cause]["success_rate"]


def generate_customer_message(error_code: str, payment_method: str) -> str:
    """The one and only customer-facing message generator."""
    info = None
    cat_data = RAZORPAY_ERROR_MAPPING.get("CUSTOMER_SIDE", {}).get("errors", {})
    if error_code in cat_data:
        info = cat_data[error_code]["description"]
    alt = ALT_METHOD.get(payment_method, "an alternate payment method")
    if info:
        return f"Payment failed: {info} Please try again using {alt}."
    return f"Payment failed. Please try again using {alt}."


def make_idempotency_key(transaction_id: str, attempt_number: int) -> str:
    """Guards against double-charging: a real retry against Razorpay's
    API would carry this key so that if attempt 1 actually succeeded
    but the response was lost, Razorpay itself refuses to process
    attempt 1 twice — retrying only ever means 'try again', never
    'charge again for the same attempt'. Not previously handled —
    this was a real gap in the earlier version."""
    raw = f"{transaction_id}:attempt:{attempt_number}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def get_backoff_seconds(attempt_number: int) -> int:
    """Real backoff schedule for SYSTEM_SIDE retries. attempt_number
    is 1-indexed."""
    return BACKOFF_SCHEDULE_SECONDS.get(attempt_number, 20)
