from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from models.schemas import DB_COLUMNS, InsertResult, MappedOpportunity

logger = logging.getLogger(__name__)

DB_INSERT_COLUMNS = tuple(column for column in DB_COLUMNS if column != "id")


class OpportunityRepository:
    def __init__(self, engine: Any, table_name: str) -> None:
        self.engine = engine
        self.table_name = table_name
        self._table = None

    @property
    def table(self) -> Any:
        if self._table is None:
            from sqlalchemy import MetaData, Table
            from sqlalchemy.exc import NoSuchTableError

            metadata = MetaData()
            try:
                self._table = Table(self.table_name, metadata, autoload_with=self.engine)
            except NoSuchTableError:
                logger.error("Falta la tabla destino: %s", self.table_name)
                raise
        return self._table

    def insert_opportunity(self, mapped_opportunity: MappedOpportunity) -> InsertResult:
        try:
            duplicate_reason = self._duplicate_reason(mapped_opportunity)
            if duplicate_reason:
                logger.info("Duplicado detectado en DB: %s url=%s", duplicate_reason, mapped_opportunity.url)
                return InsertResult(
                    inserted=False,
                    skipped=True,
                    duplicate=True,
                    reason=duplicate_reason,
                    url=mapped_opportunity.url,
                    reference=mapped_opportunity.referencia,
                    table_name=self.table_name,
                )

            row = self._row_for_insert(mapped_opportunity)
            from sqlalchemy import insert

            with self.engine.begin() as connection:
                result = connection.execute(insert(self.table), row)
                inserted_id = self._inserted_id(result)

            logger.info("Insercion exitosa en %s url=%s", self.table_name, mapped_opportunity.url)
            return InsertResult(
                inserted=True,
                inserted_id=inserted_id,
                url=mapped_opportunity.url,
                reference=mapped_opportunity.referencia,
                table_name=self.table_name,
            )
        except Exception as exc:
            logger.exception("Error insertando oportunidad en %s", self.table_name)
            return InsertResult(
                inserted=False,
                skipped=True,
                error=str(exc),
                url=mapped_opportunity.url,
                reference=mapped_opportunity.referencia,
                table_name=self.table_name,
            )

    def exists_by_url(self, url: str) -> bool:
        if not url or "url" not in self.table.c:
            return False
        from sqlalchemy import func, select

        statement = select(self.table.c.url).where(func.lower(self.table.c.url) == url.strip().lower()).limit(1)
        with self.engine.connect() as connection:
            return connection.execute(statement).first() is not None

    def exists_by_reference(self, reference: str) -> bool:
        if not reference or "referencia" not in self.table.c:
            return False
        from sqlalchemy import func, select

        statement = (
            select(self.table.c.referencia)
            .where(func.lower(self.table.c.referencia) == reference.strip().lower())
            .limit(1)
        )
        with self.engine.connect() as connection:
            return connection.execute(statement).first() is not None

    def exists_similar(self, title: str, deadline: date | None, organismo: str | None) -> bool:
        if not title or "titulo_estudio" not in self.table.c:
            return False
        if "deadline" not in self.table.c or "organismo_contratado" not in self.table.c:
            return False

        from sqlalchemy import and_, func, select

        normalized_title = self._normalize_text(title)
        conditions = [func.lower(func.trim(self.table.c.titulo_estudio)) == normalized_title]
        if deadline is not None:
            conditions.append(self.table.c.deadline == deadline)
        if organismo:
            conditions.append(func.lower(func.trim(self.table.c.organismo_contratado)) == self._normalize_text(organismo))

        statement = select(self.table.c.titulo_estudio).where(and_(*conditions)).limit(1)
        with self.engine.connect() as connection:
            return connection.execute(statement).first() is not None

    def insert_many(self, opportunities: list[MappedOpportunity]) -> list[InsertResult]:
        if not opportunities:
            return []
        return [self.insert_opportunity(opportunity) for opportunity in opportunities]

    def get_recent(self, days: int) -> list[dict[str, Any]]:
        from sqlalchemy import select

        statement = select(self.table)
        if "fecha_carga" in self.table.c:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            statement = statement.where(self.table.c.fecha_carga >= cutoff)
        if "id" in self.table.c:
            statement = statement.order_by(self.table.c.id.desc())
        elif "fecha_carga" in self.table.c:
            statement = statement.order_by(self.table.c.fecha_carga.desc())

        with self.engine.connect() as connection:
            return [dict(row._mapping) for row in connection.execute(statement).fetchall()]

    def validate_expected_columns(self) -> list[str]:
        table_columns = set(self.table.c.keys())
        missing = [column for column in DB_COLUMNS if column not in table_columns]
        for column in missing:
            logger.warning("Columna esperada no existe en %s: %s", self.table_name, column)
        return missing

    def _duplicate_reason(self, opportunity: MappedOpportunity) -> str | None:
        if opportunity.url and self.exists_by_url(opportunity.url):
            return "duplicate_url"
        if opportunity.referencia and self.exists_by_reference(opportunity.referencia):
            return "duplicate_reference"
        if opportunity.titulo_estudio and self.exists_similar(
            opportunity.titulo_estudio,
            opportunity.deadline,
            opportunity.organismo_contratado,
        ):
            return "duplicate_similar_title_deadline_authority"
        return None

    def _row_for_insert(self, opportunity: MappedOpportunity) -> dict[str, Any]:
        self.validate_expected_columns()
        table_columns = set(self.table.c.keys())
        payload = opportunity.to_db_dict(exclude_none=False)
        payload.pop("id", None)
        payload["fecha_carga"] = payload.get("fecha_carga") or datetime.now(timezone.utc)
        payload["motivo_rechazo"] = None

        row = {
            column: payload.get(column)
            for column in DB_INSERT_COLUMNS
            if column in table_columns
        }
        return row

    @staticmethod
    def _inserted_id(result: Any) -> int | None:
        try:
            if result.inserted_primary_key:
                return int(result.inserted_primary_key[0])
        except Exception:
            return None
        return None

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.strip().lower().split())
