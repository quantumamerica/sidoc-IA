Objetivo: realizar busqueda amplia de posibles oportunidades comerciales. Esta etapa devuelve candidatos potenciales, no oportunidades finales.

Contexto de ejecucion:

- Fecha actual: {{ current_date }}
- Region: {{ region }}
- Proveedor IA: {{ provider_name }}
- Fuentes configuradas: {{ sources }}

Instrucciones:

- Busca oportunidades en cualquier idioma.
- Prioriza fuentes oficiales, portales publicos, reguladores, utilities, municipios y organismos multilaterales.
- Usa `search_queries` de la fuente configurada como consultas primarias. Interpreta esas consultas como obligatorias cuando existan.
- Restringe la busqueda a `search_domains` cuando existan. No uses resultados de dominios externos salvo que no haya resultados oficiales y la fuente tenga `fallback_queries`.
- Usa `fallback_queries` solo si las consultas primarias no devuelven oportunidades verificables dentro de los dominios permitidos.
- Si usas un resultado externo por fallback, explica en `audit_notes` por que fue necesario y conserva la URL oficial mas cercana.
- Cuando la estrategia sea `direct_portal` o `multilateral_search`, prioriza estrictamente el dominio oficial antes de cualquier busqueda web general.
- Cuando la estrategia sea `web_discovery` o `city_search`, puedes detectar URLs oficiales relacionadas, pero evita agregadores, documentos historicos, ofertas laborales, redes sociales y paginas no oficiales.
- No descartes todavia por dudas menores; marca la duda en audit_notes.
- No incluyas oportunidades si la informacion esencial queda bloqueada por login, captcha o certificado.
- Conserva URLs y fragmentos de evidencia publica.
- `normalized_title` es obligatorio cuando exista un titulo verificable: debe ser un titulo limpio, sin sufijos de buscador ni texto generico como "Sin titulo".
- Usa `raw_title` para conservar el titulo original cuando difiera del normalizado.
- Si no puedes construir un `normalized_title` confiable, usa null y conserva al menos `raw_title`.
- No inventes fechas, organismos, titulos ni referencias.

Devuelve JSON estricto con este formato:

{
  "items": [
    {
      "source_id": null,
      "source_name": null,
      "source_url": null,
      "raw_title": null,
      "normalized_title": null,
      "official_url": null,
      "all_urls": [],
      "contracting_authority": null,
      "country": null,
      "deadline_raw": null,
      "description_raw": null,
      "language": null,
      "matched_keywords": [],
      "evidence_text": null,
      "evidence_urls": [],
      "requires_human_review": false,
      "audit_notes": []
    }
  ]
}
