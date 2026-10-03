"use strict";
let materialOffset = 0;
const token =
  new URLSearchParams(location.hash.slice(1)).get("token") ||
  sessionStorage.getItem("hireme-token") ||
  "";
if (token) sessionStorage.setItem("hireme-token", token);
history.replaceState(null, "", location.pathname);
let state = null,
  view = "today";
let refreshing = null;
const dirtyForms = new WeakSet();
document.addEventListener("input", (event) => {
  if (event.target.form) dirtyForms.add(event.target.form);
});
document.addEventListener("change", (event) => {
  if (event.target.form) dirtyForms.add(event.target.form);
});
function editing(selector) {
  const form = $(selector);
  return form.contains(document.activeElement) || dirtyForms.has(form);
}
function saved(form) {
  if (!form) return;
  dirtyForms.delete(form);
  if (form.id) {
    const indicator = document.querySelector(`[data-draft-for="${form.id}"]`);
    if (indicator) indicator.textContent = "";
  }
}

function renderAccounts() {
  const parent = document.querySelector("#employer-accounts");
  if (
    [...parent.querySelectorAll("form")].some(
      (form) => dirtyForms.has(form) || form.contains(document.activeElement),
    )
  )
    return;
  parent.replaceChildren();
  const accounts = state.employer_accounts || [];
  if (!accounts.length)
    return empty(parent, "No employer accounts created by this worker.");
  for (const account of accounts) {
    const box = el("article", undefined, "question");
    box.append(
      el("h3", account.company),
      el("p", `${account.origin} · ${account.state}`),
    );
    if (account.state === "uncertain") {
      const form = el("form"),
        evidence = el("textarea");
      evidence.required = true;
      evidence.minLength = 10;
      evidence.maxLength = 2000;
      evidence.rows = 2;
      evidence.setAttribute(
        "aria-label",
        `Account confirmation evidence for ${account.company}`,
      );
      evidence.placeholder =
        "How did you verify that this account exists and you can sign in?";
      form.append(evidence, el("button", "Confirm verified account"));
      form.onsubmit = async (event) => {
        event.preventDefault();
        try {
          await api("/api/account-confirm", {
            id: account.id,
            note: evidence.value,
          });
          saved(form);
          document.activeElement.blur();
          await refresh();
          note("Account confirmed. The next batch can reuse its credentials.");
        } catch (error) {
          note(error.message, true);
        }
      };
      box.append(form);
    }
    parent.append(box);
  }
}
const $ = (s) => document.querySelector(s);
const el = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
const note = (text, error = false) => {
  const notice = $("#notice");
  notice.textContent = text;
  notice.classList.toggle("error", error);
  notice.setAttribute("role", error ? "alert" : "status");
};
async function api(path, data, raw = false, extraHeaders = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: data === undefined ? "GET" : "POST",
      headers: {
        ...extraHeaders,
        "X-Hireme-Token": token,
        ...(!raw && data !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
      },
      body: data === undefined ? undefined : raw ? data : JSON.stringify(data),
    });
  } catch {
    throw new Error(
      "Cannot reach your application desk. Check that the dashboard is still running, then try again.",
    );
  }
  let value;
  try {
    value = await response.json();
  } catch {
    throw new Error(
      "The dashboard returned an unexpected response. Refresh the page and try again.",
    );
  }
  if (!response.ok) throw new Error(value.error || "Request failed");
  // Successful saves release draft protection only for the form that was saved.
  const forms = {
    "/api/facts": "#facts-form",
    "/api/template": "#template-form",
    "/api/context-text": "#context-form",
  };
  if (forms[path]) saved($(forms[path]));
  return value;
}
function show(name) {
  view = name;
  $("#page-eyebrow").textContent = {
    setup: "YOUR NEXT CHAPTER",
    today: "YOUR SEARCH, IN MOTION",
    questions: "A LITTLE HELP GOES A LONG WAY",
    profile: "THE FACTS THAT MAKE YOU, YOU",
    materials: "YOUR EXPERIENCE, IN YOUR WORDS",
    settings: "A SEARCH THAT FITS YOUR LIFE",
    providers: "YOUR CHOICE OF MODEL",
    connections: "KEEP YOUR SEARCH CONNECTED",
  }[name];
  document.querySelectorAll(".view").forEach((n) => (n.hidden = n.id !== name));
  document
    .querySelectorAll("[data-view]")
    .forEach((n) =>
      n.setAttribute(
        "aria-current",
        n.dataset.view === name ? "page" : "false",
      ),
    );
  $("#heading").textContent = {
    setup: "Make it yours",
    providers: "Your model connection",
    today: "Today’s applications",
    questions: "A few things need you",
    profile: "Your verified facts",
    materials: "Your writing and context",
    connections: "Email automation",
    settings: "Your search preferences",
  }[name];
  $("#subheading").textContent = {
    setup: "Set up once. Save as you go.",
    providers: "Choose who processes your application context.",
    today: "A real record of what the worker submitted, held and discovered.",
    questions: "Resolve the exception. Let the next cycle do the rest.",
    profile: "Saved once, reused across applications. Unknown means unknown.",
    materials:
      "Reviewed sources guide the voice and facts in your applications.",
    connections:
      "Verification codes and batch reports for your application email.",
    settings: "Choose your search boundaries. Throughput never overrides them.",
  }[name];
}
function link(url, text) {
  const a = el("a", text);
  if (!state?.demo && /^https:\/\//.test(url)) {
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  }
  return a;
}
function date(v) {
  return v
    ? new Date(v).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "—";
}
function empty(parent, text, title = "Nothing here yet", symbol = "◇") {
  const box = el("div", undefined, "empty");
  box.append(
    el("span", symbol, "empty-symbol"),
    el("strong", title),
    el("p", text),
  );
  parent.append(box);
}
const statusLabels = {
  confirmed: "Submitted",
  blocked: "Needs action",
  unknown: "Uncertain",
  awaiting_verification: "Check email",
  discovered: "Ready to evaluate",
  rejected: "Not a match",
  skipped: "Skipped",
  attempting: "Applying",
  manual: "Manual handling",
};
function jobPayload(job) {
  try {
    return JSON.parse(job.payload);
  } catch {
    return {};
  }
}
let ledgerSignature = "";
function renderLedger() {
  if (!state) return;
  $("#ledger-scope").textContent =
    state.summary && state.summary.job_count > state.jobs.length
      ? `Showing ${state.jobs.length} highest-ranked opportunities of ${state.summary.job_count}. Export CSV includes the full ledger.`
      : "";
  const query = $("#job-search").value.trim().toLocaleLowerCase();
  const filter = $("#status-filter").value;
  const jobs = state.jobs.filter((job) => {
    const searchable =
      `${job.company} ${job.title} ${jobPayload(job).location || ""}`.toLocaleLowerCase();
    return (
      (filter === "all" || (job.display_status || job.status) === filter) &&
      (!query || searchable.includes(query))
    );
  });
  const sort = $("#job-sort").value;
  jobs.sort((a, b) =>
    sort === "fit"
      ? b.score - a.score
      : sort === "company"
        ? a.company.localeCompare(b.company)
        : String(b.first_seen).localeCompare(String(a.first_seen)),
  );
  $("#ledger-count").textContent = String(jobs.length);
  const signature = JSON.stringify([
    jobs,
    state.applications,
    query,
    filter,
    sort,
  ]);
  if (signature !== ledgerSignature) {
    table(jobs, $("#jobs"), query || filter !== "all");
    ledgerSignature = signature;
  }
}
function table(jobs, parent, filtered = false) {
  parent.replaceChildren();
  if (!jobs.length) {
    const mainLedger = parent.id === "jobs";
    empty(
      parent,
      mainLedger
        ? filtered
          ? "Try another search or show all statuses."
          : "Your opportunities will appear here after your first discovery batch. You can also add a posting you found yourself."
        : "You’re all clear here. Your desk will let you know when an opportunity needs a closer look.",
      mainLedger
        ? filtered
          ? "No matching opportunities"
          : "Your next chapter starts here"
        : "All clear",
      mainLedger ? "↗" : "✓",
    );
    return;
  }
  const t = el("table"),
    head = el("thead"),
    hr = el("tr");
  t.setAttribute("aria-label", "Application opportunities");
  ["Opportunity", "Status", "Fit", "Record"].forEach((x) => {
    const th = el("th", x);
    th.scope = "col";
    hr.append(th);
  });
  head.append(hr);
  t.append(head);
  const body = el("tbody");
  for (const job of jobs) {
    const row = el("tr"),
      a = el("td"),
      companyLine = el("div", undefined, "company-line"),
      info = el("div", undefined, "company-info");
    const avatar = el(
      "span",
      job.company.trim().slice(0, 1).toUpperCase() || "?",
      "company-avatar",
    );
    avatar.setAttribute("aria-hidden", "true");
    const title = link(job.url, job.title);
    title.className = "job-title";
    info.append(
      title,
      el(
        "p",
        `${job.company} · ${jobPayload(job).location || "Location not stated"}`,
      ),
    );
    if (job.reason)
      info.append(el("p", job.reason_label || job.reason, "job-reason"));
    if (parent.id === "blocked-jobs" && job.next_step)
      info.append(el("p", job.next_step, "help"));
    companyLine.append(avatar, info);
    a.append(companyLine);
    const b = el("td");
    b.dataset.label = "Status";
    b.append(
      el(
        "span",
        job.status_label ||
          statusLabels[job.status] ||
          job.status.replaceAll("_", " "),
        "state " + (job.display_status || job.status),
      ),
    );
    const c = el("td");
    c.dataset.label = "Fit";
    c.append(
      el(
        "span",
        job.score > 0 ? `${job.score}%` : "Not evaluated",
        job.score > 0 ? "fit-score" : "subtle",
      ),
    );
    const d = el("td");
    const app = state.applications.find((x) => x.job_id === job.id);
    if (app) {
      const detail = el("details");
      detail.append(el("summary", "Answers & evidence"));
      const list = el("ul", undefined, "answer-log");
      let answers = [];
      try {
        answers = JSON.parse(app.package).answers || [];
      } catch {}
      for (const answer of answers) {
        const li = el("li"),
          provenance = answer.provenance || {};
        li.append(
          el("strong", answer.field.label),
          el("p", answer.value),
          el(
            "small",
            provenance.fact_key
              ? `Verified fact: ${provenance.fact_key}`
              : provenance.sample_parts
                ? "Your approved writing samples"
                : provenance.template_id
                  ? "Your approved writing sample"
                  : provenance.resume_quote
                    ? "Verified resume evidence"
                    : provenance.job_source
                      ? "Recorded discovery source"
                      : provenance.contextual_preference
                        ? "Selected from your confirmed skills and availability"
                        : provenance.job_title
                          ? "Role from this posting"
                          : "Your saved answer",
          ),
        );
        list.append(li);
      }
      if (!answers.length)
        list.append(el("li", "No recorded answers for this attempt."));
      detail.append(list);
      if (app.screenshot) {
        const btn = el("button", "View confirmation", "secondary");
        btn.type = "button";
        btn.onclick = async () => {
          btn.disabled = true;
          try {
            const r = await fetch(
              "/api/screenshot/" + encodeURIComponent(app.screenshot),
              { headers: { "X-Hireme-Token": token } },
            );
            if (!r.ok) throw new Error("Screenshot unavailable");
            const img = el("img"),
              url = URL.createObjectURL(await r.blob());
            img.src = url;
            img.alt = "Recorded page after submission";
            img.className = "evidence";
            img.onload = img.onerror = () => URL.revokeObjectURL(url);
            btn.replaceWith(img);
          } catch (e) {
            note(e.message, true);
            btn.disabled = false;
          }
        };
        detail.append(btn);
      }
      d.append(detail);
    } else d.append(el("span", "No attempt yet", "subtle"));
    if (job.reason) {
      const diagnostic = el("details", undefined, "diagnostic");
      diagnostic.append(
        el("summary", "Recorded details"),
        el("p", job.reason, "subtle"),
      );
      d.append(diagnostic);
    }
    row.append(a, b, c, d);
    body.append(row);
  }
  t.append(body);
  parent.append(t);
}
function attentionCount() {
  const jobIds = new Set(state.questions.map((q) => q.job_id));
  state.jobs
    .filter(
      (j) =>
        j.requires_attention ??
        ["blocked", "unknown", "awaiting_verification"].includes(j.status),
    )
    .forEach((j) => jobIds.add(j.id));
  state.applications
    .filter((a) => ["unknown", "awaiting_verification"].includes(a.state))
    .forEach((a) => jobIds.add(a.job_id));
  return (
    jobIds.size +
    (state.employer_accounts || []).filter((a) => a.state === "uncertain")
      .length
  );
}
function renderOverview(submitted) {
  const count = state.summary?.attention_count ?? attentionCount(),
    ready =
      state.summary?.status_counts.discovered ??
      state.jobs.filter((j) => j.status === "discovered").length;
  $("#metric-submitted").textContent = String(submitted);
  $("#metric-submitted-help").textContent =
    `of ${state.settings.target_per_day} daily target`;
  $("#submission-progress").max = state.settings.target_per_day;
  $("#submission-progress").value = submitted;
  $("#metric-attention").textContent = String(count);
  $("#metric-attention-help").textContent =
    count === 0
      ? "You’re all caught up"
      : `${count === 1 ? "One item needs" : `${count} items need`} a little help`;
  $("#metric-opportunities").textContent = String(
    state.summary?.job_count ?? state.jobs.length,
  );
  $("#metric-ready").textContent = ready
    ? `${ready} ready to evaluate`
    : "Discovery is ready when you are";
  $("#worker-dot").classList.toggle("enabled", state.settings.live_enabled);
  $("#workspace-date").textContent = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: state.settings.timezone,
  })
    .format(new Date())
    .toUpperCase();
  $("#question-count").textContent = count ? String(count) : "";
}
function renderQuestions() {
  if (
    [...document.querySelectorAll("#questions form")].some(
      (form) => dirtyForms.has(form) || form.contains(document.activeElement),
    )
  )
    return;
  const q = $("#question-list");
  q.replaceChildren();
  if (!state.questions.length)
    empty(
      q,
      "No unanswered personal questions. New questions will appear here without stopping the rest of the search.",
    );
  for (const x of state.questions) {
    const box = el("article", undefined, "question");
    box.append(el("h3", x.label));
    const job = state.jobs.find((j) => j.id === x.job_id);
    if (job) box.append(link(job.url, `${job.company} · ${job.title}`));
    box.append(el("p", x.reason, "subtle"));
    const f = el("form");
    const options = JSON.parse(x.options);
    const input = options.length ? el("select") : el("textarea");
    input.required = true;
    input.setAttribute("aria-label", x.label);
    if (options.length) {
      input.append(new Option("Choose an answer", ""));
      options.forEach((v) => input.append(new Option(v, v)));
    } else input.rows = 3;
    const bind = el("select");
    bind.setAttribute("aria-label", "Optional confirmed fact");
    bind.append(new Option("Save as an exact answer to this question", ""));
    for (const [k, v] of Object.entries(state.facts)) {
      if (v.confirmed)
        bind.append(new Option(`Use ${state.fact_labels[k]}: ${v.value}`, k));
    }
    bind.onchange = () => {
      if (bind.value) input.value = state.facts[bind.value].value;
    };
    const b = el("button", "Save once and reuse");
    f.append(input, bind, b);
    f.onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api("/api/answer", {
          id: x.id,
          value: input.value,
          fact_key: bind.value || null,
        });
        saved(f);
        document.activeElement.blur();
        note(
          "Answer saved. Matching applications can use it in the next cycle.",
        );
        await refresh();
      } catch (e) {
        note(e.message, true);
      }
    };
    box.append(f);
    q.append(box);
  }
  table(
    state.jobs.filter(
      (j) => j.status === "blocked" && (j.requires_attention ?? true),
    ),
    $("#blocked-jobs"),
  );
  const u = $("#uncertain");
  u.replaceChildren();
  const unknown = state.applications.filter((a) =>
    ["unknown", "awaiting_verification"].includes(a.state),
  );
  if (!unknown.length) empty(u, "No uncertain submissions.");
  for (const a of unknown) {
    const box = el("article", undefined, "question");
    const job = state.jobs.find((j) => j.id === a.job_id);
    box.append(el("h3", job ? `${job.company} · ${job.title}` : a.job_id));
    if (job) box.append(link(job.url, "Verify at the employer"));
    if (a.state === "awaiting_verification")
      box.append(
        el(
          "p",
          "Email verification pending. This application is held and will not be retried automatically.",
          "subtle",
        ),
      );
    const f = el("form"),
      select = el("select");
    select.setAttribute("aria-label", "Verified outcome");
    select.append(
      new Option("Employer confirms submission", "true"),
      new Option("Verified no submission occurred", "false"),
    );
    const text = el("textarea");
    text.required = true;
    text.minLength = 10;
    text.rows = 2;
    text.placeholder = "How did you verify the outcome?";
    text.setAttribute("aria-label", "Verification evidence");
    const b = el("button", "Record verified outcome");
    f.append(select, text, b);
    f.onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api("/api/reconcile", {
          id: a.id,
          submitted: select.value === "true",
          note: text.value,
        });
        saved(f);
        document.activeElement.blur();
        await refresh();
        note(
          "Outcome recorded. A non-submitted attempt remains held for manual handling.",
        );
      } catch (e) {
        note(e.message, true);
      }
    };
    box.append(f);
    u.append(box);
  }
}
const groups = {
  Contact: [
    "full_name",
    "first_name",
    "last_name",
    "preferred_name",
    "email",
    "phone",
    "location",
    "street",
    "city",
    "state",
    "postal_code",
    "country",
    "linkedin",
    "github",
    "website",
  ],
  "Education & experience": [
    "school",
    "high_school",
    "degree",
    "major",
    "graduation",
    "college_start",
    "highest_completed_degree",
    "gpa",
    "professional_years",
    "skills",
  ],
  "Authorization & availability": [
    "work_authorized_us",
    "needs_sponsorship",
    "citizenship",
    "us_person",
    "unrestricted_authorization",
    "earliest_start",
    "latest_start",
    "salary",
    "notice_period",
    "relocate",
    "onsite",
    "summer_2027_relocate",
    "worked_outside_resume",
    "contacts_outside_resume",
  ],
  "Optional disclosures & consent": [
    "race",
    "gender",
    "veteran",
    "disability",
    "recording",
    "background_check",
    "sms",
    "native_name",
  ],
};
const yesNoFacts = new Set([
  "work_authorized_us",
  "needs_sponsorship",
  "us_person",
  "unrestricted_authorization",
  "relocate",
  "onsite",
  "recording",
  "background_check",
  "sms",
  "worked_outside_resume",
  "contacts_outside_resume",
  "summer_2027_relocate",
]);
const monthFacts = new Set([
  "graduation",
  "college_start",
  "earliest_start",
  "latest_start",
]);
const factHelp = {
  skills:
    "Separate skills with commas. Include only skills you can honestly support.",
  professional_years:
    "Use your actual qualifying professional experience. Enter 0 if you have none.",
  us_person:
    "Answer based on your own confirmed export-control status. Do not infer this from your address.",
  needs_sponsorship: "Include sponsorship you will need now or in the future.",
  work_authorized_us:
    "Use your current authorization status; this is not extracted from your resume.",
  graduation: "Choose your expected graduation month and year.",
  email:
    "Use the email you want employers to contact. It is tied to your application history.",
};
function renderFacts() {
  const parent = $("#fact-fields");
  parent.replaceChildren();
  for (const [name, keys] of Object.entries(groups)) {
    const group = el("fieldset", undefined, "fact-group"),
      grid = el("div", undefined, "form-grid");
    group.append(el("legend", name));
    const optionalGroup = keys.every((key) => !state.required.includes(key));
    if (optionalGroup) {
      group.dataset.optionalGroup = "true";
      group.hidden = !$("#show-optional-facts").checked;
    }
    for (const key of keys) {
      const required = state.required.includes(key),
        label = el(
          "label",
          state.fact_labels[key] + (required ? " · required" : ""),
        );
      const input = el(key === "skills" ? "textarea" : "input");
      input.name = key;
      input.id = "fact-" + key;
      input.value = state.facts[key]?.value || "";
      if (key === "skills") input.rows = 2;
      if (required) input.required = true;
      if (yesNoFacts.has(key)) {
        input.setAttribute("list", "yes-no-values");
        input.pattern = "Yes|No";
        input.placeholder = "Choose Yes or No";
      }
      if (monthFacts.has(key)) input.type = "month";
      if (key === "email") {
        input.type = "email";
        input.autocomplete = "email";
      }
      if (key === "phone") {
        input.type = "tel";
        input.autocomplete = "tel";
      }
      if (key === "professional_years") {
        input.type = "number";
        input.min = "0";
        input.max = "80";
        input.step = "0.1";
      }
      const autocomplete = {
        full_name: "name",
        first_name: "given-name",
        last_name: "family-name",
        street: "street-address",
        postal_code: "postal-code",
        city: "address-level2",
        state: "address-level1",
        country: "country-name",
      };
      if (autocomplete[key]) input.autocomplete = autocomplete[key];
      if (state.facts[key] && !state.facts[key].confirmed)
        label.append(
          el("span", "Extracted from resume — please confirm", "candidate"),
        );
      label.append(input);
      if (factHelp[key]) {
        const help = el("span", factHelp[key], "help");
        help.id = "help-" + key;
        input.setAttribute("aria-describedby", help.id);
        label.append(help);
      }
      if (!required) {
        label.dataset.optionalFact = "true";
        label.hidden = !$("#show-optional-facts").checked;
      }
      grid.append(label);
    }
    group.append(grid);
    parent.append(group);
  }
  $("#resume-state").textContent = state.documents.some(
    (x) => x.kind === "resume",
  )
    ? "Resume imported and stored privately."
    : "No resume imported.";
  $("#transcript-state").textContent = state.documents.some(
    (x) => x.kind === "transcript",
  )
    ? "Transcript imported and stored privately. Upload another PDF to replace it."
    : "No transcript imported. Jobs requiring one will appear in Needs you.";
  $("#setup-status").textContent = state.missing_setup.length
    ? "Still needed: " +
      state.missing_setup.map((key) => state.fact_labels[key] || key).join(", ")
    : "Required facts are confirmed. You can start automatic applications.";
  $("#complete-setup").disabled = state.missing_setup.length > 0;
  $("#fact-completion").textContent =
    `${state.required.filter((key) => state.facts[key]?.confirmed).length} of ${state.required.length} required facts confirmed`;
}
$("#show-optional-facts").onchange = (event) => {
  document
    .querySelectorAll("[data-optional-fact],[data-optional-group]")
    .forEach((field) => (field.hidden = !event.target.checked));
};
function updateProviderFields() {
  const form = $("#provider-form"),
    paid = form.elements.provider.value.endsWith("-api");
  $("#provider-key-field").hidden = !paid;
  form.elements.key.disabled = !paid;
  $("#provider-model-help").textContent = paid
    ? "Use an exact model ID from your selected vendor. API usage has separate billing."
    : "Optional. Leave blank to use the provider’s configured model.";
  form.elements.provider_model.required = paid;
}
$("#provider-form [name=provider]").addEventListener(
  "change",
  updateProviderFields,
);
function renderTemplates() {
  const p = $("#templates");
  p.replaceChildren();
  for (const t of state.templates) {
    const d = el("details");
    d.append(
      el("summary", t.category + " · " + t.body.slice(0, 70)),
      el("p", t.body),
    );
    p.append(d);
  }
}
function renderSettings() {
  const f = $("#settings-form");
  for (const input of f.elements) {
    if (!input.name) continue;
    const v = state.settings[input.name];
    if (input.type === "checkbox") {
      input.checked = !!v;
      continue;
    }
    input.value = Array.isArray(v)
      ? v.join("\n")
      : typeof v === "object"
        ? JSON.stringify(v, null, 2)
        : v;
  }
}
function renderRuns() {
  const parent = $("#runs");
  parent.replaceChildren();
  if (!state.runs.length) {
    empty(
      parent,
      "Finish your setup and start a batch. This is where you’ll see what ran and how it went.",
      "Your desk is ready for its first batch",
      "↻",
    );
    return;
  }
  for (const run of state.runs) {
    const row = el("div", undefined, "run-row");
    let detail = run.detail;
    try {
      const data = JSON.parse(detail);
      const outcomes = Object.entries(data.outcomes || {})
        .filter(([key]) => key !== "confirmed")
        .map(
          ([key, value]) =>
            `${statusLabels[key] || key.replaceAll("_", " ")}: ${value}`,
        )
        .join("; ");
      const reason =
        data.reason ||
        Object.entries(data.reasons || {})
          .map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`)
          .join("; ");
      detail =
        `${data.confirmed || 0} submitted · ${data.attempts || 0} attempted. ${outcomes} ${reason}`.trim();
    } catch {}
    row.append(
      el("span", date(run.started)),
      el("span", run.status.replaceAll("_", " ")),
      el("span", detail),
    );
    parent.append(row);
  }
}
function render() {
  const dayFormatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: state.settings.timezone,
  });
  const today = dayFormatter.format(new Date());
  const submitted =
    state.summary?.submitted_today ??
    state.applications.filter(
      (application) =>
        application.state === "confirmed" &&
        application.attempted &&
        dayFormatter.format(new Date(application.attempted)) === today,
    ).length;
  renderOverview(submitted);
  $("#daily-progress").textContent =
    submitted >= state.settings.target_per_day
      ? "Daily target reached. Every step counts."
      : `${submitted} confirmed today · ${Math.max(0, state.settings.target_per_day - submitted)} to your daily target`;
  $("#daily-target").textContent =
    `Daily target: ${state.settings.target_per_day}`;
  $("#setup-callout").hidden = state.settings.onboarding_complete;
  $("#worker-state").textContent = state.demo
    ? "Read-only sample workspace"
    : state.worker_running
      ? state.settings.live_enabled
        ? "Batch running"
        : "Pausing active batch…"
      : !state.settings.onboarding_complete
        ? "Setup needed"
        : state.settings.live_enabled
          ? "Automatic submissions enabled"
          : "Submissions paused";
  $("#pause").textContent = state.settings.live_enabled ? "Pause" : "Resume";
  $("#pause").disabled = state.demo || !state.settings.onboarding_complete;
  $("#run").disabled =
    state.demo ||
    state.worker_running ||
    !state.settings.onboarding_complete ||
    !state.settings.live_enabled;
  $("#demo-banner").hidden = !state.demo;
  renderLedger();
  renderSetup();
  renderQuestions();
  renderAccounts();
  renderTemplates();
  renderMaterials();
  renderMail();
  if (!editing("#facts-form")) renderFacts();
  if (!editing("#settings-form")) renderSettings();
  renderRuns();
  const sources = $("#sources");
  sources.replaceChildren();
  if (!state.sources.length)
    empty(
      sources,
      "Source checks appear after discovery. Your desk keeps earlier opportunities if a source is temporarily unavailable.",
      "Discovery is ready",
      "↗",
    );
  for (const source of state.sources)
    sources.append(
      el(
        "p",
        `${source.id}: ${source.status} · ${date(source.checked)}${source.error ? " · " + source.error : ""}`,
      ),
    );
  show(view);
}
async function refresh() {
  if (refreshing) {
    await refreshing;
    return refresh();
  }
  refreshing = (async () => {
    try {
      state = await api("/api/state?material_offset=" + materialOffset);
      render();
      $("#connection-status").hidden = true;
    } catch (error) {
      const status = $("#connection-status");
      status.hidden = false;
      $("#connection-message").textContent = error.message;
      if (!state) note(error.message, true);
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}
document
  .querySelectorAll("[data-view]")
  .forEach((b) => (b.onclick = () => show(b.dataset.view)));
$("#setup-link").onclick = () => show("setup");
$("#status-filter").onchange = renderLedger;
$("#job-sort").onchange = renderLedger;
$("#job-search").oninput = renderLedger;
$("#review-queue").onclick = () => show("questions");
$("#add-posting").onclick = () => {
  const panel = $("#add-posting-panel");
  panel.open = true;
  panel.scrollIntoView({
    block: "center",
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth",
  });
  $("#job-form [name=company]").focus({ preventScroll: true });
};
$("#facts-form").onsubmit = async (e) => {
  e.preventDefault();
  if (!$("#confirm-facts").checked) return;
  const facts = Object.fromEntries(
    [...new FormData(e.target)].filter(([, v]) => v.trim()),
  );
  try {
    await api("/api/facts", { facts });
    $("#confirm-facts").checked = false;
    note("Confirmed facts saved. They will be reused automatically.");
    document.activeElement.blur();
    await refresh();
  } catch (e) {
    note(e.message, true);
  }
};
$("#resume-upload").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    await api("/api/resume", f, true);
    note(
      "Resume imported. Confirm its extracted values and supply the remaining facts.",
    );
    await refresh();
  } catch (e) {
    note(e.message, true);
  }
};
$("#settings-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const data = {};
    for (const input of event.target.elements) {
      if (!input.name) continue;
      if (input.type === "checkbox") data[input.name] = input.checked;
      else if (input.type === "number") data[input.name] = Number(input.value);
      else if (input.name === "company_aliases") {
        try {
          data[input.name] = JSON.parse(input.value || "{}");
        } catch {
          throw new Error(
            'Company aliases must be a valid JSON object, for example {"Acme Inc": "Acme"}.',
          );
        }
      } else if (Array.isArray(state.settings[input.name]))
        data[input.name] = input.value
          .split("\n")
          .map((v) => v.trim())
          .filter(Boolean);
      else data[input.name] = input.value;
    }
    await api("/api/settings", data);
    saved(event.target);
    note("Search preferences saved.");
    document.activeElement.blur();
    await refresh();
  } catch (error) {
    note(error.message, true);
  }
};
$("#complete-setup").onclick = async () => {
  try {
    const r = await api("/api/complete-setup", { start: true });
    note(r.message || "Automatic applications enabled.");
    await refresh();
  } catch (e) {
    note(e.message, true);
  }
};
$("#pause").onclick = async () => {
  try {
    await api(
      state.settings.live_enabled ? "/api/pause" : "/api/resume-worker",
      {},
    );
    await refresh();
  } catch (e) {
    note(e.message, true);
  }
};
$("#run").onclick = async () => {
  try {
    await api("/api/run", {});
    note("Cycle started. You can keep working; the ledger will update.");
    await refresh();
  } catch (e) {
    note(e.message, true);
  }
};
$("#job-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await api("/api/job", Object.fromEntries(new FormData(e.target)));
    e.target.reset();
    note(
      "Posting added. Eligibility will be checked before any form is filled.",
    );
    await refresh();
  } catch (e) {
    note(e.message, true);
  }
};
refresh().then(() => {
  if (state && !state.settings.onboarding_complete && view === "today")
    show("setup");
});
setInterval(() => {
  if (
    !document.hidden &&
    !document.activeElement.matches("input,textarea,select")
  )
    refresh();
}, 15000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
$("#retry-connection").onclick = refresh;

$("#template-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await api("/api/template", Object.fromEntries(new FormData(e.target)));
    e.target.reset();
    note("Approved wording saved.");
    await refresh();
  } catch (e) {
    note(e.message, true);
  }
};

$("#transcript-upload").onchange = async (e) => {
  const input = e.target,
    f = input.files[0];
  if (!f) return;
  input.disabled = true;
  try {
    await api("/api/transcript", f, true);
    note(
      "Transcript saved. Matching applications can upload it automatically in the next cycle.",
    );
    await refresh();
  } catch (error) {
    note(error.message, true);
  } finally {
    input.disabled = false;
    input.value = "";
  }
};

function renderMaterials() {
  const list = $("#material-list");
  if (
    list.contains(document.activeElement) ||
    [...list.querySelectorAll("form")].some((form) => dirtyForms.has(form))
  )
    return;
  list.replaceChildren();
  if (state.material_count > 20) {
    const controls = el("div", undefined, "actions"),
      previous = el("button", "Newer sources", "secondary"),
      next = el("button", "Older sources", "secondary");
    previous.disabled = materialOffset === 0;
    next.disabled = materialOffset + 20 >= state.material_count;
    previous.onclick = async () => {
      materialOffset = Math.max(0, materialOffset - 20);
      await refresh();
    };
    next.onclick = async () => {
      materialOffset += 20;
      await refresh();
    };
    controls.append(
      previous,
      el(
        "p",
        `${materialOffset + 1}–${Math.min(materialOffset + 20, state.material_count)} of ${state.material_count}`,
      ),
      next,
    );
    list.append(controls);
  }
  if (!state.materials.length)
    return empty(
      list,
      "Upload a writing sample, cover-letter example or supporting document to begin. Each source gets a review before the model uses it.",
    );
  for (const source of state.materials) {
    const box = el("article", undefined, "section");
    box.append(
      el("h2", source.original_name),
      el(
        "p",
        `${source.kind.replaceAll("_", " ")} · ${source.confirmed ? "Approved" : "Needs review"} · ${date(source.updated)}`,
        "subtle",
      ),
    );
    const form = el("form", undefined, "material-review");
    const textLabel = el("label", "Reviewed excerpt");
    const text = el("textarea");
    text.rows = 8;
    text.required = true;
    text.minLength = 20;
    text.maxLength = 12000;
    text.value = source.text;
    textLabel.append(text);
    const roleLabel = el("label", "How the model can use this");
    const role = el("select");
    role.append(
      new Option(
        "Background reference — no claim that I did this work",
        "reference",
      ),
      new Option("My own factual work and experience", "personal"),
      new Option("Writing style and structure only", "style"),
    );
    role.value = source.role;
    roleLabel.append(role);
    const approvedLabel = el("label", undefined, "confirmation");
    const approved = el("input");
    approved.type = "checkbox";
    approved.checked = !!source.confirmed;
    approvedLabel.append(
      approved,
      document.createTextNode(
        "I reviewed this excerpt and approve its selected use. Uncheck to stop using it.",
      ),
    );
    const button = el("button", "Save reviewed source");
    form.append(
      textLabel,
      el(
        "p",
        "Keep up to 12,000 characters per reviewed excerpt. Example qualifications belong in style-only sources unless they describe your own work.",
        "help",
      ),
      roleLabel,
      approvedLabel,
      button,
    );
    form.onsubmit = async (event) => {
      event.preventDefault();
      button.disabled = true;
      try {
        await api("/api/material-review", {
          id: source.id,
          text: text.value,
          role: role.value,
          confirmed: approved.checked,
        });
        saved(form);
        document.activeElement.blur();
        await refresh();
        note("Source saved. Approved use and revisions are recorded.");
      } catch (error) {
        note(error.message, true);
      } finally {
        button.disabled = false;
      }
    };
    box.append(form);
    list.append(box);
  }
}
$("#material-upload-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.target,
    file = form.elements.file.files[0],
    button = form.querySelector("button");
  if (!file) return;
  if (file.size > 20 * 1024 * 1024)
    return note("Choose a file up to 20 MiB.", true);
  button.disabled = true;
  try {
    await api("/api/material-upload", file, true, {
      "X-Upload-Name": encodeURIComponent(file.name),
      "X-Material-Kind": form.elements.kind.value,
    });
    form.reset();
    await refresh();
    note(
      "Source uploaded. Review the excerpt and choose how the model can use it.",
    );
  } catch (error) {
    note(error.message, true);
  } finally {
    button.disabled = false;
  }
};

function renderMail() {
  const mail = state.gmail;
  $("#gmail-state").textContent = mail.connected
    ? `Authorization saved for ${mail.email}.`
    : mail.client_configured
      ? "OAuth client saved. Run the connection command below to authorize Gmail."
      : "No Gmail authorization saved.";
  const form = $("#mail-settings-form");
  if (!editing("#mail-settings-form"))
    for (const input of form.elements) {
      if (input.name) input.checked = !!state.settings[input.name];
    }
  const reports = $("#report-delivery");
  reports.replaceChildren();
  if (!state.reports.length)
    empty(
      reports,
      "Batch reports appear here after the worker runs. Email delivery is optional.",
    );
  for (const report of state.reports)
    reports.append(
      el(
        "p",
        `${date(report.created)} · ${report.state}${report.last_error ? " · " + report.last_error : ""}`,
      ),
    );
}
$("#gmail-client-upload").onchange = async (event) => {
  const input = event.target,
    file = input.files[0];
  if (!file) return;
  if (file.size > 65536) {
    input.value = "";
    return note("Choose the Google OAuth client JSON, up to 64 KiB.", true);
  }
  input.disabled = true;
  try {
    await api("/api/gmail-client", file, true);
    await refresh();
    note(
      "OAuth client stored privately. Run the connection command to authorize Gmail.",
    );
  } catch (error) {
    note(error.message, true);
  } finally {
    input.disabled = false;
    input.value = "";
  }
};
$("#mail-settings-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.target;
  try {
    await api("/api/settings", {
      gmail_reports: form.elements.gmail_reports.checked,
      gmail_verification: form.elements.gmail_verification.checked,
    });
    saved(form);
    document.activeElement.blur();
    await refresh();
    note("Email preferences saved.");
  } catch (error) {
    note(error.message, true);
  }
};
$("#flush-reports").onclick = async (event) => {
  const button = event.target;
  button.disabled = true;
  try {
    const result = await api("/api/reports/flush", {});
    await refresh();
    note(
      result.error
        ? `Reports remain queued: ${result.error}`
        : `${result.sent} report(s) sent.`,
      !!result.error,
    );
  } catch (error) {
    note(error.message, true);
  } finally {
    button.disabled = false;
  }
};

const setupSteps = [
  [
    "Documents",
    "profile",
    "Import your required resume and optional transcript. Cover-letter examples go in Writing & context.",
  ],
  [
    "Key information",
    "profile",
    "Confirm the facts extracted from your resume. Add authorization and availability yourself.",
  ],
  [
    "Additional context",
    "materials",
    "Add your own experience or supporting research; choose the correct approved use.",
  ],
  [
    "Writing samples",
    "materials",
    "Upload essays or cover-letter examples. Style sources guide voice, not qualifications.",
  ],
  [
    "Job preferences",
    "settings",
    "Choose roles, locations, seniority and exclusions. Save preferences before continuing.",
  ],
  [
    "Schedule and limits",
    "settings",
    "Choose batch frequency, submission ceilings, attempt ceilings and model request caps. Save preferences.",
  ],
  [
    "Model and run location",
    "providers",
    "Connect a CLI subscription or a paid API key. Finish paused or start batches.",
  ],
];
let setupStep = -1;

function renderSetup() {
  const checks = state.readiness,
    parent = $("#machine-checks");
  parent.replaceChildren();
  parent.append(
    el("h2", "This machine"),
    el(
      "p",
      `${checks.platform} · ${checks.architecture} · Python ${checks.python}`,
    ),
    el(
      "p",
      `Browser: ${checks.browser_ready ? "available" : "missing — run setup.sh or install Chromium"} · Model: ${checks.provider.message}`,
    ),
  );
  const list = $("#setup-steps");
  list.replaceChildren();
  const completed = [
    state.documents.some((d) => d.kind === "resume"),
    state.missing_setup.filter((k) => k !== "resume").length === 0,
    state.materials.some((m) => m.confirmed && m.role === "personal"),
    state.materials.some((m) => m.confirmed && m.role === "style"),
    state.settings.onboarding_complete,
    state.settings.onboarding_complete,
    checks.provider.ready,
  ];
  $("#setup-progress-text").textContent =
    `${completed.filter(Boolean).length} of ${setupSteps.length} steps ready`;
  setupSteps.forEach(([title, route, description], index) => {
    const optional = index === 2 || index === 3,
      row = el("div", undefined, "setup-step" + (optional ? " optional" : ""));
    const number = el(
      "span",
      completed[index] ? "✓" : String(index + 1),
      "step-number" + (completed[index] ? " complete" : ""),
    );
    number.setAttribute("aria-hidden", "true");
    const content = el("div"),
      button = el("button", title + (optional ? " · optional" : ""));
    button.type = "button";
    button.onclick = () => goSetup(index);
    if (completed[index]) button.setAttribute("aria-label", title + " · ready");
    content.append(button, el("p", description, "help"));
    row.append(number, content);
    list.append(row);
  });
  const f = $("#provider-form");
  if (!editing("#provider-form"))
    for (const input of f.elements) {
      if (input.name && input.name !== "key")
        input.value = state.settings[input.name];
    }
  updateProviderFields();
  $("#provider-state").textContent = checks.provider.message;
  $("#provider-instructions").textContent =
    state.settings.provider === "claude-cli"
      ? "claude auth login"
      : state.settings.provider === "codex-cli"
        ? "codex login"
        : "Use your vendor’s console to create a key and select an accessible model ID.";
  $("#finish-paused").disabled = state.missing_setup.length > 0;
  $("#finish-start").disabled = state.missing_setup.length > 0;
}
function goSetup(index) {
  setupStep = index;
  const [title, route, description] = setupSteps[index];
  $("#guided-setup").hidden = false;
  $("#guided-progress").value = index + 1;
  $("#guided-progress-text").textContent =
    `${index + 1} / ${setupSteps.length}`;
  $("#guided-label").textContent =
    `Step ${index + 1} of ${setupSteps.length} · ${title}. ${description}`;
  $("#setup-back").disabled = index === 0;
  $("#setup-next").hidden = index === setupSteps.length - 1;
  show(route);
  $("#guided-setup").scrollIntoView({ block: "start" });
}
$("#begin-setup").onclick = () => goSetup(0);
$("#setup-back").onclick = () => goSetup(Math.max(0, setupStep - 1));
$("#setup-next").onclick = () => {
  if (setupStep === 0 && !state.documents.some((d) => d.kind === "resume"))
    return note("Import a resume before continuing.", true);
  if (setupStep === 1 && state.missing_setup.length)
    return note(
      "Confirm the required facts before continuing: " +
        state.missing_setup.join(", "),
      true,
    );
  goSetup(Math.min(setupSteps.length - 1, setupStep + 1));
};
$("#setup-exit").onclick = () => {
  $("#guided-setup").hidden = true;
  setupStep = -1;
  show("today");
};
$("#provider-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.target;
  const provider = form.elements.provider.value;
  try {
    if (provider.endsWith("-api") && !form.elements.provider_model.value.trim())
      throw new Error("Enter an exact model ID for API mode.");
    if (form.elements.key.value) {
      await api("/api/provider-key", {
        provider,
        key: form.elements.key.value,
      });
      form.elements.key.value = "";
    }
    await api("/api/settings", {
      provider,
      provider_model: form.elements.provider_model.value.trim(),
      deployment: form.elements.deployment.value,
    });
    saved(form);
    document.activeElement.blur();
    await refresh();
    note("Connection saved. Check login before starting.");
  } catch (error) {
    note(error.message, true);
  }
};
$("#check-provider").onclick = async (event) => {
  event.target.disabled = true;
  try {
    const result = await api("/api/provider-check", {});
    $("#provider-state").textContent = result.provider.message;
    note(result.provider.message, !result.provider.ready);
  } catch (error) {
    note(error.message, true);
  } finally {
    event.target.disabled = false;
  }
};
$("#remove-provider-key").onclick = async () => {
  try {
    await api("/api/remove-provider-key", {});
    await refresh();
    note("Saved API key removed.");
  } catch (error) {
    note(error.message, true);
  }
};
async function finishSetup(start) {
  try {
    const result = await api("/api/complete-setup", { start });
    $("#guided-setup").hidden = true;
    setupStep = -1;
    await refresh();
    show("today");
    note(result.message);
  } catch (error) {
    note(error.message, true);
  }
}
$("#finish-paused").onclick = () => finishSetup(false);
$("#finish-start").onclick = () => finishSetup(true);

$("#context-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api(
      "/api/context-text",
      Object.fromEntries(new FormData(event.target)),
    );
    event.target.reset();
    await refresh();
    note("Approved context saved.");
  } catch (error) {
    note(error.message, true);
  }
};

function organizePreferences() {
  const grid = $("#settings-form > .form-grid");
  const sections = [
    [
      "Where and what you’re looking for",
      "Choose the roles and places that fit your next step.",
      [
        "roles",
        "seniority",
        "locations",
        "summer_2027_locations",
        "school_locations",
        "min_annual_usd",
        "min_hourly_usd",
        "max_years_required",
        "min_fit_score",
      ],
    ],
    [
      "Companies and boundaries",
      "Keep your search focused and avoid applications you don’t want.",
      [
        "skip_companies",
        "interview_companies",
        "prior_employers",
        "max_per_company",
        "company_cooldown_days",
      ],
    ],
    [
      "Your pace",
      "Decide how often your desk works and how many applications it can submit. Targets are goals; ceilings are firm limits.",
      [
        "schedule_hours",
        "timezone",
        "target_per_cycle",
        "max_per_cycle",
        "target_per_day",
        "max_per_day",
      ],
    ],
    [
      "Model usage limits",
      "Limit the number of requests made to your chosen model. These counts include failed requests and writing reviews.",
      [
        "max_attempts_per_cycle",
        "max_model_requests_per_cycle",
        "max_model_requests_per_day",
        "max_output_tokens",
      ],
    ],
    [
      "Advanced browser settings",
      "Change these only if you need a particular browser or already use signed-in employer portals.",
      ["browser_channel", "signed_in_portals", "company_aliases"],
    ],
  ];
  for (const [title, description, keys] of sections) {
    const group = el("fieldset", undefined, "settings-group"),
      fields = el("div", undefined, "form-grid");
    group.append(
      el("legend", title),
      el("p", description, "help settings-description"),
    );
    for (const key of keys) {
      const input = grid.querySelector(`[name="${key}"]`);
      if (input) fields.append(input.closest("label"));
    }
    group.append(fields);
    grid.before(group);
  }
  grid.remove();
}
organizePreferences();

// Prevent duplicate requests while a form or immediate worker action is pending.
document.addEventListener(
  "submit",
  (event) => {
    const form = event.target;
    if (!form.onsubmit) return;
    if (form.dataset.saving === "true") {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    const handler = form.onsubmit;
    form.onsubmit = null;
    event.preventDefault();
    form.dataset.saving = "true";
    const buttons = [
      ...form.querySelectorAll('button[type="submit"],button:not([type])'),
    ];
    const previous = buttons.map((button) => button.disabled);
    buttons.forEach((button) => (button.disabled = true));
    Promise.resolve(handler.call(form, event))
      .catch((error) => note(error.message, true))
      .finally(() => {
        buttons.forEach((button, index) => (button.disabled = previous[index]));
        delete form.dataset.saving;
        form.onsubmit = handler;
      });
  },
  true,
);
for (const id of [
  "pause",
  "run",
  "complete-setup",
  "finish-paused",
  "finish-start",
]) {
  const button = $("#" + id),
    handler = button.onclick;
  button.onclick = async (event) => {
    if (button.dataset.busy === "true") return;
    button.dataset.busy = "true";
    button.disabled = true;
    try {
      await handler.call(button, event);
    } finally {
      delete button.dataset.busy;
      if (state) render();
    }
  };
}

$("#export-ledger").onclick = async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const response = await fetch("/api/export.csv", {
      headers: { "X-Hireme-Token": token },
    });
    if (!response.ok)
      throw new Error(
        "Could not export the ledger. Reconnect to your dashboard and try again.",
      );
    const url = URL.createObjectURL(await response.blob()),
      anchor = el("a");
    anchor.href = url;
    anchor.download = "application-ledger.csv";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    note("Your complete application ledger was exported.");
  } catch (error) {
    note(error.message, true);
  } finally {
    button.disabled = false;
  }
};

// Make an unsaved draft visible without placing personal text in browser storage.
document.addEventListener("input", (event) => {
  const form = event.target.form;
  if (form && form.id) {
    const indicator = document.querySelector(`[data-draft-for="${form.id}"]`);
    if (indicator) indicator.textContent = "Unsaved changes";
  }
});
