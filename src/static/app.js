const socket = io();
let photos = [];       // [{filename, thumb, timestamp}, ...]
let currentIndex = 0;
let copiesCount = 1;
let toastTimer = null;
let toastFilename = null;

// ── Socket.IO ──────────────────────────────────────────────────────────────
socket.on("new_photo", (photo) => {
  const lightboxOpen = document.getElementById("lightbox").classList.contains("open");
  photos.unshift(photo);
  if (lightboxOpen) currentIndex++;  // keep same photo selected — new one was prepended
  renderGallery();
  if (lightboxOpen) renderFilmstrip();
  showToast(photo);
});

socket.on("photo_hidden", ({ filename }) => {
  const removedIdx = photos.findIndex(p => p.filename === filename);
  photos = photos.filter(p => p.filename !== filename);
  const lightboxOpen = document.getElementById("lightbox").classList.contains("open");
  if (lightboxOpen && removedIdx >= 0) {
    if (photos.length === 0) {
      closeLightbox();
    } else if (removedIdx === currentIndex) {
      // Removed the currently-viewed photo — show newer (same index, which is now the next-newer)
      // If we were on the newest, fall back to the previous (older) one
      if (currentIndex >= photos.length) currentIndex = photos.length - 1;
      renderLightbox();
    } else if (removedIdx < currentIndex) {
      currentIndex--;
      renderLightbox();
    } else {
      renderFilmstrip();
    }
  }
  renderGallery();
});

// ── Boot ───────────────────────────────────────────────────────────────────
async function loadPhotos() {
  try {
    const res = await fetch("/api/photos");
    photos = await res.json();
    renderGallery();
  } catch (e) {
    console.error("Failed to load photos:", e);
  }
}

// ── Gallery ────────────────────────────────────────────────────────────────
function renderGallery() {
  const gallery = document.getElementById("gallery");
  const empty = document.getElementById("empty-msg");
  empty.style.display = photos.length ? "none" : "block";
  gallery.innerHTML = photos.map((p, i) => `
    <div class="cursor-pointer rounded overflow-hidden border border-gray-800 hover:border-yellow-700 transition"
         onclick="openLightbox(${i})">
      <img src="${encodeURI(p.thumb)}" class="w-full aspect-[3/2] object-cover" loading="lazy" alt="">
    </div>`).join("");
}

// ── Lightbox ───────────────────────────────────────────────────────────────
function openLightbox(index) {
  currentIndex = index;
  copiesCount = 1;
  document.getElementById("copies-count").textContent = 1;
  document.getElementById("lightbox").classList.add("open");
  renderLightbox();
}

function closeLightbox() {
  document.getElementById("lightbox").classList.remove("open");
}

function renderLightbox() {
  const photo = photos[currentIndex];
  document.getElementById("photo-main").src = `/photos/processed/${encodeURIComponent(photo.filename)}`;
  renderFilmstrip();
}

function renderFilmstrip() {
  const strip = document.getElementById("filmstrip");
  strip.innerHTML = photos.map((p, i) => `
    <img src="${encodeURI(p.thumb)}"
         class="filmstrip-item h-full aspect-[3/2] object-cover rounded cursor-pointer flex-shrink-0 ${i === currentIndex ? "active" : "opacity-50"}"
         onclick="openLightbox(${i})" alt="">`).join("");
  // scroll active into view
  const active = strip.querySelectorAll("img")[currentIndex];
  if (active) active.scrollIntoView({ block: "nearest", inline: "center" });
}

document.getElementById("close-btn").addEventListener("click", closeLightbox);

document.getElementById("prev-btn").addEventListener("click", () => {
  if (currentIndex > 0) { currentIndex--; renderLightbox(); }
});

document.getElementById("next-btn").addEventListener("click", () => {
  if (currentIndex < photos.length - 1) { currentIndex++; renderLightbox(); }
});

document.addEventListener("keydown", (e) => {
  if (emailModal.style.display === "flex") {
    if (e.key === "Escape") closeEmailModal();
    if (e.key === "Enter" && !emailSendBtn.disabled) emailSendBtn.click();
    return;  // don't fall through to lightbox nav while modal is open
  }
  if (!document.getElementById("lightbox").classList.contains("open")) return;
  if (e.key === "ArrowLeft")  document.getElementById("prev-btn").click();
  if (e.key === "ArrowRight") document.getElementById("next-btn").click();
  if (e.key === "Escape")     closeLightbox();
});

// ── Zoom on hold with pan ──────────────────────────────────────────────────
const photoEl = document.getElementById("photo-main");
function zoomAt(clientX, clientY) {
  const rect = photoEl.getBoundingClientRect();
  const x = ((clientX - rect.left) / rect.width) * 100;
  const y = ((clientY - rect.top) / rect.height) * 100;
  photoEl.style.transformOrigin = `${x}% ${y}%`;
  photoEl.classList.add("zoomed");
}
function unzoom() {
  photoEl.classList.remove("zoomed");
}
photoEl.addEventListener("mousedown", (e) => { e.preventDefault(); zoomAt(e.clientX, e.clientY); });
photoEl.addEventListener("mousemove", (e) => { if (photoEl.classList.contains("zoomed")) zoomAt(e.clientX, e.clientY); });
photoEl.addEventListener("mouseup",    unzoom);
photoEl.addEventListener("mouseleave", unzoom);

// Touch: tap to toggle zoom; swipe left/right to navigate
let _touchStartX = null;
let _touchStartY = null;
let _touchStartTime = null;
let _zoomOriginX = null;
let _zoomOriginY = null;

photoEl.addEventListener("touchstart", (e) => {
  const t = e.touches[0];
  _touchStartX = t.clientX;
  _touchStartY = t.clientY;
  _touchStartTime = Date.now();
  _zoomOriginX = t.clientX;
  _zoomOriginY = t.clientY;
}, { passive: true });

photoEl.addEventListener("touchmove", (e) => {
  if (!photoEl.classList.contains("zoomed")) return;
  const t = e.touches[0];
  zoomAt(t.clientX, t.clientY);
}, { passive: true });

photoEl.addEventListener("touchend", (e) => {
  const dt = Date.now() - _touchStartTime;
  const dx = e.changedTouches[0].clientX - _touchStartX;
  const dy = e.changedTouches[0].clientY - _touchStartY;
  const dist = Math.sqrt(dx * dx + dy * dy);

  if (photoEl.classList.contains("zoomed")) {
    // Any touch-end unzooms
    unzoom();
    return;
  }

  // Tap (short + small movement) → zoom in
  if (dt < 300 && dist < 15) {
    zoomAt(_zoomOriginX, _zoomOriginY);
    return;
  }

  // Swipe (horizontal dominant, fast enough)
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5 && dt < 400) {
    if (dx < 0 && currentIndex < photos.length - 1) { currentIndex++; renderLightbox(); }
    if (dx > 0 && currentIndex > 0)                 { currentIndex--; renderLightbox(); }
  }
});

// ── Copies stepper ─────────────────────────────────────────────────────────
document.getElementById("copies-minus").addEventListener("click", () => {
  if (copiesCount > 1) { copiesCount--; document.getElementById("copies-count").textContent = copiesCount; }
});
document.getElementById("copies-plus").addEventListener("click", () => {
  copiesCount++;
  document.getElementById("copies-count").textContent = copiesCount;
});

// ── Print ──────────────────────────────────────────────────────────────────
document.getElementById("print-btn").addEventListener("click", async () => {
  const photo = photos[currentIndex];
  const btn = document.getElementById("print-btn");
  const spinner = document.getElementById("print-spinner");
  const label = document.getElementById("print-label");

  btn.disabled = true;
  spinner.classList.remove("hidden");
  label.textContent = "Tisknu…";

  try {
    const res = await fetch("/api/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: photo.filename, copies: copiesCount }),
    });
    const data = await res.json();
    showToastMsg(data.ok ? `✓ Tisk zahájen (${copiesCount}×)` : `✗ Chyba tisku: ${data.error}`, data.ok);
  } catch (e) {
    showToastMsg("✗ Chyba připojení k tiskárně", false);
  } finally {
    btn.disabled = false;
    spinner.classList.add("hidden");
    label.textContent = "🖨 TISKNOUT";
  }
});

// ── Email modal ────────────────────────────────────────────────────────────
const emailModal   = document.getElementById("email-modal");
const emailInput   = document.getElementById("email-modal-input");
const emailStatus  = document.getElementById("email-modal-status");
const emailSendBtn = document.getElementById("email-modal-send");
const emailSpinner = document.getElementById("email-modal-spinner");
const emailSendLbl = document.getElementById("email-modal-send-label");

function openEmailModal() {
  emailInput.value = "";
  emailStatus.textContent = "";
  emailStatus.className = "text-xs text-center mt-3 min-h-4";
  setEmailBusy(false);
  emailModal.style.display = "flex";
  setTimeout(() => emailInput.focus(), 50);
}
function closeEmailModal() {
  if (emailSendBtn.disabled) return;  // don't close while sending
  emailModal.style.display = "none";
}
function setEmailBusy(busy) {
  emailSendBtn.disabled = busy;
  emailSpinner.classList.toggle("hidden", !busy);
  emailSendLbl.textContent = busy ? "Odesílám…" : "Odeslat";
  emailInput.disabled = busy;
  document.getElementById("email-modal-cancel").disabled = busy;
  document.getElementById("email-modal-close").style.pointerEvents = busy ? "none" : "auto";
}

document.getElementById("email-toggle-btn").addEventListener("click", openEmailModal);
document.getElementById("email-modal-close").addEventListener("click", closeEmailModal);
document.getElementById("email-modal-cancel").addEventListener("click", closeEmailModal);
emailModal.addEventListener("click", (e) => { if (e.target === emailModal && !emailSendBtn.disabled) closeEmailModal(); });

emailSendBtn.addEventListener("click", async () => {
  const recipient = emailInput.value.trim();
  if (!recipient) {
    emailStatus.textContent = "Zadejte e-mailovou adresu.";
    emailStatus.className = "text-xs text-center mt-3 min-h-4 text-red-400";
    return;
  }
  const photo = photos[currentIndex];
  setEmailBusy(true);
  emailStatus.textContent = "";
  try {
    const res = await fetch("/api/email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: photo.filename, recipient }),
    });
    const data = await res.json();
    if (data.ok) {
      emailStatus.textContent = data.queued
        ? "📵 Není internet — e-mail odešleme automaticky po připojení"
        : "✓ E-mail odeslán";
      emailStatus.className = "text-xs text-center mt-3 min-h-4 gold";
      setEmailBusy(false);
      setTimeout(() => { emailModal.style.display = "none"; }, data.queued ? 4000 : 1600);
    } else {
      emailStatus.textContent = "✗ " + (data.error || "Chyba odeslání");
      emailStatus.className = "text-xs text-center mt-3 min-h-4 text-red-400";
      setEmailBusy(false);
    }
  } catch (e) {
    emailStatus.textContent = "✗ Chyba spojení";
    emailStatus.className = "text-xs text-center mt-3 min-h-4 text-red-400";
    setEmailBusy(false);
  }
});

// ── Hide / delete ──────────────────────────────────────────────────────────
document.getElementById("hide-btn").addEventListener("click", async () => {
  const photo = photos[currentIndex];
  // Optimistic update — remove locally immediately without waiting for socket event
  const removedIdx = currentIndex;
  photos = photos.filter(p => p.filename !== photo.filename);
  renderGallery();
  if (document.getElementById("lightbox").classList.contains("open")) {
    if (photos.length === 0) {
      closeLightbox();
    } else {
      if (currentIndex >= photos.length) currentIndex = photos.length - 1;
      renderLightbox();
    }
  }
  try {
    await fetch("/api/hide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: photo.filename }),
    });
  } catch (e) {
    console.error("Hide failed:", e);
  }
});

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(photo) {
  toastFilename = photo.filename;
  const thumb = document.getElementById("toast-thumb");
  thumb.src = photo.thumb;
  thumb.style.display = "";
  document.getElementById("toast").querySelector("p.gold").textContent = "Nová fotografie!";
  document.getElementById("toast").querySelector("p.text-gray-400").textContent = "Klikněte pro zobrazení";
  const toast = document.getElementById("toast");
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 8000);
}

document.getElementById("toast").addEventListener("click", () => {
  if (toastFilename) {
    const idx = photos.findIndex(p => p.filename === toastFilename);
    if (idx >= 0) openLightbox(idx);
  }
  document.getElementById("toast").classList.remove("show");
});

function showToastMsg(msg, ok) {
  document.getElementById("toast-thumb").style.display = "none";
  document.getElementById("toast").querySelector("p.gold").textContent = ok ? "✓ " + msg : "✗ " + msg;
  document.getElementById("toast").querySelector("p.text-gray-400").textContent = "";
  const toast = document.getElementById("toast");
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 4000);
}

// ── Init ───────────────────────────────────────────────────────────────────
loadPhotos();

// Poll every 10s as a safety net for missed socket events (e.g. browser opened
// before the socket handshake completed, or a transient disconnect).
setInterval(async () => {
  try {
    const res = await fetch("/api/photos");
    const fresh = await res.json();
    const oldKeys = photos.map(p => p.filename).join(",");
    const newKeys = fresh.map(p => p.filename).join(",");
    if (oldKeys === newKeys) return;

    // Preserve lightbox position by filename, not index
    const lightboxOpen = document.getElementById("lightbox").classList.contains("open");
    const currentFilename = lightboxOpen && photos[currentIndex] ? photos[currentIndex].filename : null;
    photos = fresh;
    if (lightboxOpen) {
      const newIdx = currentFilename ? photos.findIndex(p => p.filename === currentFilename) : -1;
      currentIndex = newIdx >= 0 ? newIdx : 0;
      renderLightbox();
    }
    renderGallery();
  } catch (_) {}
}, 10000);
