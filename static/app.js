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
  if (lightboxOpen && removedIdx >= 0 && removedIdx < currentIndex) currentIndex--;
  renderGallery();
  if (lightboxOpen) renderFilmstrip();
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
      <img src="${p.thumb}" class="w-full aspect-[3/2] object-cover" loading="lazy" alt="">
    </div>`).join("");
}

// ── Lightbox ───────────────────────────────────────────────────────────────
function openLightbox(index) {
  currentIndex = index;
  copiesCount = 1;
  document.getElementById("copies-count").textContent = 1;
  document.getElementById("email-form").style.display = "none";
  document.getElementById("lightbox").classList.add("open");
  renderLightbox();
}

function closeLightbox() {
  document.getElementById("lightbox").classList.remove("open");
}

function renderLightbox() {
  const photo = photos[currentIndex];
  document.getElementById("photo-main").src = `/photos/processed/${photo.filename}`;
  renderFilmstrip();
}

function renderFilmstrip() {
  const strip = document.getElementById("filmstrip");
  strip.innerHTML = photos.map((p, i) => `
    <img src="${p.thumb}"
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
photoEl.addEventListener("touchstart", (e) => { const t = e.touches[0]; zoomAt(t.clientX, t.clientY); }, { passive: true });
photoEl.addEventListener("touchmove",  (e) => { const t = e.touches[0]; zoomAt(t.clientX, t.clientY); }, { passive: true });
photoEl.addEventListener("touchend",   unzoom);

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
  try {
    const res = await fetch("/api/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: photo.filename, copies: copiesCount }),
    });
    const data = await res.json();
    showToastMsg(data.ok ? `Tisk zahájen (${copiesCount}×)` : `Chyba tisku: ${data.error}`, data.ok);
  } catch (e) {
    showToastMsg("Chyba připojení k tiskárně", false);
  }
});

// ── Email ──────────────────────────────────────────────────────────────────
document.getElementById("email-toggle-btn").addEventListener("click", () => {
  const ef = document.getElementById("email-form");
  ef.style.display = ef.style.display === "none" ? "flex" : "none";
});

document.getElementById("email-send-btn").addEventListener("click", async () => {
  const photo = photos[currentIndex];
  const recipient = document.getElementById("email-input").value.trim();
  if (!recipient) return;
  try {
    const res = await fetch("/api/email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: photo.filename, recipient }),
    });
    const data = await res.json();
    showToastMsg(data.ok ? "E-mail odeslán!" : `Chyba: ${data.error}`, data.ok);
    if (data.ok) document.getElementById("email-form").style.display = "none";
  } catch (e) {
    showToastMsg("Chyba při odesílání e-mailu", false);
  }
});

// ── Hide / delete ──────────────────────────────────────────────────────────
document.getElementById("hide-btn").addEventListener("click", async () => {
  const photo = photos[currentIndex];
  try {
    await fetch("/api/hide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: photo.filename }),
    });
  } catch (e) {
    console.error("Hide failed:", e);
  }
  closeLightbox();
});

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(photo) {
  toastFilename = photo.filename;
  document.getElementById("toast-thumb").src = photo.thumb;
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
  document.getElementById("toast-thumb").src = "";
  document.getElementById("toast").querySelector("p.gold").textContent = ok ? "✓ " + msg : "✗ " + msg;
  document.getElementById("toast").querySelector("p.text-gray-400").textContent = "";
  const toast = document.getElementById("toast");
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 4000);
}

// ── Init ───────────────────────────────────────────────────────────────────
loadPhotos();
