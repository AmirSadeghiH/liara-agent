/* LiaraPilot UI — small, dependency-free client layer.
 * All state-changing actions go through the server API; nothing is reported as
 * successful until the server responds.
 */
(function () {
  "use strict";

  const STATUS = {
    queued: ["gray", "در صف"],
    running: ["teal", "در حال اجرا"],
    waiting_for_approval: ["amber", "منتظر تأیید"],
    testing: ["teal", "در حال تست"],
    deploying: ["violet", "در حال انتشار"],
    verifying: ["teal", "بررسی سلامت"],
    completed: ["green", "تکمیل‌شده"],
    failed: ["red", "ناموفق"],
    cancelled: ["gray", "لغو‌شده"],
    needs_human: ["amber", "نیازمند انسان"],
  };
  const TERMINAL = ["completed", "failed", "cancelled"];

  async function api(path, options = {}) {
    const opts = Object.assign({ headers: {} }, options);
    opts.headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    if (opts.body && typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
    const res = await fetch(path, opts);
    let body = null;
    try { body = await res.json(); } catch (e) { /* non-json */ }
    if (!res.ok) {
      const message = (body && body.error && body.error.message) || ("HTTP " + res.status);
      const err = new Error(message);
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  function message(el, text, type) {
    if (!el) return;
    el.className = "alert " + (type || "info");
    el.textContent = text;
    el.style.display = "block";
  }

  function formatTimes(scope) {
    (scope || document).querySelectorAll("time[data-utc]").forEach(function (node) {
      if (node.dataset.formatted === "1") return;
      const d = new Date(node.dataset.utc);
      if (isNaN(d.getTime())) return;
      node.textContent = d.toLocaleString("fa-IR", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
      node.dataset.formatted = "1";
    });
  }

  function badge(status) {
    const entry = STATUS[status] || ["gray", status || "—"];
    const span = document.createElement("span");
    span.className = "badge " + entry[0];
    span.textContent = entry[1];
    return span;
  }

  function stepRows(events) {
    const order = [];
    const byKey = new Map();
    (events || []).forEach(function (event) {
      if (!event.step) return;
      const attempt = (event.data && event.data.attempt) || 0;
      const key = event.step + ":" + attempt;
      if (!byKey.has(key)) {
        order.push(key);
        byKey.set(key, {
          step: event.step,
          attempt: attempt,
          label: (event.data && event.data.label_fa) || event.step,
          status: event.status,
          message: event.message,
          at: event.created_at,
        });
      } else {
        const row = byKey.get(key);
        row.status = event.status;
        row.message = event.message || row.message;
        row.at = event.created_at;
      }
    });
    return order.map(function (k) { return byKey.get(k); });
  }

  function renderTimeline(container, events) {
    if (!container) return;
    container.innerHTML = "";
    const rows = stepRows(events);
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "muted small";
      empty.textContent = "هنوز مرحله‌ای ثبت نشده است.";
      container.appendChild(empty);
      return;
    }
    rows.forEach(function (row) {
      const wrap = document.createElement("div");
      let cls = "step ";
      if (row.status === "completed") cls += "done";
      else if (row.status === "failed") cls += "failed";
      else if (row.status === "waiting_for_approval") cls += "waiting";
      else cls += "active";
      wrap.className = cls;

      const bullet = document.createElement("div");
      bullet.className = "bullet";
      bullet.textContent = row.status === "completed" ? "✓" : row.status === "failed" ? "!" : "•";

      const body = document.createElement("div");
      const title = document.createElement("div");
      title.className = "title";
      title.textContent = row.label;
      const desc = document.createElement("div");
      desc.className = "desc";
      desc.textContent = row.message || "";
      body.appendChild(title);
      body.appendChild(desc);

      const time = document.createElement("div");
      time.className = "time";
      if (row.at) {
        const d = new Date(row.at);
        time.textContent = isNaN(d.getTime()) ? "" : d.toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
      }

      wrap.appendChild(bullet);
      wrap.appendChild(body);
      wrap.appendChild(time);
      container.appendChild(wrap);
    });
  }

  async function pollWorkflow(root, intervalMs) {
    const id = root.dataset.workflowId;
    let lastStatus = root.dataset.status;
    let reloaded = false;

    async function tick() {
      try {
        const data = await api("/api/workflows/" + encodeURIComponent(id));
        renderTimeline(document.getElementById("wf-timeline"), data.events);
        const label = document.getElementById("wf-status-label");
        if (label) {
          const entry = STATUS[data.status] || ["gray", data.status];
          label.textContent = entry[1];
        }
        const holder = document.getElementById("wf-status-badge");
        if (holder) {
          holder.innerHTML = "";
          holder.appendChild(badge(data.status));
        }
        const attempt = document.getElementById("wf-attempt");
        if (attempt) attempt.textContent = String(data.attempt);

        if (data.status !== lastStatus) {
          const needsReload = ["waiting_for_approval", "completed", "failed", "cancelled", "needs_human"].indexOf(data.status) >= 0;
          lastStatus = data.status;
          if (needsReload && !reloaded) {
            reloaded = true;
            window.setTimeout(function () { window.location.reload(); }, 700);
            return;
          }
        }
        if (TERMINAL.indexOf(data.status) >= 0) {
          window.clearInterval(timer);
        }
      } catch (err) {
        /* transient errors are ignored; next tick retries */
      }
    }

    const timer = window.setInterval(tick, intervalMs || 2000);
    tick();
  }

  function initWorkflowPage() {
    const root = document.getElementById("workflow-root");
    if (!root) return;
    formatTimes();
    pollWorkflow(root, 2000);

    const cancelBtn = document.getElementById("btn-wf-cancel");
    if (cancelBtn) {
      cancelBtn.addEventListener("click", async function () {
        if (!window.confirm("این گردش‌کار لغو شود؟ عملیات در حال اجرا قابل بازگشت نیست.")) return;
        cancelBtn.disabled = true;
        try {
          await api("/api/workflows/" + encodeURIComponent(root.dataset.workflowId) + "/cancel", { method: "POST" });
          window.location.reload();
        } catch (err) {
          cancelBtn.disabled = false;
          window.alert("لغو انجام نشد: " + err.message);
        }
      });
    }
    const refresh = document.getElementById("btn-wf-refresh");
    if (refresh) refresh.addEventListener("click", function () { window.location.reload(); });
  }

  function initApprovals() {
    formatTimes();
  }

  function initDecisionButtons() {
    document.addEventListener("click", async function (event) {
      const btn = event.target.closest("[data-approval-id]");
      if (!btn) return;
      const decision = btn.dataset.decision;
      const approvalId = btn.dataset.approvalId;
      const verb = decision === "approved" ? "تأیید" : "رد";
      if (!window.confirm(verb + " این عملیات؟ تصمیم در سرور ثبت می‌شود.")) return;
      const buttons = document.querySelectorAll("[data-approval-id='" + approvalId + "']");
      buttons.forEach(function (b) { b.disabled = true; });
      try {
        await api("/api/approvals/" + encodeURIComponent(approvalId) +
          (decision === "approved" ? "/approve" : "/reject"),
          { method: "POST", body: { actor: "ui" } });
        window.location.reload();
      } catch (err) {
        buttons.forEach(function (b) { b.disabled = false; });
        window.alert("ثبت تصمیم ناموفق بود: " + err.message);
      }
    });
  }

  function initDemo() {
    const btn = document.getElementById("btn-run-demo");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      const select = document.getElementById("demo-scenario");
      const target = document.getElementById("demo-message");
      btn.disabled = true;
      message(target, "در حال ایجاد گردش‌کار دمو…", "info");
      try {
        const result = await api("/api/demo/run-scenario", {
          method: "POST",
          body: { scenario: select ? select.value : null },
        });
        message(target, "گردش‌کار ساخته شد؛ انتقال به صفحه اجرا…", "ok");
        window.location.href = "/workflows/" + encodeURIComponent(result.workflow_id);
      } catch (err) {
        btn.disabled = false;
        message(target, "اجرای دمو ناموفق بود: " + err.message, "error");
      }
    });
  }

  function initDiagnose() {
    const form = document.getElementById("diagnose-form");
    if (!form) return;
    const project = document.getElementById("project");
    const request = document.getElementById("request");
    const output = document.getElementById("diagnose-message");
    const startBtn = document.getElementById("btn-start-workflow");
    const quickBtn = document.getElementById("btn-quick-diagnose");

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (!project || !project.value) return;
      startBtn.disabled = true;
      message(output, "در حال ساخت گردش‌کار…", "info");
      try {
        const result = await api("/api/workflows", {
          method: "POST",
          body: { project: project.value, request: request.value },
        });
        window.location.href = "/workflows/" + encodeURIComponent(result.workflow_id);
      } catch (err) {
        startBtn.disabled = false;
        message(output, "شروع گردش‌کار ناموفق بود: " + err.message, "error");
      }
    });

    if (quickBtn) {
      quickBtn.addEventListener("click", async function () {
        if (!project || !project.value) return;
        quickBtn.disabled = true;
        message(output, "در حال جمع‌آوری شواهد و تحلیل…", "info");
        const panel = document.getElementById("quick-result");
        const body = document.getElementById("quick-body");
        try {
          const result = await api("/api/diagnose", {
            method: "POST",
            body: { project: project.value, request: request.value },
          });
          renderQuickDiagnosis(body, result);
          panel.style.display = "block";
          document.getElementById("quick-link").href = "/workflows/" + encodeURIComponent(result.workflow_id);
          message(output, "تشخیص کامل شد.", "ok");
        } catch (err) {
          message(output, "تشخیص ناموفق بود: " + err.message, "error");
        } finally {
          quickBtn.disabled = false;
        }
      });
    }
  }

  function renderQuickDiagnosis(container, result) {
    if (!container) return;
    const d = result.diagnosis || {};
    container.innerHTML = "";

    const head = document.createElement("div");
    head.className = "row";
    head.style.marginBottom = "10px";
    const mode = document.createElement("span");
    mode.className = "badge " + (result.simulated ? "amber" : "live");
    mode.textContent = result.simulated ? "DEMO / شبیه‌سازی‌شده" : "LIVE";
    head.appendChild(mode);
    const conf = document.createElement("span");
    conf.className = "chip";
    conf.textContent = "اطمینان: " + ({ low: "کم", medium: "متوسط", high: "زیاد" }[d.confidence] || d.confidence || "—");
    head.appendChild(conf);
    const cause = document.createElement("span");
    cause.className = "chip ltr";
    cause.textContent = d.probable_cause_key || "—";
    head.appendChild(cause);
    container.appendChild(head);

    const fields = [
      ["مشاهده", d.observation],
      ["علت محتمل", d.probable_cause],
      ["اقدام پیشنهادی", d.recommended_action],
      ["منابع", d.resource_assessment],
      ["روش بررسی", d.verification_method],
    ];
    fields.forEach(function (pair) {
      if (!pair[1]) return;
      const p = document.createElement("p");
      p.className = "small";
      const strong = document.createElement("strong");
      strong.textContent = pair[0] + ": ";
      p.appendChild(strong);
      p.appendChild(document.createTextNode(pair[1]));
      container.appendChild(p);
    });

    if (d.evidence && d.evidence.length) {
      const title = document.createElement("div");
      title.className = "small";
      title.style.marginTop = "10px";
      title.innerHTML = "<strong>شواهد:</strong>";
      container.appendChild(title);
      const ul = document.createElement("ul");
      ul.className = "small";
      d.evidence.slice(0, 6).forEach(function (item) {
        const li = document.createElement("li");
        li.textContent = item;
        ul.appendChild(li);
      });
      container.appendChild(ul);
    }
  }

  function initSettings() {
    formatTimes();
    const btn = document.getElementById("btn-test-connection");
    if (!btn) return;
    const output = document.getElementById("connection-result");
    btn.addEventListener("click", async function () {
      btn.disabled = true;
      message(output, "در حال تست اتصال…", "info");
      try {
        const result = await api("/api/settings/test-liara-connection", { method: "POST" });
        if (result.ok) {
          message(output,
            (result.simulated ? "آداپتور شبیه‌ساز پاسخ داد. " : "اتصال برقرار است. ") +
            "تعداد پروژه: " + result.project_count +
            (result.latency_ms != null ? " · " + result.latency_ms + "ms" : ""),
            "ok");
        } else {
          message(output, "اتصال ناموفق: " + (result.error ? result.error.message : "خطای نامشخص"), "error");
        }
      } catch (err) {
        message(output, "تست اتصال ناموفق بود: " + err.message, "error");
      } finally {
        btn.disabled = false;
      }
    });
  }

  function initCopyButtons() {
    document.querySelectorAll("[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const id = btn.dataset.copy;
        const source = document.getElementById(id);
        if (!source) return;
        try {
          await navigator.clipboard.writeText(source.textContent);
          const original = btn.textContent;
          btn.textContent = "کپی شد";
          window.setTimeout(function () { btn.textContent = original; }, 1500);
        } catch (err) {
          window.prompt("کپی دستی:", source.textContent);
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    formatTimes();
    initDecisionButtons();
  });

  window.LP = {
    api: api,
    formatTimes: formatTimes,
    initWorkflowPage: initWorkflowPage,
    initApprovals: initApprovals,
    initDemo: initDemo,
    initDiagnose: initDiagnose,
    initSettings: initSettings,
    initCopyButtons: initCopyButtons,
  };
})();
