Objetivo: recibir resultados crudos de busqueda y extraer oportunidades candidatas.

Instrucciones:

- Identifica procesos comerciales, licitaciones, expresiones de interes, solicitudes de propuestas, RFQ, RFP, tender notices o procurement notices.
- No apruebes ni rechaces definitivamente; esta etapa solo estructura candidatos.
- No consolides oportunidades distintas salvo que la evidencia indique claramente que son el mismo proceso.
- Conserva el idioma original de titulo, descripcion, referencia y evidencia.
- Usa null para campos no disponibles.
- Si el resultado crudo parece irrelevante, no lo incluyas.

Criterios disponibles:

{{ eligibility_criteria }}

Formato de salida obligatorio, JSON estricto:

{
  "candidates": [
    {
      "provider": "{{ provider_name }}",
      "region": "{{ region }}",
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
      "deadline_raw": null,
      "deadline_normalized": null,
      "publication_date_raw": null,
      "publication_date_normalized": null,
      "description_raw": null,
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
