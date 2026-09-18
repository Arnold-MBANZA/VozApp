(() => {
  const state = { users: [], jobs: [], me: null }, $ = id => document.getElementById(id);
  const statuses = { queued:["En attente","state-warning"],loading:["Chargement","state-warning"],processing:["En cours","state-warning"],exporting:["Export","state-warning"],completed:["Terminée","state-success"],failed:["Échec","state-error"] };
  const badge = status => { const [label, cls] = statuses[status] || [status,"state-neutral"]; return `<span class="state-pill ${cls}">${label}</span>`; };
  function renderUsers() {
    const query = $("user-search").value.toLowerCase();
    $("users-body").innerHTML = state.users.filter(user => `${user.name} ${user.email}`.toLowerCase().includes(query)).map(user => `
      <tr><td><div class="user-cell"><span class="avatar">${Voz.initials(user.name)}</span><div><strong>${Voz.escape(user.name)}</strong><small>${Voz.escape(user.email)}</small></div></div></td>
      <td><span class="content-chip ${user.role === "admin" ? "available" : ""}">${user.role === "admin" ? "Admin" : "Utilisateur"}</span></td><td>${Voz.formatDate(user.created_at)}</td><td>${user.job_count}</td>
      <td><span class="state-pill ${user.is_active ? "state-success" : "state-error"}">${user.is_active ? "Actif" : "Suspendu"}</span></td>
      <td>${user.id === state.me.id ? "<span class=muted>Vous</span>" : `<button class="row-action ${user.is_active ? "danger" : ""}" data-user="${user.id}" data-active="${!user.is_active}">${user.is_active ? "Suspendre" : "Réactiver"}</button>`}</td></tr>`).join("");
    document.querySelectorAll("[data-user]").forEach(button => button.addEventListener("click", () => updateUser(Number(button.dataset.user), button.dataset.active === "true")));
  }
  function renderJobs() {
    $("activity-empty").hidden = state.jobs.length > 0;
    $("admin-jobs-body").innerHTML = state.jobs.slice(0,100).map(job => `<tr><td><div class="file-cell"><span class="doc-icon">T</span><div><strong>${Voz.escape(job.filename)}</strong><small>${Voz.formatDuration(job.duration_seconds)}</small></div></div></td><td><div class="user-cell"><div><strong>${Voz.escape(job.owner_name)}</strong><small>${Voz.escape(job.owner_email)}</small></div></div></td><td>${Voz.formatDate(job.created_at)}</td><td>${Voz.formatBytes(job.audio_size)}</td><td>${badge(job.status)}</td></tr>`).join("");
  }
  async function load() {
    const [{ stats }, { users }, { jobs }] = await Promise.all([Voz.api("/api/admin/stats"), Voz.api("/api/admin/users"), Voz.api("/api/admin/jobs")]);
    $("stat-users").textContent = stats.users; $("stat-jobs").textContent = stats.jobs; $("stat-active").textContent = stats.active_jobs; $("stat-storage").textContent = Voz.formatBytes(stats.storage);
    state.users = users; state.jobs = jobs; renderUsers(); renderJobs();
  }
  async function updateUser(id, isActive) {
    try { await Voz.api(`/api/admin/users/${id}/status`, { method:"PATCH", body:JSON.stringify({ is_active:isActive }) }); Voz.toast(isActive ? "Compte réactivé." : "Compte suspendu."); await load(); }
    catch (error) { Voz.toast(error.message,true); }
  }
  async function init() {
    const user = await Voz.requireUser(true); if (!user) return; state.me = user; $("user-name").textContent = user.name; $("user-avatar").textContent = Voz.initials(user.name);
    Voz.bindShell(); $("user-search").addEventListener("input",renderUsers); try { await load(); } catch (error) { Voz.toast(error.message,true); }
  }
  init();
})();
