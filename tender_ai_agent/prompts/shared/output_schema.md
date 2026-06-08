Devuelve JSON estricto cuando se solicite una respuesta estructurada.

Reglas de formato:

- No incluyas Markdown.
- No incluyas texto antes ni despues del JSON.
- Usa null para campos no encontrados o no verificables.
- No inventes valores.
- Conserva el idioma original de la oportunidad en titulo, descripcion, referencia y evidencia.
- Normaliza fechas como YYYY-MM-DD solo cuando la fecha sea verificable.
- Si una fecha no puede normalizarse con seguridad, conserva el valor crudo en el campo raw correspondiente y usa null en el campo normalizado.

Objeto base de oportunidad:

{
  "provider": null,
  "region": null,
  "source_id": null,
  "source_name": null,
  "source_url": null,
  "discovered_by_prompt": null,
  "raw_title": null,
  "normalized_title": null,
  "official_url": null,
  "all_urls": [],
  "contracting_authority": null,
  "country": null,
  "geographic_scope": null,
  "process_type": null,
  "consultant_type": null,
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
  "eligibility_status": "pending",
  "validation_status": "pending",
  "rejection_reason": null,
  "evidence_text": null,
  "evidence_urls": [],
  "requires_human_review": false,
  "duplicate_group_id": null,
  "duplicate_of_url": null,
  "source_confidence": null,
  "ai_confidence": null,
  "provider_confidence": null,
  "audit_notes": []
}
