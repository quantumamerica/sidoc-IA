from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from clients.openai_client import OpenAIClient
from clients.perplexity_client import PerplexityClient
from config.settings import load_settings
from utils.logging_config import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prueba manual de proveedores IA.")
    parser.add_argument("--provider", choices=["openai", "perplexity"], required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = load_settings(PROJECT_ROOT)
    configure_logging(settings)

    client = OpenAIClient(settings) if args.provider == "openai" else PerplexityClient(settings)
    prompt = (
        "Devuelve exclusivamente JSON valido, sin Markdown ni texto adicional, "
        f'con este contenido exacto salvo el proveedor: {{"status": "ok", "provider": "{args.provider}"}}'
    )

    response = client.run_agent(prompt, response_format="json", stage="manual_test")
    print(
        json.dumps(
            {
                "provider": response.provider.value,
                "model": response.model,
                "content": response.content,
                "parsed_json": response.parsed_json,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "estimated_cost": response.estimated_cost,
                "created_at": response.created_at.isoformat(),
                "error": response.error,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0 if response.error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
