(() => {
  "use strict";

  const main = document.querySelector("#main");
  const $ = (selector) => main.querySelector(selector);
  const assetTypes = [
    ["teachers", "Teachers"],
    ["subjects", "Subjects"],
    ["classes", "Classes"],
    ["classrooms", "Classrooms"],
    ["labs", "Lab Rooms"],
  ];
  let state;
  let page = "dashboard";
  let category = "teachers";
  let lightMode = false;

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const card = (html, className = "") => `<div class="card ${className}">${html}</div>`;
  const heading = (title) => `<div class="page-head">${esc(title)}</div>`;
  const allTimetable = () => Object.entries(state.generated_timetable).flatMap(
    ([day, classes]) => Object.entries(classes).flatMap(
      ([className, periods]) => Object.entries(periods).map(([period, item]) => ({
        day, className, period: Number(period), ...item,
      })),
    ),
  );

  async function api(path, options = {}) {
    const response = await fetch(path, {
      cache: "no-store",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error(`Server returned an invalid response (${response.status}).`);
    }
    if (!response.ok) {
      const error = new Error(result.error || `Request failed (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    return result;
  }

  async function refresh(next = page) {
    state = await api("/api/state");
    document.querySelector(".app").classList.remove("signed-out");
    document.querySelector("#logout-button").hidden = false;
    render(next);
  }

  function showLogin(message = "") {
    document.querySelector(".app").classList.add("signed-out");
    document.querySelector("#logout-button").hidden = true;
    main.innerHTML = `<section class="login-page">
      <div class="card login-card">
        <div class="login-mark" aria-hidden="true">▦</div>
        <h1>Scheduler Pro</h1>
        <p class="subtle">Sign in to the hosted timetable demo.</p>
        <form id="login-form">
          <label class="field-label" for="login-username">Username</label>
          <input class="input" id="login-username" name="username" maxlength="120" autocomplete="username" required>
          <label class="field-label" for="login-password">Password</label>
          <input class="input" id="login-password" name="password" type="password" maxlength="256" autocomplete="current-password" required>
          <button class="btn login-submit" type="submit">Sign in</button>
          <p class="tiny login-status" id="login-status" role="status">${esc(message)}</p>
        </form>
      </div>
    </section>`;
    document.querySelector("#login-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const submit = form.querySelector('[type="submit"]');
      const status = document.querySelector("#login-status");
      submit.disabled = true;
      status.textContent = "Signing in…";
      try {
        await api("/api/login", {
          method: "POST",
          body: JSON.stringify(Object.fromEntries(new FormData(form))),
        });
        await refresh("dashboard");
      } catch (error) {
        status.textContent = error.message;
      } finally {
        if (submit.isConnected) submit.disabled = false;
      }
    });
    document.querySelector("#login-username").focus();
  }

  async function submitForm(form, path, onSuccess) {
    const status = form.querySelector("[data-status]");
    const submit = form.querySelector('[type="submit"]');
    status.textContent = "Saving…";
    submit.disabled = true;
    try {
      const values = Object.fromEntries(new FormData(form));
      if (form.dataset.array === "subjects") {
        values.subjects = form.querySelectorAll('input[name="subjects"]:checked')
          ? [...form.querySelectorAll('input[name="subjects"]:checked')].map((input) => input.value)
          : [];
      }
      const result = await api(path, {
        method: "POST",
        body: JSON.stringify(values),
      });
      if (onSuccess) onSuccess(form, result);
      await refresh(page);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      if (submit.isConnected) submit.disabled = false;
    }
  }

  function dashboard() {
    const teachers = state.teachers.length;
    const links = Object.values(state.teacher_expertise).reduce((sum, subjects) => sum + subjects.length, 0);
    const days = state.days.length;
    const metrics = [
      ["Teachers", teachers, "#6366F1"],
      ["Subjects", state.subjects.length, "#06B6D4"],
      ["Classes", state.classes.length, "#22C55E"],
      ["Rooms", state.classrooms.length + state.labs.length, "#F59E0B"],
      ["TT Days", days, "#A78BFA"],
    ];
    const hour = new Date().getHours();
    const greet = hour < 12 ? "Good Morning" : hour < 17 ? "Good Afternoon" : "Good Evening";
    const date = new Intl.DateTimeFormat("en-GB", {
      weekday: "long", day: "2-digit", month: "long", year: "numeric",
    }).format(new Date());
    return `<section class="page">
      <div class="dash-head"><h1>${greet}, ${esc(state.user)}</h1><span class="date">${date}</span></div>
      <div class="kpis">${metrics.map(([label, value, color]) => card(
        `<strong style="color:${color}">${value}</strong><span>${label}</span>`, "kpi",
      )).join("")}</div>
      <h2 class="section-title">Quick Actions</h2>
      <div class="actions">
        <button class="action purple" data-go="generate">Generate Timetable</button>
        <button class="action cyan" data-go="manage">Manage Assets</button>
        <button class="action green" data-go="analytics">View Analytics</button>
        <a class="action orange download-link" href="/api/backup">Download Backup</a>
      </div>
      ${card(`<h2>System Overview</h2>
        <div class="overview-line">Teacher-Subject links : ${links}</div>
        <div class="overview-line">Timetable days loaded  : ${days}</div>
        <div class="overview-line">Data source            : Private demo database</div>
        <div class="overview-line">AI assistant           : ${state.ai_configured ? `Configured (${esc(state.ai_provider)})` : "Offline helper"}</div>
        <div class="overview-line">Messaging              : Disabled in browser preview</div>`, "overview")}
    </section>`;
  }

  function expertiseForm() {
    const teacher = state.teachers[0];
    if (!teacher) return `<p class="subtle">Add a teacher before setting subject expertise.</p>`;
    const selected = state.teacher_expertise[teacher.name] || [];
    return `<form id="expertise-form" data-array="subjects">
      <h2>Set Teacher Expertise</h2>
      <label class="field-label" for="expert-teacher">Teacher</label>
      <select class="select" name="teacher" id="expert-teacher">
        ${state.teachers.map((item) => `<option value="${esc(item.name)}">${esc(item.name)}</option>`).join("")}
      </select>
      <div class="expertise">${state.subjects.map((subject) => `<label class="field-label">
        <input type="checkbox" name="subjects" value="${esc(subject)}" ${selected.includes(subject) ? "checked" : ""}> ${esc(subject)}
      </label>`).join("")}</div>
      <button class="btn green" type="submit">Save Expertise</button>
      <p class="tiny" data-status role="status"></p>
    </form>`;
  }

  function manage() {
    const names = category === "teachers"
      ? state.teachers.map((teacher) => teacher.name)
      : state[category];
    const rows = names.map((name) => {
      const teacher = state.teachers.find((item) => item.name === name);
      const subjects = teacher ? (state.teacher_expertise[name] || []) : [];
      const details = teacher
        ? `<small>${subjects.length} subject${subjects.length === 1 ? "" : "s"}: ${esc(subjects.join(", ") || "not set")}</small>`
        : "";
      return `<div class="row-card"><strong>${esc(name)}${details}</strong>
        <button class="btn red" type="button" data-delete="${esc(name)}">Delete</button></div>`;
    }).join("") || `<p class="subtle">No ${esc(category.replace("_", " "))} yet.</p>`;
    const selectedType = assetTypes.find(([key]) => key === category);
    return `${heading("Manage Assets")}<div class="page-content">
      <div class="subtabs">${assetTypes.map(([key, label]) => `<button class="tab ${key === category ? "active" : ""}" data-cat="${key}">${label}</button>`).join("")}</div>
      <div class="split">
        ${card(`<h2>Add ${esc(selectedType[1])}</h2>
          <form id="asset-form"><input class="input" name="name" maxlength="120" required placeholder="Enter name..." aria-label="New ${esc(selectedType[1])} name">
          <button class="btn green" type="submit">Add Item</button><p class="tiny" data-status role="status"></p></form>
          ${category === "teachers" ? expertiseForm() : ""}`, "panel")}
        ${card(`<h2>All ${esc(selectedType[1])}</h2>
          <input class="input" id="asset-search" placeholder="Search this list..." aria-label="Search assets">
          <div id="asset-list">${rows}</div>`, "panel")}
      </div></div>`;
  }

  function scheduleRows(schedule = state.generated_timetable) {
    return Object.entries(schedule).flatMap(([day, classes]) => Object.entries(classes).flatMap(
      ([className, periods]) => Object.entries(periods).map(([period, item]) => ({
        day, className, period: Number(period), ...item,
      })),
    ));
  }

  function generate() {
    const days = state.days.length ? state.days : ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    const timetable = scheduleRows();
    const groups = Object.entries(state.generated_timetable).map(([day, classes]) =>
      `<div class="day-block"><div class="day-title">${esc(day)}</div>${Object.entries(classes).map(([className, periods]) =>
        card(`<h3>Class: ${esc(className)}</h3>${Object.entries(periods).map(([period, item]) =>
          `<div class="period-line">P${esc(period)}: ${esc(item.subject)} — ${esc(item.teacher)} @ ${esc(item.room)}</div>`,
        ).join("")}`, "class-card"),
      ).join("")}</div>`,
    ).join("");
    return `${heading("Generate Timetable")}<div class="page-content">
      ${card(`<form id="generate-form">
        <div class="config-row"><label class="field-label">Periods/day
          <input class="input" type="number" name="periods_per_day" min="1" max="12" value="8" required></label>
          <label class="field-label">Days (comma separated)
          <input class="input" name="days" value="${esc(days.join(", "))}" required></label></div>
        <button class="btn" type="submit">Generate Now</button><p class="tiny" data-status role="status"></p>
      </form>`, "panel")}
      <p class="subtle">Loaded ${timetable.length} timetable entries from the app database.</p>
      ${groups ? card(`<h2>Current schedule</h2>${groups}`, "panel") : card(`<div class="empty">No timetable has been generated yet.</div>`, "panel")}
    </div>`;
  }

  function history() {
    const rows = state.history.map((entry) => `<tr><td>${esc(entry.class_name)}</td><td>${esc(entry.day)}</td>
      <td>${esc(entry.period)}</td><td>${esc(entry.subject)}</td><td>${esc(entry.teacher)}</td>
      <td>${esc(entry.room)}</td><td>${esc(entry.created_at)}</td></tr>`).join("");
    return `${heading("View History")}<div class="page-content">${card(`<div class="table-wrap"><table>
      <thead><tr><th>CLASS</th><th>DAY</th><th>PERIOD</th><th>SUBJECT</th><th>TEACHER</th><th>ROOM</th><th>UPDATED</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="7">No timetable entries saved yet.</td></tr>`}</tbody></table></div>`, "panel")}</div>`;
  }

  function analytics() {
    const timetable = allTimetable();
    const counts = Object.fromEntries(state.teachers.map((teacher) => [
      teacher.name, timetable.filter((entry) => entry.teacher === teacher.name).length,
    ]));
    const max = Math.max(1, ...Object.values(counts));
    const rows = state.teachers.map((teacher) => {
      const total = counts[teacher.name] || 0;
      const risk = Math.min(Math.round(((total / 40 * 0.4) + (Math.min(total / 2, 6) / 4 * 0.6)) * 100), 100);
      const color = risk > 70 ? "#ef4444" : risk > 40 ? "#f59e0b" : "#22c55e";
      return card(`<strong>${esc(teacher.name)}</strong>
        <span class="bar"><i style="width:${Math.max(4, total / max * 100)}%;background:${color}"></i></span>
        <span>${total} periods</span><b style="color:${color}">Risk: ${risk}%</b>`, "bar-row");
    }).join("");
    return `${heading("Workload Analytics")}<div class="page-content">${rows || `<p class="subtle">No teachers available.</p>`}</div>`;
  }

  function recycle() {
    const categories = Object.entries(state.deleted).flatMap(([key, names]) =>
      names.map((name) => `<div class="row-card"><strong>${esc(name)}<small>${esc(key)}</small></strong>
        <button class="btn green" type="button" data-restore="${key}" data-name="${esc(name)}">Restore</button></div>`),
    ).join("");
    return `${heading("Recycle Bin")}<div class="page-content">${categories || `<div class="empty">Recycle Bin is empty.</div>`}</div>`;
  }

  function teacherDetails() {
    const rows = state.teachers.map((teacher) => `<div class="row-card teacher-edit" data-teacher="${esc(teacher.name)}">
      <strong>${esc(teacher.name)}<small>Email: ${esc(teacher.email || "N/A")} | Phone: ${esc(teacher.phone || "N/A")}</small></strong>
      <button class="btn" type="button" data-edit="${esc(teacher.name)}">Edit</button></div>`).join("");
    return `${heading("Teacher Details")}<div class="page-content split">
      ${card(`<h2>Add/Update</h2><form id="teacher-form">
        <label class="field-label" for="teacher-name">Name</label><input class="input" name="name" id="teacher-name" maxlength="120" required>
        <label class="field-label" for="teacher-email">Email</label><input class="input" type="email" name="email" id="teacher-email" maxlength="254">
        <label class="field-label" for="teacher-phone">Phone</label><input class="input" name="phone" id="teacher-phone" maxlength="40">
        <button class="btn" type="submit">Save</button><p class="tiny" data-status role="status"></p>
      </form>`, "panel")}
      ${card(`<h2>All Teachers</h2>${rows || `<p class="subtle">No teachers yet.</p>`}`, "panel")}
    </div>`;
  }

  function feedback() {
    const rows = state.feedback.map((item) => `<div class="row-card"><strong>${esc(item.teacher || "General feedback")}
      <small>${esc(item.sentiment)} · ${esc(item.issue_type)} · ${esc(item.created_at)}</small><small>${esc(item.message)}</small></strong></div>`).join("");
    return `${heading("Teacher Feedback")}<div class="page-content split">
      ${card(`<h2>Add Feedback</h2><form id="feedback-form">
        <label class="field-label" for="feedback-teacher">Teacher (optional)</label>
        <select class="select" name="teacher" id="feedback-teacher"><option value="">General</option>
          ${state.teachers.map((teacher) => `<option value="${esc(teacher.name)}">${esc(teacher.name)}</option>`).join("")}</select>
        <label class="field-label" for="feedback-sentiment">Sentiment</label>
        <select class="select" name="sentiment" id="feedback-sentiment"><option>neutral</option><option>positive</option><option>negative</option></select>
        <label class="field-label" for="feedback-issue">Type</label>
        <input class="input" name="issue_type" id="feedback-issue" value="general" maxlength="80">
        <label class="field-label" for="feedback-message">Message</label>
        <textarea class="textarea" name="message" id="feedback-message" maxlength="4000" required></textarea>
        <button class="btn" type="submit">Save Feedback</button><p class="tiny" data-status role="status"></p>
      </form>`, "panel")}
      ${card(`<h2>Saved Feedback</h2>${rows || `<p class="subtle">No feedback saved yet.</p>`}`, "panel")}
    </div>`;
  }

  function whatsapp() {
    return `${heading("WhatsApp Hub")}<div class="page-content">
      ${card(`<h2>External messaging is disabled</h2>
        <p class="notice">WhatsApp and email can send real, billable messages. This local browser interface never loads, stores, or sends credentials.</p>
        <p class="subtle">Use the desktop app's messaging screen only when you intend to contact real recipients.</p>`, "panel")}
    </div>`;
  }

  function settings() {
    const voiceAvailable = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
    return `${heading("User Settings")}<div class="page-content">
      ${card(`<h2>Hosted demo account</h2>
        <p class="subtle">This browser session is protected by a server-side sign-in. The hosted demo uses its own fictional sample data and does not access the desktop database.</p>
        <p class="subtle">AI provider: ${state.ai_configured ? `${esc(state.ai_provider)} (API key configured on the server)` : "offline timetable helper"}</p>
        <p class="subtle">Speech input: ${voiceAvailable ? "supported by this browser; microphone permission is required" : "not supported by this browser"}</p>
        <p class="notice">Use only fictional demo information here. This demo shares one dataset between signed-in visitors; do not enter real student or staff data.</p>`, "panel")}
    </div>`;
  }

  function assistant() {
    const messages = (state.ai_history || []).map((item) =>
      `<div class="bubble ${item.role === "user" ? "user" : ""}">${esc(item.content)}</div>`,
    ).join("");
    const speechSupported = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
    const status = state.ai_configured
      ? `Configured provider · ${esc(state.ai_provider)} · key stays on server`
      : "Offline timetable helper";
    return `<div class="ai-window"><h1 class="ai-title"><span class="assistant-mark" aria-hidden="true">🤖</span> AI Assistant</h1>
      <div class="ai-status"><span>Microphone · ${speechSupported ? "browser support detected" : "not supported by this browser"}</span><span>${status}</span></div>
      <div class="chat" id="chat">${messages || `<div class="bubble">Ask about teachers, subjects, classes, or a schedule. Try “list teachers” or “show 9-A timetable Monday”. You can also ask to generate a timetable.</div>`}</div>
      <form class="chat-inputs" id="assistant-form">
        <input class="input" id="assistant-input" name="prompt" maxlength="2000" placeholder="Ask about teachers, classes, or timetable…" autocomplete="off" required aria-label="Ask the timetable assistant">
        <button class="btn" type="button" id="mic-button" ${speechSupported ? "" : "disabled"} aria-label="Start speech input">🎤</button>
        <button class="btn" type="submit">Send</button>
      </form><p class="tiny" id="assistant-status" role="status"></p>
    </div>`;
  }

  const pages = {
    dashboard, manage, generate, history, analytics, recycle,
    teachers: teacherDetails, feedback, whatsapp, settings, assistant,
  };

  function render(next = page) {
    page = pages[next] ? next : "dashboard";
    main.innerHTML = pages[page]();
    document.querySelectorAll(".nav").forEach((button) =>
      button.classList.toggle("active", button.dataset.page === page),
    );
    bindPageEvents();
  }

  function bindPageEvents() {
    main.querySelectorAll("[data-go]").forEach((button) =>
      button.addEventListener("click", () => render(button.dataset.go)),
    );
    if (page === "manage") {
      main.querySelectorAll("[data-cat]").forEach((button) =>
        button.addEventListener("click", () => {
          category = button.dataset.cat;
          render("manage");
        }),
      );
      $("#asset-search").addEventListener("input", (event) => {
        const query = event.target.value.toLocaleLowerCase();
        document.querySelectorAll("#asset-list .row-card").forEach((row) => {
          row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
        });
      });
      $("#asset-form").addEventListener("submit", (event) => {
        event.preventDefault();
        submitForm(event.currentTarget, "/api/assets", (form) => form.reset());
      });
      main.querySelectorAll("[data-delete]").forEach((button) => {
        button.addEventListener("click", async () => {
          if (!confirm(`Move "${button.dataset.delete}" to the Recycle Bin?`)) return;
          try {
            await api(`/api/assets/${encodeURIComponent(category)}/${encodeURIComponent(button.dataset.delete)}`, {
              method: "DELETE",
              headers: { "X-Asset-Name": button.dataset.delete },
            });
            await refresh();
          } catch (error) {
            alert(error.message);
          }
        });
      });
      if ($("#expertise-form")) {
        const form = $("#expertise-form");
        $("#expert-teacher").addEventListener("change", () => {
          const selected = state.teacher_expertise[$("#expert-teacher").value] || [];
          form.querySelectorAll('input[name="subjects"]').forEach((input) => {
            input.checked = selected.includes(input.value);
          });
        });
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          submitForm(form, "/api/expertise");
        });
      }
    }
    if (page === "generate") {
      $("#generate-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const status = form.querySelector("[data-status]");
        const submit = form.querySelector('[type="submit"]');
        const values = Object.fromEntries(new FormData(form));
        values.periods_per_day = Number(values.periods_per_day);
        values.days = values.days.split(",").map((day) => day.trim()).filter(Boolean);
        submit.disabled = true;
        status.textContent = "Generating and saving schedule…";
        try {
          const result = await api("/api/timetable/generate", {
            method: "POST", body: JSON.stringify(values),
          });
          await refresh();
          if ($("#generate-form")) $("#generate-form [data-status]").textContent = `Saved ${result.entries} entries for ${result.days} days.`;
        } catch (error) {
          status.textContent = error.message;
        } finally {
          if (submit.isConnected) submit.disabled = false;
        }
      });
    }
    if (page === "recycle") {
      main.querySelectorAll("[data-restore]").forEach((button) => {
        button.addEventListener("click", async () => {
          try {
            await api(`/api/restore/${encodeURIComponent(button.dataset.restore)}/${encodeURIComponent(button.dataset.name)}`, {
              method: "PATCH", headers: { "X-Asset-Name": button.dataset.name },
            });
            await refresh();
          } catch (error) {
            alert(error.message);
          }
        });
      });
    }
    if (page === "teachers") {
      $("#teacher-form").addEventListener("submit", (event) => {
        event.preventDefault();
        submitForm(event.currentTarget, "/api/teacher-details", (form) => form.reset());
      });
      main.querySelectorAll("[data-edit]").forEach((button) => {
        button.addEventListener("click", () => {
          const teacher = state.teachers.find((item) => item.name === button.dataset.edit);
          $("#teacher-name").value = teacher.name;
          $("#teacher-email").value = teacher.email || "";
          $("#teacher-phone").value = teacher.phone || "";
          $("#teacher-name").focus();
        });
      });
    }
    if (page === "feedback") {
      $("#feedback-form").addEventListener("submit", (event) => {
        event.preventDefault();
        submitForm(event.currentTarget, "/api/feedback", (form) => form.reset());
      });
    }
    if (page === "assistant") {
      $("#assistant-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const prompt = $("#assistant-input").value.trim();
        if (!prompt) return;
        const chat = $("#chat");
        const userBubble = document.createElement("div");
        userBubble.className = "bubble user";
        userBubble.textContent = prompt;
        chat.append(userBubble);
        $("#assistant-status").textContent = "Working…";
        const send = form.querySelector('[type="submit"]');
        send.disabled = true;
        try {
          const result = await api("/api/assistant", {
            method: "POST", body: JSON.stringify({ prompt }),
          });
          await refresh("assistant");
          $("#assistant-status").textContent = result.ai_configured
            ? `Answered with ${result.ai_provider}.`
            : "Answered with the offline helper.";
        } catch (error) {
          const reply = document.createElement("div");
          reply.className = "bubble";
          reply.textContent = error.message;
          chat.append(reply);
          $("#assistant-status").textContent = "The request failed.";
        } finally {
          if (send.isConnected) send.disabled = false;
        }
      });
      const micButton = $("#mic-button");
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SpeechRecognition) {
        micButton.addEventListener("click", () => {
          const recognition = new SpeechRecognition();
          recognition.lang = navigator.language || "en-US";
          recognition.interimResults = false;
          recognition.maxAlternatives = 1;
          $("#assistant-status").textContent = "Listening… allow microphone access if asked.";
          recognition.onresult = (event) => {
            $("#assistant-input").value = event.results[0][0].transcript;
            $("#assistant-input").focus();
            $("#assistant-status").textContent = "Speech recognized. Review it, then press Send.";
          };
          recognition.onerror = (event) => {
            $("#assistant-status").textContent = `Microphone input failed: ${event.error}.`;
          };
          recognition.onend = () => {
            if ($("#assistant-status").textContent === "Listening… allow microphone access if asked.") {
              $("#assistant-status").textContent = "No speech was recognized.";
            }
          };
          recognition.start();
        });
      }
    }
  }

  document.querySelectorAll(".nav").forEach((button) =>
    button.addEventListener("click", () => render(button.dataset.page)),
  );
  document.querySelector("#theme-toggle").addEventListener("click", () => {
    lightMode = !lightMode;
    document.body.classList.toggle("light", lightMode);
    document.querySelector("#theme-toggle").innerHTML = lightMode
      ? '<span class="toggle-track"><i></i></span> Light Mode'
      : '<span class="toggle-track"><i></i></span> Dark Mode';
  });

  document.querySelector("#logout-button").addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST", body: "{}" });
      showLogin("You have been signed out.");
    } catch (error) {
      main.innerHTML = `<div class="page-head">Could not sign out</div><p class="notice">${esc(error.message)}</p>`;
    }
  });

  api("/api/session").then(() => refresh()).catch((error) => {
    if (error.status === 401) {
      showLogin();
      return;
    }
    main.innerHTML = `<div class="page-head">Web app could not load</div><p class="notice">${esc(error.message)}</p>
      <p class="subtle">Please reload this page or contact the demo administrator.</p>`;
  });
})();
