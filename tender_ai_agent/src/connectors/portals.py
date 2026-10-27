from __future__ import annotations

from datetime import date
from typing import Any

from connectors.base import BaseConnector, normalize


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", []):
            return value
    return None


def _date_part(value: Any) -> str | None:
    """'2026-10-27T00:00:00.000' -> '2026-10-27'. Deja otros formatos como vienen."""
    if not value:
        return None
    text = str(value).strip()
    return text[:10] if len(text) >= 10 and text[4] == "-" and text[7] == "-" else text


class SecopConnector(BaseConnector):
    """SECOP II en datos.gov.co (Socrata). Filtra por fecha de publicacion en el servidor."""

    PAGE_SIZE = 1000

    def _records(self, since: date, until: date):
        date_field = self.config.extra("date_field", "fecha_de_publicacion_del")
        max_items = int(self.config.extra("max_items", 2000))
        offset = 0
        while offset < max_items:
            page = self._get(
                self.config.endpoint,
                {
                    "$where": f"{date_field} >= '{since.isoformat()}T00:00:00'",
                    "$order": f"{date_field} DESC",
                    "$limit": self.PAGE_SIZE,
                    "$offset": offset,
                },
            )
            if not isinstance(page, list) or not page:
                return
            yield from page
            if len(page) < self.PAGE_SIZE:
                return
            offset += self.PAGE_SIZE

    def _to_item(self, record: dict[str, Any]) -> dict[str, Any] | None:
        estado = normalize(_first(record, "estado_del_procedimiento", "estado_de_apertura_del_proceso"))
        if estado and any(word in estado for word in ("adjudicado", "cancelado", "desierto", "cerrado", "terminado")):
            return None
        url = record.get("urlproceso")
        if isinstance(url, dict):
            url = url.get("url")
        return self._item(
            title=_first(record, "nombre_del_procedimiento"),
            url=url,
            authority=_first(record, "entidad"),
            description=_first(record, "descripci_n_del_procedimiento", "descripcion_del_procedimiento"),
            deadline=_date_part(_first(record, "fecha_de_recepcion_de", "fecha_de_apertura_de_respuesta")),
            published=_date_part(_first(record, "fecha_de_publicacion_del")),
            reference=_first(record, "referencia_del_proceso", "id_del_proceso"),
            notes=[f"Modalidad: {record['modalidad_de_contratacion']}"] if record.get("modalidad_de_contratacion") else None,
        )


class PncpConnector(BaseConnector):
    """PNCP (Brasil): contrataciones publicadas por modalidad, paginadas de a 50."""

    PAGE_SIZE = 50

    def _records(self, since: date, until: date):
        max_pages = int(self.config.extra("max_pages", 20))
        for modalidad in self.config.extra("modalidades", [6]):
            for page_number in range(1, max_pages + 1):
                page = self._get(
                    self.config.endpoint,
                    {
                        "dataInicial": since.strftime("%Y%m%d"),
                        "dataFinal": until.strftime("%Y%m%d"),
                        "codigoModalidadeContratacao": modalidad,
                        "pagina": page_number,
                        "tamanhoPagina": self.PAGE_SIZE,
                    },
                )
                if not isinstance(page, dict):
                    break
                data = page.get("data") or []
                yield from data
                total_pages = page.get("totalPaginas")
                if not data or (total_pages is not None and page_number >= int(total_pages)):
                    break

    def _to_item(self, record: dict[str, Any]) -> dict[str, Any] | None:
        orgao = record.get("orgaoEntidade") or {}
        unidade = record.get("unidadeOrgao") or {}
        cnpj, ano, sequencial = orgao.get("cnpj"), record.get("anoCompra"), record.get("sequencialCompra")
        url = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}" if cnpj and ano and sequencial else record.get("linkSistemaOrigem")
        objeto = _first(record, "objetoCompra")
        lugar = ", ".join(part for part in (unidade.get("municipioNome"), unidade.get("ufSigla")) if part)
        notes = [f"Modalidade: {record['modalidadeNome']}"] if record.get("modalidadeNome") else []
        if lugar:
            notes.append(f"Local: {lugar}")
        return self._item(
            title=objeto[:300] if objeto else None,
            url=url,
            authority=_first(orgao, "razaoSocial") or _first(unidade, "nomeUnidade"),
            description=" ".join(part for part in (objeto, record.get("informacaoComplementar")) if part),
            deadline=_date_part(_first(record, "dataEncerramentoProposta")),
            published=_date_part(_first(record, "dataPublicacaoPncp")),
            reference=_first(record, "numeroControlePNCP"),
            notes=notes,
        )


class WorldBankConnector(BaseConnector):
    """Avisos de compras del Banco Mundial (search.worldbank.org), los mas recientes primero."""

    def _records(self, since: date, until: date):
        page = self._get(
            self.config.endpoint,
            {
                "format": "json",
                "rows": int(self.config.extra("rows", 500)),
                "os": 0,
                "srt": "noticedate",
                "order": "desc",
                "apilang": "en",
            },
        )
        notices = page.get("procnotices") if isinstance(page, dict) else None
        if isinstance(notices, dict):
            notices = list(notices.values())
        wanted = [normalize(value) for value in self.config.extra("notice_types", [])]
        for record in notices or []:
            if not isinstance(record, dict):
                continue
            published = _date_part(_first(record, "noticedate", "notice_date", "submission_date"))
            if published and len(published) == 10 and published < since.isoformat():
                continue
            notice_type = normalize(_first(record, "notice_type"))
            if wanted and notice_type and not any(value in notice_type for value in wanted):
                continue
            yield record

    def _to_item(self, record: dict[str, Any]) -> dict[str, Any] | None:
        notice_id = _first(record, "id")
        project = _first(record, "project_name")
        description = _first(record, "bid_description")
        title = description if description and len(str(description)) <= 300 else project
        return self._item(
            title=title,
            url=f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{notice_id}" if notice_id else None,
            authority=_first(record, "contact_organization", "borrower"),
            description=" - ".join(str(part) for part in (project, description) if part),
            deadline=_date_part(_first(record, "submission_deadline_date", "deadline_date", "submission_date")),
            published=_date_part(_first(record, "noticedate", "notice_date")),
            reference=_first(record, "bid_reference_no"),
            country=_first(record, "project_ctry_name"),
            notes=[f"Tipo de aviso: {record['notice_type']}"] if record.get("notice_type") else None,
        )


CONNECTOR_CLASSES = {
    "secop": SecopConnector,
    "pncp": PncpConnector,
    "worldbank": WorldBankConnector,
}
