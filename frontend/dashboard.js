(() => {
  const state = {
    user: null,
    jobs: [],
    courses: [],
    selected: null,
    audioUrl: null,
    polling: null
  };

  const $ = (id) => document.getElementById(id);
  const statusMap = {
    queued: ["En attente", "state-warning"],
    loading: ["Chargement", "state-warning"],
    processing: ["En cours", "state-warning"],
    exporting: ["Export", "state-warning"],
    completed: ["Terminée", "state-success"],
    failed: ["Échec", "state-error"]
  };

  function badge(status) {
    const [label, className] = statusMap[status] || [status, "state-neutral"];
    return `<span class="state-pill ${className}">${label}</span>`;
  }

  function fillUser(user) {
    state.user = user;
    $("user-firstname").textContent = user.name.split(/\s+/)[0];
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

  function renderCourseOptions() {
    const selectedUpload = $("course-select").value;
    const selectedFilter = $("history-course").value;
    const activeCourses = state.courses.filter((course) => !course.is_archived);

    $("course-select").innerHTML = [
      '<option value="">Sans cours</option>',
      ...activeCourses.map(
        (course) => `<option value="${course.id}">${Voz.escape(course.name)}</option>`
      )
    ].join("");

    $("history-course").innerHTML = [
      '<option value="all">Tous les cours</option>',
      '<option value="none">Sans cours</option>',
      ...state.courses.map(
        (course) => `<option value="${course.id}">${Voz.escape(course.name)}${course.is_archived ? " (archivé)" : ""}</option>`
      )
    ].join("");

    if ([...$("course-select").options].some((option) => option.value === selectedUpload)) {
      $("course-select").value = selectedUpload;
    }
    if ([...$("history-course").options].some((option) => option.value === selectedFilter)) {
      $("history-course").value = selectedFilter;
    }
  }

  async function loadDashboard() {
    const [{ stats }, { jobs }, { courses }] = await Promise.all([
      Voz.api("/api/dashboard"),
      Voz.api("/api/jobs?limit=200"),
      Voz.api("/api/courses?include_archived=true")
    ]);

    $("stat-total").textContent = stats.total;
    $("stat-completed").textContent = stats.completed;
    $("stat-audios").textContent = stats.audios;
    $("stat-storage").textContent = Voz.formatBytes(stats.storage);
    state.jobs = jobs;
    state.courses = courses;
    renderCourseOptions();
    renderJobs();
  }

  function renderJobs() {
    const query = $("history-search").value.trim().toLowerCase();
    const courseFilter = $("history-course").value;
    const statusFilter = $("history-status").value;
    const dateFilter = $("history-date").value;

    const jobs = state.jobs.filter((job) => {
      const searchable = `${job.filename} ${job.lesson_title || ""} ${job.course_name || ""}`.toLowerCase();
      const matchesCourse = courseFilter === "all"
        || (courseFilter === "none" && !job.course_id)
        || String(job.course_id) === courseFilter;
      const matchesStatus = statusFilter === "all"
        || (statusFilter === "processing" && ["queued", "loading", "processing", "exporting"].includes(job.status))
        || job.status === statusFilter;
      const jobDate = job.lesson_date || String(job.created_at || "").slice(0, 10);
      return searchable.includes(query)
        && matchesCourse
        && matchesStatus
        && (!dateFilter || jobDate === dateFilter);
    });

    $("history-empty").hidden = jobs.length > 0;
    $("history-body").innerHTML = jobs.map((job) => `
      <tr>
        <td><div class="file-cell"><span class="doc-icon">T</span><div><strong title="${Voz.escape(job.lesson_title || job.filename)}">${Voz.escape(job.lesson_title || job.filename)}</strong><small>${job.lesson_title ? `${Voz.escape(job.filename)} · ` : ""}${Voz.formatBytes(job.audio_size)}</small></div></div></td>
        <td><span class="course-chip" style="--course-color:${Voz.escape(job.course_color || "#718079")}">${Voz.escape(job.course_name || "Sans cours")}</span></td>
        <td>${job.lesson_date ? Voz.formatDay(job.lesson_date) : Voz.formatDate(job.created_at)}</td>
        <td>${Voz.formatDuration(job.duration_seconds)}</td>
        <td><div class="content-chips"><span class="content-chip ${job.has_audio ? "available" : ""}">Audio ${job.has_audio ? "✓" : "—"}</span><span class="content-chip ${job.has_text ? "available" : ""}">Texte ${job.has_text ? "✓" : "—"}</span></div></td>
        <td>${badge(job.status)}</td>
        <td><button class="row-action" data-open-job="${job.id}">Ouvrir</button></td>
      </tr>
    `).join("");

    document.querySelectorAll("[data-open-job]").forEach((button) => {
      button.addEventListener("click", () => openJob(button.dataset.openJob));
    });
  }

  function updateFile(file) {
    if (!file) return;
    $("drop-title").textContent = file.name;
    $("drop-subtitle").textContent = `${Voz.formatBytes(file.size)} · prêt à transcrire`;
    $("dropzone").classList.add("has-file");
    $("drop-button").textContent = "Changer le fichier";
    $("start-button").disabled = false;
    if (!$("lesson-title").value) {
      $("lesson-title").value = file.name.replace(/\.[^.]+$/, "");
    }
  }

  async function createJob() {
    const file = $("audio-input").files[0];
    if (!file) return;
    const form = new FormData();
    form.append("audio", file);
    form.append("prompt", $("context-prompt").value);
    form.append("lesson_title", $("lesson-title").value);
    form.append("lesson_date", $("lesson-date").value);
    if ($("course-select").value) form.append("course_id", $("course-select").value);

    $("start-button").disabled = true;
    $("job-progress").hidden = false;
    showProgress({ progress: 1, message: "Envoi du fichier…", filename: file.name });
    try {
      const response = await Voz.api("/api/jobs", { method: "POST", body: form });
      pollJob(response.job_id, file.name);
    } catch (error) {
      Voz.toast(error.message, true);
      $("start-button").disabled = false;
      $("job-progress").hidden = true;
    }
  }

  function showProgress(job) {
    const progress = Math.max(0, Math.min(100, job.progress || 0));
    $("progress-message").textContent = job.message || "Traitement…";
    $("progress-file").textContent = job.filename || "";
    $("progress-value").textContent = `${progress} %`;
    $("progress-bar").style.width = `${progress}%`;
  }

  function pollJob(id, filename) {
    clearInterval(state.polling);
    const tick = async () => {
      try {
        const { job } = await Voz.api(`/api/jobs/${id}`);
        showProgress({ ...job, filename });
        if (["completed", "failed"].includes(job.status)) {
          clearInterval(state.polling);
          state.polling = null;
          $("start-button").disabled = false;
          await loadDashboard();
          if (job.status === "completed") {
            Voz.toast("Transcription terminée.");
            setTimeout(() => {
              $("job-progress").hidden = true;
              openJob(id);
            }, 550);
          } else {
            Voz.toast(job.error || "La transcription a échoué.", true);
          }
        }
      } catch (error) {
        clearInterval(state.polling);
        state.polling = null;
        Voz.toast(error.message, true);
        $("start-button").disabled = false;
      }
    };
    tick();
    state.polling = setInterval(tick, 1400);
  }

  async function openJob(id) {
    try {
      const { job } = await Voz.api(`/api/jobs/${id}`);
      state.selected = job;
      $("detail-title").textContent = job.lesson_title || job.filename;
      const metadata = [
        job.course_name || "Sans cours",
        job.lesson_date ? Voz.formatDay(job.lesson_date) : Voz.formatDate(job.created_at),
        Voz.formatDuration(job.duration_seconds),
        statusMap[job.status]?.[0] || job.status
      ];
      $("detail-meta").textContent = metadata.join(" · ");
      $("audio-filename").textContent = job.filename;
      $("audio-block").hidden = !job.has_audio;
      $("raw-transcript").hidden = !job.has_text;
      $("text-deleted").hidden = job.has_text;
      $("raw-transcript").textContent = job.transcript || "";
      document.querySelectorAll("[data-download], #copy-text").forEach((button) => {
        button.hidden = !job.has_text;
      });
      document.querySelector('[data-delete="audio"]').hidden = !job.has_audio;
      document.querySelector('[data-delete="text"]').hidden = !job.has_text;
      if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
      state.audioUrl = null;
      $("audio-player").removeAttribute("src");
      $("detail-dialog").showModal();
      if (job.has_audio) {
        try {
          state.audioUrl = await Voz.blobUrl(`/api/jobs/${job.id}/audio`);
          $("audio-player").src = state.audioUrl;
        } catch (error) {
          Voz.toast(error.message, true);
        }
      }
    } catch (error) {
      Voz.toast(error.message, true);
    }
  }

  function closeDetail() {
    $("detail-dialog").close();
    $("audio-player").pause();
    if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
    state.audioUrl = null;
  }

  function confirmDelete(target) {
    const labels = {
      audio: ["Supprimer l’audio ?", "Le texte restera disponible dans votre historique."],
      text: ["Supprimer le texte ?", "L’enregistrement audio restera disponible."],
      both: ["Tout supprimer ?", "L’audio, le texte et l’entrée d’historique seront supprimés définitivement."]
    };
    $("confirm-title").textContent = labels[target][0];
    $("confirm-copy").textContent = labels[target][1];
    const dialog = $("confirm-dialog");
    dialog.dataset.target = target;
    dialog.showModal();
  }

  async function deleteSelected(target) {
    try {
      await Voz.api(`/api/jobs/${state.selected.id}?target=${target}`, { method: "DELETE" });
      Voz.toast("Suppression effectuée.");
      closeDetail();
      await loadDashboard();
    } catch (error) {
      Voz.toast(error.message, true);
    }
  }

  function clearFilters() {
    $("history-search").value = "";
    $("history-course").value = "all";
    $("history-status").value = "all";
    $("history-date").value = "";
    renderJobs();
  }

  function bind() {
    Voz.bindShell();
    ["history-search", "history-course", "history-status", "history-date"].forEach((id) => {
      $(id).addEventListener(id === "history-search" ? "input" : "change", renderJobs);
    });
    $("clear-filters").addEventListener("click", clearFilters);
    $("audio-input").addEventListener("change", (event) => updateFile(event.target.files[0]));
    const zone = $("dropzone");
    ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add("dragover");
    }));
    ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.remove("dragover");
    }));
    zone.addEventListener("drop", (event) => {
      const file = event.dataTransfer.files[0];
      if (!file) return;
      const transfer = new DataTransfer();
      transfer.items.add(file);
      $("audio-input").files = transfer.files;
      updateFile(file);
    });
    $("start-button").addEventListener("click", createJob);
    document.querySelector("[data-close-dialog]").addEventListener("click", closeDetail);
    $("detail-dialog").addEventListener("click", (event) => {
      if (event.target === $("detail-dialog")) closeDetail();
    });
    $("copy-text").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(state.selected.transcript || "");
        Voz.toast("Texte copié.");
      } catch (_) {
        Voz.toast("Copie impossible dans ce navigateur.", true);
      }
    });
    document.querySelectorAll("[data-download]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await Voz.download(
            `/api/jobs/${state.selected.id}/download/${button.dataset.download}`,
            `transcription.${button.dataset.download}`
          );
        } catch (error) {
          Voz.toast(error.message, true);
        }
      });
    });
    document.querySelectorAll("[data-delete]").forEach((button) => {
      button.addEventListener("click", () => confirmDelete(button.dataset.delete));
    });
    $("confirm-dialog").addEventListener("close", () => {
      if ($("confirm-dialog").returnValue === "confirm") {
        deleteSelected($("confirm-dialog").dataset.target);
      }
    });
  }

  async function init() {
    const user = await Voz.requireUser();
    if (!user) return;
    fillUser(user);
    bind();
    loadSystem();
    try {
      await loadDashboard();
      const params = new URLSearchParams(location.search);
      const courseId = params.get("course");
      if (courseId) {
        if (location.hash === "#new-transcription"
          && [...$("course-select").options].some((option) => option.value === courseId)) {
          $("course-select").value = courseId;
        } else if ([...$("history-course").options].some((option) => option.value === courseId)) {
          $("history-course").value = courseId;
          renderJobs();
          if (!location.hash) location.hash = "history";
        }
      }
      const jobId = params.get("job");
      if (jobId) openJob(jobId);
    } catch (error) {
      Voz.toast(error.message, true);
    }
  }

  init();
})();
