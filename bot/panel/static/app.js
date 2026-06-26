const $ = (sel) => document.querySelector(sel);

let catalog = { categories: [], actions: [] };
let chain = [];
let presets = [];
let activeCategory = null;
let uidSeq = 1;

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
    toast(`Started: ${job}`);
    refreshStatus();
    refreshPipelineState();
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

function catalogAction(id) {
  return catalog.actions.find((a) => a.id === id);
}

function newChainItem(catalogId) {
  const action = catalogAction(catalogId);
  if (!action) return null;
  const params = {};
  for (const spec of action.params || []) {
    params[spec.key] = spec.default;
  }
  return {
    uid: `c${uidSeq++}`,
    catalog_id: catalogId,
    enabled: true,
    params,
  };
}

function describeChainItem(item) {
  if (item.raw_step) return item.label || "Custom step";
  const action = catalogAction(item.catalog_id);
  if (!action) return item.catalog_id;
  const parts = [action.label];
  for (const spec of action.params || []) {
    const val = item.params?.[spec.key];
    if (val === undefined || val === "" || val === false) continue;
    if (spec.type === "bool" && val) parts.push(spec.label);
    else if (spec.key === "fights") parts.push(`×${val}`);
    else if (spec.key === "runs") parts.push(`${val} attempts`);
    else if (spec.key === "games") parts.push(`${val} games`);
    else if (spec.key === "forever" || item.params?.forever) parts.push("∞");
    else parts.push(`${spec.label}: ${val}`);
  }
  if (action.template?.forever) parts.push("∞");
  return parts.join(" · ");
}

function updatePreview() {
  const enabled = chain.filter((c) => c.enabled);
  const preview = $("#chain-preview");
  const count = $("#chain-count");
  count.textContent = `(${enabled.length} active)`;
  if (!enabled.length) {
    preview.textContent = "No active steps";
    preview.classList.add("muted");
    return;
  }
  preview.classList.remove("muted");
  preview.textContent = enabled.map((item, i) => {
    const label = describeChainItem(item);
    return `${i + 1}. ${label}`;
  }).join("  →  ");
}

function renderChain() {
  const list = $("#chain-list");
  const empty = $("#chain-empty");
  list.innerHTML = "";

  if (!chain.length) {
    empty.hidden = false;
    updatePreview();
    return;
  }
  empty.hidden = true;

  chain.forEach((item, index) => {
    const li = document.createElement("li");
    li.className = "chain-item" + (item.enabled ? "" : " chain-item-off");

    const head = document.createElement("div");
    head.className = "chain-item-head";

    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = item.enabled;
    check.title = "Enable step";
    check.addEventListener("change", () => {
      item.enabled = check.checked;
      renderChain();
    });

    const title = document.createElement("span");
    title.className = "chain-item-title";
    title.textContent = describeChainItem(item);

    const move = document.createElement("div");
    move.className = "chain-move";
    const btnUp = document.createElement("button");
    btnUp.type = "button";
    btnUp.className = "btn-icon";
    btnUp.textContent = "↑";
    btnUp.disabled = index === 0;
    btnUp.addEventListener("click", () => {
      [chain[index - 1], chain[index]] = [chain[index], chain[index - 1]];
      renderChain();
    });
    const btnDown = document.createElement("button");
    btnDown.type = "button";
    btnDown.className = "btn-icon";
    btnDown.textContent = "↓";
    btnDown.disabled = index === chain.length - 1;
    btnDown.addEventListener("click", () => {
      [chain[index], chain[index + 1]] = [chain[index + 1], chain[index]];
      renderChain();
    });
    const btnRemove = document.createElement("button");
    btnRemove.type = "button";
    btnRemove.className = "btn-icon btn-icon-danger";
    btnRemove.textContent = "✕";
    btnRemove.addEventListener("click", () => {
      chain = chain.filter((c) => c.uid !== item.uid);
      renderChain();
    });
    move.append(btnUp, btnDown, btnRemove);

    head.append(check, title, move);
    li.appendChild(head);

    const action = catalogAction(item.catalog_id);
    if (action?.params?.length) {
      const paramsRow = document.createElement("div");
      paramsRow.className = "chain-params";
      for (const spec of action.params) {
        const field = document.createElement("label");
        field.className = "param-field";
        if (spec.type === "bool") {
          const inp = document.createElement("input");
          inp.type = "checkbox";
          inp.checked = Boolean(item.params[spec.key]);
          inp.addEventListener("change", () => {
            item.params[spec.key] = inp.checked;
            renderChain();
          });
          field.append(inp, document.createTextNode(" " + spec.label));
        } else {
          const lbl = document.createElement("span");
          lbl.textContent = spec.label;
          const inp = document.createElement("input");
          inp.type = "number";
          inp.value = item.params[spec.key] ?? spec.default;
          if (spec.min != null) inp.min = spec.min;
          if (spec.max != null) inp.max = spec.max;
          if (spec.step != null) inp.step = spec.step;
          inp.addEventListener("change", () => {
            item.params[spec.key] = inp.value;
            renderChain();
          });
          field.append(lbl, inp);
        }
        paramsRow.appendChild(field);
      }
      li.appendChild(paramsRow);
    }

    list.appendChild(li);
  });
  updatePreview();
}

function renderCatalogTabs() {
  const tabs = $("#catalog-tabs");
  tabs.innerHTML = "";
  for (const cat of catalog.categories) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "catalog-tab" + (activeCategory === cat.id ? " active" : "");
    btn.textContent = cat.label;
    btn.addEventListener("click", () => {
      activeCategory = cat.id;
      renderCatalogTabs();
      renderCatalogList();
    });
    tabs.appendChild(btn);
  }
  if (!activeCategory && catalog.categories.length) {
    activeCategory = catalog.categories[0].id;
    renderCatalogTabs();
  }
}

function renderCatalogList() {
  const list = $("#catalog-list");
  list.innerHTML = "";
  const cat = catalog.categories.find((c) => c.id === activeCategory);
  if (cat?.hint) {
    const hint = document.createElement("p");
    hint.className = "catalog-hint";
    hint.textContent = cat.hint;
    list.appendChild(hint);
  }
  const actions = catalog.actions.filter((a) => a.category === activeCategory);
  for (const action of actions) {
    const card = document.createElement("article");
    card.className = "catalog-card";
    const h4 = document.createElement("h4");
    h4.textContent = action.label;
    const p = document.createElement("p");
    p.textContent = action.description;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm btn-primary";
    btn.textContent = "+ Add";
    btn.addEventListener("click", () => {
      const item = newChainItem(action.id);
      if (item) {
        chain.push(item);
        renderChain();
        toast(`Added: ${action.label}`);
      }
    });
    card.append(h4, p, btn);
    list.appendChild(card);
  }
}

function renderPresetsSelect() {
  const sel = $("#preset-select");
  const current = sel.value;
  sel.innerHTML = '<option value="">— Choose preset —</option>';
  for (const p of presets) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    if (p.description) opt.title = p.description;
    sel.appendChild(opt);
  }
  if (current && presets.some((p) => p.id === current)) sel.value = current;
}

function loadPresetIntoChain(presetId) {
  const preset = presets.find((p) => p.id === presetId);
  if (!preset) return;
  chain = (preset.chain || []).map((item) => ({
    ...item,
    uid: `c${uidSeq++}`,
    enabled: item.enabled !== false,
    params: { ...(item.params || {}) },
  }));
  $("#opt-recover").checked = preset.recover_on_failure !== false;
  $("#save-preset-id").value = preset.id;
  $("#save-preset-name").value = preset.name;
  renderChain();
  toast(`Preset loaded: ${preset.name}`);
}

async function loadGuide() {
  try {
    const data = await api("/api/guide");
    $("#guide-basic").innerHTML = data.basic_html || "<p>Guide not available.</p>";
    $("#guide-advanced").innerHTML = data.advanced_html || "<p>Advanced section not available.</p>";
  } catch {
    $("#guide-basic").innerHTML = "<p class='hint'>Could not load guide.</p>";
  }
}

function initGuideTabs() {
  const tabs = document.querySelectorAll(".guide-tab");
  const panels = {
    basic: $("#guide-basic"),
    advanced: $("#guide-advanced"),
  };
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const key = tab.dataset.guideTab;
      tabs.forEach((t) => {
        const on = t === tab;
        t.classList.toggle("active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      for (const [name, panel] of Object.entries(panels)) {
        const show = name === key;
        panel.hidden = !show;
        panel.classList.toggle("active", show);
      }
    });
  });
}

async function loadCatalog() {
  catalog = await api("/api/pipeline/catalog");
  activeCategory = catalog.categories[0]?.id || null;
  renderCatalogTabs();
  renderCatalogList();
}

async function loadPresets() {
  const data = await api("/api/pipeline/presets");
  presets = data.presets || [];
  renderPresetsSelect();
}

async function refreshPipelineState() {
  try {
    const data = await api("/api/pipeline/state");
    const pending = $("#pending-state");
    const resumeBtn = $("#btn-resume");
    if (!data.pending) {
      pending.hidden = true;
      resumeBtn.hidden = true;
      return;
    }
    pending.hidden = false;
    resumeBtn.hidden = false;
    const ul = $("#pending-steps");
    ul.innerHTML = "";
    for (const step of data.steps || []) {
      const li = document.createElement("li");
      li.className = "pending-step-" + step.status;
      const err = step.error ? ` — ${step.error}` : "";
      li.textContent = `${step.index}. [${step.status}] ${step.label}${err}`;
      ul.appendChild(li);
    }
  } catch {
    /* ignore */
  }
}

async function runChain(resume = false) {
  try {
    await api("/api/pipeline/run", {
      method: "POST",
      body: JSON.stringify({
        chain,
        name: resume ? "resume" : ($("#save-preset-name").value || "panel"),
        recover_on_failure: $("#opt-recover").checked,
        force: $("#opt-force").checked,
        resume,
      }),
    });
    toast(resume ? "Resuming…" : "Chain started");
    refreshStatus();
    refreshPipelineState();
  } catch (e) {
    toast(e.message, true);
  }
}

async function savePreset() {
  const id = $("#save-preset-id").value.trim().toLowerCase();
  const name = $("#save-preset-name").value.trim() || id;
  if (!id) {
    toast("Enter a preset ID (e.g. my-routine)", true);
    return;
  }
  try {
    await api("/api/pipeline/save-preset", {
      method: "POST",
      body: JSON.stringify({
        id,
        name,
        chain,
        recover_on_failure: $("#opt-recover").checked,
        overwrite: true,
      }),
    });
    toast(`Preset saved: ${id}`);
    await loadPresets();
    $("#preset-select").value = id;
  } catch (e) {
    toast(e.message, true);
  }
}

async function refreshStatus() {
  try {
    const st = await api("/api/status");
    const emu = st.emulator || st.ldplayer;
    setPill($("#pill-ld"), emu.running, emu.running ? "Emulator ON" : "Emulator OFF");
    setPill($("#pill-adb"), st.adb.connected, st.adb.connected ? "ADB OK" : "ADB OFF");
    setPill($("#pill-screen"), st.adb.connected, st.screen || "?");
    if (st.job.running) {
      setPill($("#pill-job"), "busy", `Running: ${st.job.label}`);
    } else if (st.job.last_error) {
      setPill($("#pill-job"), false, "Error (see log)");
    } else {
      setPill($("#pill-job"), true, "Idle");
    }

    const busy = st.job.running;
    document.querySelectorAll("[data-job], #btn-run-chain, #btn-resume, #btn-skills-refresh, .catalog-card button").forEach((btn) => {
      btn.disabled = busy;
    });

    $("#btn-stop").disabled = st.stop_requested;
  } catch {
    setPill($("#pill-ld"), false, "Panel error");
  }
}

async function refreshDailyStatus() {
  try {
    const data = await api("/api/daily-status");
    $("#daily-status").textContent = data.lines.join("\n") || "(no data)";
  } catch {
    $("#daily-status").textContent = "(could not load)";
  }
}

async function refreshLog() {
  try {
    const data = await api("/api/logs?lines=120");
    const el = $("#log-view");
    el.textContent = data.lines.join("\n") || "(empty log)";
    el.scrollTop = el.scrollHeight;
  } catch {
    $("#log-view").textContent = "(could not read logs/bot.log)";
  }
}

async function loadSoloClaims() {
  const data = await api("/api/claims");
  const root = $("#solo-claims");
  root.innerHTML = "";

  for (const group of data.groups || []) {
    const claims = (group.items || []).filter((it) => it.kind === "claim");
    if (!claims.length) continue;

    const section = document.createElement("section");
    section.className = `solo-tier tier-${group.id}`;
    const title = document.createElement("h4");
    title.textContent = group.label;
    section.appendChild(title);

    const grid = document.createElement("div");
    grid.className = "solo-claims-grid";
    for (const item of claims) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn claim-btn" + (item.main_loop ? " main-loop" : "");
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
let labeledSkillOptions = [];

function buildSkillPickerSelect(selected = "") {
  const sel = document.createElement("select");
  sel.className = "meta-select skill-pick-select";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "Same as…";
  sel.appendChild(empty);
  for (const opt of labeledSkillOptions) {
    const item = document.createElement("option");
    item.value = opt.id;
    item.textContent = opt.label;
    if (opt.id === selected) item.selected = true;
    sel.appendChild(item);
  }
  return sel;
}

async function mergeSkillImage(catalogFp, targetSkillId) {
  if (!targetSkillId) {
    toast("Pick a skill to group with", true);
    return;
  }
  const data = await api("/api/skills/merge", {
    method: "POST",
    body: JSON.stringify({ catalog_fp: catalogFp, target_skill_id: targetSkillId }),
  });
  toast(`Grouped as ${data.id}`);
  await loadSkills();
}

async function deleteSkillImage(skill) {
  const what = skill.catalog_fp ? "this catalog image" : `template ${skill.id}`;
  if (!window.confirm(`Delete ${what}?`)) return;
  await api("/api/skills/delete", {
    method: "POST",
    body: JSON.stringify({
      skill_id: skill.id,
      catalog_fp: skill.catalog_fp || null,
    }),
  });
  toast(skill.catalog_fp ? "Image deleted" : `${skill.id} removed`);
  await loadSkills();
}

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
  if (!pending.length) return;

  const title = document.createElement("h4");
  title.textContent = `Pending unknowns (${pending.length})`;
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
    stats.textContent = `Seen ${sk.seen_count}x · conf ${Number(sk.best_confidence || 0).toFixed(2)}`;

    const nameInput = document.createElement("input");
    nameInput.className = "meta-input name-input";
    nameInput.placeholder = "skill_name";

    const categorySelect = buildLabeledSelect(skillCategories, categoryLabels, "");
    categorySelect.classList.add("category-select");

    const groupSelect = buildLabeledSelect(skillGroups, groupLabels, "", {
      allowEmpty: true,
      emptyLabel: "No group",
    });
    groupSelect.classList.add("group-select");

    const sameSelect = buildSkillPickerSelect();
    sameSelect.classList.add("pending-same-select");

    const scoreInput = document.createElement("input");
    scoreInput.className = "score-input";
    scoreInput.type = "number";
    scoreInput.min = "0";
    scoreInput.max = "999";
    scoreInput.value = String(sk.score || 0);

    const actions = document.createElement("div");
    actions.className = "pending-skill-actions";

    const btnGroup = document.createElement("button");
    btnGroup.className = "btn btn-sm";
    btnGroup.textContent = "Same as";
    btnGroup.addEventListener("click", () => {
      mergeSkillImage(sk.catalog_fp, sameSelect.value).catch((e) => toast(e.message, true));
    });

    const btnSave = document.createElement("button");
    btnSave.className = "btn btn-primary btn-xs";
    btnSave.textContent = "Label new";
    btnSave.addEventListener("click", () => saveSkillMeta(sk).catch((e) => toast(e.message, true)));

    const btnDelete = document.createElement("button");
    btnDelete.className = "btn btn-ghost btn-xs btn-danger-text";
    btnDelete.textContent = "Delete";
    btnDelete.addEventListener("click", () => deleteSkillImage(sk).catch((e) => toast(e.message, true)));

    actions.append(sameSelect, btnGroup, btnSave, btnDelete);
    meta.append(stats, nameInput, categorySelect, groupSelect, scoreInput, actions);
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
  const wrap = document.querySelector(".skills-table-wrap");
  const scrollTop = wrap ? wrap.scrollTop : 0;
  try {
    const data = await api("/api/skills");
    skillCategories = data.categories || [];
    skillGroups = data.groups || [];
    categoryLabels = data.category_labels || {};
    groupLabels = data.group_labels || {};
    labeledSkillOptions = (data.skills || [])
      .filter((sk) => sk.id && !String(sk.id).startsWith("catalog/"))
      .map((sk) => ({ id: sk.id, label: `${sk.id} (${sk.score})` }))
      .sort((a, b) => a.id.localeCompare(b.id));
    renderPendingSkills(data.pending || []);
    if (!data.skills.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="muted-cell">No skills in catalog</td></tr>';
      return;
    }
    tbody.innerHTML = "";
    for (const sk of data.skills) {
      const tr = document.createElement("tr");
      tr.dataset.skillId = sk.id;
      if (String(sk.source).startsWith("manual")) tr.classList.add("manual");

      const thumbTd = document.createElement("td");
      thumbTd.className = "skill-thumb-cell";
      const images = sk.catalog_images || [];
      if (images.length) {
        const stack = document.createElement("div");
        stack.className = "skill-thumb-stack";
        for (const img of images.slice(0, 3)) {
          const el = document.createElement("img");
          el.className = "skill-thumb";
          el.src = img.image_url;
          el.alt = sk.id;
          el.title = img.fp;
          stack.appendChild(el);
        }
        if (images.length > 3) {
          const more = document.createElement("span");
          more.className = "skill-thumb-more";
          more.textContent = `+${images.length - 3}`;
          stack.appendChild(more);
        }
        thumbTd.appendChild(stack);
      } else {
        thumbTd.innerHTML = '<span class="muted">—</span>';
      }

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
        emptyLabel: "No group",
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
      const imgCount = (sk.catalog_images || []).length;
      const extra = imgCount > 1 ? ` · ${imgCount} imgs` : "";
      srcTd.innerHTML = `<span class="source-tag">${sk.source}${extra}</span>`;

      const actionsTd = document.createElement("td");
      const actions = document.createElement("div");
      actions.className = "skill-actions";

      const btnMinus = document.createElement("button");
      btnMinus.className = "btn btn-xs";
      btnMinus.textContent = "-5";
      btnMinus.addEventListener("click", () => bumpSkillScore(sk.id, -5).catch((e) => toast(e.message, true)));

      const btnPlus = document.createElement("button");
      btnPlus.className = "btn btn-xs";
      btnPlus.textContent = "+5";
      btnPlus.addEventListener("click", () => bumpSkillScore(sk.id, 5).catch((e) => toast(e.message, true)));

      const btnSave = document.createElement("button");
      btnSave.className = "btn btn-primary btn-xs";
      btnSave.textContent = "Save";
      btnSave.addEventListener("click", () => saveSkillMeta(sk).catch((e) => toast(e.message, true)));

      actions.append(btnMinus, btnPlus, btnSave);

      if ((sk.catalog_images || []).length) {
        for (const img of sk.catalog_images) {
          const btnDelImg = document.createElement("button");
          btnDelImg.className = "btn btn-ghost btn-xs btn-danger-text";
          btnDelImg.textContent = "Del img";
          btnDelImg.title = `Delete image ${img.fp}`;
          btnDelImg.addEventListener("click", () => {
            deleteSkillImage({ id: sk.id, catalog_fp: img.fp }).catch((e) => toast(e.message, true));
          });
          actions.appendChild(btnDelImg);
        }
      } else if (sk.entry_type === "template") {
        const btnDel = document.createElement("button");
        btnDel.className = "btn btn-ghost btn-xs btn-danger-text";
        btnDel.textContent = "Delete";
        btnDel.addEventListener("click", () => deleteSkillImage(sk).catch((e) => toast(e.message, true)));
        actions.appendChild(btnDel);
      }

      actionsTd.appendChild(actions);
      tr.append(thumbTd, nameTd, catTd, groupTd, scoreTd, srcTd, actionsTd);
      tbody.appendChild(tr);
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="muted-cell">${e.message}</td></tr>`;
  }
  if (wrap) wrap.scrollTop = scrollTop;
}

document.querySelectorAll("[data-job]").forEach((btn) => {
  btn.addEventListener("click", () => runJob(btn.dataset.job));
});

$("#btn-stop").addEventListener("click", async () => {
  try {
    await api("/api/stop", { method: "POST", body: "{}" });
    toast("STOP enabled");
    refreshStatus();
  } catch (e) {
    toast(e.message, true);
  }
});

$("#btn-clear-stop").addEventListener("click", async () => {
  try {
    await api("/api/clear-stop", { method: "POST", body: "{}" });
    toast("STOP cleared");
    refreshStatus();
  } catch (e) {
    toast(e.message, true);
  }
});

$("#btn-run-chain").addEventListener("click", () => runChain(false));
$("#btn-resume").addEventListener("click", () => runChain(true));
$("#btn-save-preset").addEventListener("click", () => savePreset());
$("#btn-chain-clear").addEventListener("click", () => {
  chain = [];
  renderChain();
});
$("#preset-select").addEventListener("change", (ev) => {
  if (ev.target.value) loadPresetIntoChain(ev.target.value);
});
$("#btn-clear-state").addEventListener("click", async () => {
  try {
    await api("/api/pipeline/clear-state", { method: "POST", body: "{}" });
    toast("Saved state discarded");
    refreshPipelineState();
  } catch (e) {
    toast(e.message, true);
  }
});

$("#btn-refresh-log").addEventListener("click", refreshLog);
$("#btn-skills-refresh").addEventListener("click", () => loadSkills());

async function init() {
  initGuideTabs();
  loadGuide();
  try {
    await loadCatalog();
    await loadPresets();
    await loadSoloClaims();
    const defaultPreset = presets.find((p) => p.id === "5-arena-farm");
    if (defaultPreset) {
      $("#preset-select").value = "5-arena-farm";
      loadPresetIntoChain("5-arena-farm");
    }
  } catch (e) {
    toast("Failed to load panel: " + e.message, true);
  }
  loadSkills();
  refreshStatus();
  refreshDailyStatus();
  refreshLog();
  refreshPipelineState();
}

init();
setInterval(refreshStatus, 2500);
setInterval(refreshLog, 4000);
setInterval(refreshPipelineState, 5000);
setInterval(refreshDailyStatus, 15000);
