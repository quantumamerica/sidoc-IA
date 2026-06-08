Objetivo: mapear una oportunidad validada a las columnas exactas de la tabla destino.

Columnas destino:

- id_fuente
- url
- fuente
- organismo_contratado
- titulo_estudio
- deadline
- ambito_geografico
- categoria
- fecha_publicacion
- fecha_modificacion
- descripcion
- idioma
- tema
- seleccion
- estado
- negocio_id
- referencia
- controlcomercial
- cant_palabras_match
- palabras_match
- resumen_descrip
- colaborador_id
- fecha_carga
- motivo_rechazo
- responsable_id
- situacion
- tipo_propuesta
- filial_id
- filtro_gemini
- seguimiento
- comentario
- comentarios_personales
- estado_seguimiento

Reglas de mapping:

- id no se debe completar; lo genera la base de datos.
- fecha_carga debe ser la fecha actual: {{ current_date }}.
- estado puede quedar como "pendiente" o el valor configurable indicado por el sistema.
- seleccion puede quedar null o el valor configurable indicado por el sistema.
- Campos no encontrados deben ser null.
- No inventes fechas ni organismos.
- deadline debe estar normalizado como YYYY-MM-DD si se pudo validar.
- Conserva el titulo original en titulo_estudio.
- idioma debe ser el idioma original detectado.
- descripcion debe ser suficientemente completa, pero fiel a la fuente y no inventada.
- resumen_descrip debe ser un resumen breve fiel a la fuente.
- motivo_rechazo debe ser null para oportunidades aprobadas.

Formato de salida obligatorio, JSON estricto:

{
  "mapped": [
    {
      "id_fuente": null,
      "url": null,
      "fuente": null,
      "organismo_contratado": null,
      "titulo_estudio": null,
      "deadline": null,
      "ambito_geografico": null,
      "categoria": null,
      "fecha_publicacion": null,
      "fecha_modificacion": null,
      "descripcion": null,
      "idioma": null,
      "tema": null,
      "seleccion": null,
      "estado": "pendiente",
      "negocio_id": null,
      "referencia": null,
      "controlcomercial": null,
      "cant_palabras_match": null,
      "palabras_match": null,
      "resumen_descrip": null,
      "colaborador_id": null,
      "fecha_carga": "{{ current_date }}",
      "motivo_rechazo": null,
      "responsable_id": null,
      "situacion": null,
      "tipo_propuesta": null,
      "filial_id": null,
      "filtro_gemini": null,
      "seguimiento": null,
      "comentario": null,
      "comentarios_personales": null,
      "estado_seguimiento": null
    }
  ],
  "internal_metadata": [
    {
      "source_id": null,
      "provider": null,
      "run_id": null,
      "evidence_urls": [],
      "audit_notes": []
    }
  ]
}
