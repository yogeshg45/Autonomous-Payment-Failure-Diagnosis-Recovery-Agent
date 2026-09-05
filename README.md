# AI Revenue Recovery — Razorpay Buildthon 2026 (Track 03)

An agent that streams payment transactions, detects revenue-degradation
events in real time, diagnoses the root cause of each failure, uses a
trained ML model to judge each transaction's real recovery odds,
executes a bounded (rate-limited, compliant) recovery workflow, and
proves exactly how much money it recovered — with a full audit trail.

## Result on the demo batch
- **750 transactions processed, 134 failures**
- **5 degradation events correctly detected**
- **₹321,718 recovered from 60 transactions (44.8% recovery rate)**
- **74 compliant escalations, zero retries beyond enforced caps**

## Architecture

```
Data ─▶ Degradation Detector ─▶ Root Cause Classifier ─▶ Strategy Mapper
                                                              │
                                                              ▼
                                          Recovery-Likelihood Model (ML)
                                                              │
                                                              ▼
                                          Recovery Agent (bounded, simulated)
                                                              │
                                                              ▼
                                    Money Calculator + Audit Trail
                                          │                       │
                                          ▼                       ▼
                    Degradation Alert Explainer    Transaction Q&A Chatbot
                         (Groq/GPT-OSS, rule-based      (Groq/GPT-OSS, rule-based
                          fallback available)             fallback available)
                                          │                       │
                                          ▼                       ▼
                                  Panel "Transaction Entry" Catalog
                              (one plain-English card per unique error
                               code, cached — Error Guide dashboard tab)
```

## What's rule-based, and why

Root-cause classification (`error_code -> CUSTOMER/SYSTEM/MERCHANT_SIDE`)
and the retry/escalation policy are **deterministic lookups, not ML** —
on purpose. We tested training a classifier on this (see
`proof/` and the writeup below) and found it circular: the target
is already a 1:1 function of a documented mapping, so a trained model
just re-derives — worse — what the lookup already does perfectly.
Root-cause diagnosis and compliance rules need to be deterministic and
auditable anyway, so this is the correct engineering choice, not a
shortcut.

## What's genuinely ML

`src/train_recovery_model.py` trains a Logistic Regression model to
predict **per-transaction recovery likelihood** from `amount`,
`payment_method`, `hour`, and `root_cause` — a target that is NOT a
lookup of any single feature. Trained on a simulated historical
corpus (3,000 records; today's ~130 live failures alone aren't enough
data for a reliable per-transaction model). Validated:

- Held-out AUC: **0.606**
- Theoretical Bayes-optimal ceiling for this feature set: **~0.615-0.623**
  (computed directly — see script output) — the model is within ~0.01-0.02
  of the ceiling, meaning the residual gap is irreducible transaction-level
  randomness, not underfitting.

This model's output replaces a flat 60%/75% per-bucket guess with a real
per-transaction probability that drives the recovery simulation.

`src/recovery_core.py` is the single source of truth for classification,
ML scoring, idempotency keys, and backoff timing — both the batch agent
(`revenue_recovery_agent.py`) and the autonomous LLM agent
(`llm_recovery_agent.py`) import from it, so they can never give
different answers for the same transaction.

## Safety and realism details

- **Idempotency keys**: every retry attempt gets a unique, stable key
  (`make_idempotency_key`) — in a real integration this guards against
  double-charging if a retry's response is lost mid-flight.
- **Real exponential backoff**: SYSTEM_SIDE retries use an actual 5s/10s/20s
  schedule. The interactive agent (`llm_recovery_agent.py`) sleeps for real;
  the 750-row batch script logs the schedule but doesn't sleep for real
  (disclosed tradeoff — sleeping across 71 SYSTEM_SIDE failures would take
  real minutes for no demo value).
- **Stopping-rule proof**: `llm_recovery_agent.py`'s `__main__` block
  deliberately calls `attempt_retry` 5 times against a cap of 2, and shows
  only 2 ever execute — proving the cap is enforced in code, not trusted
  to the LLM's compliance with instructions.

## What's LLM, and why it's scoped the way it is

**LLM_PROVIDER is `groq`** (OpenAI's GPT-OSS-120B via Groq's
OpenAI-compatible API) — generous free-tier rate limit, and fast
enough that live tool-calling doesn't feel sluggish during a demo.

`src/llm_provider.py` is the single place that talks to Groq. It does
not duplicate any safety logic — the tool-calling agent imports the
exact same `attempt_retry`, `escalate`, etc. functions from
`llm_recovery_agent.py`, so the retry-cap guarantee is proven once in
one place, not re-implemented alongside the LLM call.

Four LLM-powered components, all routed through `llm_provider.py`:

1. **Degradation alert explainer** — explains *why* a degradation alert
   fired, in plain English, from the real error distribution in that window.
   Narrative only, no decision authority.
2. **Transaction Q&A chatbot** (`src/transaction_qa_chatbot.py`) — lets a
   customer or support agent ask about a specific failed transaction.
   Grounded only on that transaction's already-decided audit trail record.
   Explicitly declines authority it doesn't have (e.g. asked to "just
   retry it again") instead of pretending to comply.
3. **Panel "Transaction Entry" catalog** (`src/panel_transaction_entries.py`)
   — **new**: one plain-English card per *unique error code* in the batch
   (typically 15-25 codes, not per transaction), each with the technical
   description, why it's grouped CUSTOMER/SYSTEM/MERCHANT-side, what the
   agent did, and the money involved. Built once, cached to
   `outputs/transaction_entries.json`, served from that file — so the
   Error Guide dashboard tab never depends on a live LLM call working
   at demo time. This is the fix for "the panel doesn't want to read 750
   rows" without spending 750 API calls to summarize them.
4. **Autonomous tool-calling agent** (tool functions defined in
   `src/llm_recovery_agent.py`, driven live by `run_groq_tool_agent`
   in `src/llm_provider.py`) — the LLM decides which tool to call and
   reasons about why, but every safety-critical limit (retry caps,
   no-retry for MERCHANT_SIDE) is enforced inside the tools
   themselves, not by LLM judgment. Best run live on a handful of
   transactions for a demo, not the full batch.

All four fall back to a deterministic rule-based response if no key is
configured or a call fails, so the pipeline never depends on the LLM
being available.

`server.py` keeps outbound call volume down: it caches every Q&A
answer in memory keyed by (transaction, question), and spaces
consecutive LLM calls at least 1.5 seconds apart so a burst of clicks
can't trip whichever provider's own rate limiting.

## Demoing the LLM parts to an audience without it being a liability

The system is designed so the LLM is optional narration, never a
dependency — lean into that instead of hiding it:

- **Run the deterministic parts first and lead with them.** Batch
  Results, Audit Trail, and the stopping-rule proof (Autonomous Agent
  tab) need no network call, no API key, and cannot fail live — that's
  where the actual "749 recoveries decided correctly" claim lives.
- **Build the Error Guide catalog (`python3 src/panel_transaction_entries.py`)
  before the demo, not during it.** It's a one-time offline step; the
  dashboard tab just reads the resulting file, so it can't fail live
  regardless of API status.
- **Test your exact GROQ_MODEL string once, right before presenting**,
  ideally on the same network you'll demo on. Model retirements happen
  with little notice, and venue wifi/firewalls can block outbound API
  calls even when the key is fine.
- **If a live call fails during the demo, say so and show the fallback
  — don't panic.** The rule-based fallback answering instantly instead
  of erroring out is a feature you built on purpose; call it out as
  "this is what happens if the LLM provider is unavailable" rather than
  treating it as something going wrong.
- The Transaction Q&A tab's `provider` field and the QA log's per-answer
  caption (groq / rule-based, and whether it was served from cache)
  show you exactly what happened on each call, so you can diagnose or
  explain a live failure in front of judges instead of guessing.

## Data honesty note

- Error taxonomy (`src/razorpay_error_mapping.py`, 59 codes / 3 buckets)
  is sourced directly from Razorpay's published documentation.
- The 3-bucket model was confirmed against Razorpay's own `error_source`
  field in **real test-mode API responses** — see `proof/` for the actual
  Order/Payment JSON pulled from a live Razorpay test account.
- Batch-scale transaction volume (750 rows) and the degradation timeline
  are simulated, since no live merchant traffic was available — sampled
  from the 24 error codes Razorpay's own docs flag as most common.
- Recovery outcomes are simulated with a disclosed, feature-dependent
  probability function (see `train_recovery_model.py` docstring), not
  real re-charges.

## Repo layout

```
src/          All source code (data generator, error mapping, ML training,
              the agent, both LLM components)
models/       Trained recovery_likelihood_model.pkl
data/         The 750-transaction demo dataset
outputs/      audit_trail.csv/.json, final_report.json — results of a run
proof/        Real Razorpay test-mode API responses + the scripts used to
              pull them (schema validation evidence)
server.py     Flask backend for the web dashboard (/api/* endpoints)
frontend/     index.html, style.css, app.js — the dashboard UI
```

## Interactive Prototype (recommended for the demo)

`server.py` is a small Flask backend (`/api/*` endpoints, no business
logic of its own — it's a thin layer over `src/recovery_core.py`,
`src/transaction_qa_chatbot.py` and `src/llm_recovery_agent.py`) paired
with a hand-built frontend in `frontend/` (`index.html`, `style.css`,
`app.js` — no framework, no build step). Tested end to end: every
endpoint below returns real data from a live run.

```bash
pip install -r requirements.txt
# Run steps 1-3 above at least once first, so the dashboard has data to show
python3 server.py
# then open http://localhost:5000
```

`scikit-learn` is pinned in `requirements.txt` to match the version
`models/recovery_likelihood_model.pkl` was trained with. If you ever
see `'LogisticRegression' object has no attribute 'multi_class'` (or
similar), your installed scikit-learn drifted from that pin — either
`pip install -r requirements.txt` again in a clean venv, or just
regenerate the model against whatever version you have installed:
`python3 src/train_recovery_model.py`. Either way, `recovery_core.py`
now catches this and falls back to the flat per-bucket rate instead
of crashing the agent, so a version mismatch degrades gracefully
rather than erroring out live.

Six tabs, all served from a single Flask + vanilla JS web UI:
1. **Batch Results** — the headline numbers, degradation alerts, recovery-by-cause chart
2. **Error Guide** — one plain-English card per unique error code (not per transaction), built for a non-technical panel; reads from a precomputed file, so it never depends on a live LLM call
3. **Audit Trail** — filterable table of every failed transaction's full decision chain, each row expandable to its plain-English explanation
4. **Transaction Q&A** — ask about any specific transaction; try asking it to "just retry it again" and watch it decline correctly
5. **Autonomous Agent Demo** — a one-click proof that the retry cap holds even when deliberately pushed past its limit (works with no API key), plus a live Groq/GPT-OSS-powered run if you provide a key
6. **Real Razorpay API** — enter your own test-mode key to create a genuine Order via the live API, right from the UI (same call already validated in `proof/`)

There's no in-browser "Configuration" panel — copy `.env.example` to
`.env`, fill in `GROQ_API_KEY` plus `RAZORPAY_KEY_ID`/
`RAZORPAY_KEY_SECRET`, and restart `python3 server.py`. `server.py`
loads `.env` automatically (via `python-dotenv`) and every endpoint
reads its key straight from the process environment — nothing is
typed into or sent from the page. `.env` itself stays out of git via
`.gitignore`.

## Running it

**Run every command from the repo root** — the scripts write into
`data/`, `models/`, and `outputs/` automatically (creating those
folders if needed), and read from them the same way. This has been
tested end to end from a clean clone.

```bash
pip install -r requirements.txt

# 1. Generate the demo dataset -> writes to data/, outputs/
python3 src/payment_degradation_data_generator_v2.py

# 2. Train the recovery-likelihood model -> writes to models/, outputs/
python3 src/train_recovery_model.py

# 3. Run the full agent -> reads data/ + models/, writes outputs/
python3 src/revenue_recovery_agent.py

# 4. (Optional — works with either provider) Prove the stopping rule + ML consistency
python3 src/llm_recovery_agent.py

# 5. (Optional) Try the Q&A chatbot against the audit trail just generated
python3 src/transaction_qa_chatbot.py

# 6. Build the panel-friendly "Transaction Entry" catalog (one card per
#    unique error code — cheap even with a live key, ~21 calls not 750)
python3 src/panel_transaction_entries.py

# 7. (Optional — needs your own key) Live LLM calls instead of the fallback
cp .env.example .env   # then fill in GROQ_API_KEY
export GROQ_API_KEY="your-key-here"     # get one free at console.groq.com/keys

# 8. Launch the dashboard
python3 server.py
```

## What's simulated vs. real — summary table

| Component | Real | Simulated |
|---|---|---|
| Error taxonomy | ✅ Razorpay's own docs | |
| 3-bucket root-cause model | ✅ Confirmed via live API `error_source` | |
| Order/Payment schema | ✅ Pulled from live test-mode API | |
| Transaction volume / timing | | ✅ Generated for demo scale |
| Recovery outcomes | | ✅ Feature-dependent simulation, disclosed |
| Recovery-likelihood ML model | ✅ Really trained, really validated | |
| LLM explanations (Groq/GPT-OSS) | ✅ Really generated (with API key) | |
| Retry-cap / stopping-rule guarantee | ✅ Enforced in code, provider-independent, tested | |

Built for Razorpay Buildthon 2026, Track 03: AI Revenue Recovery.
