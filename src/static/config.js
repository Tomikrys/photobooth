// ── Helpers ────────────────────────────────────────────────────────────────
function showBanner(msg, ok) {
  const b = document.getElementById("banner");
  b.textContent = msg;
  b.className = `rounded px-4 py-2 mb-4 text-sm text-center ${ok ? "bg-green-900 text-green-300" : "bg-red-900 text-red-300"}`;
  b.classList.remove("hidden");
  setTimeout(() => b.classList.add("hidden"), 4000);
}

function setSelectOptions(selectEl, options, current) {
  selectEl.innerHTML = "";
  if (!options.length) {
    // Keep the current known value so a failed enumeration doesn't overwrite it on save
    const val = current || "";
    selectEl.innerHTML = val
      ? `<option value="${val}">${val} (z .env)</option>`
      : '<option value="">— nenalezeno —</option>';
    return;
  }
  options.forEach(o => {
    const opt = document.createElement("option");
    opt.value = o;
    opt.textContent = o;
    if (o === current) opt.selected = true;
    selectEl.appendChild(opt);
  });
  // If nothing matched current, add it as first option so it's preserved on save
  if (current && !options.includes(current)) {
    const opt = document.createElement("option");
    opt.value = current;
    opt.textContent = current + " (z .env)";
    opt.selected = true;
    selectEl.prepend(opt);
  }
}

const PLACEHOLDER_VALUES = new Set(["Načítám…", "— nenalezeno —", "Chyba načítání", ""]);

// ── Load current config ─────────────────────────────────────────────────────
let _cfg = {};

async function loadConfig() {
  const res = await fetch("/api/config");
  _cfg = await res.json();

  // Text/password fields — fill directly from .env values
  const textFields = [
    "SMTP_SERVER","SMTP_PORT","SMTP_USER","SMTP_PASS",
    "IMAP_SERVER","IMAP_POLL_INTERVAL","IMAP_USER","IMAP_PASS",
    "CAMERA_DIR","RAW_DIR","PROCESSED_DIR","THUMBS_DIR","PRINTED_DIR","HIDDEN_DIR",
  ];
  textFields.forEach(k => {
    const el = document.getElementById(k);
    if (el) el.value = _cfg[k] || "";
  });

  await Promise.all([loadPrinters(), loadMtpDevices()]);
}

// ── Printer ─────────────────────────────────────────────────────────────────
async function loadPrinters() {
  const sel = document.getElementById("printer-select");
  sel.innerHTML = '<option>Načítám…</option>';
  try {
    const res = await fetch("/api/config/printers");
    const list = await res.json();
    setSelectOptions(sel, list, _cfg.PRINTER_NAME || "");
  } catch {
    sel.innerHTML = '<option value="">Chyba načítání</option>';
  }
}

// ── MTP devices ─────────────────────────────────────────────────────────────
async function loadMtpDevices() {
  const sel = document.getElementById("camera-device-select");
  sel.innerHTML = '<option>Načítám…</option>';
  try {
    const res = await fetch("/api/config/mtp-devices");
    const list = await res.json();
    setSelectOptions(sel, list, _cfg.CAMERA_NAME || "");
    await loadMtpFolders();
  } catch {
    sel.innerHTML = '<option value="">Chyba načítání</option>';
  }
}

async function onDeviceChange() {
  await loadMtpFolders();
}

async function loadMtpFolders() {
  const deviceSel = document.getElementById("camera-device-select");
  const folderSel = document.getElementById("camera-folder-select");
  const device = deviceSel.value;
  if (!device || device === "Načítám…" || device === "— nenalezeno —") {
    folderSel.innerHTML = '<option value="">— vyberte zařízení —</option>';
    return;
  }
  folderSel.innerHTML = '<option>Načítám…</option>';
  try {
    const res = await fetch(`/api/config/mtp-folders?device=${encodeURIComponent(device)}`);
    const list = await res.json();
    setSelectOptions(folderSel, list, _cfg.CAMERA_FOLDER_PATTERN || "");
  } catch {
    folderSel.innerHTML = '<option value="">Chyba načítání</option>';
  }
}

// ── Restart NikonMove ───────────────────────────────────────────────────────
async function restartNikon() {
  const status = document.getElementById("nikon-status");
  status.textContent = "Restartuji…";
  try {
    await fetch("/api/config/restart-nikon", { method: "POST" });
    status.textContent = "✓ NikonMove restarted";
    setTimeout(() => status.textContent = "", 3000);
  } catch {
    status.textContent = "✗ Chyba restartu";
  }
}

// ── Save ────────────────────────────────────────────────────────────────────
async function saveConfig() {
  const data = {};

  // Printer
  const printerSel = document.getElementById("printer-select");
  if (printerSel.value && !PLACEHOLDER_VALUES.has(printerSel.value)) data.PRINTER_NAME = printerSel.value;

  // Camera
  const deviceSel = document.getElementById("camera-device-select");
  const folderSel = document.getElementById("camera-folder-select");
  if (deviceSel.value && !PLACEHOLDER_VALUES.has(deviceSel.value)) data.CAMERA_NAME = deviceSel.value;
  if (folderSel.value && !PLACEHOLDER_VALUES.has(folderSel.value)) data.CAMERA_FOLDER_PATTERN = folderSel.value;

  // Text/password fields — skip password fields if left empty (don't blank real creds)
  [
    "SMTP_SERVER","SMTP_PORT","SMTP_USER","SMTP_PASS",
    "IMAP_SERVER","IMAP_POLL_INTERVAL","IMAP_USER","IMAP_PASS",
    "CAMERA_DIR","RAW_DIR","PROCESSED_DIR","THUMBS_DIR","PRINTED_DIR","HIDDEN_DIR",
  ].forEach(k => {
    const el = document.getElementById(k);
    if (!el) return;
    const isPassword = k.endsWith("_PASS");
    if (isPassword && !el.value) return; // don't overwrite with empty
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
  } catch (e) {
    showBanner("✗ Chyba spojení", false);
  }
}

// ── Logs ────────────────────────────────────────────────────────────────────
const LEVEL_COLORS = { DEBUG: "log-DEBUG", INFO: "log-INFO", WARNING: "log-WARNING", ERROR: "log-ERROR" };
let _lastLogCount = 0;

async function loadLogs() {
  try {
    const res = await fetch("/api/logs");
    const lines = await res.json();
    if (lines.length === _lastLogCount) return;
    _lastLogCount = lines.length;

    const box = document.getElementById("log-box");
    box.innerHTML = lines.map(l =>
      `<div class="log-line ${LEVEL_COLORS[l.level] || ""}">[${l.t}] ${l.level.padEnd(7)} ${l.name}: ${l.msg}</div>`
    ).join("");

    if (document.getElementById("log-autoscroll").checked) {
      box.scrollTop = box.scrollHeight;
    }
  } catch {}
}

async function setLogLevel() {
  const level = document.getElementById("log-level-select").value;
  await fetch("/api/config/log-level", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level }),
  });
}

// ── Init ────────────────────────────────────────────────────────────────────
loadConfig();
loadLogs();
setInterval(loadLogs, 2000);
