(() => {
  const form = document.getElementById("auth-form"), alertBox = document.getElementById("form-alert");
  const mode = document.body.dataset.authMode;
  if (Voz.token()) Voz.api("/api/auth/me").then(() => location.href = "/app").catch(() => Voz.clearSession());
  document.querySelectorAll(".password-toggle").forEach(button => button.addEventListener("click", () => {
    const input = button.closest(".password-field").querySelector("input");
    input.type = input.type === "password" ? "text" : "password"; button.textContent = input.type === "password" ? "Afficher" : "Masquer";
  }));
  form.addEventListener("submit", async event => {
    event.preventDefault(); alertBox.hidden = true;
    if (!form.reportValidity()) return;
    const values = Object.fromEntries(new FormData(form));
    if (mode === "register" && values.password !== values.confirm_password) { alertBox.textContent = "Les deux mots de passe ne correspondent pas."; alertBox.hidden = false; return; }
    const button = form.querySelector("button[type=submit]"), original = button.innerHTML;
    button.disabled = true; button.textContent = mode === "login" ? "Connexion…" : "Création…";
    try {
      const body = mode === "login" ? { email: values.email, password: values.password } : { name: values.name, email: values.email, password: values.password };
      const result = await Voz.api(`/api/auth/${mode}`, { method: "POST", body: JSON.stringify(body) });
      Voz.storeSession(result.token); location.href = "/app";
    } catch (error) { alertBox.textContent = error.message; alertBox.hidden = false; button.disabled = false; button.innerHTML = original; }
  });
})();
