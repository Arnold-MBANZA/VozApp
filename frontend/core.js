(() => {
  const base = String(window.VOZLOCAL_CONFIG?.apiBaseUrl || "").replace(/\/$/, "");
  const tokenKey = "vozlocal_session";
  let toastTimer;

  const token = () => localStorage.getItem(tokenKey) || "";
  const storeSession = (value) => localStorage.setItem(tokenKey, value);
  const clearSession = () => localStorage.removeItem(tokenKey);

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (token()) headers.set("Authorization", `Bearer ${token()}`);
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    let response;
    try {
      response = await fetch(`${base}${path}`, { ...options, headers });
    } catch (_) {
      throw new Error("Le serveur de transcription est inaccessible. Vérifiez qu’il est allumé.");
    }
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      if (response.status === 401) clearSession();
      throw new Error(payload?.detail || `Erreur ${response.status}`);
    }
    return payload;
  }

  async function download(path, fallback) {
    const headers = token() ? { Authorization: `Bearer ${token()}` } : {};
    let response;
    try { response = await fetch(`${base}${path}`, { headers }); }
    catch (_) { throw new Error("Téléchargement impossible : serveur inaccessible."); }
    if (!response.ok) {
      let message = "Téléchargement impossible.";
      try { message = (await response.json()).detail || message; } catch (_) {}
      throw new Error(message);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
    const name = match ? decodeURIComponent(match[1].replace(/\"/g, "")) : fallback;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = name; document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function blobUrl(path) {
    const response = await fetch(`${base}${path}`, { headers: { Authorization: `Bearer ${token()}` } });
    if (!response.ok) throw new Error("Audio indisponible.");
    return URL.createObjectURL(await response.blob());
  }

  function formatBytes(bytes = 0) {
    if (!bytes) return "0 Mo";
    const units = ["o", "Ko", "Mo", "Go"];
    const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 3);
    return `${(bytes / 1024 ** exponent).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} ${units[exponent]}`;
  }
  function formatDate(value) {
    if (!value) return "—";
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
  }
  function formatDuration(seconds) {
    if (!seconds) return "—";
    const rounded = Math.round(seconds), hours = Math.floor(rounded / 3600), minutes = Math.floor((rounded % 3600) / 60), secs = rounded % 60;
    return hours ? `${hours} h ${String(minutes).padStart(2,"0")} min` : `${minutes} min ${String(secs).padStart(2,"0")} s`;
  }
  function initials(name = "") { return name.split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]).join("").toUpperCase() || "U"; }
  function escape(value = "") { const div = document.createElement("div"); div.textContent = String(value); return div.innerHTML; }
  function toast(message, error = false) {
    const element = document.getElementById("toast");
    if (!element) return;
    clearTimeout(toastTimer); element.textContent = message; element.className = `toast show${error ? " error" : ""}`;
    toastTimer = setTimeout(() => element.className = "toast", 3600);
  }
  async function requireUser(admin = false) {
    if (!token()) { location.href = "/login"; return null; }
    try {
      const result = await api("/api/auth/me");
      if (admin && result.user.role !== "admin") { location.href = "/app"; return null; }
      return result.user;
    } catch (_) { location.href = "/login"; return null; }
  }
  async function logout() {
    try { await api("/api/auth/logout", { method: "POST" }); } catch (_) {}
    clearSession(); location.href = "/login";
  }
  function bindShell() {
    document.getElementById("logout-button")?.addEventListener("click", logout);
    const sidebar = document.getElementById("sidebar");
    document.getElementById("sidebar-toggle")?.addEventListener("click", () => sidebar?.classList.toggle("open"));
    sidebar?.querySelectorAll("a").forEach(link => link.addEventListener("click", () => sidebar.classList.remove("open")));
  }
  window.Voz = { base, token, storeSession, clearSession, api, download, blobUrl, formatBytes, formatDate, formatDuration, initials, escape, toast, requireUser, logout, bindShell };
})();
