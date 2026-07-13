from dataclasses import dataclass

from aion_formats.level import BrushList, ObjectsList


SOURCE_OBJECT = "OBJECT"
SOURCE_BRUSH = "BRUSH"


@dataclass(frozen=True)
class LevelCgfJob:
    source_type: str
    source_index: int
    cgf_reference: str
    import_mode: str
    cache_key: tuple[str, str]
    position: tuple[float, float, float] | None = None
    scale: float | None = None
    heading_raw: int | None = None
    heading_degrees: float | None = None
    transform: tuple[float, ...] | None = None
    mesh_index: int | None = None


@dataclass(frozen=True)
class UnresolvedCgfReference:
    source_type: str
    source_index: int
    reason: str
    reference_index: int | None = None


@dataclass(frozen=True)
class LevelCgfJobs:
    jobs: tuple[LevelCgfJob, ...]
    unresolved: tuple[UnresolvedCgfReference, ...]

    @property
    def object_jobs(self) -> tuple[LevelCgfJob, ...]:
        return tuple(job for job in self.jobs if job.source_type == SOURCE_OBJECT)

    @property
    def brush_jobs(self) -> tuple[LevelCgfJob, ...]:
        return tuple(job for job in self.jobs if job.source_type == SOURCE_BRUSH)


def _cache_key(cgf_reference: str, import_mode: str) -> tuple[str, str]:
    return (cgf_reference.replace("\\", "/").lower(), import_mode)


def collect_level_cgf_jobs(
    objects: ObjectsList | None,
    brush: BrushList | None,
    import_mode: str = "VISUAL",
) -> LevelCgfJobs:
    jobs = []
    unresolved = []

    if objects is not None:
        for index, placement in enumerate(objects.placements):
            if not placement.vegetation_file:
                unresolved.append(
                    UnresolvedCgfReference(
                        source_type=SOURCE_OBJECT,
                        source_index=index,
                        reason="missing vegetation file reference",
                        reference_index=placement.vegetation_index,
                    )
                )
                continue

            jobs.append(
                LevelCgfJob(
                    source_type=SOURCE_OBJECT,
                    source_index=index,
                    cgf_reference=placement.vegetation_file,
                    import_mode=import_mode,
                    cache_key=_cache_key(placement.vegetation_file, import_mode),
                    position=placement.position,
                    scale=placement.scale,
                    heading_raw=placement.heading_raw,
                    heading_degrees=placement.heading_degrees,
                )
            )

    if brush is not None:
        for node in brush.nodes:
            if not node.mesh_file_name:
                unresolved.append(
                    UnresolvedCgfReference(
                        source_type=SOURCE_BRUSH,
                        source_index=node.index,
                        reason="missing brush mesh reference",
                        reference_index=node.mesh_index,
                    )
                )
                continue

            jobs.append(
                LevelCgfJob(
                    source_type=SOURCE_BRUSH,
                    source_index=node.index,
                    cgf_reference=node.mesh_file_name,
                    import_mode=import_mode,
                    cache_key=_cache_key(node.mesh_file_name, import_mode),
                    transform=node.transform,
                    mesh_index=node.mesh_index,
                )
            )

    return LevelCgfJobs(jobs=tuple(jobs), unresolved=tuple(unresolved))
