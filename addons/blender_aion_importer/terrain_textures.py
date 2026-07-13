from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TerrainDetailTextureReference:
    raw_path: str
    normalized_relative_path: str
    resolved_path: str | None
    exists: bool


def resolve_terrain_detail_texture(
    client_root: str | Path | None,
    detail_texture: str | None,
) -> TerrainDetailTextureReference:
    raw_path = detail_texture or ""
    normalized_relative_path = raw_path.replace("\\", "/").lstrip("/")

    if not client_root or not normalized_relative_path:
        return TerrainDetailTextureReference(
            raw_path=raw_path,
            normalized_relative_path=normalized_relative_path,
            resolved_path=None,
            exists=False,
        )

    resolved_path = Path(client_root) / Path(*normalized_relative_path.split("/"))
    return TerrainDetailTextureReference(
        raw_path=raw_path,
        normalized_relative_path=normalized_relative_path,
        resolved_path=str(resolved_path),
        exists=resolved_path.is_file(),
    )
