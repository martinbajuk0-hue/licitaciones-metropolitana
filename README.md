# Licitaciones Metropolitana

Sistema autónomo de gestión de licitaciones para **Metropolitana Pisos**:
detecta, analiza, prepara y da seguimiento a las licitaciones públicas y
privadas de Uruguay relacionadas con pisos, revestimientos, césped
sintético, goma, alfombras y accesorios.

Implementa el rol y el flujo de trabajo de 15 pasos definidos por el
departamento de licitaciones de la empresa. Ver `CLAUDE.md` para el rol
completo y `docs/FLUJO_DE_TRABAJO.md` para el detalle paso a paso.

## Qué hace

1. **Monitorea** Compras Estatales (ARCE) tres veces al día, detecta
   licitaciones nuevas y cambios (aclaraciones/modificaciones) sobre las
   ya vistas.
2. **Descarga y lee** el pliego completo y sus anexos (PDF, Word, Excel,
   imágenes) — nunca descarta una licitación solo por el título.
3. **Identifica** qué productos de Metropolitana aplican, extrae los
   datos clave (organismo, fechas, garantías, criterios de evaluación),
   detecta riesgos (multas, certificaciones especiales, contradicciones)
   y arma el checklist documental.
4. **Clasifica** cada oportunidad en una escala ★ a ★★★★★ con un score
   auditable, y genera un cronograma de tareas.
5. **Genera un informe** en Markdown por licitación (`reports/`) y avisa
   por email.
6. **Publica un visor web** (`docs/index.html`, servido por GitHub Pages)
   con todos los llamados relevantes detectados — no solo los que llegan
   por email — filtrable por organismo, rubro, score mínimo y estado.
7. Provee **plantillas y prompts reutilizables** para armar el borrador
   de oferta técnica/administrativa y cotizar.
8. Permite **marcar licitaciones puntuales para seguimiento** desde el
   visor (botón "🔔 Seguir esta licitación") y avisa por email, aparte y
   destacado, si ARCE publica una aclaración/ajuste/adjudicación sobre
   esa licitación puntual — ver "Seguimiento de licitaciones marcadas"
   más abajo.

## Estructura del proyecto

```
monitor.py              # Monitoreo diario (cron) + detección de cambios
parser.py                # Extracción de texto de PDF/Word/Excel/imágenes
analyzer.py               # Campos clave, identificación de productos, resumen, score
risk.py                    # Detección de riesgos/multas/certificaciones/contradicciones
checklist.py                # Checklist documental
pricing.py                   # Cotización (nunca inventa precios)
report.py                     # Informe ejecutivo .md + clasificación ★
catalogo.py                    # Persistencia del catálogo para el visor web (docs/)
seguimiento.py                  # Lista de licitaciones marcadas + revisión de novedades ARCE
seguimiento_issue.py             # Procesa el GitHub Issue que marca/desmarca una licitación
cli.py                            # Analizar una licitación puntual a demanda

config/
  settings.py              # Loader central de configuración (único punto de acceso a los YAML)
  empresa.yaml              # Datos de Metropolitana Pisos

knowledge/
  keywords.yaml             # Palabras clave por categoría de producto
  sinonimos.yaml             # Siglas y variantes (organismos, documentación, productos)
  organismos.yaml             # Organismos públicos prioritarios
  productos.yaml               # Catálogo de productos y equivalencias
  precios.yaml                  # Lista de precios (vacía hasta cargarla)

prompts/                        # Prompts reutilizables para cada paso del flujo
templates/                      # Modelos de oferta técnica/administrativa, consultas, etc.
docs/                           # Documentación + visor web (servido por GitHub Pages)
  index.html                    # Visor: lista filtrable de llamados detectados
  data/llamados.json            # Catálogo (generado y commiteado por el workflow)
  data/seguimiento.json         # Licitaciones marcadas para seguimiento (idem)
  informes/*.md                 # Informe completo de cada llamado (idem)
data/                           # Estado runtime (licitaciones ya vistas)
reports/                        # Informes generados (gitignored por defecto)

.github/workflows/monitor.yml  # Cron de GitHub Actions (7am, 12pm, 6pm hora Uruguay)
.github/workflows/seguimiento.yml  # Procesa los issues de "🔔 Seguir esta licitación"
```

Ver `docs/ARQUITECTURA.md` para el diagrama de flujo de datos completo y
`AGENTS.md` para la definición de cada agente especializado.

## Uso rápido

```bash
pip install -r requirements.txt

# Correr el monitoreo diario manualmente
python monitor.py --sin-email

# Analizar una licitación puntual
python cli.py analizar --url "https://www.comprasestatales.gub.uy/..." --titulo "Suministro de pisos - Intendencia de X"

# Cotizar
python cli.py cotizar --items piso_spc:120 zocalo:40 --margen 25
```

Ver `docs/GUIA_USO.md` para el detalle de variables de entorno y flujos
completos.

## Configuración

El sistema se ajusta editando los archivos YAML en `knowledge/` y
`config/` — agregar una palabra clave, un organismo o un producto nuevo no
requiere tocar código. Ver "Extender el sistema" en `docs/ARQUITECTURA.md`.

Variables de entorno (secrets en GitHub Actions):

- `GMAIL_USER` / `GMAIL_APP_PASSWORD` / `EMAIL_DESTINO` — envío de email.
- `ANTHROPIC_API_KEY` — opcional, habilita el resumen ejecutivo narrativo
  vía Claude (si no está, el sistema usa un resumen extractivo por reglas
  y sigue funcionando igual).

## Visor web

Cada corrida del monitor guarda un resumen de cada llamado relevante en
`docs/data/llamados.json` y su informe completo en `docs/informes/*.md`
(vía `catalogo.py`), y el workflow de GitHub Actions los commitea al
repo automáticamente. `docs/index.html` lee ese JSON y muestra una tabla
filtrable (organismo, rubro, score mínimo, nuevo/con cambios) con acceso
al informe completo de cada uno — sin depender de buscar en el email.

**Paso manual único, una sola vez:** activar GitHub Pages para que
`docs/index.html` quede accesible como sitio web. Esto es una
configuración del repositorio en GitHub, no se puede hacer por commit:

1. En GitHub, ir a **Settings → Pages** del repositorio.
2. En "Build and deployment" → "Source", elegir **Deploy from a branch**.
3. Rama: **main** (o la que corresponda), carpeta: **/docs**.
4. Guardar. GitHub va a publicar el sitio en
   `https://<usuario>.github.io/<repo>/` (tarda uno o dos minutos la
   primera vez).

Después de eso, el visor se actualiza solo en cada corrida del monitor
— no hace falta repetir este paso.

## Seguimiento de licitaciones marcadas

Para una licitación puntual que interesa especialmente, el visor tiene un
botón **"🔔 Seguir esta licitación"** (columna "Seguimiento" de la tabla).
No hace falta tocar código ni JSON a mano:

1. En el visor, click en "🔔 Seguir" en la fila de la licitación que
   interesa. Se abre una pestaña nueva de GitHub con un Issue ya
   completo.
2. Click en **"Submit new issue"** en esa pestaña (eso es lo único que
   hay que confirmar).
3. En unos segundos, `.github/workflows/seguimiento.yml` procesa el
   issue, agrega la licitación a `docs/data/seguimiento.json`, comenta la
   confirmación en el propio issue y lo cierra automáticamente.
4. Al recargar el visor (puede tardar uno o dos minutos, lo que tarda el
   workflow), esa fila pasa a mostrar "🔔 Siguiendo" con un link para
   "Dejar de seguir" — mismo mecanismo, a la inversa.

Cada corrida del monitor (3 veces al día) revisa el feed de ARCE
puntualmente para cada licitación en seguimiento, buscando si apareció
una aclaración, un ajuste o una adjudicación sobre ese llamado. Si
encuentra algo nuevo, lo manda en una sección aparte y destacada al
principio del email ("🔔 Actualizaciones en licitaciones que seguís") —
sin pasar por el filtro de relevancia ni de score mínimo: si se marcó a
mano, se avisa sí o sí. Esto es un mecanismo aparte y más preciso que la
detección general de "aclaraciones/modificaciones" (ítem 1 de "Qué
hace"), que hoy en la práctica solo cubre el momento en que una
licitación se ve por primera vez — ver el docstring de `seguimiento.py`
para el detalle técnico de por qué.

**No requiere ningún secret ni token nuevo:** el botón del visor solo abre
un formulario de GitHub Issues ya completo: quien lo usa confirma con su
propia sesión de GitHub (la misma con la que ya administra el
repositorio), y el workflow usa el token automático de GitHub Actions
para comentar/cerrar el issue y commitear el cambio.

## Estado de los datos

- `knowledge/precios.yaml` está **vacío a propósito**: no existe una lista
  de precios en los documentos de origen del rol. `pricing.py` nunca
  inventa un precio — carga la lista real ahí antes de cotizar formalmente.
- `config/empresa.yaml` ya tiene los datos societarios cargados.

## Tests

```bash
python -m unittest discover -s tests -v
```
