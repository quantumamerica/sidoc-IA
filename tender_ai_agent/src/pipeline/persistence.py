from __future__ import annotations

import logging
from datetime import datetime, timezone

from config.settings import Settings
from models.schemas import InsertResult, MappedOpportunity
from storage.database import get_engine
from storage.repositories import OpportunityRepository
from utils.json_utils import write_json

logger = logging.getLogger(__name__)


class PersistenceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last_insert_results: list[InsertResult] = []

    def persist(
        self,
        opportunities: list[MappedOpportunity],
        dry_run: bool,
        run_id: str | None = None,
        skip_db: bool = False,
    ) -> int:
        self.last_insert_results = []
        if skip_db:
            logger.info("Modo --no-db activo: no se insertan oportunidades.")
            return 0
        if dry_run:
            logger.info("Dry-run activo: no se insertan oportunidades.")
            return 0

        engine = get_engine(self.settings)
        if engine is None:
            logger.warning("DATABASE_URL no configurada: no se insertan oportunidades.")
            return 0

        repository = OpportunityRepository(engine, self.settings.db_table_name)
        results = repository.insert_many(opportunities)
        self.last_insert_results = results
        self._save_audit(results, run_id=run_id)
        return sum(1 for result in results if result.inserted)

    def _save_audit(self, results: list[InsertResult], run_id: str | None) -> None:
        if not results:
            return
        duplicates_or_errors = [
            result.model_dump(mode="json")
            for result in results
            if result.duplicate or result.error or result.skipped
        ]
        if not duplicates_or_errors:
            return

        if run_id:
            path = self.settings.output_dir / run_id / "db_insert_audit.json"
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = self.settings.log_dir / "audit" / f"db_insert_audit_{stamp}.json"
        write_json(path, duplicates_or_errors)
