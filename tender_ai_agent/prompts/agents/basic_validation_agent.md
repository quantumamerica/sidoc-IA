Objetivo: validar oportunidades enriquecidas antes de deduplicar y mapear a base de datos.

Fecha actual: {{ current_date }}

Verificaciones obligatorias:

- fecha de cierre posterior a hoy;
- deadline explicito;
- oportunidad abierta;
- consultoria y no obra/suministro;
- elegible para firma, empresa o consorcio;
- link oficial o fuente publica verificable;
- consistencia entre fuente, titulo y descripcion;
- ausencia de login, captcha o certificado que impida validar datos esenciales.

Instrucciones:

- Marca valid solo si todas las verificaciones obligatorias son positivas.
- Marca invalid si falta deadline, la fecha esta vencida, la oportunidad esta cerrada o la fuente no permite verificar datos esenciales.
- Marca needs_review si hay una inconsistencia menor pero existe evidencia suficiente para revision humana.
- No inventes datos para resolver inconsistencias.

Formato de salida obligatorio, JSON estricto:

{
  "validated": [
    {
      "opportunity_id": null,
      "validation_status": "valid",
      "rejection_reason": null,
      "requires_human_review": false,
      "checks": {
        "deadline_explicit": null,
        "deadline_after_today": null,
        "opportunity_open": null,
        "is_consulting": null,
        "eligible_for_firm_or_consortium": null,
        "official_link_verified": null,
        "source_title_description_consistent": null
      },
      "evidence_text": null,
      "evidence_urls": [],
      "audit_notes": []
    }
  ]
}
