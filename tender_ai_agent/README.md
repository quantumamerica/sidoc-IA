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
12. Mapear campos a la tabla destino.
13. Insertar oportunidades aprobadas en base de datos.
14. Guardar descartadas con motivo de rechazo.
15. Generar reporte de ejecucion.

## Configuracion

- `config/sources.yaml`: fuentes y regiones.
- `config/region_groups.yaml`: grupos de regiones para ejecuciones parciales.
- `prompts/shared`: criterios y formato comun.
- `prompts/discovery`: instrucciones por region.
- `prompts/agents`: instrucciones por etapa del pipeline.

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

