# Tender AI Agent

CLI en Python para buscar diariamente oportunidades comerciales y licitaciones relevantes para consultoria en energia electrica, regulacion economica, tarifas, renovables, generacion distribuida y modelizacion economico-financiera.

El proyecto esta preparado para ejecutar el mismo pipeline con dos proveedores de IA:

- OpenAI
- Perplexity

La idea es comparar resultados entre proveedores, detectar diferencias, consolidar oportunidades aprobadas y cargar solo informacion verificable en una base de datos existente.

## Estado actual

Este repositorio contiene el esqueleto inicial ejecutable:

- CLI con `argparse`.
- Configuracion por `.env` y YAML.
- Prompts editables en Markdown.
- Modelos Pydantic iniciales.
- Orquestador de pipeline con etapas separadas.
- Clientes base para OpenAI y Perplexity.
- Persistencia preparada para SQLAlchemy contra una tabla existente.
- Auditoria de respuestas crudas, descartes y reportes de ejecucion.

La implementacion profunda de los agentes de busqueda, extraccion, validacion y enriquecimiento queda pendiente por diseno.

## Instalacion

```bash
cd tender_ai_agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Editar `.env` con las claves y la cadena de conexion correspondientes.

## Comandos

```bash
python main.py run --all
python main.py run --region latam
python main.py run --region africa
python main.py run --provider openai
python main.py run --provider perplexity
python main.py run --compare-providers
python main.py run --dry-run
python main.py sources --list
python main.py report --last-run
python main.py negocios --list
python main.py negocios --classify "Green hydrogen feasibility study"
```

## Pipeline esperado

1. Cargar configuracion.
2. Cargar fuentes desde YAML.
3. Cargar prompts desde Markdown.
4. Ejecutar busqueda con OpenAI.
5. Ejecutar busqueda con Perplexity.
6. Guardar respuestas crudas.
7. Identificar oportunidades candidatas.
8. Filtrar oportunidades no elegibles.
9. Enriquecer oportunidades viables.
10. Validar vigencia, fecha de cierre, alcance y link oficial.
11. Deduplicar.
12. Asignar unidad de negocio de QUANTUM.
13. Mapear campos a la tabla destino.
14. Insertar oportunidades aprobadas en base de datos.
15. Guardar descartadas con motivo de rechazo.
16. Generar reporte de ejecucion.

## Configuracion

- `config/sources.yaml`: fuentes y regiones.
- `config/region_groups.yaml`: grupos de regiones para ejecuciones parciales.
- `config/negocios.yaml`: catalogo de unidades de negocio y sus palabras clave.
- `prompts/shared`: criterios y formato comun.
- `prompts/discovery`: instrucciones por region.
- `prompts/agents`: instrucciones por etapa del pipeline.

## Juez IA

Dos etapas filtran las oportunidades antes de cargarlas: la calidad de contenido (se entiende
que se contrata) y la validacion de negocio (es una convocatoria concreta y encaja con
QUANTUM). Las dos usan el mismo cliente, elegido con `AI_JUDGE_PROVIDER`:

- `anthropic` (por defecto): Claude, modelo `ANTHROPIC_MODEL` (por defecto `claude-opus-5-5`)
  con esfuerzo `ANTHROPIC_EFFORT` (por defecto `low`) y salida JSON validada por esquema.
  Requiere `ANTHROPIC_API_KEY`; si falta, el juez usa Gemini para no frenar la corrida.
- `gemini`: Gemini con `GOOGLE_API_KEY` y `GEMINI_MODEL`.

La columna `filtro_gemini` conserva los valores "Seleccionada por Gemini" y "Descartada por
Gemini" porque SGQ filtra por ellos; el modelo que decidio queda en las notas de auditoria.
Antes del juez, la elegibilidad descarta URLs de listados (paginacion `?page=N`,
`/status/active`, `/current-procurement`, etc.) porque no identifican una oportunidad.

La elegibilidad tambien descarta los avisos que no estan en espanol, ingles, portugues o
frances (`ALLOWED_LANGUAGES=es,en,pt,fr`). Manda el idioma que declara el buscador o la
segunda lectura; si no declara, se estima por palabras frecuentes del titulo y la
descripcion, y si el texto es corto o ambiguo, pasa. Un titulo escrito mayormente en otro
alfabeto (arabe, cirilico, griego, chino) se descarta siempre. El motivo queda como
`language_not_allowed`. Con las candidatas del 4-nov-2026 habria descartado 4 de 227
(tres avisos en sueco de Trollhattan y una nota en griego sobre gas en Chipre).

Cada alta guarda su origen en columnas `ia_*` de `licitacion` (las crea la migracion de SGQ;
mientras no existan se omiten y el log lo avisa una vez por corrida):

| columna | contenido |
| --- | --- |
| `ia_run_id` | corrida (`outputs/<run_id>`) |
| `ia_modalidad` | `contextual` (fuente con dominio) u `open_web` (busqueda por tema) |
| `ia_busqueda` | fuente o tema que la encontro |
| `ia_modelo_juez` | modelo que la aprobo |
| `ia_puntaje` | puntaje del juez (0 a 1) |
| `ia_motivo_juez` | justificacion del juez |
| `ia_evidencia_url` | URL oficial o de evidencia |

## Segunda lectura de resultados web

Perplexity muchas veces trae resultados web pero devuelve una lista vacia: en las corridas del 29 y 30-oct-2026 paso en 99 de 112 busquedas. Cuando eso pasa, `SearchResultsReader` le pasa a Claude (`SECOND_READER_MODEL`, por defecto `claude-sonnet-5-5`) los primeros resultados con titulo, fragmento y fecha. Claude marca cuales son convocatorias concretas, y las URLs salen siempre del resultado, nunca del modelo. Lo extraido sigue el pipeline normal (elegibilidad, calidad, juez) y queda marcado para revision humana. Se apaga con `SECOND_READER_ENABLED=false`. En los raw de cada busqueda queda `metadata.second_reader` (resultados leidos, convocatorias, modelo, costo) y la respuesta original de Perplexity en `metadata.perplexity_content`.

## Conectores a APIs de portales

Muchos portales de compras no aparecen en las busquedas IA con filtro de dominio porque sus avisos se cargan dinamicamente. Para esos portales hay conectores que leen sus APIs de datos abiertas, sin clave y sin costo de IA, definidos en `config/connectors.yaml`:

| id | Portal | Region |
| --- | --- | --- |
| `secop` | SECOP II, Colombia (datos.gov.co) | latam |
| `pncp` | PNCP, Brasil (Compras.gov.br) | latam |
| `worldbank` | Avisos de compras del Banco Mundial | multilaterals |

Cada conector trae los avisos publicados en los ultimos `lookback_days` y deja pasar solo los que tienen un termino de `sector_terms` y uno de `service_terms` en el titulo o la descripcion. Lo que pasa entra al pipeline como cualquier otra candidata (elegibilidad, juez IA, deduplicacion, negocio, DB), con modalidad `api` y `source_id` `api_<id>`. Si un portal falla, se registra el error y la corrida sigue.

El Banco Mundial esta encendido desde el 28-oct-2026; SECOP y PNCP siguen apagados (`enabled: false`). Para probarlos sin tocar la base:

```bash
python main.py conectores --probar            # todos
python main.py conectores --probar --id pncp --dias 7
python main.py conectores --probar --id secop --ver-descartados   # muestra titulos que no pasaron, para ajustar terminos
```

Cada termino tiene que empezar una palabra (`power` no matchea `empowerment`). `exclude_terms` descarta por titulo (por ejemplo, puestos de consultor individual) y `service_terms_in_title: true` exige el termino de servicio en el titulo. Si el portal responde 429 o 503, el conector espera y reintenta hasta 3 veces; `request_pause_seconds` agrega una pausa entre paginas (PNCP la necesita).

Cuando los resultados se vean bien, poner `enabled: true` en el conector. `--skip-connectors` en `run` o `CONNECTORS_ENABLED=false` en `.env` los apagan a todos.

## Asignacion de unidad de negocio

La etapa `negocio_assignment` corre entre la deduplicacion y el mapeo a la base, y solo
sobre las oportunidades que ya pasaron todos los filtros. Completa la columna `negocio_id`
de la tabla destino con una de las seis unidades de negocio de QUANTUM:

| slug | negocio | prioridad | alcance |
| --- | --- | --- | --- |
| `desarrollo_it` | Desarrollo IT | 1 | Software, GIS, SCADA, bases de datos, plataformas de datos, IA/ML e IoT aplicados a utilities o energia |
| `agua` | Agua | 2 | Agua potable, saneamiento, aguas residuales, alcantarillado y tarifas de agua |
| `gas` | Gas | 3 | Gas natural y derivados: GNL, biometano, amoniaco e hidrogeno en cualquier color |
| `generacion` | Generacion | 4 | Mercados mayoristas, modelos de red, despacho y subastas de energia y potencia |
| `nuevos_negocios` | Nuevos Negocios | 5 | Transicion energetica, renovables, almacenamiento, eficiencia y movilidad electrica |
| `electricidad` | Electricidad | 6 | Regulacion electrica, calculo tarifario, distribucion, transmision, VNR, tasa de capital y perdidas |

La asigna el **Juez 3**: Claude (`NEGOCIO_JUDGE_MODEL`, por defecto `claude-opus-5-5`, con
la misma `ANTHROPIC_API_KEY` de los otros jueces) lee cada oportunidad que paso todos los
filtros y elige la unidad con `prompts/agents/negocio_assignment_agent.md`. Recibe titulo,
organismo, pais, fuente, resumen, descripcion y el motivo del juez de negocio, y decide por
el objeto central del contrato. Las palabras clave ya no deciden ni se le pasan como pista.
La respuesta se valida con un esquema que solo admite slugs del catalogo.

Si Claude no responde (sin `ANTHROPIC_API_KEY`, error de la API o slug invalido), se usa
como respaldo el mayor score de las palabras clave de `config/negocios.yaml` (o
`DEFAULT_NEGOCIO_ID` si no hay senales) y la oportunidad queda marcada para revision humana.
El veredicto queda en `metadata.negocio_judge` y en las notas `[Negocio]`.

El `negocio_id` que se escribe se resuelve asi: primero `sidoc_id` de `config/negocios.yaml`,
y si esta en null, buscando el `nombre` o los `nombres_alternativos` en la tabla `negocio`
de SIDOC (nombre configurable con `NEGOCIO_TABLE_NAME`). El lookup ignora filas marcadas
como borradas y se resuelve una sola vez por corrida.

Los `sidoc_id` del catalogo ya estan completados con los ids verificados contra la tabla
`negocio`: Desarrollo IT 13, Agua 4, Gas 3, Generacion 11, Nuevos Negocios 7 y
Electricidad 2. Estan fijos a proposito para que la asignacion no dependa de la
conectividad con la base. Al apuntar a otra base, verificar que coincidan con
`python main.py negocios --list`.

Para ver el estado de resolucion de los ids y las filas reales de la tabla:

```bash
python main.py negocios --list
```

Para probar un texto suelto (con `--use-judge` consulta al Juez 3 como en la corrida; sin
el, muestra solo el score de palabras clave del respaldo):

```bash
python main.py negocios --classify "Revision tarifaria de distribucion electrica"
python main.py negocios --classify "Fortalecimiento institucional" --use-judge
```

`scripts/test_negocio_assignment.py` fija que decida el Juez 3 y el comportamiento del
respaldo por palabras clave. Si se editan las palabras clave, ese script debe seguir pasando.

Para desactivar la etapa: `NEGOCIO_ASSIGNMENT_ENABLED=false` o
`python main.py run --skip-negocio-assignment`. En ese caso `negocio_id` vuelve a tomar
`DEFAULT_NEGOCIO_ID`.

## Base de datos

La tabla destino debe existir previamente. El nombre se configura con:

```env
DB_TABLE_NAME=licitacion
```

Si `DRY_RUN=true` o se ejecuta `python main.py run --dry-run`, no se insertan registros.

## Criterios de inclusion

- Oportunidad abierta.
- Deadline explicito y posterior a la fecha actual.
- Proceso para firmas consultoras, empresas o consorcios.
- Consultoria tecnica, economica o regulatoria vinculada a energia electrica, renovables, tarifas, utilities, demanda, CAPEX/OPEX, planificacion, modelizacion financiera o fortalecimiento institucional.
- Link oficial o fuente publica verificable.
- Informacion suficiente para cargar una oportunidad util en la base.

## Criterios de exclusion

- Obras civiles, construccion, EPC o suministro de equipamiento.
- Fiscalizacion o supervision de obra.
- Owner's Engineer predominantemente constructivo.
- Estudios ambientales o sociales sin componente economico-regulatorio o energetico relevante.
- Consultores individuales salvo excepcion justificada.
- Oportunidades sin fecha de cierre explicita.
- Oportunidades cerradas, adjudicadas o canceladas.
- Oportunidades que requieran login, captcha o certificado para validar informacion.

## Salidas

- `outputs/raw`: respuestas crudas por proveedor.
- `outputs/reports`: reportes JSON de ejecucion.
- `logs/audit`: descartes, errores y auditoria.

