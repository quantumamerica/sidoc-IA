from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from utils.dates import today_utc_date


VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class PromptLoader:
    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir

    def load(self, relative_path: str) -> str:
        path = self.prompts_dir / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Prompt no encontrado: {path}")
        return path.read_text(encoding="utf-8")

    def load_optional(self, relative_path: str) -> str:
        path = self.prompts_dir / relative_path
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def render(self, template: str, variables: dict[str, Any] | None = None) -> str:
        values = variables or {}

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in values or values[key] is None:
                return ""
            return self._stringify(values[key])

        return VARIABLE_PATTERN.sub(replace, template)

    def render_file(self, relative_path: str, variables: dict[str, Any] | None = None) -> str:
        return self.render(self.load(relative_path), variables)

    def shared_variables(
        self,
        *,
        current_date: date | str | None = None,
        region: str | None = None,
        sources: Any = None,
        provider_name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        variables: dict[str, Any] = {
            "current_date": current_date or today_utc_date().isoformat(),
            "region": region,
            "sources": sources,
            "provider_name": provider_name,
            "eligibility_criteria": self.load_optional("shared/eligibility_criteria.md"),
            "output_schema": self.load_optional("shared/output_schema.md"),
        }
        if extra:
            variables.update(extra)
        return variables

    def compose(
        self,
        *,
        agent_prompt: str,
        discovery_prompt: str | None = None,
        variables: dict[str, Any] | None = None,
        include_shared: bool = True,
    ) -> str:
        parts: list[str] = []
        if include_shared:
            parts.extend(
                [
                    self.load_optional("shared/eligibility_criteria.md"),
                    self.load_optional("shared/output_schema.md"),
                ]
            )
        parts.append(self.load(agent_prompt))
        if discovery_prompt:
            parts.append(self.load(discovery_prompt))

        rendered = [self.render(part, variables) for part in parts if part.strip()]
        return "\n\n".join(rendered)

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, date):
            return value.isoformat()
        if hasattr(value, "model_dump"):
            return json.dumps(value.model_dump(mode="json"), ensure_ascii=False)
        return json.dumps(value, ensure_ascii=False, default=str)
