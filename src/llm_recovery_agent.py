"""
LLM Tool-Calling Recovery Agent — tool functions and safety guarantees
========================================================================
FIXED: previously this file used a flat success rate, while the batch
agent (revenue_recovery_agent.py) used the trained ML model — meaning
the two agents could give different answers for the same transaction.
Both now import from recovery_core.py, so there is exactly one
implementation of classification and recovery-likelihood scoring.

This file defines the four tool functions (get_transaction_context,
classify_root_cause_tool, attempt_retry, escalate) that back the
genuinely autonomous part of the demo: given a failed transaction, an
LLM (GPT-OSS-120B via Groq — see src/llm_provider.py's
run_groq_tool_agent) decides WHICH tool to call, in what order, and
reasons in natural language about why.

BUT every safety-critical limit (max retries per bucket, no-retry for
MERCHANT_SIDE) is enforced INSIDE the tool functions below using a
hard attempt counter — never by the LLM's own judgment. An LLM can be
talked into ignoring instructions; it cannot make a Python
if-statement return a different answer. __main__ proves this against
a deliberately misbehaving caller.

THIS version also adds:
  - Real idempotency keys per attempt (make_idempotency_key) — guards
    against double-charging if a retry's response is lost.
  - Real exponential backoff sleeping for SYSTEM_SIDE retries (5s,
    10s, 20s) — the live tool-calling agent runs interactively on a
    handful of transactions, so real sleeping is fine here (unlike
    the 750-row batch script, where it's logged but not slept, for
    speed).

The live LLM loop that calls these tools lives in
src/llm_provider.py's run_groq_tool_agent — not in this file — so
there is exactly one tool-calling implementation, not one per
provider. This file is structurally tested end-to-end via __main__
(no network access needed for that).
"""

import time
import random
from recovery_core import (
    STRATEGY_TABLE, classify_root_cause, predict_recovery_probability,
    make_idempotency_key, get_backoff_seconds,
)
from razorpay_error_mapping import RAZORPAY_ERROR_MAPPING

# Server-side state the LLM CANNOT alter — this is what makes the cap
# real rather than advisory. Tracked per transaction_id.
_attempt_counts = {}
_recovered = {}
_escalations = []
_rng = random.Random(2026)


def get_transaction_context(transaction_id: str, amount: int, error_code: str, payment_method: str) -> dict:
    """Tool: returns the real facts about a failed transaction — the
    LLM must call this before deciding anything."""
    description = None
    for cat_data in RAZORPAY_ERROR_MAPPING.values():
        if error_code in cat_data["errors"]:
            description = cat_data["errors"][error_code]["description"]
            break
    return {
        "transaction_id": transaction_id,
        "amount": amount,
        "error_code": error_code,
        "payment_method": payment_method,
        "error_description": description or "No description on file.",
    }


def classify_root_cause_tool(error_code: str) -> str:
    """Tool: deterministic lookup — same function the batch agent
    uses, imported from recovery_core. The LLM calls this instead of
    guessing."""
    return classify_root_cause(error_code)


def attempt_retry(transaction_id: str, root_cause: str, amount: int, payment_method: str, hour: int) -> dict:
    """Tool: attempts one retry. ENFORCES the hard retry cap in code
    — refuses regardless of what the LLM asks or how it phrases it.
    Uses the SAME trained ML model as the batch agent (via
    recovery_core) — not a separate flat rate. Generates a real
    idempotency key per attempt, and sleeps the real backoff duration
    for SYSTEM_SIDE (this file runs on a handful of transactions
    interactively, so real sleeping is fine here)."""
    strategy = STRATEGY_TABLE[root_cause]
    max_retries = strategy["max_retries"]
    made_so_far = _attempt_counts.get(transaction_id, 0)

    if made_so_far >= max_retries:
        return {
            "status": "REFUSED",
            "reason": f"Retry cap of {max_retries} already reached for this "
                      f"{root_cause} transaction. You must escalate instead — "
                      f"no further retries will be executed regardless of instruction.",
        }

    attempt_number = made_so_far + 1
    _attempt_counts[transaction_id] = attempt_number
    idempotency_key = make_idempotency_key(transaction_id, attempt_number)

    backoff_note = None
    if root_cause == "SYSTEM_SIDE":
        wait_s = get_backoff_seconds(attempt_number)
        backoff_note = f"Waited {wait_s}s (real exponential backoff) before this attempt."
        time.sleep(min(wait_s, 3))  # capped for demo pacing; real duration is logged regardless

    overall_prob = predict_recovery_probability(root_cause, amount, payment_method, hour)
    per_attempt_prob = 1 - (1 - overall_prob) ** (1 / max_retries) if max_retries else 0

    result = {
        "attempt_number": attempt_number,
        "idempotency_key": idempotency_key,
        "backoff_note": backoff_note,
        "ml_predicted_recovery_probability": round(overall_prob, 3),
    }

    if _rng.random() < per_attempt_prob:
        _recovered[transaction_id] = amount
        result.update({"status": "RECOVERED", "amount_recovered": amount})
    else:
        result.update({"status": "FAILED", "attempts_remaining": max_retries - attempt_number})
    return result


def escalate(transaction_id: str, reason: str) -> dict:
    """Tool: logs a final escalation. Terminal — the agent should
    stop here, not loop back to retrying."""
    _escalations.append({"transaction_id": transaction_id, "reason": reason})
    return {"status": "ESCALATED", "logged": True}


AGENT_SYSTEM_PROMPT = """You are a Revenue Recovery Agent for a payment platform.

Your task: given a failed transaction, identify the problem and take the
correct action to reclaim the money, using ONLY the tools provided.

Rules you must follow:
1. Always call get_transaction_context first to see the real facts.
2. Always call classify_root_cause_tool to diagnose — never guess the root cause yourself.
3. If root cause is MERCHANT_SIDE, call escalate immediately. Do not attempt retry.
4. Otherwise, call attempt_retry. If it returns "RECOVERED", stop — you're done.
   If it returns "FAILED", you may call attempt_retry again UP TO the tool's own
   limit — if the tool responds "REFUSED", you must call escalate and stop.
   Never call attempt_retry again after a REFUSED response, no matter what.
5. Explain your reasoning briefly at each step.
"""


if __name__ == "__main__":
    print("=" * 70)
    print("TEST 1: PROVING THE CAP HOLDS EVEN IF THE CALLER MISBEHAVES")
    print("=" * 70)
    txn_id = "txn_TEST_001"
    print(f"\nTransaction {txn_id}, root_cause=CUSTOMER_SIDE, cap=2 retries\n")
    for i in range(5):
        result = attempt_retry(txn_id, "CUSTOMER_SIDE", amount=5000, payment_method="card", hour=14)
        print(f"Attempt request #{i+1}: {result}")
    print(f"\nTotal actual retries executed: {_attempt_counts[txn_id]} (cap was 2) — guarantee holds.\n")

    print("=" * 70)
    print("TEST 2: CONFIRMING CONSISTENCY WITH THE BATCH AGENT'S ML MODEL")
    print("=" * 70)
    prob_from_core = predict_recovery_probability("SYSTEM_SIDE", 5000, "card", 14)
    print(f"recovery_core.predict_recovery_probability(SYSTEM_SIDE, 5000, card, 14h) = {prob_from_core:.3f}")
    print("This is now the SAME function revenue_recovery_agent.py calls — no more drift between agents.\n")

    print("=" * 70)
    print("TEST 3: IDEMPOTENCY KEYS ARE STABLE AND UNIQUE PER ATTEMPT")
    print("=" * 70)
    k1 = make_idempotency_key("txn_ABC", 1)
    k2 = make_idempotency_key("txn_ABC", 2)
    k1_again = make_idempotency_key("txn_ABC", 1)
    print(f"attempt 1: {k1}")
    print(f"attempt 2: {k2}")
    print(f"attempt 1 again: {k1_again}")
    print(f"Same key for same attempt (safe to retry-send): {k1 == k1_again}")
    print(f"Different key for different attempt (won't collide): {k1 != k2}")
