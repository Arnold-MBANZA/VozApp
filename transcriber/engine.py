from __future__ import annotations

import os
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable


DEFAULT_MODEL = "freds0/distil-whisper-large-v3-ptbr"


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    segments: list[Segment]
    duration_seconds: float


def detect_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return f"NVIDIA CUDA — {torch.cuda.get_device_name(0)}"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "Apple Silicon — Metal"
    except Exception:
        pass
    return "Processeur — CPU"


class TranscriptionEngine:
    def __init__(self) -> None:
        self.model_name = os.getenv("TRANSCRIBER_MODEL", DEFAULT_MODEL)
        self.demo_mode = os.getenv("TRANSCRIBER_DEMO", "0") == "1"
        self._pipeline = None
        self._load_lock = Lock()
        self._run_lock = Lock()

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline

        with self._load_lock:
            if self._pipeline is not None:
                return self._pipeline

            import torch
            from transformers import pipeline

            if torch.cuda.is_available():
                device = 0
                dtype = torch.float16
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
                dtype = torch.float16
            else:
                device = -1
                dtype = torch.float32

            self._pipeline = pipeline(
                task="automatic-speech-recognition",
                model=self.model_name,
                dtype=dtype,
                device=device,
            )
        return self._pipeline

    @staticmethod
    def _split_audio(audio_path: Path, output_dir: Path) -> list[Path]:
        """Decode the recording into independent Whisper-sized WAV files."""
        segment_seconds = max(
            10,
            min(29, int(os.getenv("TRANSCRIBER_SEGMENT_SECONDS", "28"))),
        )
        output_pattern = output_dir / "segment_%05d.wav"
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            str(output_pattern),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "FFmpeg est introuvable. Installez-le avec : brew install ffmpeg"
            ) from exc
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or "").strip()
            raise RuntimeError(
                "FFmpeg n’a pas pu décoder ce fichier audio. "
                + (details[-500:] if details else "Vérifiez que le fichier n’est pas corrompu.")
            ) from exc

        chunks = sorted(output_dir.glob("segment_*.wav"))
        if not chunks:
            raise RuntimeError("FFmpeg n’a produit aucun segment audio exploitable.")
        return chunks

    @staticmethod
    def _wav_duration(audio_path: Path) -> float:
        with wave.open(str(audio_path), "rb") as audio:
            frame_rate = audio.getframerate()
            return audio.getnframes() / frame_rate if frame_rate else 0.0

    def transcribe(
        self,
        audio_path: Path,
        prompt: str = "",
        progress: Callable[[int, str], None] | None = None,
    ) -> TranscriptionResult:
        notify = progress or (lambda _value, _message: None)
        if self.demo_mode:
            return self._demo_transcription(notify)

        notify(8, "Découpage sécurisé de l’enregistrement…")
        with tempfile.TemporaryDirectory(prefix="vozlocal_") as temporary_dir:
            audio_chunks = self._split_audio(audio_path, Path(temporary_dir))
            chunk_durations = [self._wav_duration(path) for path in audio_chunks]
            total_duration = sum(chunk_durations)

            notify(18, "Préparation du moteur de transcription…")
            pipe = self._load_pipeline()

            generate_kwargs: dict = {"language": "pt", "task": "transcribe"}
            if prompt and hasattr(pipe.tokenizer, "get_prompt_ids"):
                try:
                    generate_kwargs["prompt_ids"] = pipe.tokenizer.get_prompt_ids(
                        prompt[:500], return_tensors="pt"
                    )
                except (TypeError, ValueError):
                    # Older tokenizer releases can lack tensor prompt support.
                    pass

            segments: list[Segment] = []
            text_parts: list[str] = []
            elapsed = 0.0

            with self._run_lock:
                for index, (chunk_path, chunk_duration) in enumerate(
                    zip(audio_chunks, chunk_durations), start=1
                ):
                    progress_value = 20 + round(67 * (index - 1) / len(audio_chunks))
                    notify(
                        progress_value,
                        f"Transcription du segment {index}/{len(audio_chunks)}…",
                    )
                    output = pipe(
                        str(chunk_path),
                        return_timestamps=True,
                        generate_kwargs=generate_kwargs,
                    )

                    chunk_text = str(output.get("text", "")).strip()
                    raw_chunks = output.get("chunks", []) or []
                    local_segments: list[Segment] = []
                    for raw_chunk in raw_chunks:
                        timestamp = raw_chunk.get("timestamp") or (0.0, None)
                        local_start = max(0.0, float(timestamp[0] or 0.0))
                        raw_end = timestamp[1]
                        local_end = (
                            chunk_duration if raw_end is None else max(local_start, float(raw_end))
                        )
                        local_start = min(local_start, chunk_duration)
                        local_end = min(max(local_end, local_start), chunk_duration)
                        segment_text = str(raw_chunk.get("text", "")).strip()
                        if segment_text:
                            local_segments.append(
                                Segment(
                                    start=elapsed + local_start,
                                    end=elapsed + local_end,
                                    text=segment_text,
                                )
                            )

                    if not chunk_text and local_segments:
                        chunk_text = " ".join(segment.text for segment in local_segments)
                    if chunk_text:
                        text_parts.append(chunk_text)
                        if not local_segments:
                            local_segments.append(
                                Segment(
                                    start=elapsed,
                                    end=elapsed + chunk_duration,
                                    text=chunk_text,
                                )
                            )
                    segments.extend(local_segments)
                    elapsed += chunk_duration

        text = " ".join(text_parts).strip()
        notify(88, "Finalisation de la transcription…")
        return TranscriptionResult(
            text=text,
            segments=segments,
            duration_seconds=total_duration,
        )

    @staticmethod
    def _demo_transcription(notify: Callable[[int, str], None]) -> TranscriptionResult:
        steps = [
            (25, "Chargement du modèle local…"),
            (48, "Analyse des voix…"),
            (72, "Transcription en portugais brésilien…"),
            (88, "Révision des segments…"),
        ]
        for value, message in steps:
            notify(value, message)
            time.sleep(0.35)
        segments = [
            Segment(0, 7.4, "Na aula de hoje, vamos retomar a relação entre Igreja e Eucaristia."),
            Segment(7.4, 15.8, "Essa relação ajuda a compreender a expressão Corpo de Cristo na tradição cristã."),
            Segment(15.8, 24.2, "Em seguida, analisaremos a recepção desse tema no pensamento de Santo Agostinho."),
        ]
        return TranscriptionResult(
            text=" ".join(segment.text for segment in segments),
            segments=segments,
            duration_seconds=24.2,
        )
