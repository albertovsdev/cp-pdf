# Arquitectura

Qué existe en código hoy: módulos, responsabilidades, firmas públicas y
flujo. **El porqué de cada decisión vive en `PLAN.md`**; este documento no
lo repite. Si los dos se contradicen, `PLAN.md` manda en el *porqué* y éste
en el *qué*.

---

## 1. Mapa de módulos

```
src/contapdf/
├── ir.py              Representación intermedia. No depende de nada.
├── cuentas.py         Números de cuenta: esquema, jerarquía, forma canónica.
├── extract/           PDF → IR. Único lugar que sabe de pdfplumber/pypdfium2.
│   ├── pdf_text.py      texto nativo por palabras
│   ├── pdf_chars.py     texto nativo por corridas del content stream
│   ├── ocr.py           rasteriza y lee con Tesseract
│   ├── dedup.py         quita tokens repetidos
│   ├── tokens.py        separa tokens que el PDF entrega pegados
│   └── strategy.py      elige estrategia y normaliza
├── layout/            Geometría. NO depende del lector de PDF.
│   ├── lines.py         palabras → renglones
│   ├── columns.py       renglones → columnas
│   ├── region.py        acota la zona de tabla
│   └── headers.py       etiqueta las columnas
├── parsers/           IR → datos del dominio. NO saben de qué extractor vino.
│   ├── base.py          Layout, mapeo, parse_monto, protocolo Parser
│   ├── balanza.py  auxiliar.py  polizas.py  estado_cuenta.py  mayor.py
├── validate/rules.py  Checksums y cobertura.
├── templates/         Aprender un formato una vez.
│   ├── fingerprint.py   huella del layout
│   └── store.py         persistencia por tenant
├── recalculo.py       Rellena saldos con ancla verificada.
├── reintento.py       Relee por OCR lo que la aritmética señala.
├── export/excel.py    Datos + cobertura → .xlsx
├── pipeline.py        Orquestación de punta a punta.
├── cli.py             Punto de entrada, y la superficie que comparte con web/.
└── web/               Interfaz HTTP. Habla con el núcleo SOLO por cli.py.
    ├── app.py           app Flask: subir, estado, descargar
    └── templates/       HTML servido directo, sin build step
```

### Dependencias que el código respeta

| Regla | Por qué importa operativamente |
|---|---|
| `layout/` no importa pdfplumber ni pypdfium2 | La geometría se prueba con fixtures JSON, sin abrir un PDF |
| `parsers/` no importa ningún módulo de `extract/` | Un parser consume `Document` venga de donde venga, incluido OCR |
| `ir.py` no importa nada del proyecto | Es la frontera; todo lo demás depende de él |
| `validate/` importa parsers, no al revés | Un parser nunca decide si su salida es válida |
| `web/` no importa parsers, reglas, exportadores ni pipeline | Habla por `cli.procesar_documento()`. Si pudiera alcanzarlos, repetiría la orquestación y las dos versiones se separarían en la primera corrección. Un test lee los imports y lo impide. |

La única dirección permitida es
`ir → cuentas → layout → parsers → validate → export`, con `extract/`
colgando de `ir` y `pipeline`/`cli` por encima de todo.

---

## 2. Firmas públicas

### `ir.py` — el contrato central

```python
@dataclass(frozen=True)
class Word:   text, x0, x1, top, bottom, size, bold, page, run=0
@dataclass
class Line:   words: list[Word], top, bottom, page
@dataclass
class ColumnSpec: index, align, x_min, x_max, support, header=""
@dataclass(frozen=True)
class Page:   number, width, height, words: tuple[Word,...], ruling_lines=0
@dataclass(frozen=True)
class Document: source: str, page_count: int,
                open_pages: Callable[[], Iterator[Page]]
```

`Document` no guarda las páginas: guarda **cómo abrirlas**. Cada llamada a
`open_pages()` reabre el PDF y devuelve un generador.

`Word.run` identifica la corrida de texto de la que salió la palabra. Solo
`pdf_chars` lo llena; los demás extractores dejan `0`.

### `extract/`

```python
pdf_text.extract(path, *, page_numbers=None) -> Document
pdf_chars.extract(path, *, page_numbers=None, hueco=1.2) -> Document
ocr.extract(path, *, page_numbers=None, dpi=300, idioma="spa",
            binario="tesseract", psm="6", confianza_minima=40.0) -> Document
ocr.leer_pagina(path, numero, *, ...) -> Page      # unidad del reintento
ocr.hay_tesseract(*, binario="tesseract") -> bool  # nunca lanza

@dataclass(frozen=True)
class strategy.Decision: estrategia, motivo, senales: dict

strategy.decidir(path, *, paginas_muestra=2, umbral_traslape=0.02,
                 umbral_cid=0.5, binario="tesseract") -> Decision
strategy.extraer_con_motivo(path, *, estrategia=None, page_numbers=None,
                            paginas_muestra=2,
                            umbral_cid=0.5) -> tuple[Document, Decision]
strategy.extraer(path, *, estrategia=None, page_numbers=None,
                 paginas_muestra=2) -> tuple[Document, str]
strategy.esta_contaminada(path, *, paginas_muestra=2,
                          umbral_traslape=0.02) -> bool
strategy.tokens_contaminados(words) -> list[Word]
strategy.palabras_traslapadas(words) -> int
strategy.fraccion_cid(words) -> float

dedup.multiplicador(words) -> int
dedup.deduplicar(words) -> tuple[Word, ...]
dedup.deduplicar_pagina(page) -> Page
tokens.separar_fecha_pegada(words) -> tuple[Word, ...]
```

`extraer()` es la puerta que usa todo el sistema: elige estrategia, y el
`Document` que devuelve ya viene deduplicado y con los tokens pegados
sueltos. Los extractores crudos no normalizan nada.

**Tres señales deciden la estrategia**, cada una con su umbral medido:

| Señal | Qué delata | Estrategia |
|---|---|---|
| `tokens_contaminados` | glifos de dos corridas en una palabra | `pdf_chars` |
| `palabras_traslapadas` > 0.02 | una columna impresa encima de otra | `pdf_chars` |
| `fraccion_cid` ≥ 0.5 | el PDF no trae el mapa que traduce glifos | `ocr` |

El CID se evalúa **primero**: cuando el archivo no trae el mapa, ni
`pdf_text` ni `pdf_chars` lo salvan. Y el umbral es una fracción alta a
propósito — el OCR cuesta ~21 s por documento, así que lo que lo justifica
es que el documento sea ilegible, no que traiga un sello digital en CID;
eso último lo cubre `reintento.reintentar_cid`, página por página. Si el
documento pide OCR y no hay Tesseract, `decidir()` devuelve `pdf_text` y lo
dice en el motivo, en vez de fallar.

`Decision.motivo` viaja hasta el reporte del CLI: mandar un documento a OCR
cuesta veinte veces más que no mandarlo, y esa decisión no puede quedarse
en un log. `extraer()` conserva su firma de siempre porque hay veintitantos
llamadores que la desempaquetan.

### `layout/`

```python
lines.group(words, tol=2.5) -> list[Line]
columns.is_amount(text, *, en_columna_de_cuenta=False) -> bool
columns.zona_de_cuenta(lines, tol=3.0) -> tuple[float, float] | None
columns.detect(lines, *, tol=3.0, min_support=3) -> list[ColumnSpec]
columns.amount_columns(lines, *, tol=3.0, min_support=3) -> list[ColumnSpec]
columns.amount_anchors(lines, *, tol=3.0, min_support=3) -> list[float]
region.find_table_region(lines, *, tol=3.0, min_support=3,
                         min_amount_columns=2, max_gap_lines=8,
                         max_header_lines=3) -> Region | None
region.lines_within(lines, region) -> list[Line]
headers.assign(lines, region, columns, *, max_distance=40.0,
               max_header_lines=4, pitch_factor=1.3) -> list[ColumnSpec]
```

`Region` es un `NamedTuple(top, bottom)`: se desempaqueta como tupla.
`find_table_region` devuelve `None` cuando la página no tiene tabla; eso no
es un error.

### `parsers/base.py`

```python
parse_monto(texto) -> Decimal          # ÚNICO lugar donde se parsea dinero
es_cuenta(texto) -> bool
normalizar(texto) -> str               # minúsculas, sin acentos
detectar_layout(paginas, *, tol=3.0, min_support=3) -> Layout | None
celdas(line, layout) -> dict[int, str]
lineas_de_tabla(page) -> list[Line]
renglones_de_tabla(page, layout) -> list[dict[int, str]]

@dataclass(frozen=True)
class Layout:
    columns: tuple[ColumnSpec, ...]
    texto_en_montos: bool = False
    headers -> tuple[str, ...]         # propiedades
    montos  -> tuple[ColumnSpec, ...]
    textos  -> tuple[ColumnSpec, ...]
    indice_de(word, *, max_distance=40.0) -> int | None

class Parser(Protocol):
    def parse(self, document: Document) -> object: ...
```

### `parsers/estado_cuenta.py`

```python
@dataclass(frozen=True)
class MetaEstadoCuenta:  banco, rfc, periodo_ini, periodo_fin, anio,
                         total_saldo_inicial, total_saldo_corte
@dataclass(frozen=True)
class CuentaBancaria:    num_cuenta, clabe, producto, moneda,
                         saldo_inicial, depositos, retiros, saldo_corte
@dataclass(frozen=True)
class MovimientoBancario: num_cuenta, dia, fecha, descripcion, referencia,
                          deposito, retiro, saldo, pagina
@dataclass(frozen=True)
class EstadoCuenta:      meta, cuentas, movimientos, mapeo
                         cuenta(num) / movimientos_de(num)   # metodos
@dataclass(frozen=True)
class TipoDeReporte:     clave, etiqueta, evidencia, cuentas
class ReporteNoEsperado(LayoutDesconocido):  .tipo -> TipoDeReporte

detectar_cabecera(paginas) -> Layout | None
EstadoCuentaParser(paginas_muestra=2, *, separador_continuacion="")
```

Los saldos son de la **cuenta**, no del documento. Un estado de una sola
cuenta queda con `cuentas` de longitud 1, sin caso especial.

`detectar_cabecera` lee la fila de encabezado de la tabla de movimientos y
devuelve un `Layout` cuyos `header` son las etiquetas del banco. Devuelve
`None` cuando ninguna pagina trae una; eso no es un error.

`ReporteNoEsperado` es un `LayoutDesconocido` que ademas dice QUE es el
documento (`clave`, `etiqueta` legible, `evidencia` del propio texto y las
`cuentas` que si se pudieron leer). Quien ya atrapaba `LayoutDesconocido`
no se entera del cambio.

### `cli.py` — la superficie que comparten la terminal y la web

```python
TIPOS_DE_DOCUMENTO -> tuple[tuple[str, str], ...]   # (nombre, ayuda)

@dataclass(frozen=True)
class ResultadoDocumento: tipo, fuente, paginas, estrategia,
                          motivo_estrategia, cobertura, plantilla,
                          reutilizada, resumen, datos, destino=None
                          cuadra -> bool

class DocumentoNoReconocido(ValueError):  .detalle, .clave

procesar_documento(tipo, pdf, destino=None, *, paginas_muestra=3,
                   tenant_id=None, plantillas=None) -> ResultadoDocumento
```

`procesar_documento()` devuelve DATOS y no imprime nada; el CLI la envuelve
para escribir su reporte y la capa web para renderizar el suyo. Traduce
`LayoutDesconocido` y `ReporteNoEsperado` a `DocumentoNoReconocido`, con
mensaje legible, para que quien llame no tenga que importar las excepciones
del núcleo.

### `web/`

```python
crear_app(*, trabajos: Path | None = None) -> Flask
```

Rutas: `GET /` (formulario), `POST /procesar` (302 a la página de estado),
`GET /trabajo/<id>` (estado o resultado), `GET /descargar/<id>`.

**El trabajo corre en un hilo.** `auxiliar-gume` tarda 3m57s y ninguna
página puede esperar eso, así que la subida devuelve un id al instante y la
página de estado se refresca sola con el tiempo transcurrido. El registro de
trabajos es un diccionario en `app.extensions`, nunca un global de módulo.

**Nada se queda en disco**: el PDF se borra al terminar el procesamiento, el
Excel al descargarse, y un barrido en cada petición borra todo lo que pase
de 30 minutos.

### `cuentas.py`

```python
@dataclass(frozen=True)
class EsquemaCuenta: separador="-", anchos=(), marcador=None, largo=0

inferir_esquema(cuentas) -> EsquemaCuenta
nivel_y_padre(cuenta, esquema=None) -> tuple[int, str]
canonizar(texto, *, ancho=18) -> str
canonizar_cuenta(cuenta, esquema=None, *, ancho=18) -> str
```

`canonizar*` es lo que permite cruzar el mismo catálogo entre reportes que
lo imprimen distinto.

### `validate/rules.py`

```python
CUADRA = "cuadra"; FALLA = "falla"; NO_VERIFICABLE = "no_verificable"

@dataclass(frozen=True)
class Discrepancia:   fila, indice, regla, esperado: Decimal, obtenido: Decimal
@dataclass(frozen=True)
class ResultadoRegla: regla, estado, aplicables: int|None = None,
                      evaluados=0, exactas=0, exactas_impresas=0,
                      exactas_recalculadas=0, con_tolerancia=(),
                      discrepancias=(), motivo=""
                      comprobaciones -> int   # DEPRECADO, se retira en fase 8
                      resumen() -> str
@dataclass(frozen=True)
class Cobertura:      reglas, naturalezas={}, saldos={}
                      discrepancias / cuadran / fallan / no_verificables
                      aplicables / evaluados / exactas_recalculadas
                      resumen() / resumen_naturaleza() / resumen_saldos()
@dataclass(frozen=True)
class ReglasBalanza:  tolerancia=0.01, subconjunto_totales="nivel_1",
                      exige_partida_doble=True
                      ReglasBalanza.para(balanza) -> ReglasBalanza

evaluar_balanza(balanza, *, reglas=None) -> Cobertura
evaluar_auxiliar(auxiliar, *, reglas=None) -> Cobertura
evaluar_polizas(libro, *, reglas=None) -> Cobertura
naturaleza_por_cuenta(auxiliar, *, tolerancia=TOLERANCIA) -> dict[str, str]
recalculo.ancla_de_seccion(movimientos, subtotal, signo) -> bool
    # 'D' | 'A' | '' por cuenta, por mayoria de los renglones que la
    # revelan. La usan _saldo_corrido y recalculo.recalcular_saldos: el
    # signo de una identidad de saldo NUNCA se cablea.
evaluar_estado_cuenta(estado, *, reglas=None) -> Cobertura
    # 4 reglas, todas POR CUENTA: resumen, resumen_movimientos,
    # saldo_corrido y total_declarado (la fila TOTAL contra la suma)
evaluar_mayor(mayor, *, balanza=None, reglas=None) -> Cobertura
validar_balanza(balanza, *, reglas=None) -> list[Discrepancia]
```

### `templates/`

```python
@dataclass(frozen=True)
class Huella:    tokens, columnas_monto, forma_cuenta;  .valor -> str
huella_de(layout, cuentas=()) -> Huella | None

@dataclass(frozen=True)
class Plantilla: tenant_id, huella, tipo, estrategia, mapeo, forma,
                 verificado_por, orientacion_verificada, filas_afectadas,
                 esquema, reglas, cobertura, pendiente_de_confirmacion,
                 confirmada_por="", confirmada_en="", version=1,
                 separador_continuacion=""
                 pendientes() -> list[dict]
                 que_confirmar() -> dict | None   # el primero de pendientes()

class AlmacenPlantillas:
    __init__(raiz)
    guardar(plantilla) -> Path          # rechaza si cobertura["fallan"]
    buscar(tenant_id, huella) -> Plantilla | None
    listar(tenant_id) -> list[Plantilla]
    confirmar(tenant_id, huella, *, por, cuando=None) -> Plantilla
```

### `pipeline.py` y `export/excel.py`

```python
procesar_balanza(pdf, *, tenant_id=None, almacen=None,
                 paginas_muestra=3, estrategia=None) -> Resultado
procesar_auxiliar(...)       -> ResultadoAuxiliar
procesar_polizas(...)        -> ResultadoPolizas
procesar_estado_cuenta(...)  -> ResultadoEstadoCuenta
procesar_mayor(..., balanza=None) -> ResultadoMayor

exportar_balanza(balanza, cobertura, destino) -> Path
exportar_auxiliar(auxiliar, cobertura, destino) -> Path
exportar_polizas(libro, cobertura, destino) -> Path
exportar_estado_cuenta(estado, cobertura, destino) -> Path
exportar_mayor(mayor, cobertura, destino) -> Path
```

Los cinco tipos de documento salen a Excel. Los que devuelven una sola
tabla (`balanza`, `auxiliar`) escriben dos hojas; los que devuelven tablas
relacionadas (`polizas`, `estado_cuenta`, `mayor`) escriben las
relacionadas, una plana denormalizada y la validación.

Todos los `Resultado*` traen `cobertura`, `estrategia`, `motivo_estrategia`,
`huella`, `plantilla` y `reutilizada`.

---

## 3. El flujo de un documento

```
PDF
 └─ strategy.extraer_con_motivo(pdf)           pdf_text | pdf_chars | ocr
     ├─ decidir()                              3 señales medidas + el porqué
     ├─ dedup.deduplicar_pagina()              por página, al vuelo
     └─ tokens.separar_fecha_pegada()
 └─ Document  (open_pages() → Iterator[Page])

 └─ pipeline.procesar_*()
     ├─ muestra de páginas
     ├─ parsers.base.detectar_layout(muestra)
     │    ├─ lines.group()
     │    ├─ region.find_table_region()  +  lines_within()
     │    ├─ columns.detect() + columns.amount_columns()
     │    └─ headers.assign()
     ├─ templates.fingerprint.huella_de(layout, cuentas)
     ├─ AlmacenPlantillas.buscar(tenant, huella)
     │    ├─ hay plantilla → se aplica su mapeo, sin volver a proponer
     │    └─ no hay        → parser.parse() propone y verifica
     ├─ <Parser>.parse(document)                UNA sola pasada completa
     ├─ validate.evaluar_*()                    → Cobertura
     └─ AlmacenPlantillas.guardar()             solo si cobertura.fallan == 0

`procesar_estado_cuenta` es la excepción del cuadro: su layout NO sale de
`detectar_layout` sino de `estado_cuenta.detectar_cabecera`, que lee la fila
de encabezado de la tabla. La huella se arma con ese vocabulario, que es lo
que distingue **(banco, tipo de reporte)** —el eje real de la plantilla— y
lo que impide que dos reportes distintos del mismo banco colisionen.

 └─ export.exportar_*(datos, cobertura, destino) → .xlsx
 └─ cli.reportar(..., cobertura, ...)            → texto
```

Carriles aparte, disparados por la aritmética y no por el flujo normal:

```
reintento.paginas_a_reintentar(auxiliar) → reintentar_ilegibles(pdf, aux)
reintento.paginas_con_cid(documento)     → reintentar_cid(pdf)
```

`recalculo.recalcular_saldos()` **ya no es un carril aparte**: desde la fase
7g `procesar_auxiliar()` lo llama siempre, justo entre el parseo y la
validación. Sólo rellena las secciones cuyos dos extremos están anclados
contra el subtotal declarado; donde no hay ancla el saldo se queda en `None`
y la cobertura lo declara. Cada saldo derivado queda con
`saldo_origen="recalculado"`, nunca confundido con uno impreso.

---

## 4. Invariantes que impone el tipo

No son convenciones: el código no compila o no corre si se violan.

| Invariante | Cómo se impone |
|---|---|
| No se reporta un resultado sin su cobertura | `reportar()` y `exportar_*()` reciben `Cobertura`, no `list[Discrepancia]`. No hay forma de llamarlos con solo las discrepancias. |
| Una comprobación sobre un dato derivado no cuenta como verificación | `exactas_impresas` y `exactas_recalculadas` suman `exactas` y `__post_init__` lo impone. Comprobar `saldo = anterior + debe − haber` sobre un saldo generado con esa fórmula es una tautología, y `Cobertura.resumen()` lo advierte en voz alta. |
| Ningún conteo se imprime sin su denominador | `ResultadoRegla` guarda `aplicables` (el universo de casos del documento) además de `evaluados`. `__post_init__` **lanza** si una regla cuadra con `aplicables=None`, o si `aplicables < evaluados`. `resumen()` y el detalle del CLI siempre escriben «N de M». |
| El dinero nunca es `float` | `parse_monto()` devuelve `Decimal` y es el único parseador. Un test AST prohíbe llamar a `float()` en los módulos de dinero. |
| Un dato ilegible no se inventa | Los campos que pueden faltar son `Decimal | None`: `FilaAuxiliar.saldo`, `MovimientoBancario.saldo`, `MesMayor.saldo`, `Poliza.total_debe`. Quien consume tiene que decidir qué hacer con `None`. |
| Un valor derivado declara su procedencia | `FilaBalanza.naturaleza_origen`, `FilaAuxiliar.saldo_origen`, `Mapeo.verificado_por`. |
| El signo de una identidad de saldo no se cablea | `naturaleza_por_cuenta()` lo deriva de los datos y es el único origen para `_saldo_corrido` y `recalcular_saldos`. Un test de espejo (intercambiar debe y haber) falla si alguien vuelve a fijarlo. |
| No se aprende un formato que no cuadró | `AlmacenPlantillas.guardar()` lanza `PlantillaRechazada` si `cobertura["fallan"]`. |
| Un tenant no ve lo de otro | La ruta se deriva del `tenant_id` validado contra `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`; `TenantInvalido` bloquea todo lo demás. |
| El núcleo no imprime | Tests AST prohíben `print` y lectura de `os.environ` bajo `src/contapdf/`. `cli.py` escribe a un stream que recibe por parámetro. |
| Sin estado global mutable | Test AST: toda asignación a nivel de módulo va en MAYÚSCULAS o con `_`, y nunca es `list`/`dict`/`set` literal. |

---

## 5. Los cinco parsers

| Parser | Documento | Entrada | Salida | Estrategia |
|---|---|---|---|---|
| `BalanzaParser` | Balanza de comprobación | 3 formatos | `Balanza(filas, totales, mapeo)` | `pdf_text`, `pdf_chars` en Business Pro |
| `AuxiliarParser` | Auxiliar de cuentas | 2 formatos | `Auxiliar(filas, secciones, mapeo)` | `pdf_text` |
| `PolizasParser` | Libro diario | 2 formatos | `LibroDiario(polizas, movimientos, cfdi)` | `pdf_text`, `pdf_chars` en Diario General |
| `EstadoCuentaParser` | Estado de cuenta | 6 formatos, 5 bancos | `EstadoCuenta(meta, cuentas, movimientos)` | `pdf_text`, `pdf_chars` segun el documento |
| `MayorParser` | Libro mayor | 1 formato | `Mayor(cuentas, meses)` | `pdf_text` |

Todos exponen la misma forma:

```python
parse(document, *, layout=None, mapeo=None) -> <resultado>
```

`layout` y `mapeo` permiten aplicar una plantilla ya aprendida y saltarse
la detección. `EstadoCuentaParser` recibe además `separador_continuacion`,
que también sale de la plantilla. Todos lanzan `LayoutDesconocido` (en `parsers/balanza.py`)
cuando no reconocen el documento.

Los que devuelven tablas relacionadas —`polizas`, `mayor`— exportan además
una hoja plana denormalizada. Los que devuelven una tabla —`balanza`,
`auxiliar`— no la necesitan. `estado_cuenta` devuelve dos tablas
relacionadas (`cuentas` y `movimientos`) pero todavía **no tiene
`exportar_estado_cuenta`**: solo se alcanza por API.

### Cómo generaliza `EstadoCuentaParser` a seis formatos

Sin una sola rama por banco; un test lo impone leyendo el módulo y
prohibiendo que nombre a ninguno.

| Mecanismo | Qué resuelve |
|---|---|
| `_CAMPOS_TABLA` | El vocabulario del encabezado: `Depósitos`/`Abonos`/`MONTO DEL DEPOSITO` son la misma columna. Se compara con y sin espacios, porque un formato imprime `F E C H A` letra por letra. |
| Anclas del encabezado | El importe va a la columna cuyo **borde derecho** tiene más cerca, con tolerancia de media separación entre columnas. |
| `_campo_heredado` | Encabezado agrupado: `SALDO` en el renglón de arriba abarcando `OPERACIÓN` y `LIQUIDACIÓN`, y se consulta **solo** si la subetiqueta no significa nada por sí sola. |
| `_FECHAS` | Seis formatos de fecha (`03`, `01-ABR-2025`, `01-JUL-23`, `1 SEP`, `JUL. 03`, `01/DIC`) normalizados a `dd/mm/aaaa`. El año sale del período declarado. |
| `_CAMPOS_CUENTAS` | El resumen que lista las cuentas del documento, con su fila `TOTAL`. |
| `_CAMPOS_RESUMEN` | Las etiquetas de saldo, comparadas por el **final** de la etiqueta y sin espacios: un renglón puede traer dos parejas etiqueta-valor. |
| `_secciones` / `_seccion_de` | La cuenta a la que pertenece un movimiento: la sección que lo contiene, reconocida por cómo abre el renglón. |
| `_junta_signos` | El `$` y el `-` que vienen en su propio token. `-$` delante de un saldo es la única marca de que es negativo. |

La tabla **no** se acota con `find_table_region`: en estos documentos deja
páginas enteras fuera (BBVA página 2 devuelve `None` con 40 movimientos
impresos). Se acota con lo que el documento garantiza —los seis formatos
reimprimen el encabezado en cada página de tabla— y una continuación tiene
que venir a menos de 12pt del renglón anterior.

---

## 6. Puntos de extensión

**Un formato nuevo del mismo tipo de documento.** No se toca código: se
agregan sinónimos a la tabla `_CAMPOS`/`_FORMAS` del parser correspondiente
y el mecanismo de proponer-y-verificar hace el resto. Si el formato trae
una forma estructuralmente distinta (columnas partidas contra columna con
signo), se agrega una `Forma` a `_FORMAS`.

**Un extractor nuevo.** Implementar
`extract(path, *, page_numbers=None) -> Document` produciendo el mismo IR, y
enrutarlo en `strategy.extraer()`. `ocr.py` es el ejemplo: `layout/` y
`parsers/` no se enteraron.

**Una señal nueva para elegir extractor.** Una función
`f(words) -> int|bool` en `strategy.py` y una condición más en
`esta_contaminada()`. Hoy hay dos: tokens contaminados y palabras
traslapadas.

**Una regla de validación nueva.** Una función
`_regla(datos, tolerancia) -> ResultadoRegla` en `validate/rules.py` y
agregarla a la tupla del `evaluar_*` correspondiente. Debe devolver
`NO_VERIFICABLE` con motivo cuando no pueda correr, nunca omitirse.

**Un tipo de documento nuevo.** Parser en `parsers/`, `evaluar_*` en
`validate/rules.py`, `procesar_*` en `pipeline.py`, `exportar_*` en
`export/excel.py`. La huella y el almacén no cambian: `Plantilla.tipo` es
un `str` libre.

**Otro almacén de plantillas.** `AlmacenPlantillas` es una clase concreta
con cuatro métodos (`guardar`, `buscar`, `listar`, `confirmar`). Sustituirla
por una implementación con base de datos no requiere tocar `pipeline.py`
más allá del tipo del parámetro.

---

## 7. Qué NO hace el sistema

- **No hay capa web, cola ni workers.** El punto de entrada es
  `python -m contapdf.cli`, con seis comandos: `balanza`, `auxiliar`,
  `polizas`, `estado-cuenta`, `mayor` y `confirmar`. Los cinco primeros
  tienen la misma forma (`<comando> <pdf> [-o] [--tenant] [--plantillas]`),
  el mismo reporte de cobertura y los mismos códigos de salida
  (0 cuadra, 1 hay discrepancias, 2 no se pudo procesar).
- **No cruza documentos automáticamente.** `evaluar_mayor(balanza=...)` es
  el único cruce y hay que pasarle el otro documento a mano; ningún módulo
  sale a buscar archivos.
- **No recupera un PDF cuya tinta no existe.** El reintento por OCR sirve
  para texto perdido, no para texto nunca dibujado.
- **No decide reglas contables.** Cuando la aritmética no alcanza, entrega
  `no_verificable` con el dato y la pregunta.
- **No hay concurrencia ni límite de trabajos.** Cada `procesar_*` es una
  llamada síncrona que reabre el PDF.

### Qué es imposible hoy sin cambiar contratos

| Quiero… | Choca con |
|---|---|
| Depósitos y retiros por cuenta cuando el documento no los desglosa | Se quedan en `None`; repartir el total del documento sería inventarlo |
| Distinguir una continuación partida a la mitad de una partida por palabra | La geometría es idéntica en los dos casos y se midió que no hay discriminador; `separador_continuacion` lo confirma un humano una vez por formato y la plantilla lo guarda |
| Una cuenta de crédito, donde el saldo corre al revés | `_saldo_corrido_bancario` fija el signo `saldo + depósito − retiro`; una sección de crédito falla la regla y lo declara |
| Un identificador de póliza estable entre lecturas | `Poliza.poliza_id` es la posición en esa lectura |
| Procesar sin materializar el documento | `AuxiliarParser`, `PolizasParser`, `MayorParser` y `EstadoCuentaParser` hacen `list(document.open_pages())`. Solo `BalanzaParser` transmite página por página |
| Reglas de validación por tenant | `ReglasBalanza` se deduce del documento o se pasa a mano; la plantilla la guarda pero `evaluar_*` no la lee del almacén |
| Cancelar un trabajo a media corrida | No hay puntos de cancelación |
