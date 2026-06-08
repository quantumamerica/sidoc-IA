from __future__ import annotations

from config.settings import Settings
from models.schemas import (
    OpenWebDiscoveryConfig,
    OpenWebRegionConfig,
    OpenWebSourcePolicy,
    OpenWebTheme,
    ProviderName,
    RawProviderResponse,
    SourceConfig,
)
from utils.prompt_loader import PromptLoader
from utils.source_loader import SourceLoader


class DiscoveryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.prompt_loader = PromptLoader(settings.prompts_dir)

    def build_messages(
        self,
        region_prompt_name: str,
        source: SourceConfig,
        provider_name: str | None = None,
    ) -> list[dict[str, str]]:
        variables = self.prompt_loader.shared_variables(
            region=source.region,
            sources=[source.to_json_dict(exclude_none=True)],
            provider_name=provider_name,
            extra={
                "source_id": source.id,
                "source_name": source.name,
                "source_url": source.url,
            },
        )
        system_role = self.prompt_loader.render_file("shared/system_role.md", variables)
        user_prompt = self.prompt_loader.compose(
            agent_prompt="agents/search_agent.md",
            discovery_prompt=f"discovery/{region_prompt_name}",
            variables=variables,
            include_shared=True,
        )

        return [
            {"role": "system", "content": system_role},
            {"role": "user", "content": user_prompt},
        ]

    def load_open_web_config(self) -> OpenWebDiscoveryConfig:
        path = self.settings.config_dir / "open_web_discovery.yaml"
        if not path.exists():
            return OpenWebDiscoveryConfig(enabled=False)
        data = SourceLoader._read_yaml(path)
        return OpenWebDiscoveryConfig.model_validate(data)

    def build_open_web_messages(
        self,
        *,
        region: str,
        theme: OpenWebTheme,
        region_config: OpenWebRegionConfig,
        source_policy: OpenWebSourcePolicy,
        provider_name: str | None = None,
    ) -> list[dict[str, str]]:
        variables = self.prompt_loader.shared_variables(
            region=region,
            sources=[],
            provider_name=provider_name,
            extra={
                "theme_id": theme.id,
                "theme_name": theme.name,
                "theme_queries": self._regionalized_queries(theme.search_queries, region_config.query_terms),
                "theme_keywords": theme.keywords,
                "region_scope": region_config.region_scope,
                "languages": region_config.languages,
                "region_query_terms": region_config.query_terms,
                "official_source_policy": source_policy.to_json_dict(exclude_none=True),
            },
        )
        system_role = self.prompt_loader.render_file("shared/system_role.md", variables)
        user_prompt = self.prompt_loader.compose(
            agent_prompt="agents/open_web_discovery_agent.md",
            variables=variables,
            include_shared=True,
        )

        return [
            {"role": "system", "content": system_role},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _regionalized_queries(theme_queries: list[str], region_terms: list[str]) -> list[str]:
        if not theme_queries or not region_terms:
            return theme_queries
        focused_terms = " OR ".join(region_terms[:6])
        return [f"{query} ({focused_terms})" for query in theme_queries]

    def dry_run_response(self, provider: ProviderName, region: str, source: SourceConfig) -> RawProviderResponse:
        return RawProviderResponse(
            provider=provider,
            region=region,
            source_id=source.id,
            source_name=source.name,
            source_url=source.url,
            prompt_name="dry_run",
            content='{"items": []}',
            metadata={"dry_run": True, "source_name": source.name},
        )
