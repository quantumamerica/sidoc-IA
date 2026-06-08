Objetivo: decidir si cada oportunidad candidata pasa el filtro preliminar de elegibilidad o se rechaza.

Fecha actual: {{ current_date }}

Criterios:

{{ eligibility_criteria }}

Instrucciones:

- Evalua cada candidata contra todos los criterios.
- Aprueba solo si existe evidencia suficiente de que la oportunidad esta abierta, tiene deadline explicito posterior a hoy y corresponde a consultoria para firma, empresa o consorcio.
- Rechaza oportunidades sin deadline explicito.
- Rechaza procesos cerrados, adjudicados o cancelados.
- Rechaza EPC, obras, construccion, suministro de equipos, supervision/fiscalizacion de obras y Owner's Engineer predominantemente constructivo.
- Usa needs_review solo cuando la oportunidad parece relevante pero falta una aclaracion no esencial.
- Incluye motivo de rechazo usando una de estas claves cuando aplique: no_deadline, deadline_expired, login_required, captcha_required, not_consulting, individual_consultant, epc_or_works, equipment_supply, construction_supervision, environmental_only, insufficient_evidence, duplicate, invalid_url, other.

Formato de salida obligatorio, JSON estricto:

{
  "results": [
    {
      "candidate_id": null,
      "eligibility_status": "eligible",
      "rejection_reason": null,
      "requires_human_review": false,
      "decision_notes": null,
      "evidence_text": null,
      "evidence_urls": []
    }
  ]
}
