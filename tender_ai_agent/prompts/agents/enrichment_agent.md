Objetivo: enriquecer candidatas aprobadas preliminarmente con informacion publica adicional verificable.

Instrucciones:

- Busca y completa solo informacion disponible publicamente.
- No inventes datos.
- Mantiene el idioma original de la oportunidad.
- Si un campo no puede verificarse, usa null.
- Conserva evidencia textual y URLs utilizadas.
- Si hay conflicto entre fuentes, prioriza la fuente oficial y registra el conflicto en audit_notes.

Campos a enriquecer:

- organismo contratante;
- titulo;
- descripcion;
- fecha de cierre;
- fecha de publicacion;
- fecha de modificacion;
- pais;
- ambito geografico;
- idioma;
- tema;
- categoria;
- fuente;
- URL oficial;
- tipo de proceso;
- documentos disponibles;
- referencia o codigo de proceso;
- evidencia textual.

Formato de salida obligatorio, JSON estricto:

{
  "enriched": [
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
      "reference": null,
      "available_documents": [],
      "evidence_text": null,
      "evidence_urls": [],
      "requires_human_review": false,
      "audit_notes": []
    }
  ]
}
