// AI Revenue Recovery — frontend logic
// Talks only to the Flask backend (server.py) on the same origin.
// No API keys ever live in the browser: GROQ_API_KEY, RAZORPAY_KEY_ID
// and RAZORPAY_KEY_SECRET are read by server.py from your local .env
// file (see .env.example) and never sent to or requested from this page.

const money = (n) => "\u20B9" + Number(n || 0).toLocaleString("en-IN");

const TAB_META = {
  batch: { title: "Overview", subtitle: "Live snapshot of the recovery pipeline's last batch run." },
  audit: { title: "Transactions", subtitle: "Every failed transaction, its diagnosis, and what the agent did about it." },
  entries: { title: "Error Guide", subtitle: "One plain-English card per distinct error code — built for a non-technical panel." },
  qa: { title: "Support Chat", subtitle: "Ask a grounded question about any single transaction's outcome." },
  agent: { title: "Recovery Agent", subtitle: "Watch the bounded, tool-calling agent decide and act in real time." },
  razorpay: { title: "Live API", subtitle: "Fire a real Razorpay test-mode order using your own .env credentials." },
};

// ---------------- Tabs (sidebar nav) ----------------
document.querySelectorAll(".navlink").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".navlink").forEach((t) => { t.classList.remove("is-active"); t.setAttribute("aria-selected", "false"); });
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("is-active"));
    tab.classList.add("is-active");
    tab.setAttribute("aria-selected", "true");
    document.getElementById("panel-" + tab.dataset.tab).classList.add("is-active");
    const meta = TAB_META[tab.dataset.tab];
    if (meta) {
      document.getElementById("pageTitle").textContent = meta.title;
      document.getElementById("pageSubtitle").textContent = meta.subtitle;
    }
  });
});

// ---------------- Status strip ----------------
async function loadStatus() {
  const res = await fetch("/api/status");
  const s = await res.json();
  const dot = (on) => `<span class="dot ${on ? "dot--on" : "dot--off"}"></span>`;
  const providerLabel = s.llm_provider_active === "groq"
    ? `GPT-OSS via Groq active (${s.groq_model})`
    : "No LLM key — rule-based fallback active";
  document.getElementById("statusStrip").innerHTML = `
    <span>${dot(s.data_present)}Dataset generated</span>
    <span>${dot(s.ml_model_loaded)}ML model trained</span>
    <span>${dot(s.report_present)}Agent run complete</span>
    <span>${dot(s.entries_present)}Error guide built</span>
    <span>${dot(s.llm_provider_active !== "rule_based")}${providerLabel}</span>
    <span>${dot(s.razorpay_keys_in_env)}Razorpay keys loaded from .env</span>
  `;
}

// ---------------- Tab 1: Batch results ----------------
let rootCauseChart = null;

async function loadReport() {
  const res = await fetch("/api/report");
  if (!res.ok) {
    document.getElementById("heroEmpty").hidden = false;
    document.getElementById("heroStats").hidden = true;
    return;
  }
  const r = await res.json();
  document.getElementById("heroEmpty").hidden = true;
  document.getElementById("heroStats").hidden = false;

  document.getElementById("statProcessed").textContent = r.total_transactions_processed.toLocaleString("en-IN");
  document.getElementById("statFailed").textContent = r.total_failed_transactions.toLocaleString("en-IN");
  document.getElementById("statRecovered").textContent = money(r.total_amount_recovered_inr);
  document.getElementById("statRate").textContent = r.recovery_rate_pct + "%";
  document.getElementById("statEscalations").textContent = r.total_escalations.toLocaleString("en-IN");

  const alertsBody = document.querySelector("#alertsTable tbody");
  alertsBody.innerHTML = "";
  if (r.degradation_alerts.length === 0) {
    document.getElementById("alertsEmpty").hidden = false;
  } else {
    document.getElementById("alertsEmpty").hidden = true;
    r.degradation_alerts.forEach((a, i) => {
      alertsBody.insertAdjacentHTML("beforeend", `
        <tr>
          <td class="num">${i + 1}</td>
          <td class="num">${a.at_transaction}</td>
          <td class="mono">${a.timestamp}</td>
          <td class="num">${a.baseline_success_rate}%</td>
          <td class="num">${a.current_success_rate}%</td>
          <td class="num">-${a.drop_points} pts</td>
        </tr>`);
    });
  }

  const rcBody = document.querySelector("#rootCauseTable tbody");
  rcBody.innerHTML = "";
  const causes = Object.keys(r.root_cause_breakdown);
  causes.forEach((cause) => {
    const d = r.root_cause_breakdown[cause];
    rcBody.insertAdjacentHTML("beforeend", `
      <tr>
        <td>${causeTag(cause)}</td>
        <td class="num">${d.failed}</td>
        <td class="num">${d.recovered}</td>
        <td class="num">${money(d.amount_recovered)}</td>
        <td class="num">${money(d.amount_at_risk)}</td>
      </tr>`);
  });

  const ctx = document.getElementById("rootCauseChart");
  const chartData = {
    labels: causes.map((c) => c.replace("_", " ")),
    datasets: [
      { label: "Recovered", data: causes.map((c) => r.root_cause_breakdown[c].amount_recovered), backgroundColor: "#3395ff" },
      { label: "At risk (unrecovered)", data: causes.map((c) => r.root_cause_breakdown[c].amount_at_risk - r.root_cause_breakdown[c].amount_recovered), backgroundColor: "#e4e8f0" },
    ],
  };
  if (rootCauseChart) rootCauseChart.destroy();
  if (window.Chart) {
    rootCauseChart = new Chart(ctx, {
      type: "bar",
      data: chartData,
      options: {
        responsive: true,
        plugins: { legend: { position: "bottom", labels: { font: { family: "Inter", size: 11 } } } },
        scales: { x: { stacked: true }, y: { stacked: true, ticks: { callback: (v) => "\u20B9" + v.toLocaleString("en-IN") } } },
      },
    });
  }

  const sr = r.stopping_rules_enforced;
  document.getElementById("stoppingRulesText").textContent =
    `${r.total_escalations} transactions escalated. Max retries enforced: ` +
    `${sr.CUSTOMER_SIDE_max_retries} customer-side, ${sr.SYSTEM_SIDE_max_retries} system-side, ` +
    `${sr.MERCHANT_SIDE_max_retries} merchant-side.`;
}

function causeTag(cause) {
  const cls = cause === "CUSTOMER_SIDE" ? "customer" : cause === "SYSTEM_SIDE" ? "system" : "merchant";
  return `<span class="tag tag--${cls}">${cause.replace("_", " ")}</span>`;
}

// ---------------- Tab 2: Audit trail ----------------
let auditRecordsCache = [];

async function loadAuditFilters() {
  const res = await fetch("/api/audit");
  if (!res.ok) return;
  const data = await res.json();
  const causesEl = document.getElementById("causeFilters");
  data.root_causes_available.forEach((cause) => {
    const id = "cause-" + cause;
    const label = document.createElement("label");
    label.innerHTML = `<input type="checkbox" id="${id}" value="${cause}" checked> ${cause.replace("_", " ")}`;
    causesEl.appendChild(label);
    label.querySelector("input").addEventListener("change", loadAuditTable);
  });
  document.getElementById("outcomeFilter").addEventListener("change", loadAuditTable);
  loadAuditTable();
  populateQaTxnSelect(data.records.map((r) => r.transaction_id));
}

async function loadAuditTable() {
  const checked = [...document.querySelectorAll("#causeFilters input:checked")].map((i) => i.value);
  const outcome = document.getElementById("outcomeFilter").value;
  const params = new URLSearchParams();
  checked.forEach((c) => params.append("root_cause", c));
  params.set("outcome", outcome);
  const res = await fetch("/api/audit?" + params.toString());
  if (!res.ok) return;
  const data = await res.json();
  auditRecordsCache = data.records;
  document.getElementById("auditCount").textContent = `Showing ${data.count} of ${data.total} failed transactions`;

  const body = document.querySelector("#auditTable tbody");
  body.innerHTML = "";
  data.records.forEach((r, i) => {
    const outcomeTag = r.recovered
      ? `<span class="tag tag--recovered">Recovered</span>`
      : r.escalated
      ? `<span class="tag tag--escalated">Escalated</span>`
      : `<span class="tag">Pending</span>`;
    body.insertAdjacentHTML("beforeend", `
      <tr>
        <td class="num">${i + 1}</td>
        <td class="mono">${r.transaction_id}</td>
        <td class="num">${money(r.amount)}</td>
        <td>${r.payment_method}</td>
        <td class="mono">${r.error_code}</td>
        <td>${causeTag(r.root_cause)}</td>
        <td>${r.action_taken.replace(/_/g, " ")}</td>
        <td class="num">${r.attempts_made} / ${r.max_retries_allowed}</td>
        <td>${outcomeTag}</td>
        <td>${r.escalation_reason || "—"}</td>
      </tr>
      ${r.panel_explanation ? `<tr class="row--explain"><td></td><td colspan="9" class="explain-cell">💬 ${r.panel_explanation}</td></tr>` : ""}`);
  });
}

// ---------------- Tab: Error Guide (panel-friendly entries) ----------------
async function loadEntries() {
  const res = await fetch("/api/transaction-entries");
  const grid = document.getElementById("entriesGrid");
  if (!res.ok) {
    document.getElementById("entriesEmpty").hidden = false;
    grid.innerHTML = "";
    return;
  }
  document.getElementById("entriesEmpty").hidden = true;
  const data = await res.json();
  grid.innerHTML = data.entries.map((e) => `
    <div class="entry-card">
      <div class="entry-card__top">
        ${causeTag(e.root_cause)}
        <span class="mono entry-card__code">${e.error_code}</span>
      </div>
      <p class="entry-card__plain">${e.plain_english}</p>
      <div class="entry-card__stats">
        <span>${e.occurrences} occurrence(s)</span>
        <span>${money(e.amount_at_risk_inr)} at risk</span>
        <span>${money(e.amount_recovered_inr)} recovered</span>
        <span>${e.recovery_rate_pct}% recovery rate</span>
      </div>
      <span class="entry-card__meta">explained by: ${e.explained_by.replace("_", " ")}</span>
    </div>`).join("");
}

// ---------------- Tab 3: Transaction Q&A ----------------
function populateQaTxnSelect(txnIds) {
  const select = document.getElementById("qaTxnSelect");
  select.innerHTML = txnIds.map((id) => `<option value="${id}">${id}</option>`).join("");
}

document.getElementById("qaForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const txnId = document.getElementById("qaTxnSelect").value;
  const question = document.getElementById("qaQuestion").value;
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  try {
    const res = await fetch("/api/qa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transaction_id: txnId, question }),
    });
    const data = await res.json();
    const log = document.getElementById("qaLog");
    if (!res.ok) {
      log.insertAdjacentHTML("afterbegin", `<div class="notice notice--error">${data.message || "Something went wrong."}</div>`);
      return;
    }
    const meta = data.used_llm
      ? "Answered by GPT-OSS-120B (Groq)" + (data.cached ? " (cached answer)" : "")
      : "Rule-based fallback" + (data.cached ? " (cached answer)" : "");
    log.insertAdjacentHTML("afterbegin", `
      <div class="qa-entry">
        <p class="qa-entry__q">${txnId} — "${question}"</p>
        <p class="qa-entry__a">${data.answer}</p>
        <span class="qa-entry__meta">${meta}</span>
      </div>`);
  } finally {
    btn.disabled = false;
  }
});

// ---------------- Tab 4: Autonomous agent ----------------
document.getElementById("proofBtn").addEventListener("click", async (e) => {
  const btn = e.target;
  btn.disabled = true;
  const list = document.getElementById("proofResults");
  const summary = document.getElementById("proofSummary");
  list.innerHTML = "";
  summary.hidden = true;
  try {
    const res = await fetch("/api/agent/stopping-rule-proof", { method: "POST" });
    const data = await res.json();
    data.results.forEach((r, i) => {
      const extra = r.status === "REFUSED" ? ` — ${r.reason}` : r.status === "RECOVERED" ? ` — ₹${r.amount_recovered} recovered` : "";
      list.insertAdjacentHTML("beforeend", `<li class="status-${r.status}">Request #${i + 1}: ${r.status}${extra}</li>`);
    });
    summary.hidden = false;
    summary.textContent = `${data.requests_made} requests made, only ${data.attempts_executed} actually executed (cap was ${data.cap}). Enforcement holds in code.`;
  } finally {
    btn.disabled = false;
  }
});

async function loadFailedTransactionsForAgent() {
  const res = await fetch("/api/failed-transactions");
  if (!res.ok) return;
  const rows = await res.json();
  const select = document.getElementById("agentTxnSelect");
  select.innerHTML = rows
    .map((r) => `<option value='${JSON.stringify(r).replace(/'/g, "&apos;")}'>${r.transaction_id} — ${r.error_code} — \u20B9${r.amount}</option>`)
    .join("");
}

document.getElementById("agentForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const resultEl = document.getElementById("agentResult");
  const raw = document.getElementById("agentTxnSelect").value;
  const txn = JSON.parse(raw.replace(/&apos;/g, "'"));
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  resultEl.textContent = "Agent reasoning...";
  try {
    const res = await fetch("/api/agent/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transaction_id: txn.transaction_id, amount: txn.amount, error_code: txn.error_code,
        payment_method: txn.payment_method, hour: txn.hour,
      }),
    });
    const data = await res.json();
    resultEl.textContent = res.ok ? data.response : "Agent call failed: " + (data.message || "unknown error");
  } finally {
    btn.disabled = false;
  }
});

// ---------------- Tab 5: Real Razorpay order ----------------
document.getElementById("razorpayForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pre = document.getElementById("razorpayResult");
  pre.hidden = false;
  const amount = document.getElementById("rpAmount").value;
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  pre.textContent = "Calling Razorpay...";
  try {
    const res = await fetch("/api/razorpay/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount }),
    });
    const data = await res.json();
    pre.textContent = res.ok ? JSON.stringify(data.order, null, 2) : "Error: " + (data.message || "unknown error");
  } finally {
    btn.disabled = false;
  }
});

// ---------------- Init ----------------
loadStatus();
loadReport();
loadAuditFilters();
loadEntries();
loadFailedTransactionsForAgent();
