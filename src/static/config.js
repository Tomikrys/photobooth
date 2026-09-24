// ── Custom dropdown ───────────────────────────────────────────────────────────
// State: { id -> { value, display } }
const _selectState = {};

function toggleDropdown(id) {
  const dd = document.getElementById(id + "-dropdown");
  const isOpen = dd.classList.contains("open");
  // Close all dropdowns first
  document.querySelectorAll(".custom-select-dropdown.open").forEach(el => el.classList.remove("open"));
  if (!isOpen) dd.classList.add("open");
}

// Close dropdowns when clicking outside
document.addEventListener("click", e => {
  if (!e.target.closest(".custom-select-wrap")) {
    document.querySelectorAll(".custom-select-dropdown.open").forEach(el => el.classList.remove("open"));
  }
});

function buildDropdown(id, options, current) {
  const display = document.getElementById(id + "-display");
  const dropdown = document.getElementById(id + "-dropdown");
  dropdown.innerHTML = "";

  if (!options.length) {
    // No live devices — show .env value as a passive hint, don't pretend it's selectable
    const label = current ? current + " (nepripojeno)" : "— nenalezeno —";
    display.textContent = label;
    _selectState[id] = { value: current || "", display: label };
    const opt = document.createElement("div");
    opt.className = "custom-select-option" + (current ? " selected" : "");
    opt.textContent = label;
    opt.dataset.val = current || "";
    opt.onclick = () => pickOption(id, current || "", label);
    dropdown.appendChild(opt);
    return;
  }

  // Devices found — auto-select best match: exact, partial, or first in list
  const selected = options.find(o => o === current)
    || options.find(o => current && o.includes(current))
    || options.find(o => current && current.includes(o))
    || options[0];

  display.textContent = selected;
  _selectState[id] = { value: selected, display: selected };

  options.forEach(o => {
    const opt = document.createElement("div");
    opt.className = "custom-select-option" + (o === selected ? " selected" : "");
    opt.textContent = o;
    opt.dataset.val = o;
    opt.onclick = () => pickOption(id, o, o);
    dropdown.appendChild(opt);
  });
}

function pickOption(id, value, label) {
  _selectState[id] = { value, display: label };
  document.getElementById(id + "-display").textContent = label;
  document.getElementById(id + "-dropdown").classList.remove("open");
  document.querySelectorAll(`#${id}-dropdown .custom-select-option`).forEach(el => {
    el.classList.toggle("selected", el.dataset.val === value);
  });
  if (id === "camera-device") loadMtpFolders();
}

function getSelectValue(id) {
  return _selectState[id]?.value || "";
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function showBanner(msg, ok) {
  const b = document.getElementById("banner");
  b.textContent = msg;
  b.className = `rounded px-4 py-2 mb-4 text-sm text-center ${ok ? "bg-green-900 text-green-300" : "bg-red-900 text-red-300"}`;
  b.classList.remove("hidden");
  setTimeout(() => b.classList.add("hidden"), 4000);
}

const PLACEHOLDER_VALUES = new Set(["Načítám…", "— nenalezeno —", "— vyberte zařízení —", "Chyba načítání", ""]);

// ── Load current config ───────────────────────────────────────────────────────
let _cfg = {};

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    _cfg = await res.json();
  } catch {
    showBanner("✗ Nepodařilo se načíst konfiguraci", false);
    return;
  }

  const textFields = [
    "SMTP_SERVER","SMTP_PORT","SMTP_USER","SMTP_PASS",
    "IMAP_SERVER","IMAP_POLL_INTERVAL","IMAP_USER","IMAP_PASS",
    "CAMERA_DIR","RAW_DIR","PROCESSED_DIR","THUMBS_DIR","PRINTED_DIR","HIDDEN_DIR","EMAIL_QUEUE_PATH",
    "WEDDING_NAMES","WEDDING_YEAR","EMAIL_SUBJECT","EMAIL_BODY",
  ];
  textFields.forEach(k => {
    const el = document.getElementById(k);
    if (el) el.value = _cfg[k] || "";
  });

  const names = _cfg.WEDDING_NAMES || "";
  const year  = _cfg.WEDDING_YEAR  || "";
  const sub = document.getElementById("config-subtitle");
  if (sub && names) sub.textContent = "FOTO KOUTEK — " + names + (year ? " " + year : "");

  await Promise.all([loadPrinters(), loadMtpDevices()]);
}

// ── Printer ───────────────────────────────────────────────────────────────────
async function loadPrinters() {
  document.getElementById("printer-display").textContent = "Načítám…";
  try {
    const res = await fetch("/api/config/printers");
    const list = await res.json();
    buildDropdown("printer", list, _cfg.PRINTER_NAME || "");
  } catch {
    document.getElementById("printer-display").textContent = "Chyba načítání";
  }
}

// ── MTP devices ───────────────────────────────────────────────────────────────
async function loadMtpDevices() {
  document.getElementById("camera-device-display").textContent = "Načítám…";
  try {
    const res = await fetch("/api/config/mtp-devices");
    const list = await res.json();
    buildDropdown("camera-device", list, _cfg.CAMERA_NAME || "");
    await loadMtpFolders();
  } catch {
    document.getElementById("camera-device-display").textContent = "Chyba načítání";
  }
}

async function loadMtpFolders() {
  const device = getSelectValue("camera-device");
  if (!device || PLACEHOLDER_VALUES.has(device)) {
    document.getElementById("camera-folder-display").textContent = "— vyberte zařízení —";
    _selectState["camera-folder"] = { value: "", display: "— vyberte zařízení —" };
    document.getElementById("camera-folder-dropdown").innerHTML = "";
    return;
  }
  document.getElementById("camera-folder-display").textContent = "Načítám…";
  try {
    const res = await fetch(`/api/config/mtp-folders?device=${encodeURIComponent(device)}`);
    const list = await res.json();
    buildDropdown("camera-folder", list, _cfg.CAMERA_FOLDER_PATTERN || "");
  } catch {
    document.getElementById("camera-folder-display").textContent = "Chyba načítání";
  }
}

// ── Restart NikonMove ─────────────────────────────────────────────────────────
async function restartNikon() {
  const status = document.getElementById("nikon-status");
  status.textContent = "Restartuji…";
  try {
    await fetch("/api/config/restart-nikon", { method: "POST" });
    status.style.color = "#86efac";
    status.textContent = "✓ NikonMove restarted";
    setTimeout(() => { status.textContent = ""; }, 3000);
  } catch {
    status.style.color = "#f87171";
    status.textContent = "✗ Chyba restartu";
  }
}

// ── Save ──────────────────────────────────────────────────────────────────────
async function saveConfig() {
  const data = {};

  const printer = getSelectValue("printer");
  if (printer && !PLACEHOLDER_VALUES.has(printer)) data.PRINTER_NAME = printer;

  const device = getSelectValue("camera-device");
  if (device && !PLACEHOLDER_VALUES.has(device)) data.CAMERA_NAME = device;

  const folder = getSelectValue("camera-folder");
  if (folder && !PLACEHOLDER_VALUES.has(folder)) data.CAMERA_FOLDER_PATTERN = folder;

  [
    "SMTP_SERVER","SMTP_PORT","SMTP_USER","SMTP_PASS",
    "IMAP_SERVER","IMAP_POLL_INTERVAL","IMAP_USER","IMAP_PASS",
    "CAMERA_DIR","RAW_DIR","PROCESSED_DIR","THUMBS_DIR","PRINTED_DIR","HIDDEN_DIR",
  ].forEach(k => {
    const el = document.getElementById(k);
    if (!el) return;
    if (k.endsWith("_PASS") && !el.value) return;
    data[k] = el.value;
  });

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const r = await res.json();
    if (r.ok) {
      showBanner("✓ Nastavení uloženo a aplikováno.", true);
      _cfg = { ..._cfg, ...data };
    } else {
      showBanner("✗ Chyba při ukládání: " + (r.error || "?"), false);
    }
  } catch {
    showBanner("✗ Chyba spojení", false);
  }
}

// ── Log level custom select ───────────────────────────────────────────────────
let _currentLogLevel = "INFO";

function pickLogLevel(level) {
  _currentLogLevel = level;
  document.getElementById("log-level-display").textContent = level;
  document.getElementById("log-level-dropdown").classList.remove("open");
  document.querySelectorAll("#log-level-dropdown .custom-select-option").forEach(el => {
    el.classList.toggle("selected", el.dataset.val === level);
  });
  fetch("/api/config/log-level", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level }),
  });
}

// ── Logs ──────────────────────────────────────────────────────────────────────
const LEVEL_COLORS = { DEBUG: "log-DEBUG", INFO: "log-INFO", WARNING: "log-WARNING", ERROR: "log-ERROR" };
let _lastLogCount = 0;

const HTTP_NOISE = /werkzeug.*GET \/api\/logs|GET \/api\/logs HTTP/;

async function loadLogs(force) {
  try {
    const res = await fetch("/api/logs");
    const lines = await res.json();
    if (!force && lines.length === _lastLogCount) return;
    _lastLogCount = lines.length;

    const filterHttp = document.getElementById("log-filter-http")?.checked;
    const filtered = filterHttp
      ? lines.filter(l => !HTTP_NOISE.test(l.msg) && !(l.name === "werkzeug" && l.msg.includes("GET /api/logs")))
      : lines;

    const box = document.getElementById("log-box");
    box.innerHTML = filtered.map(l =>
      `<div class="log-line ${LEVEL_COLORS[l.level] || ""}">[${l.t}] ${l.level.padEnd(7)} ${l.name}: ${l.msg}</div>`
    ).join("");

    if (document.getElementById("log-autoscroll").checked) {
      box.scrollTop = box.scrollHeight;
    }
  } catch {}
}

// ── Init ──────────────────────────────────────────────────────────────────────
// Set data-val on static log-level options for the selected state tracking
document.querySelectorAll("#log-level-dropdown .custom-select-option").forEach(el => {
  if (!el.dataset.val) el.dataset.val = el.textContent.trim();
});

loadConfig();
loadLogs(true);
setInterval(loadLogs, 2000);
