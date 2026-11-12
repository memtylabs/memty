// Memty Bridge content script.
// ⚡ Memty / Alt+M   -> add your saved facts to the prompt as readable bullets (visible, editable).
// Select text        -> a "+ Save to Memty" bubble appears; facts are proposed, you edit, then save.
// + Save             -> same, for the latest answer when nothing is selected.
// The pill can be dragged anywhere (double-click the grip to reset). Network calls go
// through background.js; this script never sees the pairing token.
(() => {
  // Reloading or updating the extension orphans the copy already running in open
  // tabs ("Extension context invalidated"). background.js injects a fresh copy;
  // the fresh copy tells older ones to remove themselves, then takes over.
  document.dispatchEvent(new CustomEvent("memty:teardown"));
  for (const old of document.querySelectorAll(":root > div[data-memty-bridge]")) old.remove();
  // Copies from before v0.3 had no teardown hook: drop their orphaned pill too.
  for (const old of document.documentElement.children) {
    if (old.tagName === "DIV" && !old.dataset.memtyBridge && old.style.zIndex === "2147483647"
        && old.style.position === "fixed" && !old.shadowRoot && !old.childElementCount) old.remove();
  }
  const lifetime = new AbortController();
  const signal = lifetime.signal;
  const alive = () => { try { return !!chrome.runtime?.id; } catch { return false; } };

  const EDITORS = [
    "#prompt-textarea",                       // ChatGPT
    'div.ProseMirror[contenteditable="true"]', // Claude.ai, ChatGPT
    "rich-textarea .ql-editor",                // Gemini
    'textarea[placeholder]',                   // Perplexity
    'div[contenteditable="true"][role="textbox"]',
    "textarea",
  ];
  // Best-effort answer selectors; a text selection always takes priority.
  const ANSWERS = {
    "chatgpt.com": '[data-message-author-role="assistant"]',
    "chat.openai.com": '[data-message-author-role="assistant"]',
    "claude.ai": '[data-testid="assistant-message"], .font-claude-response, .font-claude-message',
    "gemini.google.com": "model-response message-content, model-response",
    "www.perplexity.ai": ".prose",
    "perplexity.ai": ".prose",
  };
  const POS_KEY = `memtyPos:${location.hostname}`;
  const MIN_SELECTION = 12;
  const MAX_SELECTION_CHARS = 50_000;

  const host = document.createElement("div");
  host.style.cssText = "position:fixed;top:0;left:0;width:0;height:0;z-index:2147483647;";
  host.dataset.memtyBridge = "1";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; }
      .bar { position:fixed; display:flex; align-items:center; gap:2px; padding:3px;
             border-radius:999px; background:linear-gradient(135deg,#7c3aed,#4f46e5);
             border:1px solid rgba(255,255,255,.55); box-shadow:0 4px 14px rgba(79,70,229,.45);
             font:600 13px/1 system-ui,-apple-system,sans-serif; color:#fff; user-select:none; }
      .grip { cursor:grab; padding:6px 4px 6px 7px; opacity:.75; letter-spacing:-2px;
              touch-action:none; -webkit-user-select:none; }
      .grip:active { cursor:grabbing; }
      button { all:unset; cursor:pointer; padding:7px 11px; border-radius:999px; color:#fff;
               white-space:nowrap; }
      button:hover, button:focus-visible { background:rgba(255,255,255,.2); }
      button[disabled] { opacity:.6; cursor:progress; }
      .sep { width:1px; height:16px; background:rgba(255,255,255,.4); }
      .bubble { position:fixed; padding:7px 12px; border-radius:999px; background:#4f46e5; color:#fff;
                font:600 12px/1 system-ui,sans-serif; box-shadow:0 4px 14px rgba(0,0,0,.3);
                border:1px solid rgba(255,255,255,.55); }
      .card { position:fixed; right:16px; bottom:16px; width:380px; max-width:calc(100vw - 32px);
              max-height:min(460px, calc(100vh - 32px)); display:flex; flex-direction:column;
              background:#fff; color:#111827; border:1px solid #c7d2fe; border-radius:14px;
              box-shadow:0 12px 40px rgba(0,0,0,.28); font:13px/1.4 system-ui,sans-serif; }
      .card header { padding:12px 14px 8px; font-weight:700; display:flex; justify-content:space-between; }
      .card header small { font-weight:400; color:#6b7280; }
      .review-note { margin:0 14px 8px; color:#92400e; font-size:12px; }
      .project { display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin:0 14px 8px;
                 color:#374151; font-size:12px; }
      .project select, .project input { min-width:0; max-width:100%; padding:4px 6px;
                 border:1px solid #c7d2fe; border-radius:6px; background:#fff; color:#111827; font:inherit; }
      .source { margin:0 14px 8px; color:#4338ca; font-size:12px; }
      .source summary { cursor:pointer; }
      .source pre { max-height:100px; overflow:auto; margin:6px 0 0; padding:8px;
                    white-space:pre-wrap; overflow-wrap:anywhere; color:#374151; background:#f9fafb; }
      .list { overflow:auto; min-height:0; padding:0 14px; }
      .context-choice { display:block; width:100%; padding:10px 8px; border-radius:8px;
                        color:#111827; font:13px/1.35 system-ui,sans-serif; white-space:normal; }
      .context-choice:hover, .context-choice:focus-visible { background:#eef2ff; }
      .context-choice strong, .context-choice small { display:block; }
      .context-choice small { margin-top:3px; color:#6b7280; }
      .fact { display:grid; grid-template-columns:18px 1fr; gap:4px 8px; padding:8px 0;
              border-top:1px solid #eef2ff; align-items:start; }
      .fact input[type=checkbox] { margin:3px 0 0; accent-color:#4f46e5; }
      .fact .label { all:unset; font:600 12px/1.3 system-ui,sans-serif; color:#4338ca; padding:2px 4px;
                     margin-left:-4px; border-radius:6px; }
      .fact .label:hover { background:#eef2ff; }
      .fact .label:focus { background:#eef2ff; outline:2px solid #a5b4fc; }
      .fact textarea { grid-column:2; width:100%; resize:vertical; min-height:34px; padding:6px 8px;
                       border:1px solid #e5e7eb; border-radius:8px; font:13px/1.35 system-ui,sans-serif;
                       color:#111827; background:#f9fafb; }
      .fact textarea:focus { outline:2px solid #a5b4fc; background:#fff; }
      .fact.off textarea { opacity:.45; }
      .row { display:flex; gap:8px; justify-content:flex-end; padding:10px 14px 12px; }
      .row button { padding:8px 14px; border-radius:8px; color:#374151; background:#f3f4f6; }
      .row button.primary { color:#fff; background:#4f46e5; }
      .row button.primary:hover { background:#4338ca; }
      .toast { position:fixed; right:16px; bottom:16px; max-width:360px; background:#111827; color:#fff;
               padding:10px 14px; border-radius:10px; font:13px/1.35 system-ui,sans-serif;
               box-shadow:0 8px 24px rgba(0,0,0,.3); border-left:4px solid #7c3aed; }
      [hidden] { display:none !important; }
    </style>
    <div class="bar" hidden>
      <span class="grip" title="Drag to move · double-click to reset">⋮⋮</span>
      <button class="inject" title="Add your saved facts to this prompt (Alt+M)">⚡ Memty</button>
      <span class="sep"></span>
      <button class="save" title="Save facts from your selection or the latest answer">＋ Save</button>
      <span class="sep"></span>
      <button class="facts" title="View, edit, or delete your saved facts">☰</button>
    </div>
    <button class="bubble" hidden title="Turn the selected text into facts">＋ Save to Memty</button>
    <div class="card" hidden></div>
    <div class="toast" hidden></div>`;
  const $ = (selector) => root.querySelector(selector);
  const bar = $(".bar");
  const bubble = $(".bubble");
  const card = $(".card");
  const toastEl = $(".toast");
  const injectBtn = $(".inject");
  const saveBtn = $(".save");
  document.documentElement.appendChild(host);

  let editor = null;
  // Older releases stored a prompt-relative offset. Keep it until the user
  // moves or resets the pill, then store a stable viewport position instead.
  let offset = { x: 0, y: 0 };
  let position = null;
  let positionLoaded = false;
  let positionTouched = false;
  let drag = null;
  let pickerRevision = 0;
  let lastPos = "";
  let toastTimer = 0;

  chrome.storage.local.get(POS_KEY, (stored) => {
    const saved = stored?.[POS_KEY];
    if (!positionTouched && Number.isFinite(saved?.x) && Number.isFinite(saved?.y)) {
      if (saved.anchor === "viewport") position = { x: saved.x, y: saved.y };
      else offset = { x: saved.x, y: saved.y };
    }
    positionLoaded = true;
    schedule();
  });

  // ---------------------------------------------------------------- placement
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0;
  const isEditor = (el) => !!el && (el.tagName === "TEXTAREA" || el.isContentEditable);

  function findEditor() {
    const active = document.activeElement;
    if (isEditor(active) && active !== host) return active.closest('[contenteditable="true"]') || active;
    if (visible(editor)) return editor;
    for (const selector of EDITORS) {
      const found = [...document.querySelectorAll(selector)].find(visible);
      if (found) return found;
    }
    return null;
  }

  const resizeObserver = new ResizeObserver(() => schedule());

  function clampPosition(x, y, width, height) {
    return {
      x: Math.min(Math.max(4, x), Math.max(4, innerWidth - width - 4)),
      y: Math.min(Math.max(4, y), Math.max(4, innerHeight - height - 4)),
    };
  }

  function place() {
    if (!positionLoaded) return;
    const found = findEditor();
    if (found !== editor) {
      if (editor) resizeObserver.unobserve(editor);
      editor = found;
      if (editor) resizeObserver.observe(editor);
    }
    const hidden = !editor && !drag;
    if (bar.hidden !== hidden) bar.hidden = hidden;
    if (hidden) return;
    const width = bar.offsetWidth || 190;
    const height = bar.offsetHeight || 32;
    const rect = editor?.getBoundingClientRect();
    // Once moved, the pill no longer follows a changing ChatGPT composer.
    const target = position || (rect
      ? { x: rect.right - width + offset.x, y: rect.top - height - 8 + offset.y }
      : { x: drag.left, y: drag.top });
    const placed = clampPosition(target.x, target.y, width, height);
    const pos = `${Math.round(placed.x)},${Math.round(placed.y)}`;
    if (pos !== lastPos) { // only touch styles when something moved
      lastPos = pos;
      bar.style.left = `${Math.round(placed.x)}px`;
      bar.style.top = `${Math.round(placed.y)}px`;
    }
  }

  let frame = 0;
  function schedule() {
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; place(); });
  }

  // Drag the pill by its grip; the position is remembered per site.
  const grip = $(".grip");
  grip.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || event.button !== 0 || drag) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = bar.getBoundingClientRect();
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY,
             left: rect.left, top: rect.top, moved: false };
    grip.setPointerCapture(event.pointerId);
  });
  grip.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    event.preventDefault();
    event.stopPropagation();
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (!dx && !dy) return;
    position = clampPosition(drag.left + dx, drag.top + dy, bar.offsetWidth, bar.offsetHeight);
    Object.assign(drag, { x: event.clientX, y: event.clientY, left: position.x, top: position.y, moved: true });
    positionTouched = true;
    schedule();
  });
  const finishDrag = (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    event.stopPropagation();
    const moved = drag.moved;
    drag = null;
    if (moved && alive()) chrome.storage.local.set({ [POS_KEY]: { ...position, anchor: "viewport" } });
    schedule();
  };
  grip.addEventListener("pointerup", finishDrag);
  grip.addEventListener("pointercancel", finishDrag);
  grip.addEventListener("lostpointercapture", finishDrag);
  grip.addEventListener("dblclick", () => {
    positionTouched = true;
    position = null;
    offset = { x: 0, y: 0 };
    chrome.storage.local.remove(POS_KEY);
    schedule();
  });

  // ---------------------------------------------------------------- helpers
  function toast(text, ms = 4000) {
    toastEl.textContent = text;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, ms);
  }

  function ask(message) {
    if (!alive()) { // let the message show before the stale pill disappears
      setTimeout(teardown, 5000);
      return Promise.reject(new Error("Memty was updated. Refresh this page to use it here."));
    }
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(message, (reply) => {
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
        reply?.ok ? resolve(reply.result) : reject(new Error(reply?.error || "No response from Memty"));
      });
    });
  }

  async function busy(button, label, work) {
    if (button.disabled) return;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = label;
    try {
      await work();
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  const textOf = (el) => (el.tagName === "TEXTAREA" ? el.value : el.innerText);

  function prepend(el, text) {
    el.focus();
    if (el.tagName === "TEXTAREA") {
      // Use the native setter so React-controlled textareas register the change.
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(el, `${text}\n\n${el.value}`);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.setSelectionRange(el.value.length, el.value.length);
      return;
    }
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(true);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    // One insertText call goes through the editor's own pipeline (ProseMirror, Quill, Lexical).
    if (!document.execCommand("insertText", false, `${text}\n\n`)) {
      el.prepend(document.createTextNode(`${text}\n\n`));
      el.dispatchEvent(new InputEvent("input", { bubbles: true }));
    }
    // Leave the caret at the end so the user keeps typing their question.
    range.selectNodeContents(el);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  // Readable text of an answer or selection, with code blocks fenced so the
  // vault can summarize them (it never stores code itself).
  function readable(content) {
    const sandbox = document.createElement("div");
    sandbox.style.cssText = "position:fixed;left:-99999px;top:0;width:800px;white-space:normal;";
    sandbox.append(content);
    for (const pre of sandbox.querySelectorAll("pre")) {
      const code = pre.querySelector("code") || pre;
      const lang = (code.className.match(/language-([\w+#-]+)/) || [])[1] || "";
      const fenced = document.createElement("pre");
      fenced.textContent = `\n\`\`\`${lang}\n${code.textContent.trim()}\n\`\`\`\n`;
      pre.replaceWith(fenced);
    }
    for (const link of sandbox.querySelectorAll("a[href]")) {
      const href = link.getAttribute("href") || "";
      const label = link.textContent.trim();
      if (/^https?:\/\//i.test(href) && label && label !== href && !/^\d+$/.test(label)) {
        link.append(document.createTextNode(` (${href})`));
      }
    }
    // innerText drops the browser's list markers; retain the boundaries for extraction.
    for (const item of sandbox.querySelectorAll("li")) item.prepend(document.createTextNode("- "));
    document.body.append(sandbox);
    const text = sandbox.innerText;
    sandbox.remove();
    return text.trim();
  }

  function selectionText() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return "";
    const anchor = selection.anchorNode?.parentElement;
    if (anchor && (anchor.closest('[contenteditable="true"], textarea') || anchor === host)) return "";
    if (String(selection).trim().length < MIN_SELECTION) return "";
    return readable(selection.getRangeAt(0).cloneContents());
  }

  function latestAnswer() {
    const selector = ANSWERS[location.hostname];
    const nodes = selector ? [...document.querySelectorAll(selector)].filter(visible) : [];
    return nodes.length ? readable(nodes[nodes.length - 1].cloneNode(true)) : "";
  }

  // ---------------------------------------------------------------- actions
  async function inject() {
    if (!card.hidden) return toast("Finish or close the open panel first.");
    const el = findEditor();
    if (!el) return toast("Click into the prompt box first.");
    await busy(injectBtn, "⚡ …", async () => {
      try {
        const { contexts } = await ask({ type: "contexts" });
        if (signal.aborted || !card.hidden) return;
        if (!contexts?.length) return toast("No saved contexts yet. Select text and save it first.");
        chooseContext(contexts, el);
      } catch (error) {
        toast(error.message, 6000);
      }
    });
  }

  function chooseContext(contexts, originalEditor) {
    const revision = ++pickerRevision;
    let choosing = false;
    card.replaceChildren();
    const header = document.createElement("header");
    header.textContent = "Choose a saved context";
    const hint = document.createElement("small");
    hint.textContent = "Newest first";
    header.append(hint);
    const list = document.createElement("div");
    list.className = "list";
    contexts.forEach((context, index) => {
      const choice = document.createElement("button");
      choice.className = "context-choice";
      const title = document.createElement("strong");
      title.textContent = `${index + 1}. ${context.preview}`;
      const detail = document.createElement("small");
      const time = context.updated_at ? new Date(context.updated_at).toLocaleString() : "";
      detail.textContent = [context.namespace, `${context.count} fact(s)`, time].filter(Boolean).join(" · ");
      choice.append(title, detail);
      choice.addEventListener("click", async () => {
        if (choosing) return;
        choosing = true;
        list.querySelectorAll("button").forEach((button) => { button.disabled = true; });
        try {
          const capsule = await ask({ type: "capsule", namespace: context.namespace, context: context.id });
          if (signal.aborted || revision !== pickerRevision || card.hidden) return;
          if (!capsule.text) return toast(capsule.omitted
            ? "No facts could be added because of privacy settings or the context size."
            : "This context has no available facts.");
          const el = visible(originalEditor) ? originalEditor : findEditor();
          if (!el) return toast("Click into the prompt box and choose the context again.");
          if (textOf(el).includes(capsule.text)) return toast("This context is already in the prompt.");
          prepend(el, capsule.text);
          closeCard();
          const note = capsule.redacted ? `, ${capsule.redacted} kept private` : "";
          const omitted = capsule.omitted ? ` ${capsule.omitted} not included due to privacy or space.` : "";
          toast(`Added ${capsule.facts} fact(s) from ${capsule.namespace}${note}.${omitted}`);
        } catch (error) {
          if (!signal.aborted && revision === pickerRevision && !card.hidden) toast(error.message, 6000);
        } finally {
          choosing = false;
          list.querySelectorAll("button").forEach((button) => { button.disabled = false; });
        }
      });
      list.append(choice);
    });
    const actions = document.createElement("div");
    actions.className = "row";
    const cancel = document.createElement("button");
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", closeCard);
    actions.append(cancel);
    card.append(header, list, actions);
    card.hidden = false;
    list.querySelector("button")?.focus();
  }

  function label(slot) {
    if (/^(?:note|fact)_[0-9a-f]{6,}$/.test(slot)) return "Note";
    const text = slot.replace(/_\d+$/, "").replace(/[_.]+/g, " ");
    return text.charAt(0).toUpperCase() + text.slice(1);
  }
  const toSlot = (title) => title.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);

  function review(facts, source, original, warnings = [], namespaceInfo = {}) {
    card.replaceChildren();
    const header = document.createElement("header");
    header.textContent = "Save to Memty";
    const hint = document.createElement("small");
    hint.textContent = `${facts.length} from ${source} · edit before saving`;
    header.append(hint);
    const project = document.createElement("label");
    project.className = "project";
    project.append("Save to project: ");
    const projectSelect = document.createElement("select");
    const names = [...new Set([...(namespaceInfo.namespaces || []), namespaceInfo.namespace || "personal"])];
    for (const name of names) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name + (name === namespaceInfo.namespace && namespaceInfo.detected ? " (suggested)" : "");
      option.selected = name === (namespaceInfo.namespace || "personal");
      projectSelect.append(option);
    }
    const newProject = document.createElement("option");
    newProject.value = "__new__";
    newProject.textContent = "＋ New project…";
    projectSelect.append(newProject);
    const customProject = document.createElement("input");
    customProject.placeholder = "e.g. repo.memty";
    customProject.hidden = true;
    projectSelect.addEventListener("change", () => {
      customProject.hidden = projectSelect.value !== "__new__";
      if (!customProject.hidden) customProject.focus();
    });
    project.append(projectSelect, customProject);
    const sourceDetails = document.createElement("details");
    sourceDetails.className = "source";
    const sourceSummary = document.createElement("summary");
    sourceSummary.textContent = "Review original text (not saved)";
    const sourceText = document.createElement("pre");
    sourceText.textContent = original;
    sourceDetails.append(sourceSummary, sourceText);
    const note = document.createElement("div");
    note.className = "review-note";
    note.textContent = warnings.join(" ");
    const list = document.createElement("div");
    list.className = "list";
    const rows = facts.map((fact) => {
      const row = document.createElement("div");
      row.className = "fact";
      const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: true });
      const name = Object.assign(document.createElement("input"), {
        className: "label", value: label(fact.slot), title: "Title (editable)", spellcheck: false });
      const value = Object.assign(document.createElement("textarea"), { value: fact.value, rows: 1 });
      box.onchange = () => row.classList.toggle("off", !box.checked);
      row.append(box, name, value);
      list.append(row);
      return { box, name, value, fact };
    });
    const actions = document.createElement("div");
    actions.className = "row";
    const cancel = Object.assign(document.createElement("button"), { textContent: "Cancel" });
    const save = Object.assign(document.createElement("button"), { textContent: `Save ${rows.length}`, className: "primary" });
    function recount() { save.textContent = `Save ${rows.filter((r) => r.box.checked).length}`; }
    rows.forEach((r) => r.box.addEventListener("change", recount));
    actions.append(cancel, save);
    card.append(header, project);
    if (warnings.length) card.append(note);
    card.append(sourceDetails, list, actions);
    toastEl.hidden = true;
    card.hidden = false;
    rows[0]?.value.focus();
    cancel.onclick = () => { card.hidden = true; };
    save.onclick = () => busy(save, "Saving…", async () => {
      const projectName = (projectSelect.value === "__new__" ? customProject.value : projectSelect.value).trim().toLowerCase();
      if (projectName.length > 255 || !/^[a-z0-9][a-z0-9_-]{0,63}(?:\.[a-z0-9][a-z0-9_-]{0,63})*$/.test(projectName)) {
        return toast("Choose a project name such as repo.memty or project.api.");
      }
      const chosen = rows.filter((r) => r.box.checked && r.value.value.trim())
        .map((r) => {
          // An unchanged title keeps its original slot, so several "Note"s never collide.
          const title = r.name.value.trim();
          const slot = title === label(r.fact.slot) ? r.fact.slot : toSlot(title) || r.fact.slot;
          return { slot, value: r.value.value.trim().replace(/\s+/g, " ") };
        });
      const used = new Set();
      for (const fact of chosen) { // two facts renamed to the same title: keep both
        let unique = fact.slot;
        for (let n = 2; used.has(unique); n += 1) unique = `${fact.slot.slice(0, 45)}_${n}`;
        used.add(unique);
        fact.slot = unique;
      }
      if (!chosen.length) return toast("Nothing selected.");
      try {
        const result = await ask({ type: "save", namespace: projectName, facts: chosen });
        card.hidden = true;
        const skipped = result.skipped.length ? ` (${result.skipped.length} skipped: ${result.skipped[0].message})` : "";
        toast(`Saved ${result.saved.length} fact(s) to ${result.namespace}${skipped}.`);
      } catch (error) {
        toast(error.message, 6000);
      }
    });
  }

  async function extractFrom(text, source, button) {
    if (!card.hidden) return toast("Finish or close the open panel first.");
    if (text.length > MAX_SELECTION_CHARS) {
      return toast("That text is too long to review at once. Select a shorter passage and save it in parts.", 6000);
    }
    await busy(button, "…", async () => {
      try {
        const { facts, warnings = [] } = await ask({ type: "extract", text });
        if (signal.aborted) return;
        if (!card.hidden) return toast("Finish or close the open panel first.");
        if (!facts.length) return toast(warnings.join(" ") || "No clear facts found. Try selecting a shorter, specific passage.", 6000);
        const namespaceInfo = await ask({ type: "namespace-options", hint: text, title: document.title });
        if (signal.aborted) return;
        if (!card.hidden) return toast("Finish or close the open panel first.");
        review(facts, source, text, warnings, namespaceInfo);
      } catch (error) {
        toast(error.message, 6000);
      }
    });
  }

  function saveFacts() {
    const selected = selectionText();
    if (selected) return extractFrom(selected, "your selection", saveBtn);
    const answer = latestAnswer();
    if (!answer) return toast("Select the text you want to remember, then click ＋ Save.");
    return extractFrom(answer, "the latest answer", saveBtn);
  }

  // Selection bubble: appears just above the selected text.
  let selectionTimer = 0;
  function updateBubble() {
    clearTimeout(selectionTimer);
    selectionTimer = setTimeout(() => {
      const selection = window.getSelection();
      const text = selection && !selection.isCollapsed ? String(selection).trim() : "";
      const anchor = selection?.anchorNode?.parentElement;
      if (text.length < MIN_SELECTION || !selection.rangeCount ||
          anchor?.closest('[contenteditable="true"], textarea')) {
        bubble.hidden = true;
        return;
      }
      const rect = selection.getRangeAt(0).getBoundingClientRect();
      if (!rect.width && !rect.height) { bubble.hidden = true; return; }
      bubble.hidden = false;
      const top = rect.top > 44 ? rect.top - 38 : rect.bottom + 8;
      bubble.style.top = `${Math.round(Math.min(top, innerHeight - 36))}px`;
      bubble.style.left = `${Math.round(Math.min(Math.max(4, rect.left + rect.width / 2 - 60), innerWidth - 140))}px`;
    }, 120);
  }

  // ---------------------------------------------------------------- wiring
  // Keep focus and the text selection when our buttons are pressed.
  root.addEventListener("mousedown", (event) => {
    if (!event.composedPath().some((node) => node === card)) event.preventDefault();
  });
  injectBtn.addEventListener("click", inject);
  saveBtn.addEventListener("click", saveFacts);
  $(".facts").addEventListener("click", () => ask({ type: "open-facts" }).catch((error) => toast(error.message)));
  bubble.addEventListener("click", () => {
    const selected = selectionText();
    bubble.hidden = true;
    if (selected) extractFrom(selected, "your selection", saveBtn);
  });
  document.addEventListener("mouseup", updateBubble, { capture: true, signal });
  document.addEventListener("keyup", (event) => { if (event.shiftKey) updateBubble(); }, { capture: true, signal });
  document.addEventListener("selectionchange", () => {
    if (!bubble.hidden && window.getSelection()?.isCollapsed) bubble.hidden = true;
  }, { signal });
  function closeCard() {
    pickerRevision += 1;
    card.hidden = true;
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !card.hidden) { closeCard(); return; }
    if (event.altKey && !event.ctrlKey && !event.metaKey && event.code === "KeyM") {
      event.preventDefault();
      event.stopPropagation();
      inject();
    }
  }, { capture: true, signal });

  // No scroll listener: prompt boxes are pinned, and measuring on every scroll
  // frame of a streaming answer is what made chats stutter.
  window.addEventListener("resize", schedule, { signal });
  document.addEventListener("focusin", schedule, { capture: true, signal });
  const interval = setInterval(() => {
    if (!alive()) { if (toastEl.hidden) teardown(); return; } // extension removed or reloaded
    if (document.visibilityState === "visible") schedule();
  }, 1200);

  function teardown() {
    lifetime.abort();
    clearInterval(interval);
    clearTimeout(toastTimer);
    resizeObserver.disconnect();
    host.remove();
  }
  document.addEventListener("memty:teardown", teardown, { once: true, signal });
  schedule();
})();
