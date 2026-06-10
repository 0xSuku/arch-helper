const $ = (sel) => document.querySelector(sel);

function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  el.classList.toggle("error", isError);
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 3500);
}

function dailyParams() {
  return {
    force: $("#opt-force").checked,
    recover_emulator: $("#opt-recover").checked,
    recover_ldplayer: $("#opt-recover").checked,
  };
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function runJob(job, extraParams = {}) {
  try {
    const params = { ...dailyParams(), ...extraParams };
    await api("/api/run", {
      method: "POST",
      body: JSON.stringify({ job, params }),
    });
    toast(`Iniciado: ${job}`);
    refreshStatus();
  } catch (e) {
    toast(e.message, true);
  }
}

function setPill(el, ok, label) {
  el.textContent = label;
  el.classList.remove("ok", "bad", "busy");
  if (ok === true) el.classList.add("ok");
  else if (ok === false) el.classList.add("bad");
  else if (ok === "busy") el.classList.add("busy");
}

async function refreshStatus() {
  try {
    const st = await api("/api/status");
    const emu = st.emulator || st.ldplayer;
    setPill($("#pill-ld"), emu.running, emu.running ? "Emulador ON" : "Emulador OFF");
    setPill($("#pill-adb"), st.adb.connected, st.adb.connected ? "ADB OK" : "ADB OFF");
    setPill($("#pill-screen"), st.adb.connected, st.screen || "?");
    if (st.job.running) {
      setPill($("#pill-job"), "busy", `Corriendo: ${st.job.label}`);
    } else if (st.job.last_error) {
      setPill($("#pill-job"), false, "Error (ver log)");
    } else {
      setPill($("#pill-job"), true, "Idle");
    }

    const busy = st.job.running;
    document.querySelectorAll("[data-job]").forEach((btn) => {
      btn.disabled = busy;
    });

    if (st.stop_requested) {
      $("#btn-stop").disabled = true;
    } else {
      $("#btn-stop").disabled = false;
    }
  } catch {
    setPill($("#pill-ld"), false, "Panel error");
  }
}

async function refreshDailyStatus() {
  try {
    const data = await api("/api/daily-status");
    $("#daily-status").textContent = data.lines.join("\n") || "(sin datos)";
  } catch {
    $("#daily-status").textContent = "(no se pudo cargar)";
  }
}

async function refreshLog() {
  try {
    const data = await api("/api/logs?lines=120");
    const el = $("#log-view");
    el.textContent = data.lines.join("\n") || "(log vacío)";
    el.scrollTop = el.scrollHeight;
  } catch {
    $("#log-view").textContent = "(no se pudo leer logs/bot.log)";
  }
}

async function loadClaims() {
  const data = await api("/api/claims");
  const root = $("#task-groups");
  root.innerHTML = "";

  for (const group of data.groups || []) {
    const section = document.createElement("section");
    section.className = `tier-block tier-${group.id}`;

    const head = document.createElement("div");
    head.className = "tier-head";
    const title = document.createElement("h3");
    title.textContent = group.label;
    head.appendChild(title);
    if (group.hint) {
      const hint = document.createElement("p");
      hint.className = "tier-hint";
      hint.textContent = group.hint;
      head.appendChild(hint);
    }
    section.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "claims-grid";

    for (const item of group.items || []) {
      if (item.needs_games) {
        const row = document.createElement("div");
        row.className = "inline play-row";
        const input = document.createElement("input");
        input.type = "number";
        input.id = "play-games";
        input.value = "5";
        input.min = "1";
        input.max = "99";
        const btn = document.createElement("button");
        btn.className = "btn" + (group.id === "trusted" ? " btn-primary" : "");
        btn.textContent = item.label;
        btn.dataset.job = item.job;
        btn.addEventListener("click", () => {
          const n = Number($("#play-games").value) || 5;
          runJob(item.job, { games: n });
        });
        row.appendChild(input);
        row.appendChild(btn);
        grid.appendChild(row);
        continue;
      }

      const btn = document.createElement("button");
      let cls = "btn claim-btn";
      if (group.id === "trusted") cls += " btn-primary";
      else if (group.id === "paused") cls += " btn-muted";
      if (item.main_loop) cls += " main-loop";
      btn.className = cls;
      btn.textContent = item.label;
      btn.dataset.job = item.job;
      btn.title = item.id;
      btn.addEventListener("click", () => runJob(item.job));
      grid.appendChild(btn);
    }

    section.appendChild(grid);
    root.appendChild(section);
  }
}

let skillCategories = [];
let skillGroups = [];
let categoryLabels = {};
let groupLabels = {};

function buildLabeledSelect(values, labels, selected, { allowEmpty = false, emptyLabel = "—" } = {}) {
  const sel = document.createElement("select");
  sel.className = "meta-select";
  if (allowEmpty) {
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = emptyLabel;
    if (!selected) empty.selected = true;
    sel.appendChild(empty);
  }
  for (const value of values) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = labels[value] || value;
    if (value === selected) opt.selected = true;
    sel.appendChild(opt);
  }
  return sel;
}

async function saveSkillMeta(skill) {
  const row = document.querySelector(`[data-skill-id="${CSS.escape(skill.id)}"]`);
  if (!row) return;
  const name = row.querySelector(".name-input").value.trim();
  const category = row.querySelector(".category-select").value;
  const group = row.querySelector(".group-select").value;
  const score = Number(row.querySelector(".score-input").value);
  const data = await api("/api/skills/update", {
    method: "POST",
    body: JSON.stringify({
      skill_id: skill.id,
      name,
      category,
      group,
      score,
      catalog_fp: skill.catalog_fp,
    }),
  });
  toast(`${data.id} [${data.category}${data.group ? ` / ${data.group}` : ""}] -> ${score}`);
  await loadSkills();
}

function renderPendingSkills(pending) {
  const root = $("#pending-skills");
  root.innerHTML = "";
  if (!pending.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No hay unknowns pendientes para etiquetar.";
    root.appendChild(empty);
    return;
  }

  const title = document.createElement("h3");
  title.textContent = `Unknowns pendientes (${pending.length})`;
  root.appendChild(title);

  const grid = document.createElement("div");
  grid.className = "pending-grid";
  for (const sk of pending) {
    const card = document.createElement("article");
    card.className = "pending-skill-card";
    card.dataset.skillId = sk.id;

    const img = document.createElement("img");
    img.className = "pending-skill-img";
    img.src = sk.image_url;
    img.alt = sk.id;

    const meta = document.createElement("div");
    meta.className = "pending-skill-meta";

    const stats = document.createElement("div");
    stats.className = "pending-skill-stats";
    stats.textContent = `Visto ${sk.seen_count}x · conf ${Number(sk.best_confidence || 0).toFixed(2)} · ${sk.source_context || "play"}`;

    const nameInput = document.createElement("input");
    nameInput.className = "meta-input name-input";
    nameInput.placeholder = "nombre_skill";
    nameInput.value = "";

    const categorySelect = buildLabeledSelect(skillCategories, categoryLabels, "");
    categorySelect.classList.add("category-select");

    const groupSelect = buildLabeledSelect(skillGroups, groupLabels, "", {
      allowEmpty: true,
      emptyLabel: "Sin grupo",
    });
    groupSelect.classList.add("group-select");

    const scoreInput = document.createElement("input");
    scoreInput.className = "score-input";
    scoreInput.type = "number";
    scoreInput.min = "0";
    scoreInput.max = "999";
    scoreInput.value = String(sk.score || 0);

    const btnSave = document.createElement("button");
    btnSave.className = "btn btn-primary btn-xs";
    btnSave.textContent = "Etiquetar";
    btnSave.addEventListener("click", () => saveSkillMeta(sk).catch((e) => toast(e.message, true)));

    meta.append(stats, nameInput, categorySelect, groupSelect, scoreInput, btnSave);
    card.append(img, meta);
    grid.appendChild(card);
  }
  root.appendChild(grid);
}

async function bumpSkillScore(skillId, delta) {
  const data = await api("/api/skills/bump", {
    method: "POST",
    body: JSON.stringify({ skill_id: skillId, delta }),
  });
  toast(`${data.id} -> ${data.score} (${delta >= 0 ? "+" : ""}${delta})`);
  await loadSkills();
}

async function loadSkills() {
  const tbody = $("#skills-body");
  try {
    const data = await api("/api/skills");
    skillCategories = data.categories || [];
    skillGroups = data.groups || [];
    categoryLabels = data.category_labels || {};
    groupLabels = data.group_labels || {};
    renderPendingSkills(data.pending || []);
    if (!data.skills.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="muted-cell">Sin skills en catálogo</td></tr>';
      return;
    }
    tbody.innerHTML = "";
    for (const sk of data.skills) {
      const tr = document.createElement("tr");
      tr.dataset.skillId = sk.id;
      if (String(sk.source).startsWith("manual")) tr.classList.add("manual");

      const nameTd = document.createElement("td");
      const nameInput = document.createElement("input");
      nameInput.className = "meta-input name-input";
      nameInput.value = sk.name;
      nameTd.appendChild(nameInput);

      const catTd = document.createElement("td");
      const catSelect = buildLabeledSelect(skillCategories, categoryLabels, sk.category);
      catSelect.classList.add("category-select");
      catTd.appendChild(catSelect);

      const groupTd = document.createElement("td");
      const groupSelect = buildLabeledSelect(skillGroups, groupLabels, sk.group, {
        allowEmpty: true,
        emptyLabel: "Sin grupo",
      });
      groupSelect.classList.add("group-select");
      groupTd.appendChild(groupSelect);

      const scoreTd = document.createElement("td");
      const scoreInput = document.createElement("input");
      scoreInput.className = "score-input";
      scoreInput.type = "number";
      scoreInput.min = "0";
      scoreInput.max = "999";
      scoreInput.value = String(sk.score);
      scoreTd.appendChild(scoreInput);

      const srcTd = document.createElement("td");
      srcTd.innerHTML = `<span class="source-tag">${sk.source}</span>`;

      const actionsTd = document.createElement("td");
      const actions = document.createElement("div");
      actions.className = "skill-actions";

      const btnSave = document.createElement("button");
      btnSave.className = "btn btn-primary btn-xs";
      btnSave.textContent = "Guardar";
      btnSave.addEventListener("click", () => saveSkillMeta(sk).catch((e) => toast(e.message, true)));

      const btnMinus = document.createElement("button");
      btnMinus.className = "btn btn-xs";
      btnMinus.textContent = "-5";
      btnMinus.addEventListener("click", () => bumpSkillScore(sk.id, -5).catch((e) => toast(e.message, true)));

      const btnPlus = document.createElement("button");
      btnPlus.className = "btn btn-xs";
      btnPlus.textContent = "+5";
      btnPlus.addEventListener("click", () => bumpSkillScore(sk.id, 5).catch((e) => toast(e.message, true)));

      actions.append(btnMinus, btnPlus, btnSave);
      actionsTd.appendChild(actions);

      tr.append(nameTd, catTd, groupTd, scoreTd, srcTd, actionsTd);
      scoreInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") btnSave.click();
      });
      tbody.appendChild(tr);
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted-cell">${e.message}</td></tr>`;
  }
}

document.querySelectorAll("[data-job]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const job = btn.dataset.job;
    if (job === "play") {
      runJob("play", { games: Number($("#play-games").value) || 5 });
    } else {
      runJob(job);
    }
  });
});

$("#btn-stop").addEventListener("click", async () => {
  try {
    await api("/api/stop", { method: "POST", body: "{}" });
    toast("STOP activado");
    refreshStatus();
  } catch (e) {
    toast(e.message, true);
  }
});

$("#btn-clear-stop").addEventListener("click", async () => {
  try {
    await api("/api/clear-stop", { method: "POST", body: "{}" });
    toast("STOP quitado");
    refreshStatus();
  } catch (e) {
    toast(e.message, true);
  }
});

$("#btn-refresh-log").addEventListener("click", refreshLog);
$("#btn-skills-refresh").addEventListener("click", () => loadSkills());

loadClaims().catch(() => toast("No se cargaron claims", true));
loadSkills();
refreshStatus();
refreshDailyStatus();
refreshLog();
setInterval(refreshStatus, 2500);
setInterval(refreshLog, 4000);
setInterval(refreshDailyStatus, 15000);
