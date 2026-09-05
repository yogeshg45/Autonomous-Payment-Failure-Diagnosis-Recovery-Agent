"""
AI Revenue Recovery — Web Backend
==================================
Run with: python3 server.py   (from the repo root)

This is a real HTTP backend + a hand-built frontend (frontend/index.html,
style.css, app.js). This file is a thin API layer over
src/recovery_core.py, src/transaction_qa_chatbot.py and
src/llm_recovery_agent.py. No business logic lives here.

API keys (Groq, Razorpay test keys) live ONLY in your local .env
file and are loaded once into this process's environment at startup
(python-dotenv). The browser never collects, stores, or sends them —
there is no "Configuration" panel on the frontend. Copy .env.example
to .env, fill in your real keys, and restart the server.

REQUEST-VOLUME NOTE: LLM_PROVIDER defaults to "groq" (OpenAI's
GPT-OSS-120B via Groq's API — OpenAI-compatible, generous free-tier
rate limit). This file also (a) caches identical Q&A answers in memory so
re-asking the same question about the same transaction never re-calls
any API, and (b) enforces a minimum spacing between outbound LLM
calls (see _throttle_llm below) so a burst of clicks can't trip
Groq's own rate limiting.
"""

import os
import sys
import time
import json
import threading

from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()  # reads .env in the repo root into os.environ, if present

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

DATA_CSV = "data/payment_transactions_v2.csv"
AUDIT_JSON = "outputs/audit_trail.json"
FINAL_REPORT = "outputs/final_report.json"

# Minimum seconds between outbound LLM calls from this process,
# across every endpoint that uses one. Keeps a burst of QA questions
# or agent runs from tripping Groq's own rate limiting.
MIN_LLM_CALL_INTERVAL_S = 1.5

app = Flask(__name__, static_folder="frontend", static_url_path="")

_qa_cache = {}  # (transaction_id, question.lower().strip()) -> (answer, used_llm_provider)
_llm_lock = threading.Lock()
_last_llm_call_at = 0.0
_entries_cache = None  # in-memory cache of outputs/transaction_entries.json


def _throttle_llm():
    """Blocks just long enough to keep outbound LLM calls spaced out
    by MIN_LLM_CALL_INTERVAL_S. Cheap way to cut the number of
    requests that actually leave this process without touching the
    LLM-calling code itself."""
    global _last_llm_call_at
    with _llm_lock:
        wait = MIN_LLM_CALL_INTERVAL_S - (time.time() - _last_llm_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_llm_call_at = time.time()


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _entries_by_error_code():
    """Loads outputs/transaction_entries.json (built once, offline, by
    src/panel_transaction_entries.py) and indexes it by error_code so
    each audit row can be annotated with a panel-friendly explanation
    with zero extra LLM calls at request time. Returns {} if the
    catalog hasn't been built yet — callers must handle that gracefully."""
    global _entries_cache
    if _entries_cache is not None:
        return _entries_cache
    data = _read_json("outputs/transaction_entries.json")
    if data is None:
        _entries_cache = {}
    else:
        _entries_cache = {e["error_code"]: e for e in data.get("entries", [])}
    return _entries_cache


# ----------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------
@app.route("/")
def index():
    return app.send_static_file("index.html")


# ----------------------------------------------------------------
# Status — which pipeline steps have been run
# ----------------------------------------------------------------
@app.route("/api/status")
def status():
    from recovery_core import ML_MODEL_LOADED
    from llm_provider import active_provider, GROQ_MODEL
    return jsonify({
        "ml_model_loaded": ML_MODEL_LOADED,
        "data_present": os.path.exists(DATA_CSV),
        "audit_present": os.path.exists(AUDIT_JSON),
        "report_present": os.path.exists(FINAL_REPORT),
        "entries_present": os.path.exists("outputs/transaction_entries.json"),
        "llm_provider_active": active_provider(),
        "groq_key_in_env": bool(os.environ.get("GROQ_API_KEY")),
        "groq_model": GROQ_MODEL,
        "razorpay_keys_in_env": bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET")),
    })


# ----------------------------------------------------------------
# Tab 1 — Batch results
# ----------------------------------------------------------------
@app.route("/api/report")
def report():
    data = _read_json(FINAL_REPORT)
    if data is None:
        return jsonify({"error": "not_found",
                         "message": "Run `python3 src/revenue_recovery_agent.py` first."}), 404
    return jsonify(data)


# ----------------------------------------------------------------
# Tab 2 — Audit trail (filterable)
# ----------------------------------------------------------------
@app.route("/api/audit")
def audit():
    data = _read_json(AUDIT_JSON)
    if data is None:
        return jsonify({"error": "not_found",
                         "message": "Run `python3 src/revenue_recovery_agent.py` first."}), 404

    root_causes = request.args.getlist("root_cause")
    outcome = request.args.get("outcome", "all")

    filtered = data
    if root_causes:
        filtered = [r for r in filtered if r["root_cause"] in root_causes]
    if outcome == "recovered":
        filtered = [r for r in filtered if r["recovered"]]
    elif outcome == "escalated":
        filtered = [r for r in filtered if r["escalated"]]

    entries = _entries_by_error_code()
    for r in filtered:
        entry = entries.get(r["error_code"])
        r["panel_explanation"] = entry["plain_english"] if entry else None

    return jsonify({
        "total": len(data),
        "count": len(filtered),
        "root_causes_available": sorted({r["root_cause"] for r in data}),
        "entries_available": bool(entries),
        "records": filtered,
    })


@app.route("/api/audit/<txn_id>")
def audit_one(txn_id):
    data = _read_json(AUDIT_JSON) or []
    for r in data:
        if r["transaction_id"] == txn_id:
            entry = _entries_by_error_code().get(r["error_code"])
            r["panel_explanation"] = entry["plain_english"] if entry else None
            return jsonify(r)
    return jsonify({"error": "not_found"}), 404


# ----------------------------------------------------------------
# Tab: panel-friendly "Transaction Entry" catalog — one card per
# unique error code, precomputed offline by
# src/panel_transaction_entries.py. Serving this is just a file read,
# so it never depends on a live LLM call working during the demo.
# ----------------------------------------------------------------
@app.route("/api/transaction-entries")
def transaction_entries():
    data = _read_json("outputs/transaction_entries.json")
    if data is None:
        return jsonify({"error": "not_found",
                         "message": "Run `python3 src/panel_transaction_entries.py` first "
                                    "(after the batch agent has produced an audit trail)."}), 404
    return jsonify(data)


# ----------------------------------------------------------------
# Tab 3 — Transaction Q&A chatbot
# ----------------------------------------------------------------
@app.route("/api/qa", methods=["POST"])
def qa():
    if not os.path.exists(AUDIT_JSON):
        return jsonify({"error": "not_found",
                         "message": "Run the agent first."}), 404
    body = request.get_json(force=True) or {}
    txn_id = body.get("transaction_id")
    question = (body.get("question") or "Why did my payment fail?").strip()

    cache_key = (txn_id, question.lower())
    if cache_key in _qa_cache:
        answer, provider_used = _qa_cache[cache_key]
        return jsonify({"answer": answer, "used_llm": provider_used != "rule_based",
                         "provider": provider_used, "cached": True})

    from llm_provider import answer_question, active_provider
    from transaction_qa_chatbot import load_transaction_record
    record = load_transaction_record(txn_id, audit_trail_path=AUDIT_JSON)
    if record is None:
        return jsonify({"answer": f"I don't have a record for transaction {txn_id}.",
                         "used_llm": False, "provider": "rule_based", "cached": False})

    if active_provider() != "rule_based":
        _throttle_llm()
    answer, provider_used = answer_question(record, question)
    _qa_cache[cache_key] = (answer, provider_used)
    return jsonify({"answer": answer, "used_llm": provider_used != "rule_based",
                     "provider": provider_used, "cached": False})


# ----------------------------------------------------------------
# Tab 4 — Autonomous agent
# ----------------------------------------------------------------
@app.route("/api/agent/stopping-rule-proof", methods=["POST"])
def stopping_rule_proof():
    from llm_recovery_agent import attempt_retry, _attempt_counts
    txn_id = f"demo_txn_{int(time.time())}"
    results = []
    for i in range(5):
        r = attempt_retry(txn_id, "CUSTOMER_SIDE", amount=5000, payment_method="card", hour=14)
        results.append(r)
    return jsonify({
        "transaction_id": txn_id,
        "requests_made": 5,
        "attempts_executed": _attempt_counts.get(txn_id, 0),
        "cap": 2,
        "results": results,
    })


@app.route("/api/failed-transactions")
def failed_transactions():
    if not os.path.exists(DATA_CSV):
        return jsonify({"error": "not_found",
                         "message": "Run `python3 src/payment_degradation_data_generator_v2.py` first."}), 404
    import pandas as pd
    df = pd.read_csv(DATA_CSV)
    failed = df[df["status"] == "failed"]
    cols = ["transaction_id", "amount", "error_code", "payment_method", "hour"]
    return jsonify(failed[cols].to_dict(orient="records"))


@app.route("/api/agent/run", methods=["POST"])
def agent_run():
    body = request.get_json(force=True) or {}
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return jsonify({"error": "missing_api_key",
                         "message": "Add GROQ_API_KEY to your .env file (see .env.example) "
                                    "and restart the server to run the live agent."}), 400
    try:
        _throttle_llm()
        from llm_provider import run_groq_tool_agent
        text = run_groq_tool_agent(
            body["transaction_id"], int(body["amount"]), body["error_code"],
            body["payment_method"], hour=int(body.get("hour", 12)), api_key=api_key,
        )
        return jsonify({"response": text, "provider": "groq"})
    except Exception as e:
        return jsonify({"error": "agent_failed", "message": str(e), "provider": "groq"}), 500


# ----------------------------------------------------------------
# Tab 5 — Real Razorpay test-mode order
# ----------------------------------------------------------------
@app.route("/api/razorpay/create-order", methods=["POST"])
def razorpay_create_order():
    body = request.get_json(force=True) or {}
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    amount_rupees = body.get("amount", 100)
    if not key_id or not key_secret:
        return jsonify({"error": "missing_credentials",
                         "message": "Add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET to your "
                                    ".env file (see .env.example) and restart the server."}), 400
    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.create({
            "amount": int(float(amount_rupees) * 100),
            "currency": "INR",
            "receipt": f"prototype_demo_{int(time.time())}",
        })
        return jsonify({"order": order})
    except Exception as e:
        return jsonify({"error": "razorpay_failed", "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"AI Revenue Recovery dashboard: http://localhost:{port}")
    app.run(debug=True, port=port)
