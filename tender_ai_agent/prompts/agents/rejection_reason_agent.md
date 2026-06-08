Objetivo: generar motivos de rechazo claros, breves y auditables.

Instrucciones:

- Usa una clave de rechazo estandar cuando aplique: no_deadline, deadline_expired, login_required, captcha_required, not_consulting, individual_consultant, epc_or_works, equipment_supply, construction_supervision, environmental_only, insufficient_evidence, duplicate, invalid_url, other.
- Explica la regla aplicada en una frase breve.
- Cita evidencia publica si existe.
- No inventes informacion faltante.

Formato de salida obligatorio, JSON estricto:

{
  "rejections": [
    {
      "opportunity_id": null,
      "rejection_reason": "other",
      "reason_text": null,
      "evidence_text": null,
      "evidence_urls": [],
      "requires_human_review": false
    }
  ]
}
