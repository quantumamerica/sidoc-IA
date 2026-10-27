"""Conectores a APIs de portales con respuestas simuladas (sin red)."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config.settings import load_settings
from connectors.base import to_raw_response
from connectors.registry import build_connectors, load_connector_configs
from models.schemas import ProviderName
from pipeline.identification import IdentificationService

SETTINGS = load_settings(PROJECT_ROOT)
TODAY = date(2026, 10, 27)


def connector(connector_id: str, pages: list):
    [instance] = build_connectors(SETTINGS, only_enabled=False, connector_id=connector_id)
    calls: list[dict] = []

    def fake_get(url, params):
        calls.append(params)
        return pages[len(calls) - 1] if len(calls) <= len(pages) else []

    instance._get = fake_get
    return instance, calls


def test_config() -> None:
    configs = {config.id: config for config in load_connector_configs(SETTINGS)}
    assert set(configs) == {"secop", "pncp", "worldbank"}
    assert not any(config.enabled for config in configs.values()), "el piloto arranca apagado"
    assert build_connectors(SETTINGS, region="latam") == []
    assert {c.config.id for c in build_connectors(SETTINGS, region="latam", only_enabled=False)} == {"secop", "pncp"}


def test_secop() -> None:
    instance, calls = connector(
        "secop",
        [[
            {
                "nombre_del_procedimiento": "Consultoría para el estudio tarifario de energía eléctrica",
                "descripci_n_del_procedimiento": "Estudio de costos",
                "entidad": "CREG",
                "fecha_de_publicacion_del": "2026-10-26T00:00:00.000",
                "fecha_de_recepcion_de": "2026-11-20T00:00:00.000",
                "referencia_del_proceso": "CREG-CM-010-2026",
                "urlproceso": {"url": "https://community.secop.gov.co/Public/Tendering/OpportunityDetail/Index?noticeUID=CO1.NTC.1"},
                "estado_del_procedimiento": "Publicado",
            },
            {"nombre_del_procedimiento": "Compra de papelería", "urlproceso": {"url": "https://x/2"}},
            {
                "nombre_del_procedimiento": "Consultoría tarifas de energía",
                "urlproceso": {"url": "https://x/3"},
                "estado_del_procedimiento": "Adjudicado",
            },
        ]],
    )
    result = instance.fetch(TODAY)
    assert result.error is None and result.fetched == 3
    assert len(result.items) == 1
    item = result.items[0]
    assert item["referencia"] == "CREG-CM-010-2026"
    assert item["deadline_raw"] == "2026-11-20" and item["publication_date_raw"] == "2026-10-26"
    assert "fecha_de_publicacion_del >= '2026-10-24" in calls[0]["$where"]


def test_pncp_paging() -> None:
    record = {
        "objetoCompra": "Contratação de consultoria para estudo de revisão tarifária de energia elétrica",
        "orgaoEntidade": {"cnpj": "00000000000191", "razaoSocial": "ANEEL"},
        "unidadeOrgao": {"municipioNome": "Brasília", "ufSigla": "DF"},
        "anoCompra": 2026,
        "sequencialCompra": 15,
        "numeroControlePNCP": "00000000000191-1-000015/2026",
        "dataPublicacaoPncp": "2026-10-25T10:00:00",
        "dataEncerramentoProposta": "2026-11-30T18:00:00",
        "modalidadeNome": "Pregão - Eletrônico",
    }
    pages = [{"data": [record], "totalPaginas": 2}, {"data": [{"objetoCompra": "Aquisição de cadeiras"}], "totalPaginas": 2}]
    pages += [{"data": [], "totalPaginas": 0}] * 4
    instance, calls = connector("pncp", pages)
    result = instance.fetch(TODAY)
    assert result.error is None and result.fetched == 2
    assert [c["pagina"] for c in calls[:2]] == [1, 2]
    assert len(calls) == 4, "dos paginas para la primera modalidad y una vacia para cada una de las otras dos"
    assert result.items[0]["official_url"] == "https://pncp.gov.br/app/editais/00000000000191/2026/15"
    assert "Local: Brasília, DF" in result.items[0]["audit_notes"]


def test_worldbank() -> None:
    payload = {
        "procnotices": [
            {
                "id": "OP00412345",
                "notice_type": "Request for Expression of Interest",
                "noticedate": "2026-10-26",
                "submission_deadline_date": "2026-11-15T00:00:00Z",
                "project_name": "Energy Sector Reform Project",
                "bid_description": "Consultancy for electricity tariff study",
                "project_ctry_name": "Honduras",
                "contact_organization": "ENEE",
            },
            {
                "id": "OP2",
                "notice_type": "Contract Award",
                "noticedate": "2026-10-26",
                "bid_description": "Consultancy for electricity tariff study",
            },
            {
                "id": "OP3",
                "notice_type": "Request for Expression of Interest",
                "noticedate": "2026-09-01",
                "bid_description": "Consultancy for electricity tariff study",
            },
        ]
    }
    instance, _ = connector("worldbank", [payload])
    result = instance.fetch(TODAY)
    assert result.error is None and result.fetched == 1
    [item] = result.items
    assert item["country"] == "Honduras"
    assert item["official_url"].endswith("/procurement-detail/OP00412345")


def test_error_does_not_raise() -> None:
    instance, _ = connector("secop", [])

    def boom(url, params):
        raise ConnectionError("403 Forbidden")

    instance._get = boom
    result = instance.fetch(TODAY)
    assert result.items == [] and "403" in result.error


def test_identification_reads_connector_items() -> None:
    instance, _ = connector(
        "secop",
        [[{
            "nombre_del_procedimiento": "Consultoría regulación de gas natural",
            "entidad": "CREG",
            "urlproceso": {"url": "https://x/1"},
        }]],
    )
    result = instance.fetch(TODAY)
    raw = to_raw_response(ProviderName.PERPLEXITY, "latam", "20261027_230000", result, instance.config)
    [candidate] = IdentificationService().identify([raw])
    assert candidate.source_id == "api_secop"
    assert candidate.metadata["raw_response_metadata"]["discovery_mode"] == "api"
    assert json.loads(raw.content)["items"][0]["contracting_authority"] == "CREG"


def main() -> None:
    test_config()
    test_secop()
    test_pncp_paging()
    test_worldbank()
    test_error_does_not_raise()
    test_identification_reads_connector_items()
    print("OK conectores")


if __name__ == "__main__":
    main()
