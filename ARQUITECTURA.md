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
└── cli.py             Punto de entrada.
```

### Dependencias que el código respeta

| Regla | Por qué importa operativamente |
|---|---|
| `layout/` no importa pdfplumber ni pypdfium2 | La geometría se prueba con fixtures JSON, sin abrir un PDF |
| `parsers/` no importa ningún módulo de `extract/` | Un parser consume `Document` venga de donde venga, incluido OCR |
| `ir.py` no importa nada del proyecto | Es la frontera; todo lo demás depende de él |
| `validate/` importa parsers, no al revés | Un parser nunca decide si su salida es válida |

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

strategy.extraer(path, *, estrategia=None, page_numbers=None,
                 paginas_muestra=2) -> tuple[Document, str]
strategy.esta_contaminada(path, *, paginas_muestra=2,
                          umbral_traslape=0.02) -> bool
strategy.tokens_contaminados(words) -> list[Word]
strategy.palabras_traslapadas(words) -> int

dedup.multiplicador(words) -> int
dedup.deduplicar(words) -> tuple[Word, ...]
dedup.deduplicar_pagina(page) -> Page
tokens.separar_fecha_pegada(words) -> tuple[Word, ...]
```

`extraer()` es la puerta que usa todo el sistema: elige estrategia, y el
`Document` que devuelve ya viene deduplicado y con los tokens pegados
sueltos. Los extractores crudos no normalizan nada.

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
class ResultadoRegla: regla, estado, comprobaciones=0, exactas=0,
                      con_tolerancia=(), discrepancias=(), motivo=""
@dataclass(frozen=True)
class Cobertura:      reglas, naturalezas={}, saldos={}
                      discrepancias / cuadran / fallan / no_verificables
                      resumen() / resumen_naturaleza() / resumen_saldos()
@dataclass(frozen=True)
class ReglasBalanza:  tolerancia=0.01, subconjunto_totales="nivel_1",
                      exige_partida_doble=True
                      ReglasBalanza.para(balanza) -> ReglasBalanza

evaluar_balanza(balanza, *, reglas=None) -> Cobertura
evaluar_auxiliar(auxiliar, *, reglas=None) -> Cobertura
evaluar_polizas(libro, *, reglas=None) -> Cobertura
evaluar_estado_cuenta(estado, *, reglas=None) -> Cobertura
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
                 confirmada_por="", confirmada_en="", version=1
                 que_confirmar() -> dict | None

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
exportar_polizas(libro, cobertura, destino) -> Path
exportar_mayor(mayor, cobertura, destino) -> Path
```

Todos los `Resultado*` traen `cobertura`, `estrategia`, `huella`,
`plantilla` y `reutilizada`.

---

## 3. El flujo de un documento

```
PDF
 └─ strategy.extraer(pdf)                      elige pdf_text | pdf_chars
     ├─ esta_contaminada()                     glifos pegados o sobreimpresión
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

 └─ export.exportar_*(datos, cobertura, destino) → .xlsx
 └─ cli.reportar(..., cobertura, ...)            → texto
```

Carriles aparte, disparados por la aritmética y no por el flujo normal:

```
reintento.paginas_a_reintentar(auxiliar) → reintentar_ilegibles(pdf, aux)
reintento.paginas_con_cid(documento)     → reintentar_cid(pdf)
recalculo.recalcular_saldos(auxiliar)    → Auxiliar con saldos recalculados
```

---

## 4. Invariantes que impone el tipo

No son convenciones: el código no compila o no corre si se violan.

| Invariante | Cómo se impone |
|---|---|
| No se reporta un resultado sin su cobertura | `reportar()` y `exportar_*()` reciben `Cobertura`, no `list[Discrepancia]`. No hay forma de llamarlos con solo las discrepancias. |
| El dinero nunca es `float` | `parse_monto()` devuelve `Decimal` y es el único parseador. Un test AST prohíbe llamar a `float()` en los módulos de dinero. |
| Un dato ilegible no se inventa | Los campos que pueden faltar son `Decimal | None`: `FilaAuxiliar.saldo`, `MovimientoBancario.saldo`, `MesMayor.saldo`, `Poliza.total_debe`. Quien consume tiene que decidir qué hacer con `None`. |
| Un valor derivado declara su procedencia | `FilaBalanza.naturaleza_origen`, `FilaAuxiliar.saldo_origen`, `Mapeo.verificado_por`. |
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
| `EstadoCuentaParser` | Estado de cuenta | 1 banco | `EstadoCuenta(meta, movimientos)` | `pdf_chars` |
| `MayorParser` | Libro mayor | 1 formato | `Mayor(cuentas, meses)` | `pdf_text` |

Todos exponen la misma forma:

```python
parse(document, *, layout=None, mapeo=None) -> <resultado>
```

`layout` y `mapeo` permiten aplicar una plantilla ya aprendida y saltarse
la detección. Todos lanzan `LayoutDesconocido` (en `parsers/balanza.py`)
cuando no reconocen el documento.

Los tres que devuelven tablas relacionadas —`polizas`, `mayor`— exportan
además una hoja plana denormalizada. Los que devuelven una tabla —`balanza`,
`auxiliar`, `estado_cuenta`— no la necesitan.

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
  `python -m contapdf.cli`, con dos comandos: `balanza` y `confirmar`.
  Los otros cuatro parsers solo se alcanzan por API.
- **No procesa varias cuentas bancarias en un mismo estado de cuenta.**
  `MetaEstadoCuenta` tiene un `num_cuenta` y una `clabe`, en singular.
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
| Varias cuentas en un estado de cuenta | `EstadoCuenta.meta` es un único `MetaEstadoCuenta` |
| Un identificador de póliza estable entre lecturas | `Poliza.poliza_id` es la posición en esa lectura |
| Procesar sin materializar el documento | `AuxiliarParser`, `PolizasParser`, `MayorParser` y `EstadoCuentaParser` hacen `list(document.open_pages())`. Solo `BalanzaParser` transmite página por página |
| Reglas de validación por tenant | `ReglasBalanza` se deduce del documento o se pasa a mano; la plantilla la guarda pero `evaluar_*` no la lee del almacén |
| Cancelar un trabajo a media corrida | No hay puntos de cancelación |
