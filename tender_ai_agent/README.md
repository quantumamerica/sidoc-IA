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

La clasificacion es hibrida y se resuelve en este orden:

1. **Reglas dominantes.** Si el texto contiene palabras clave dominantes de un negocio, se
   asigna sin consultar a Gemini. Si dominan varios, gana el de prioridad mas baja. Esto
   hace deterministas las reglas duras: todo lo de hidrogeno va a `gas`, y si el entregable
   central es un sistema informatico va a `desarrollo_it`.
2. **Score por palabras clave.** Si el negocio con mejor score supera
   `NEGOCIO_RULES_STRONG_THRESHOLD`, se asigna por reglas. Ante un empate dentro de
   `NEGOCIO_RULES_MARGIN`, desempata la prioridad del catalogo.
3. **Gemini.** Si el score no alcanza, se consulta al modelo con
   `prompts/agents/negocio_assignment_agent.md`. El prompt le prohibe devolver null: ante
   duda elige el mejor encaje y baja `confidence`.
4. **Fallback.** Si Gemini falla o no hay `GOOGLE_API_KEY`, se toma el mayor score de
   reglas; si no hay ninguna senal, se usa `DEFAULT_NEGOCIO_ID`.

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

Para calibrar las palabras clave sin correr el pipeline, con el detalle de coincidencias y
score por negocio:

```bash
python main.py negocios --classify "Revision tarifaria de distribucion electrica"
python main.py negocios --classify "Fortalecimiento institucional" --use-gemini
```

`scripts/test_negocio_assignment.py` fija el comportamiento esperado de la capa
determinista. Si se editan las palabras clave, ese script debe seguir pasando.

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

