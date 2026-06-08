from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from config.settings import Settings
from models.schemas import RegionConfig, SourceConfig


class SourceLoader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load_sources(self) -> list[SourceConfig]:
        data = self._read_yaml(self.settings.config_dir / "sources.yaml")
        raw_sources = data.get("sources", [])
        sources: list[SourceConfig] = []
        seen_ids: set[str] = set()

        for index, item in enumerate(raw_sources, start=1):
            try:
                source = SourceConfig.model_validate(item)
            except ValidationError as exc:
                raise ValueError(f"Fuente invalida en sources.yaml posicion {index}: {exc}") from exc

            if source.id in seen_ids:
                raise ValueError(f"Fuente duplicada en sources.yaml: {source.id}")
            seen_ids.add(source.id)
            sources.append(source)

        return sources

    def load_regions(self) -> dict[str, RegionConfig]:
        data = self._read_yaml(self.settings.config_dir / "region_groups.yaml")
        regions = data.get("regions", {})
        return {
            key: RegionConfig(
                key=key,
                description=value["description"],
                prompt_file=value["prompt_file"],
            )
            for key, value in regions.items()
        }

    def list_sources(
        self,
        *,
        region: str | None = None,
        enabled_only: bool = False,
        skip_restricted: bool = False,
    ) -> list[SourceConfig]:
        sources = self.load_sources()
        return self.filter_sources(
            sources,
            region=region,
            enabled_only=enabled_only,
            skip_restricted=skip_restricted,
        )

    def select_sources(
        self,
        region: str,
        *,
        enabled_only: bool = True,
        skip_restricted: bool = True,
    ) -> list[SourceConfig]:
        return self.list_sources(
            region=None if region == "all" else region,
            enabled_only=enabled_only,
            skip_restricted=skip_restricted,
        )

    @staticmethod
    def filter_sources(
        sources: list[SourceConfig],
        *,
        region: str | None = None,
        enabled_only: bool = False,
        skip_restricted: bool = False,
    ) -> list[SourceConfig]:
        filtered = sources
        if region:
            filtered = [source for source in filtered if source.region == region]
        if enabled_only:
            filtered = [source for source in filtered if source.enabled]
        if skip_restricted:
            filtered = [source for source in filtered if not source.is_restricted]
        return filtered

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}
