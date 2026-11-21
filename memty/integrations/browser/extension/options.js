// Memty fact manager: view, edit, delete, and add the facts Memty shares with chat AIs.
// Talks only to the local bridge on 127.0.0.1; private values never come back from it.
const $ = (id) => document.getElementById(id);
const NEW_NAMESPACE = "__new__";
let settings = { port: 8765, token: "", namespace: "" };
let facts = [];

const status = (text, kind = "") => { $("status").textContent = text; $("status").className = `status ${kind}`; };
const base = () => `http://127.0.0.1:${Number(settings.port) || 8765}`;
const label = (slot) => {
  slot = slot.replace(/__c[0-9a-f]{12}$/, "");
  if (/^(?:note|fact)_[0-9a-f]{6,}$/.test(slot)) return "Note";
  const text = slot.replace(/_\d+$/, "").replace(/[_.]+/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};
const toSlot = (title) => title.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);
const ago = (ms) => {
  const minutes = Math.round((Date.now() - ms) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return new Date(ms).toLocaleDateString();
};

async function pair() {
  const response = await fetch(`${base()}/pair`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.token) {
    throw Object.assign(new Error(body.message || `HTTP ${response.status}`), { code: body.error });
  }
  settings.token = body.token;
  await chrome.storage.local.set({ token: body.token });
}

async function api(path, body) {
  if (!settings.token) await pair();
  const send = () => fetch(`${base()}${path}`, {
    method: body ? "POST" : "GET",
    headers: { Authorization: `Bearer ${settings.token}`, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  let response = await send();
  if (response.status === 401) { await pair(); response = await send(); } // token was rotated
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw Object.assign(new Error(data.message || data.error || `HTTP ${response.status}`), { code: data.error });
  }
  return data;
}

async function loadNamespaces() {
  const { namespaces, counts = {} } = await api("/namespaces");
  if (!settings.namespace) {
    const [best] = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    settings.namespace = best ? best[0] : "personal";
    await chrome.storage.local.set({ namespace: settings.namespace });
  }
  const names = [...new Set([...namespaces, settings.namespace])].sort();
  $("namespace").replaceChildren(
    ...names.map((name) => new Option(`${name} (${counts[name] || 0})`, name, false, name === settings.namespace)),
    new Option("＋ New namespace…", NEW_NAMESPACE));
}

async function loadFacts() {
  ({ facts } = await api(`/facts?${new URLSearchParams({ namespace: settings.namespace })}`));
  render();
}

function row(fact) {
  const isSecret = fact?.sensitivity === "SECRET";
  const el = document.createElement("div");
  el.className = fact ? (isSecret ? "fact secret" : "fact") : "fact new";
  const titleWrap = document.createElement("div");
  titleWrap.className = "title-wrap";
  const title = Object.assign(document.createElement("input"), {
    className: "title", value: fact ? label(fact.slot) : "", placeholder: "Title, e.g. Main language" });
  titleWrap.append(title);
  if (isSecret) {
    const badge = document.createElement("span");
    badge.className = "badge secret";
    badge.textContent = "Secret";
    badge.title = "Stays on this computer · Context cannot be sent to web chats";
    titleWrap.append(badge);
  }
  const value = Object.assign(document.createElement("textarea"), {
    value: isSecret ? "" : (fact?.value ?? ""), rows: 1,
    placeholder: isSecret
      ? "Secret: hidden on this computer. Type a new value to replace it."
      : (fact?.private ? "Private: hidden here. Type a new value to replace it." : "Value, e.g. Python 3.12") });
  const actions = document.createElement("div");
  actions.className = "actions";
  const privateBox = Object.assign(document.createElement("input"), {
    type: "checkbox", checked: isSecret || !!fact?.private, disabled: isSecret });
  const privateLabel = document.createElement("label");
  privateLabel.className = "private";
  privateLabel.title = isSecret
    ? "Secret facts always stay on this computer and cannot be sent to web chats"
    : "Private facts are shown to chat AIs only as [private]";
  privateLabel.append(privateBox, "Private");
  const save = Object.assign(document.createElement("button"), { className: "primary", textContent: fact ? "Save" : "Add", disabled: !!fact });
  actions.append(privateLabel, save);
  let del;
  if (fact) {
    del = Object.assign(document.createElement("button"), { className: "danger", textContent: "Delete" });
    actions.append(del);
  }
  el.append(titleWrap, value, actions);
  if (fact) {
    const meta = document.createElement("div");
    meta.className = "meta";
    const secretPrefix = isSecret ? "🔒 Secret (stays on this computer) · " : "";
    meta.textContent = `${secretPrefix}${fact.source === "you" ? "Added or confirmed by you" : "Saved from a chat"} · ${ago(fact.updated_at)}`;
    el.append(meta);
  }

  const dirty = () => {
    if (!fact) return;
    save.disabled = title.value.trim() === label(fact.slot) && value.value === (isSecret ? "" : (fact.value ?? ""))
      && privateBox.checked === (isSecret || fact.private);
  };
  [title, value].forEach((input) => input.addEventListener("input", dirty));
  privateBox.addEventListener("change", dirty);

  save.addEventListener("click", async () => {
    const titleText = title.value.trim();
    const slot = fact && titleText === label(fact.slot) ? fact.slot : toSlot(titleText);
    if (!slot) return title.focus();
    if (!fact && !value.value.trim()) return value.focus();
    save.disabled = true;
    try {
      await api("/facts/update", {
        namespace: settings.namespace, slot: fact?.slot || slot, new_slot: slot,
        value: value.value.trim() || null, private: privateBox.checked,
      });
      status(`Saved "${titleText}".`, "ok");
      await loadFacts();
    } catch (error) {
      save.disabled = false;
      status(error.message, "bad");
    }
  });
  del?.addEventListener("click", async () => {
    if (!confirm(`Delete "${label(fact.slot)}"? Memty will forget it completely, including its history.`)) return;
    try {
      await api("/facts/delete", { namespace: settings.namespace, slot: fact.slot });
      status(`Deleted "${label(fact.slot)}".`, "ok");
      await loadFacts();
    } catch (error) {
      status(error.message, "bad");
    }
  });
  return el;
}

function render() {
  $("deleteAll").disabled = !facts.length;
  const query = $("search").value.trim().toLowerCase();
  const shown = facts.filter((f) => !query || `${label(f.slot)} ${f.sensitivity === "SECRET" ? "secret" : (f.value ?? "")}`.toLowerCase().includes(query));
  $("list").replaceChildren(...shown.map(row));
  if (!shown.length) {
    $("list").append(Object.assign(document.createElement("div"), {
      className: "empty",
      textContent: facts.length ? "No facts match your search." : "No facts yet. Select text in a chat and click ＋ Save to Memty, or add one here.",
    }));
  }
}

function showConnect(error) {
  const offline = error instanceof TypeError; // fetch could not reach 127.0.0.1
  const states = {
    offline: ["Start Memty on this computer",
      "Memty isn't running. Run this once in a terminal. It also starts Memty every time you log in:",
      "memty serve --autostart", "Not installed yet? Run: pip install memty"],
    pairing_required: ["Connect this browser to Memty",
      "For your safety, Memty only talks to browsers you approve. Run this in a terminal, then click Try again:",
      "memty pair", "You need this after reinstalling the extension, or to add another browser."],
  };
  const [title, text, cmd, why] = states[offline ? "offline" : error.code] ||
    ["Couldn't reach your facts", error.message, "memty pair", ""];
  $("connectTitle").textContent = title;
  $("connectText").textContent = text;
  $("connectCmd").textContent = cmd;
  $("connectWhy").textContent = why;
  $("connect").hidden = false;
  $("app").hidden = true;
  status(offline ? "Not running" : "Not connected", "warn");
}

async function start() {
  settings = await chrome.storage.local.get({ port: 8765, token: "", namespace: "" });
  $("port").value = settings.port;
  $("token").value = settings.token;
  status("Checking Memty…");
  try {
    await loadNamespaces();
    await loadFacts();
    $("token").value = settings.token;
    $("connect").hidden = true;
    $("app").hidden = false;
    status("Connected to Memty on this computer", "ok");
  } catch (error) {
    showConnect(error);
  }
}

$("namespace").addEventListener("change", async (event) => {
  let name = event.target.value;
  if (name === NEW_NAMESPACE) {
    name = (prompt("New namespace, e.g. work.project or personal") || "").trim().toLowerCase();
    if (!name) return loadNamespaces();
  }
  settings.namespace = name;
  await chrome.storage.local.set({ namespace: name });
  await loadNamespaces();
  await loadFacts().catch((error) => status(error.message, "bad"));
});
$("search").addEventListener("input", render);
$("retry").addEventListener("click", start);
$("copyCmd").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("connectCmd").textContent);
  $("copyCmd").textContent = "Copied";
  setTimeout(() => { $("copyCmd").textContent = "Copy"; }, 1500);
});
$("add").addEventListener("click", () => {
  if ($("list").querySelector(".fact.new")) return $("list").querySelector(".fact.new .title").focus();
  const fresh = row(null);
  $("list").prepend(fresh);
  fresh.querySelector(".title").focus();
});
$("deleteAll").addEventListener("click", async () => {
  const namespace = settings.namespace;
  const count = facts.length;
  if (!count) return;
  const what = count === 1 ? "1 fact" : `all ${count} facts`;
  if (!confirm(`Delete ${what} in "${namespace}"?\n\nThis includes private facts and facts hidden by your search. ` +
      "Memty will forget them completely, including their history. This can't be undone.")) return;
  $("deleteAll").disabled = true;
  try {
    const { deleted } = await api("/facts/delete-all", { namespace, confirm: namespace });
    status(`Deleted ${deleted} fact${deleted === 1 ? "" : "s"} from "${namespace}".`, "ok");
    await loadNamespaces();
    await loadFacts();
  } catch (error) {
    status(error.message, "bad");
    render();
  }
});
$("saveConn").addEventListener("click", async () => {
  await chrome.storage.local.set({ port: Number($("port").value) || 8765, token: $("token").value.trim() });
  start();
});
start();
