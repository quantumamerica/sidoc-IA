Objetivo: detectar oportunidades duplicadas entre fuentes, regiones y proveedores.

Criterios de duplicacion:

- URL oficial igual o equivalente;
- titulo similar;
- mismo organismo contratante;
- mismo deadline;
- mismo pais o ambito geografico;
- misma referencia o codigo de proceso;
- descripcion sustancialmente equivalente.

Instrucciones:

- Agrupa duplicados en duplicate_group_id.
- Selecciona como registro principal el que tenga mejor URL oficial, evidencia mas completa, deadline validado y mayor confianza.
- No combines campos conflictivos sin evidencia; registra conflictos en audit_notes.
- Marca duplicate_of_url en registros duplicados cuando exista URL principal.

Formato de salida obligatorio, JSON estricto:

{
  "unique_opportunities": [
    {
      "opportunity_id": null,
      "duplicate_group_id": null,
      "selected_as_primary": true,
      "duplicate_of_url": null,
      "merge_notes": null
    }
  ],
  "duplicates": [
    {
      "opportunity_id": null,
      "duplicate_group_id": null,
      "duplicate_of_url": null,
      "rejection_reason": "duplicate",
      "evidence_text": null
    }
  ],
  "conflicts": []
}
