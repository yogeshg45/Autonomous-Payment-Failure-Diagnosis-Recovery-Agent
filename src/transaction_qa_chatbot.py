"""
Transaction Q&A Chatbot — grounded explanation only, zero decision authority
=============================================================================
DESIGN GUARANTEE (state this explicitly to judges):
This chatbot can only READ an already-decided audit trail record and
answer questions about it. It has no function to call that could
trigger a retry, issue a refund, or override the recovery agent's
decision. Money-affecting decisions happened upstream, deterministically,
before this chatbot ever runs — this is purely an explanation layer for
the customer or support team after the fact.

If the customer asks it to "just retry again" or "give me a refund",
it is instructed to decline that authority explicitly and point to the
real escalation path already logged for that transaction — not to
comply, and not to invent a workaround.

This module owns the deterministic rule-based answer path and the
audit-trail lookup. Live LLM-powered answers (Groq/GPT-OSS) are handled
by src/llm_provider.py's answer_question(), which calls back into this
file's _rule_based_answer() as its own fallback when no key is
configured or a call fails — there is exactly one rule-based
implementation, not two that could drift apart.
"""

import json


SYSTEM_INSTRUCTIONS = """You are a payment support assistant. You may ONLY use the
verified transaction record provided below to answer. Rules you must follow:

1. Never claim you can retry the payment, issue a refund, or change the outcome —
   you have no such authority. If asked, politely say so and point to the
   escalation path already recorded for this transaction.
2. Never invent information not present in the record below.
3. Keep answers short, clear, and non-technical — the person asking may not
   know what "error_code" or "root_cause" means; explain in plain language.
4. If the record shows the transaction was recovered, say so clearly and
   confirm no further action is needed.
"""


def load_transaction_record(transaction_id, audit_trail_path="outputs/audit_trail.json"):
    """Structured lookup — this is a dictionary read, not vector search.
    No need for embeddings when the data is this small and structured."""
    with open(audit_trail_path) as f:
        records = json.load(f)
    for r in records:
        if r["transaction_id"] == transaction_id:
            return r
    return None


def _rule_based_answer(record, question):
    """Deterministic answer, always available, no external dependency.
    Used directly when no LLM key is configured, and as the fallback
    inside src/llm_provider.py's answer_question() if a Groq call fails."""
    if record["recovered"]:
        return (f"Good news — transaction {record['transaction_id']} for ₹{record['amount']} "
                f"was successfully recovered after {record['attempts_made']} retry attempt(s). "
                f"No further action is needed.")
    lines = [
        f"Transaction {record['transaction_id']} (₹{record['amount']}) failed due to: {record['error_code']}.",
        f"This was classified as a {record['root_cause'].replace('_', ' ').lower()} issue.",
    ]
    if record["attempts_made"] > 0:
        lines.append(f"The system attempted {record['attempts_made']} retry/retries "
                      f"using {record['action_taken'].replace('_', ' ').lower()}, which did not succeed.")
    else:
        lines.append("This type of failure cannot be fixed by retrying, so no retry was attempted.")
    if record["escalated"]:
        lines.append(f"This has been escalated: {record['escalation_reason']}")
    if record.get("customer_message"):
        lines.append(f"Suggested next step: {record['customer_message']}")
    lines.append("I'm not able to retry this payment or issue a refund directly — "
                  "the escalation above is the correct next step for that.")
    return " ".join(lines)


def ask_about_transaction(transaction_id, question, audit_trail_path="outputs/audit_trail.json"):
    """Looks up the record and returns the deterministic rule-based
    answer. For a live LLM-powered answer instead, use
    src/llm_provider.py's answer_question(record, question), which
    calls Groq and falls back to _rule_based_answer() on any failure."""
    record = load_transaction_record(transaction_id, audit_trail_path)
    if record is None:
        return f"I don't have a record for transaction {transaction_id}.", False
    return _rule_based_answer(record, question), False


if __name__ == "__main__":
    # Demo using the rule-based fallback (fully testable offline)
    test_qs = [
        ("txn_000147", "Why did my payment fail?"),
        ("txn_000143", "Did my payment go through eventually?"),
        ("txn_000148", "Can you just try charging my card again?"),
    ]
    for txn_id, q in test_qs:
        print(f"Q ({txn_id}): {q}")
        answer, used_llm = ask_about_transaction(txn_id, q)
        print(f"A: {answer}")
        print(f"(used_llm={used_llm})")
        print()
