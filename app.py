from __future__ import annotations

import mimetypes
import os
import shutil
import threading
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
from transcriber.engine import (
    TranscriptionEngine,
    TranscriptionResult,
    detect_device,
)
from transcriber.formatters import build_exports


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

DATA_DIR = database.DATA_DIR
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"

ALLOWED_EXTENSIONS = {
    ".m4a",
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".webm",
    ".mp4",
}

ACTIVE_STATUSES = {
    "queued",
    "loading",
    "processing",
    "exporting",
}

MAX_UPLOAD_BYTES = (
    max(
        10,
        int(os.getenv("VOZLOCAL_MAX_UPLOAD_MB", "500")),
    )
    * 1024
    * 1024
)

for directory in (UPLOAD_DIR, OUTPUT_DIR):
    directory.mkdir(parents=True, exist_ok=True)


database.initialize_database()

app = FastAPI(
    title="VozLocal",
    version="2.0.0",
)

engine = TranscriptionEngine()

job_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="vozlocal-worker",
)


allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "VOZLOCAL_ALLOWED_ORIGINS",
        "",
    ).split(",")
    if origin.strip()
]

if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=[
            "GET",
            "POST",
            "PATCH",
            "DELETE",
            "OPTIONS",
        ],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "ngrok-skip-browser-warning",
        ],
        expose_headers=[
            "Content-Disposition",
        ],
    )


class RegisterPayload(BaseModel):
    name: str
    email: str
    password: str


class LoginPayload(BaseModel):
    email: str
    password: str


class UserStatusPayload(BaseModel):
    is_active: bool


class AttemptLimiter:
    def __init__(
        self,
        maximum: int = 10,
        window_seconds: int = 900,
    ) -> None:
        self.maximum = maximum
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()

        with self._lock:
            attempts = self._attempts[key]

            while (
                attempts
                and now - attempts[0] > self.window_seconds
            ):
                attempts.popleft()

            if len(attempts) >= self.maximum:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "Trop de tentatives. "
                        "Réessayez dans quelques minutes."
                    ),
                )

            attempts.append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


login_limiter = AttemptLimiter()


def bearer_token(request: Request) -> str:
    authorization = request.headers.get(
        "Authorization",
        "",
    )

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="Authentification requise.",
        )

    return token.strip()


def current_user(request: Request) -> dict[str, Any]:
    session_token = bearer_token(request)
    user = database.user_from_token(session_token)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Session invalide ou expirée.",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=403,
            detail="Ce compte est suspendu.",
        )

    return user


def admin_user(
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Accès réservé à l’administration.",
        )

    return user


def validate_account_fields(
    name: str,
    email: str,
    password: str,
) -> tuple[str, str]:
    clean_name = " ".join(name.strip().split())
    clean_email = database.normalize_email(email)

    if len(clean_name) < 2 or len(clean_name) > 80:
        raise HTTPException(
            status_code=400,
            detail=(
                "Le nom doit contenir entre "
                "2 et 80 caractères."
            ),
        )

    email_domain = (
        clean_email.rsplit("@", 1)[-1]
        if "@" in clean_email
        else ""
    )

    if (
        "@" not in clean_email
        or "." not in email_domain
        or len(clean_email) > 254
    ):
        raise HTTPException(
            status_code=400,
            detail="Adresse e-mail invalide.",
        )

    if len(password) < 10:
        raise HTTPException(
            status_code=400,
            detail=(
                "Le mot de passe doit contenir "
                "au moins 10 caractères."
            ),
        )

    if len(password) > 200:
        raise HTTPException(
            status_code=400,
            detail="Le mot de passe est trop long.",
        )

    return clean_name, clean_email


def auth_response(
    user: dict[str, Any],
) -> dict[str, Any]:
    return {
        "token": database.create_session(user["id"]),
        "user": user,
    }


def owned_job(
    job_id: str,
    user: dict[str, Any],
    *,
    include_text: bool = False,
) -> dict[str, Any]:
    owner_id = (
        None
        if user["role"] == "admin"
        else user["id"]
    )

    job = database.get_job(
        job_id,
        owner_id,
        include_text=include_text,
    )

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Transcription introuvable.",
        )

    return job


def process_job(
    job_id: str,
    audio_path: Path,
    source_stem: str,
    prompt: str,
) -> None:
    try:
        database.update_job(
            job_id,
            status="loading",
            progress=12,
            message="Chargement du modèle…",
        )

        result = engine.transcribe(
            audio_path,
            prompt=prompt,
            progress=lambda value, message: (
                database.update_job(
                    job_id,
                    status="processing",
                    progress=value,
                    message=message,
                )
            ),
        )

        database.update_job(
            job_id,
            status="exporting",
            progress=92,
            message="Création des fichiers…",
        )

        job_output = OUTPUT_DIR / job_id
        job_output.mkdir(
            parents=True,
            exist_ok=True,
        )

        raw_result = TranscriptionResult(
            text=result.text,
            segments=[],
            duration_seconds=result.duration_seconds,
        )

        build_exports(
            raw_result,
            source_stem,
            job_output,
            ["txt", "docx"],
        )

        segments = [
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            }
            for segment in result.segments
        ]

        database.update_job(
            job_id,
            status="completed",
            progress=100,
            message="Transcription terminée",
            transcript=result.text,
            segments_json=database.segments_to_json(
                segments
            ),
            text_deleted=0,
            duration_seconds=result.duration_seconds,
            completed_at=database.utc_now(),
            error=None,
        )

    except Exception as exc:
        database.update_job(
            job_id,
            status="failed",
            progress=0,
            message="La transcription a échoué.",
            error=str(exc),
        )


def remove_output_directory(job_id: str) -> None:
    output = OUTPUT_DIR / job_id

    if output.is_dir():
        shutil.rmtree(
            output,
            ignore_errors=True,
        )


def remove_audio_file(record: Any) -> None:
    stored_name = record["stored_audio_name"]

    if (
        not stored_name
        or Path(stored_name).name != stored_name
    ):
        return

    (UPLOAD_DIR / stored_name).unlink(
        missing_ok=True
    )


@app.post(
    "/api/auth/register",
    status_code=201,
)
def register(
    payload: RegisterPayload,
    request: Request,
) -> dict[str, Any]:
    host = (
        request.client.host
        if request.client
        else "unknown"
    )

    key = f"register:{host}"

    login_limiter.check(key)

    name, email = validate_account_fields(
        payload.name,
        payload.email,
        payload.password,
    )

    try:
        user = database.create_user(
            name,
            email,
            payload.password,
        )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Un compte utilise déjà "
                    "cette adresse e-mail."
                ),
            ) from exc

        raise

    login_limiter.clear(key)

    return auth_response(user)


@app.post("/api/auth/login")
def login(
    payload: LoginPayload,
    request: Request,
) -> dict[str, Any]:
    host = (
        request.client.host
        if request.client
        else "unknown"
    )

    normalized_email = database.normalize_email(
        payload.email
    )

    key = f"login:{host}:{normalized_email}"

    login_limiter.check(key)

    user = database.authenticate_user(
        payload.email,
        payload.password,
    )

    if not user:
        raise HTTPException(
            status_code=401,
            detail="E-mail ou mot de passe incorrect.",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=403,
            detail="Ce compte est suspendu.",
        )

    login_limiter.clear(key)

    return auth_response(user)


@app.post("/api/auth/logout")
def logout(
    request: Request,
    _user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    database.revoke_session(
        bearer_token(request)
    )

    return {
        "logged_out": True,
    }


@app.get("/api/auth/me")
def me(
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return {
        "user": user,
    }


@app.get("/api/system")
def system_info(
    _user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return {
        "device": detect_device(),
        "model": engine.model_name,
        "demo_mode": engine.demo_mode,
        "online": True,
    }


@app.get("/api/dashboard")
def dashboard(
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return {
        "stats": database.user_stats(user["id"]),
        "recent": database.list_jobs(
            user["id"],
            limit=5,
        ),
    }


@app.post(
    "/api/jobs",
    status_code=202,
)
def create_job(
    audio: Annotated[UploadFile, File()],
    prompt: Annotated[str, Form()] = "",
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    original_filename = Path(
        audio.filename or "audio"
    ).name

    suffix = Path(
        original_filename
    ).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                "Format non pris en charge. "
                "Utilisez M4A, MP3, WAV, FLAC, "
                "OGG, WEBM ou MP4."
            ),
        )

    if len(prompt) > 500:
        raise HTTPException(
            status_code=400,
            detail=(
                "Le contexte ne peut pas "
                "dépasser 500 caractères."
            ),
        )

    job_id = uuid.uuid4().hex
    stored_name = f"{job_id}{suffix}"
    audio_path = UPLOAD_DIR / stored_name

    written = 0

    try:
        with audio_path.open("wb") as destination:
            while chunk := audio.file.read(
                1024 * 1024
            ):
                written += len(chunk)

                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "Le fichier dépasse la limite "
                            f"de {MAX_UPLOAD_BYTES // 1024 // 1024} Mo."
                        ),
                    )

                destination.write(chunk)

    except Exception:
        audio_path.unlink(missing_ok=True)
        raise

    if written == 0:
        audio_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=400,
            detail="Le fichier audio est vide.",
        )

    database.insert_job(
        {
            "id": job_id,
            "user_id": user["id"],
            "filename": original_filename,
            "stored_audio_name": stored_name,
            "audio_size": written,
            "status": "queued",
            "progress": 3,
            "message": (
                "Fichier reçu, en attente "
                "de traitement"
            ),
            "prompt": prompt.strip(),
        }
    )

    job_executor.submit(
        process_job,
        job_id,
        audio_path,
        Path(original_filename).stem,
        prompt.strip(),
    )

    return {
        "job_id": job_id,
        "status": "queued",
    }


@app.get("/api/jobs")
def jobs(
    limit: int = 100,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return {
        "jobs": database.list_jobs(
            user["id"],
            limit=limit,
        ),
    }


@app.get("/api/jobs/{job_id}")
def job_detail(
    job_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return {
        "job": owned_job(
            job_id,
            user,
            include_text=True,
        ),
    }


@app.get("/api/jobs/{job_id}/audio")
def job_audio(
    job_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> FileResponse:
    job = owned_job(
        job_id,
        user,
    )

    if not job["has_audio"]:
        raise HTTPException(
            status_code=404,
            detail=(
                "Le fichier audio a été supprimé."
            ),
        )

    record = database.get_job_record(job_id)
    stored_name = record["stored_audio_name"]

    if Path(stored_name).name != stored_name:
        raise HTTPException(
            status_code=404,
            detail="Fichier audio introuvable.",
        )

    path = UPLOAD_DIR / stored_name

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Fichier audio introuvable.",
        )

    media_type = (
        mimetypes.guess_type(
            job["filename"]
        )[0]
        or "application/octet-stream"
    )

    return FileResponse(
        path,
        filename=job["filename"],
        media_type=media_type,
    )


@app.get(
    "/api/jobs/{job_id}/download/{file_format}"
)
def download_export(
    job_id: str,
    file_format: str,
    user: dict[str, Any] = Depends(current_user),
) -> FileResponse:
    job = owned_job(
        job_id,
        user,
        include_text=True,
    )

    if file_format not in {"txt", "docx"}:
        raise HTTPException(
            status_code=404,
            detail="Format non disponible.",
        )

    if not job["has_text"]:
        raise HTTPException(
            status_code=404,
            detail="Le texte a été supprimé.",
        )

    output_dir = OUTPUT_DIR / job_id

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_result = TranscriptionResult(
        text=job["transcript"] or "",
        segments=[],
        duration_seconds=(
            job["duration_seconds"] or 0
        ),
    )

    exports = build_exports(
        raw_result,
        Path(job["filename"]).stem,
        output_dir,
        [file_format],
    )

    path = exports[file_format]

    media_type = (
        "text/plain; charset=utf-8"
        if file_format == "txt"
        else (
            "application/vnd.openxmlformats-"
            "officedocument.wordprocessingml.document"
        )
    )

    return FileResponse(
        path,
        filename=path.name,
        media_type=media_type,
    )


@app.delete("/api/jobs/{job_id}")
def delete_job_content(
    job_id: str,
    target: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    if target not in {
        "audio",
        "text",
        "both",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "Choisissez audio, text ou both."
            ),
        )

    job = owned_job(
        job_id,
        user,
    )

    if job["status"] in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                "Attendez la fin du traitement "
                "avant de supprimer ce contenu."
            ),
        )

    record = database.get_job_record(job_id)

    if target in {"audio", "both"}:
        remove_audio_file(record)
        database.clear_job_audio(job_id)

    if target in {"text", "both"}:
        remove_output_directory(job_id)
        database.clear_job_text(job_id)

    if target == "both":
        database.delete_job(job_id)

        return {
            "deleted": "both",
            "job_removed": True,
        }

    return {
        "deleted": target,
        "job_removed": False,
    }


@app.get("/api/admin/stats")
def get_admin_stats(
    _admin: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {
        "stats": database.admin_stats(),
    }


@app.get("/api/admin/users")
def get_admin_users(
    _admin: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {
        "users": database.list_users(),
    }


@app.get("/api/admin/jobs")
def get_admin_jobs(
    limit: int = 200,
    _admin: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {
        "jobs": database.list_jobs(
            None,
            limit=limit,
        ),
    }


@app.patch(
    "/api/admin/users/{user_id}/status"
)
def update_user_status(
    user_id: int,
    payload: UserStatusPayload,
    admin: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    if (
        user_id == admin["id"]
        and not payload.is_active
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Vous ne pouvez pas suspendre "
                "votre propre compte."
            ),
        )

    if not database.set_user_active(
        user_id,
        payload.is_active,
    ):
        raise HTTPException(
            status_code=404,
            detail="Utilisateur introuvable.",
        )

    return {
        "updated": True,
    }


def page(name: str) -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / name
    )


@app.get(
    "/",
    include_in_schema=False,
)
def home_page() -> FileResponse:
    return page("index.html")


@app.get(
    "/login",
    include_in_schema=False,
)
def login_page() -> FileResponse:
    return page("login.html")


@app.get(
    "/register",
    include_in_schema=False,
)
def register_page() -> FileResponse:
    return page("register.html")


@app.get(
    "/app",
    include_in_schema=False,
)
def dashboard_page() -> FileResponse:
    return page("dashboard.html")


@app.get(
    "/admin",
    include_in_schema=False,
)
def admin_page() -> FileResponse:
    return page("admin.html")


app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIR),
    name="assets",
)