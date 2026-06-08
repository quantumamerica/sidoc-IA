Objetivo: realizar una busqueda abierta en internet por tema y region para detectar oportunidades oficiales que no necesariamente pertenezcan a las fuentes configuradas en `sources.yaml`.

Contexto de ejecucion:

- Fecha actual: {{ current_date }}
- Region: {{ region }}
- Proveedor IA: {{ provider_name }}
- Tema: {{ theme_name }}
- ID tema: {{ theme_id }}
- Alcance regional: {{ region_scope }}
- Idiomas sugeridos: {{ languages }}
- Terminos regionales sugeridos: {{ region_query_terms }}
- Consultas tematicas sugeridas: {{ theme_queries }}
- Keywords tematicas: {{ theme_keywords }}
- Politica de fuentes oficiales: {{ official_source_policy }}

Instrucciones:

- Busca oportunidades en cualquier idioma relevante para la region.
- Usa las consultas tematicas y los terminos regionales como base, pero puedes reformularlas para encontrar fuentes oficiales.
- Devuelve solo oportunidades desde fuentes oficiales o publicas verificables: portales de contratacion, ministerios, reguladores, utilities publicas, operadores de sistema, municipios, bancos multilaterales, agencias ONU, fondos climaticos u organismos internacionales.
- No uses agregadores, noticias, blogs, LinkedIn, redes sociales, bolsas de trabajo ni paginas comerciales como fuente final.
- Si un agregador o noticia ayuda a descubrir una oportunidad, conserva solo la URL oficial final. Si no encuentras URL oficial, no incluyas el item.
- Prioriza consultorias, estudios, asistencia tecnica, servicios profesionales, advisory, market studies, feasibility studies, regulatory support, financial/economic analysis y program evaluation.
- Evita EPC, obras, construccion, suministro de equipos, vacantes laborales, grants sin procurement, publicaciones academicas y documentos historicos sin oportunidad abierta o revisable.
- `normalized_title` es obligatorio cuando exista un titulo verificable: debe ser un titulo limpio, sin sufijos de buscador ni texto generico como "Sin titulo".
- Usa `raw_title` para conservar el titulo original cuando difiera del normalizado.
- Si no puedes construir un `normalized_title` confiable, usa null; el pipeline descartara esa oportunidad.
- No inventes fechas. Si no puedes normalizar una fecha, usa `deadline_raw` con el texto encontrado y `deadline_normalized: null`.
- No inventes organismos, paises, referencias ni URLs.
- Conserva fragmentos de evidencia publica en `evidence_text`.
- Incluye URLs oficiales en `evidence_urls`.
- Usa `audit_notes` para explicar dudas, por ejemplo fecha relativa, pagina indice, documento PDF o necesidad de revision humana.
- Limita la salida a oportunidades razonablemente relevantes para el tema y la region.

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
      "geographic_scope": null,
      "process_type": null,
      "deadline_raw": null,
      "deadline_normalized": null,
      "publication_date_raw": null,
      "publication_date_normalized": null,
      "modification_date_raw": null,
      "modification_date_normalized": null,
      "description_raw": null,
      "description_summary": null,
      "language": null,
      "topic": null,
      "category": null,
      "matched_keywords": [],
      "matched_keywords_count": null,
      "evidence_text": null,
      "evidence_urls": [],
      "requires_human_review": false,
      "audit_notes": []
    }
  ]
}
