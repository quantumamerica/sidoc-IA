from __future__ import annotations

import logging

from config.settings import Settings
from connectors.base import BaseConnector, ConnectorConfig
from connectors.portals import CONNECTOR_CLASSES
from utils.source_loader import SourceLoader

logger = logging.getLogger(__name__)


def load_connector_configs(settings: Settings) -> list[ConnectorConfig]:
    path = settings.config_dir / "connectors.yaml"
    if not path.exists():
        return []
    data = SourceLoader._read_yaml(path) or {}
    return [ConnectorConfig.model_validate(item) for item in data.get("connectors") or []]


def build_connectors(
    settings: Settings,
    *,
    region: str | None = None,
    only_enabled: bool = True,
    connector_id: str | None = None,
) -> list[BaseConnector]:
    connectors: list[BaseConnector] = []
    for config in load_connector_configs(settings):
        if only_enabled and not config.enabled:
            continue
        if region is not None and config.region != region:
            continue
        if connector_id is not None and config.id != connector_id:
            continue
        connector_class = CONNECTOR_CLASSES.get(config.id)
        if connector_class is None:
            logger.warning("Conector sin implementacion id=%s, se omite", config.id)
            continue
        connectors.append(connector_class(config, settings))
    return connectors
