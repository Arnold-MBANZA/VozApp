(() => {
  const base = String(
    window.VOZLOCAL_CONFIG?.apiBaseUrl || ""
  ).replace(/\/$/, "");

  const tokenKey = "vozlocal_session";
  let toastTimer;

  const token = () => localStorage.getItem(tokenKey) || "";

  const storeSession = (value) => {
    localStorage.setItem(tokenKey, value);
  };

  const clearSession = () => {
    localStorage.removeItem(tokenKey);
  };

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});

    headers.set("ngrok-skip-browser-warning", "true");

    if (token()) {
      headers.set("Authorization", `Bearer ${token()}`);
    }

    if (
      options.body &&
      !(options.body instanceof FormData) &&
      !headers.has("Content-Type")
    ) {
      headers.set("Content-Type", "application/json");
    }

    let response;

    try {
      response = await fetch(`${base}${path}`, {
        ...options,
        headers
      });
    } catch (_) {
      throw new Error(
        "Le serveur de transcription est inaccessible. Vérifiez qu’il est allumé."
      );
    }

    const contentType = response.headers.get("content-type") || "";

    const payload = contentType.includes("application/json")
      ? await response.json()
      : null;

    if (!response.ok) {
      if (response.status === 401) {
        clearSession();
      }

      throw new Error(payload?.detail || `Erreur ${response.status}`);
    }

    if (!contentType.includes("application/json")) {
      throw new Error(
        "Le serveur a renvoyé une réponse invalide. Vérifiez la connexion ngrok."
      );
    }

    return payload;
  }

  async function download(path, fallback) {
    const headers = {
      "ngrok-skip-browser-warning": "true"
    };

    if (token()) {
      headers.Authorization = `Bearer ${token()}`;
    }

    let response;

    try {
      response = await fetch(`${base}${path}`, { headers });
    } catch (_) {
      throw new Error(
        "Téléchargement impossible : serveur inaccessible."
      );
    }

    if (!response.ok) {
      let message = "Téléchargement impossible.";

      try {
        message = (await response.json()).detail || message;
      } catch (_) {
        // La réponse n'est pas au format JSON.
      }

      throw new Error(message);
    }

    const blob = await response.blob();
    const disposition =
      response.headers.get("content-disposition") || "";

    const match = disposition.match(
      /filename\*?=(?:UTF-8''|")?([^";]+)/i
    );

    const name = match
      ? decodeURIComponent(match[1].replace(/"/g, ""))
      : fallback;

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");

    anchor.href = url;
    anchor.download = name;

    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();

    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function blobUrl(path) {
    const headers = {
      Authorization: `Bearer ${token()}`,
      "ngrok-skip-browser-warning": "true"
    };

    let response;

    try {
      response = await fetch(`${base}${path}`, { headers });
    } catch (_) {
      throw new Error(
        "Audio indisponible : serveur inaccessible."
      );
    }

    if (!response.ok) {
      throw new Error("Audio indisponible.");
    }

    return URL.createObjectURL(await response.blob());
  }

  function formatBytes(bytes = 0) {
    if (!bytes) {
      return "0 Mo";
    }

    const units = ["o", "Ko", "Mo", "Go"];

    const exponent = Math.min(
      Math.floor(Math.log(bytes) / Math.log(1024)),
      3
    );

    return `${(bytes / 1024 ** exponent).toLocaleString("fr-FR", {
      maximumFractionDigits: 1
    })} ${units[exponent]}`;
  }

  function formatDate(value) {
    if (!value) {
      return "—";
    }

    return new Intl.DateTimeFormat("fr-FR", {
      dateStyle: "medium",
      timeStyle: "short"
    }).format(new Date(value));
  }

  function formatDay(value) {
    if (!value) {
      return "—";
    }

    const normalized = /^\d{4}-\d{2}-\d{2}$/.test(value)
      ? `${value}T12:00:00`
      : value;

    return new Intl.DateTimeFormat("fr-FR", {
      dateStyle: "medium"
    }).format(new Date(normalized));
  }

  function formatDuration(seconds) {
    if (!seconds) {
      return "—";
    }

    const rounded = Math.round(seconds);
    const hours = Math.floor(rounded / 3600);
    const minutes = Math.floor((rounded % 3600) / 60);
    const secs = rounded % 60;

    return hours
      ? `${hours} h ${String(minutes).padStart(2, "0")} min`
      : `${minutes} min ${String(secs).padStart(2, "0")} s`;
  }

  function initials(name = "") {
    return (
      name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0])
        .join("")
        .toUpperCase() || "U"
    );
  }

  function escape(value = "") {
    const div = document.createElement("div");
    div.textContent = String(value);
    return div.innerHTML;
  }

  function toast(message, error = false) {
    const element = document.getElementById("toast");

    if (!element) {
      return;
    }

    clearTimeout(toastTimer);

    element.textContent = message;
    element.className = `toast show${error ? " error" : ""}`;

    toastTimer = setTimeout(() => {
      element.className = "toast";
    }, 3600);
  }

  function paginate(items, requestedPage = 1, pageSize = 5) {
    const collection = Array.isArray(items) ? items : [];
    const size = Math.max(1, Number(pageSize) || 5);
    const total = collection.length;
    const totalPages = Math.max(1, Math.ceil(total / size));
    const page = Math.min(totalPages, Math.max(1, Number(requestedPage) || 1));
    const start = (page - 1) * size;

    return {
      items: collection.slice(start, start + size),
      page,
      pageSize: size,
      total,
      totalPages,
      start,
      end: Math.min(start + size, total)
    };
  }

  function paginationPages(current, total) {
    if (total <= 7) {
      return Array.from({ length: total }, (_, index) => index + 1);
    }

    const pages = new Set([1, total, current - 1, current, current + 1]);
    const ordered = [...pages]
      .filter((page) => page >= 1 && page <= total)
      .sort((left, right) => left - right);
    const result = [];

    ordered.forEach((page, index) => {
      if (index && page - ordered[index - 1] > 1) {
        result.push("ellipsis");
      }
      result.push(page);
    });

    return result;
  }

  function renderPagination(target, pagination, onPageChange) {
    const element = typeof target === "string"
      ? document.getElementById(target)
      : target;

    if (!element) {
      return;
    }

    if (!pagination.total || pagination.total <= pagination.pageSize) {
      element.hidden = true;
      element.innerHTML = "";
      return;
    }

    element.hidden = false;
    const pages = paginationPages(pagination.page, pagination.totalPages);
    const pageButtons = pages.map((page) => {
      if (page === "ellipsis") {
        return '<span class="pagination-ellipsis" aria-hidden="true">…</span>';
      }

      const current = page === pagination.page;
      return `<button class="pagination-button pagination-number${current ? " current" : ""}" type="button" data-page="${page}"${current ? ' aria-current="page"' : ""}>${page}</button>`;
    }).join("");

    element.innerHTML = `
      <span class="pagination-summary">${pagination.start + 1}–${pagination.end} sur ${pagination.total}</span>
      <nav class="pagination-actions" aria-label="Pagination">
        <button class="pagination-button pagination-nav" type="button" data-page="${pagination.page - 1}" ${pagination.page === 1 ? "disabled" : ""}>← Précédent</button>
        <span class="pagination-pages">${pageButtons}</span>
        <button class="pagination-button pagination-nav" type="button" data-page="${pagination.page + 1}" ${pagination.page === pagination.totalPages ? "disabled" : ""}>Suivant →</button>
      </nav>`;

    element.querySelectorAll("[data-page]:not([disabled])").forEach((button) => {
      button.addEventListener("click", () => onPageChange(Number(button.dataset.page)));
    });
  }

  async function requireUser(admin = false) {
    if (!token()) {
      location.href = "/login";
      return null;
    }

    try {
      const result = await api("/api/auth/me");

      if (admin && result.user.role !== "admin") {
        location.href = "/app";
        return null;
      }

      return result.user;
    } catch (_) {
      clearSession();
      location.href = "/login";
      return null;
    }
  }

  async function logout() {
    try {
      await api("/api/auth/logout", {
        method: "POST"
      });
    } catch (_) {
      // La session locale sera quand même supprimée.
    }

    clearSession();
    location.href = "/login";
  }

  function bindShell() {
    document
      .getElementById("logout-button")
      ?.addEventListener("click", logout);

    const sidebar = document.getElementById("sidebar");

    document
      .getElementById("sidebar-toggle")
      ?.addEventListener("click", () => {
        sidebar?.classList.toggle("open");
      });

    sidebar?.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        sidebar.classList.remove("open");
      });
    });
  }

  window.Voz = {
    base,
    token,
    storeSession,
    clearSession,
    api,
    download,
    blobUrl,
    formatBytes,
    formatDate,
    formatDay,
    formatDuration,
    initials,
    escape,
    toast,
    paginate,
    renderPagination,
    requireUser,
    logout,
    bindShell
  };
})();
