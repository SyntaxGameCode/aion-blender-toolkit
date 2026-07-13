from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .level_jobs import SOURCE_BRUSH, SOURCE_OBJECT, LevelCgfJob
from .resource_resolver import ResolvedLevelCgfJob


TemplateKey = tuple[str, str]


@dataclass(frozen=True)
class LevelCgfTemplate:
    template_key: TemplateKey
    import_mode: str
    normalized_reference: str
    normalized_resolved_path: str
    resolved_path: Path
    placements: tuple[LevelCgfJob, ...]
    placement_count: int
    object_placement_count: int
    brush_placement_count: int


@dataclass(frozen=True)
class LevelCgfTemplateCollection:
    templates: tuple[LevelCgfTemplate, ...]
    total_placement_count: int
    max_placements_per_template: int


def make_level_cgf_template_key(resolved_job: ResolvedLevelCgfJob) -> TemplateKey:
    if resolved_job.resolved_path is None:
        raise ValueError("resolved path is required for a level CGF template")

    normalized_path = _normalize_resolved_path(resolved_job.resolved_path)
    return (normalized_path, resolved_job.job.import_mode)


def group_level_cgf_templates(
    resolved_jobs: Iterable[ResolvedLevelCgfJob],
) -> LevelCgfTemplateCollection:
    grouped: dict[TemplateKey, list[ResolvedLevelCgfJob]] = {}
    for resolved_job in resolved_jobs:
        key = make_level_cgf_template_key(resolved_job)
        grouped.setdefault(key, []).append(resolved_job)

    templates = []
    for template_key, grouped_jobs in grouped.items():
        first = grouped_jobs[0]
        placements = tuple(resolved_job.job for resolved_job in grouped_jobs)
        source_counts = Counter(job.source_type for job in placements)
        templates.append(
            LevelCgfTemplate(
                template_key=template_key,
                import_mode=first.job.import_mode,
                normalized_reference=first.normalized_reference,
                normalized_resolved_path=template_key[0],
                resolved_path=first.resolved_path,
                placements=placements,
                placement_count=len(placements),
                object_placement_count=source_counts[SOURCE_OBJECT],
                brush_placement_count=source_counts[SOURCE_BRUSH],
            )
        )

    return LevelCgfTemplateCollection(
        templates=tuple(templates),
        total_placement_count=sum(template.placement_count for template in templates),
        max_placements_per_template=max(
            (template.placement_count for template in templates),
            default=0,
        ),
    )


def _normalize_resolved_path(path: Path) -> str:
    return path.resolve().as_posix().lower()
