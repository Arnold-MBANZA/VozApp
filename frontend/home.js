(() => {
  const menu = document.getElementById("mobile-menu"), nav = document.querySelector(".site-nav");
  menu?.addEventListener("click", () => { const open = nav.classList.toggle("open"); menu.setAttribute("aria-expanded", String(open)); });
  if (Voz.token()) {
    Voz.api("/api/auth/me").then(({ user }) => {
      const actions = document.getElementById("public-actions");
      actions.innerHTML = `<span class="muted">${Voz.escape(user.name)}</span><a class="button button-primary button-small" href="/app">Mon tableau de bord</a>`;
    }).catch(() => Voz.clearSession());
  }
})();
