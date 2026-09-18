(() => {
  const state = { user: null, courses: [], jobs: [], selected: null, editing: null };
  const $ = (id) => document.getElementById(id);
  const statusMap = {
    queued: ["En attente", "state-warning"], loading: ["Chargement", "state-warning"],
    processing: ["En cours", "state-warning"], exporting: ["Export", "state-warning"],
    completed: ["Terminée", "state-success"], failed: ["Échec", "state-error"]
  };

  function badge(status) {
    const [label, className] = statusMap[status] || [status, "state-neutral"];
    return `<span class="state-pill ${className}">${label}</span>`;
  }

  function fillUser(user) {
    state.user = user;
    $("user-name").textContent = user.name;
    $("user-avatar").textContent = Voz.initials(user.name);
    $("user-role").textContent = user.role === "admin" ? "Administrateur" : "Utilisateur";
    $("admin-link").hidden = user.role !== "admin";
  }

  async function loadSystem() {
    try {
      const data = await Voz.api("/api/system");
      $("server-dot").classList.add("online");
      $("server-label").textContent = "Serveur connecté";
      $("server-device").textContent = data.device;
    } catch (_) {
      $("server-label").textContent = "Serveur hors ligne";
      $("server-device").textContent = "Vérifiez votre Mac";
    }
  }

  async function loadData() {
    const [{ courses }, { jobs }] = await Promise.all([
      Voz.api("/api/courses?include_archived=true"),
      Voz.api("/api/jobs?limit=500")
    ]);
    state.courses = courses;
    state.jobs = jobs;
    renderCourses();
    const id = new URLSearchParams(location.search).get("id");
    if (id) selectCourse(id === "none" ? "none" : Number(id), false);
  }

  function unassignedCourse() {
    const jobs = state.jobs.filter((job) => !job.course_id);
    return {
      id: "none", name: "Sans cours", teacher: "Enregistrements non classés",
      color: "#718079", is_archived: false, job_count: jobs.length,
      completed_count: jobs.filter((job) => job.status === "completed").length,
      latest_job_at: jobs.map((job) => job.created_at).sort().at(-1) || null
    };
  }

  function renderCourses() {
    const query = $("course-search").value.trim().toLowerCase();
    const showArchived = $("show-archived").checked;
    const all = [unassignedCourse(), ...state.courses].filter((course) => {
      const searchable = `${course.name} ${course.teacher || ""}`.toLowerCase();
      return searchable.includes(query) && (!course.is_archived || showArchived);
    });
    $("courses-empty").hidden = all.length > 1 || Boolean(query);
    $("course-grid").innerHTML = all.map((course) => `
      <button class="course-card${String(state.selected?.id) === String(course.id) ? " selected" : ""}${course.is_archived ? " archived" : ""}" data-course-id="${course.id}" style="--course-color:${Voz.escape(course.color)}">
        <span class="course-card-top"><span class="course-monogram">${course.id === "none" ? "—" : Voz.escape(course.name.charAt(0).toUpperCase())}</span>${course.is_archived ? '<span class="state-pill state-neutral">Archivé</span>' : ""}</span>
        <span class="course-card-copy"><strong>${Voz.escape(course.name)}</strong><small>${Voz.escape(course.teacher || "Enseignant non renseigné")}</small></span>
        <span class="course-card-meta"><span>${course.job_count} séance${course.job_count > 1 ? "s" : ""}</span><span>${course.completed_count} terminée${course.completed_count > 1 ? "s" : ""}</span></span>
        <span class="course-card-foot">${course.latest_job_at ? `Dernière activité ${Voz.formatDate(course.latest_job_at)}` : "Aucune activité"}<b>→</b></span>
      </button>
    `).join("");
    document.querySelectorAll("[data-course-id]").forEach((card) => {
      card.addEventListener("click", () => selectCourse(card.dataset.courseId === "none" ? "none" : Number(card.dataset.courseId)));
    });
  }

  async function selectCourse(id, updateUrl = true) {
    let course;
    let jobs;
    if (id === "none") {
      course = unassignedCourse();
      jobs = state.jobs.filter((job) => !job.course_id);
    } else {
      try {
        const result = await Voz.api(`/api/courses/${id}`);
        course = result.course;
        jobs = result.jobs;
      } catch (error) {
        Voz.toast(error.message, true);
        return;
      }
    }
    state.selected = course;
    if (updateUrl) history.replaceState(null, "", `/courses?id=${course.id}`);
    renderCourses();
    renderDetail(course, jobs);
    $("course-detail").hidden = false;
    $("course-detail").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderDetail(course, jobs) {
    $("detail-course-color").style.background = course.color;
    $("detail-course-name").textContent = course.name;
    $("detail-course-teacher").textContent = course.teacher || "Enseignant non renseigné";
    $("detail-course-state").textContent = course.is_archived ? "COURS ARCHIVÉ" : "COURS";
    $("detail-job-count").textContent = course.job_count;
    $("detail-completed-count").textContent = course.completed_count;
    $("detail-latest").textContent = course.latest_job_at ? Voz.formatDate(course.latest_job_at) : "—";
    const isUnassigned = course.id === "none";
    $("edit-course").hidden = isUnassigned;
    $("archive-course").hidden = isUnassigned;
    $("delete-course").hidden = isUnassigned;
    $("archive-course").textContent = course.is_archived ? "Réactiver" : "Archiver";
    $("add-course-audio").href = isUnassigned ? "/app#new-transcription" : `/app?course=${course.id}#new-transcription`;
    $("course-jobs-empty").hidden = jobs.length > 0;
    $("course-jobs-body").innerHTML = jobs.map((job) => `
      <tr>
        <td><div class="file-cell"><span class="doc-icon">T</span><div><strong>${Voz.escape(job.lesson_title || job.filename)}</strong><small>${Voz.escape(job.filename)}</small></div></div></td>
        <td>${job.lesson_date ? Voz.formatDay(job.lesson_date) : Voz.formatDate(job.created_at)}</td>
        <td>${Voz.formatDuration(job.duration_seconds)}</td>
        <td><div class="content-chips"><span class="content-chip ${job.has_audio ? "available" : ""}">Audio ${job.has_audio ? "✓" : "—"}</span><span class="content-chip ${job.has_text ? "available" : ""}">Texte ${job.has_text ? "✓" : "—"}</span></div></td>
        <td>${badge(job.status)}</td>
        <td><a class="row-action row-action-link" href="/app?job=${job.id}">Ouvrir</a></td>
      </tr>
    `).join("");
  }

  function openCourseDialog(course = null) {
    state.editing = course;
    $("course-dialog-kicker").textContent = course ? "MODIFIER LE COURS" : "NOUVEAU COURS";
    $("course-dialog-title").textContent = course ? "Modifier le cours" : "Créer un cours";
    $("course-name").value = course?.name || "";
    $("course-teacher").value = course?.teacher || "";
    $("course-color").value = course?.color || "#0d6b53";
    $("course-color-value").value = $("course-color").value;
    $("course-form-error").hidden = true;
    $("course-dialog").showModal();
    setTimeout(() => $("course-name").focus(), 50);
  }

  function closeCourseDialog() { $("course-dialog").close(); }

  async function saveCourse(event) {
    event.preventDefault();
    const payload = {
      name: $("course-name").value,
      teacher: $("course-teacher").value,
      color: $("course-color").value
    };
    $("save-course").disabled = true;
    try {
      const result = await Voz.api(state.editing ? `/api/courses/${state.editing.id}` : "/api/courses", {
        method: state.editing ? "PATCH" : "POST", body: JSON.stringify(payload)
      });
      closeCourseDialog();
      Voz.toast(state.editing ? "Cours modifié." : "Cours créé.");
      await loadData();
      selectCourse(result.course.id);
    } catch (error) {
      $("course-form-error").textContent = error.message;
      $("course-form-error").hidden = false;
    } finally {
      $("save-course").disabled = false;
    }
  }

  async function toggleArchive() {
    if (!state.selected || state.selected.id === "none") return;
    try {
      const result = await Voz.api(`/api/courses/${state.selected.id}`, {
        method: "PATCH", body: JSON.stringify({ is_archived: !state.selected.is_archived })
      });
      Voz.toast(result.course.is_archived ? "Cours archivé." : "Cours réactivé.");
      await loadData();
      selectCourse(result.course.id);
    } catch (error) { Voz.toast(error.message, true); }
  }

  async function deleteCourse() {
    if (!state.selected || state.selected.id === "none") return;
    try {
      await Voz.api(`/api/courses/${state.selected.id}`, { method: "DELETE" });
      Voz.toast("Cours supprimé. Ses contenus sont maintenant dans Sans cours.");
      state.selected = null;
      $("course-detail").hidden = true;
      history.replaceState(null, "", "/courses");
      await loadData();
    } catch (error) { Voz.toast(error.message, true); }
  }

  function bind() {
    Voz.bindShell();
    $("create-course").addEventListener("click", () => openCourseDialog());
    document.querySelector("[data-create-course]").addEventListener("click", () => openCourseDialog());
    document.querySelectorAll("[data-close-course]").forEach((button) => button.addEventListener("click", closeCourseDialog));
    $("course-dialog").addEventListener("click", (event) => { if (event.target === $("course-dialog")) closeCourseDialog(); });
    $("course-form").addEventListener("submit", saveCourse);
    $("course-color").addEventListener("input", () => { $("course-color-value").value = $("course-color").value; });
    $("course-search").addEventListener("input", renderCourses);
    $("show-archived").addEventListener("change", renderCourses);
    $("edit-course").addEventListener("click", () => openCourseDialog(state.selected));
    $("archive-course").addEventListener("click", toggleArchive);
    $("delete-course").addEventListener("click", () => $("delete-course-dialog").showModal());
    $("delete-course-dialog").addEventListener("close", () => {
      if ($("delete-course-dialog").returnValue === "confirm") deleteCourse();
    });
  }

  async function init() {
    const user = await Voz.requireUser();
    if (!user) return;
    fillUser(user);
    bind();
    loadSystem();
    try { await loadData(); } catch (error) { Voz.toast(error.message, true); }
  }

  init();
})();
