from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .level_jobs import LevelCgfJob


@dataclass(frozen=True)
class ResolvedLevelCgfJob:
    job: LevelCgfJob
    original_reference: str
    normalized_reference: str
    resolved_path: Path | None
    missing_reason: str | None = None


@dataclass(frozen=True)
class LevelResourceResolution:
    client_root: Path | None
    enabled: bool
    resolved: tuple[ResolvedLevelCgfJob, ...]
    missing: tuple[ResolvedLevelCgfJob, ...]
    unique_resolved_paths: tuple[Path, ...]


def normalize_resource_reference(reference: str) -> str:
    return reference.replace("\\", "/").strip().lstrip("/").lower()


def resolve_level_cgf_jobs(
    jobs: Iterable[LevelCgfJob],
    client_root: str | Path | None,
) -> LevelResourceResolution:
    if not client_root:
        return LevelResourceResolution(
            client_root=None,
            enabled=False,
            resolved=(),
            missing=(),
            unique_resolved_paths=(),
        )

    root = Path(client_root)
    resolved_jobs = []
    missing_jobs = []
    path_cache: dict[str, Path | None] = {}

    for job in jobs:
        normalized_reference = normalize_resource_reference(job.cgf_reference)
        if normalized_reference not in path_cache:
            path_cache[normalized_reference] = _resolve_case_insensitive_path(root, normalized_reference)

        resolved_path = path_cache[normalized_reference]
        resolved_job = ResolvedLevelCgfJob(
            job=job,
            original_reference=job.cgf_reference,
            normalized_reference=normalized_reference,
            resolved_path=resolved_path,
            missing_reason=None if resolved_path is not None else "file not found",
        )
        if resolved_path is None:
            missing_jobs.append(resolved_job)
        else:
            resolved_jobs.append(resolved_job)

    unique_paths = tuple(dict.fromkeys(job.resolved_path for job in resolved_jobs if job.resolved_path is not None))
    return LevelResourceResolution(
        client_root=root,
        enabled=True,
        resolved=tuple(resolved_jobs),
        missing=tuple(missing_jobs),
        unique_resolved_paths=unique_paths,
    )


def _resolve_case_insensitive_path(root: Path, normalized_reference: str) -> Path | None:
    current = root
    for part in normalized_reference.split("/"):
        if not part:
            continue

        candidate = current / part
        if candidate.exists():
            current = candidate
            continue

        if not current.is_dir():
            return None

        lowered_part = part.lower()
        match = next((child for child in current.iterdir() if child.name.lower() == lowered_part), None)
        if match is None:
            return None
        current = match

    return current if current.is_file() else None
