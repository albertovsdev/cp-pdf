# cp-pdf — Plan de construcción

Sistema de conversión de PDFs contables a Excel, con mapeo por plantillas y
validación aritmética.

**Regla de oro:** ningún parser se escribe sin un fixture que lo pruebe
primero. Fixture → test que falla → parser → test que pasa.

Estado: **fases 0, 1 y 2 completadas** (2026-08). Siguiente: fase 3.

**Alcance: 5 tipos de documento.** El Libro Mayor se agregó tras confirmarlo
con el cliente. Y cada tipo tiene variantes fuertes entre empresas: no basta
un parser por tipo, hace falta un parser por tipo capaz de absorber
variantes vía plantilla (fase 4).

---

## 0. Restricciones de arquitectura

El sistema terminará en un servidor compartido, con varios usuarios y
documentos de **varias empresas distintas**. Estas reglas aplican a todo el
código bajo `src/contapdf/` desde la primera línea. Son baratas ahora y muy
caras de meter después.

- **Sin estado global mutable.** Nada de variables a nivel de módulo que
  guarden configuración o resultados; nada de leer `os.environ` al importar.
  Toda configuración se pasa como parámetro explícito. Con varios trabajos
  en paralelo, un global se contamina entre peticiones y mezcla datos de
  empresas distintas.
- **Sin efectos secundarios en el núcleo.** Las funciones no imprimen a
  stdout, no escriben archivos, no leen rutas fijas y no dependen del
  directorio actual. Devuelven datos. Para mensajes, `logging`, nunca `print`.
- **Procesamiento por página.** `extract()` entrega página por página
  (generador). Un PDF de 968 páginas no puede cargarse entero en memoria en
  un servidor compartido.
- **Funciones puras y deterministas.** Misma entrada, misma salida. Es lo
  que hace posible testear, cachear y paralelizar.
- **Una sola pasada completa por documento.** `Document.open_pages` reabre
  el PDF en cada recorrido, así que cada pasada cuesta un parseo entero.
  Los parsers detectan columnas sobre una MUESTRA de páginas (la primera
  con tabla más un par al azar) y luego hacen una única pasada aplicando
  ese layout. Nunca un recorrido para detectar y otro para extraer: en un
  PDF de 968 páginas eso duplica el costo.
- **Aislamiento por tenant.** Cada trabajo con su directorio temporal
  propio, borrado al terminar. Las rutas de salida se derivan del ID de
  usuario, nunca del nombre del archivo subido. Las plantillas de mapeo
  (fase 4) van ligadas a la empresa, no son globales.

`scripts/dump_layout.py` **no** cumple estas reglas (usa `SALT` como global
de módulo e imprime a stdout). Está bien: es un script de una sola corrida,
no forma parte del núcleo. No copiar ese patrón a `src/`.

---

## 1. Contratos de datos

### 1.1 Representación intermedia (IR)

Toda extracción — texto nativo u OCR — produce lo mismo:

```python
@dataclass(frozen=True)
class Word:
    text: str
    x0: float; x1: float
    top: float; bottom: float
    size: float
    bold: bool
    page: int

@dataclass
class Line:
    words: list[Word]
    top: float
    bottom: float
    page: int

@dataclass
class ColumnSpec:
    index: int
    align: str          # 'left' | 'right'
    x_min: float
    x_max: float
    support: int
    header: str = ""
```

Consecuencia: los parsers **no saben** si el texto vino de un PDF nativo o
de OCR. Se pueden testear sin instalar Tesseract.

**Dos reglas que ya validamos con datos reales y que el núcleo debe respetar:**

1. **Agrupar renglones por solapamiento vertical, no por `top`.** En las
   pólizas el importe está centrado en una celda alta y su `top` difiere
   ~6pt del de la etiqueta, pero es el mismo renglón lógico.
2. **Detectar columnas de montos por `x1`, no por `x0`.** Los montos van
   alineados a la derecha; agrupar todo por `x0` genera decenas de falsas
   columnas.

### 1.2 Salidas canónicas por tipo de documento

**Balanza de comprobación** — una tabla:

`cuenta`, `nivel`, `cuenta_padre`, `naturaleza`, `nombre`,
`saldo_ini_deudor`, `saldo_ini_acreedor`, `debe`, `haber`,
`saldo_fin_deudor`, `saldo_fin_acreedor`

`nivel` y `cuenta_padre` se derivan del número de cuenta, no vienen del PDF.

`BalanzaParser.parse()` devuelve un objeto `Balanza` con `.filas` y
`.totales`, no una lista. La fila «Totales» no cabe en una `FilaBalanza`
(no tiene cuenta ni naturaleza) y el validador la necesita. `Balanza` es
iterable, así que `list(parse(doc))` sí entrega `list[FilaBalanza]`.

**Libro diario / pólizas** — tres tablas relacionadas, NO una tabla plana:

```
polizas(poliza_id, tipo, naturaleza, fecha, descripcion, folio,
        total_debe, total_haber)
movimientos(poliza_id, orden, cuenta, nombre_cuenta, debe, haber)
cfdi(poliza_id, fecha, documento, uuid, rfc, tipo)
```

Al Excel salen como 3 hojas + una hoja plana denormalizada (encabezado
repetido en cada movimiento), que es la que el contador va a filtrar.

**Auxiliar de cuentas** — tabla con la cuenta arrastrada desde el
encabezado de sección:

`cuenta`, `nombre_cuenta`, `saldo_inicial_cuenta`, `folio`, `fecha`,
`tipo_movimiento`, `documento`, `tercero`, `debe`, `haber`, `saldo`

**Estado de cuenta** — metadata + movimientos:

```
meta: banco, rfc, num_cuenta, clabe, periodo_ini, periodo_fin,
      saldo_inicial, depositos, retiros, saldo_corte
movimientos: dia, fecha, descripcion, referencia, deposito, retiro, saldo
```

### 1.3 Validación: cada documento trae su propio checksum

**Contra qué suma cuadra la fila «Totales» (medido, fase 2):** contra la
suma del **nivel 1 únicamente**. Ni todas las filas ni solo las hojas
cuadran. Sumar todas contaría dos veces a las cuentas padre, que ya
agregan a sus hijas.

No se validan las identidades `Σ ini_deudor == Σ ini_acreedor` ni su
equivalente de saldos finales, aunque el documento real las cumple: una
balanza filtrada por rango de cuentas las rompe legítimamente y
generarían falsos positivos.

```
balanza:   saldo_ini + debe - haber == saldo_fin  (por renglón, con signo
           según naturaleza)
           Σ debe == Σ haber
poliza:    Σ debe == Σ haber  (por póliza)
auxiliar:  saldo[n] == saldo[n-1] + debe[n] - haber[n]
edocta:    saldo_inicial + Σ depositos - Σ retiros == saldo_corte
           saldo[n] == saldo[n-1] ± movimiento[n]
```

**Si la validación falla, no se entrega el Excel limpio**: se entrega con
las filas sospechosas marcadas y un reporte de discrepancias. Con OCR de
por medio esto no es opcional.

---

## 2. Hallazgos de la fase 0

Medidos sobre los fixtures reales. **Son los números de referencia**: si el
código nuevo da otra cosa, hay que investigar por qué, no ajustar el test.

| Documento | Páginas | Columnas (página completa) | Columnas (región) | Bordes |
|---|---|---|---|---|
| Balanza | 1, 2, 9 | 9, 9, 9 | 9, 9 | pág 9 sí |
| Pólizas | 1, 2, 500 | 5, 5, 4 | — | sí |
| Auxiliar | 1, 2, 398 | 6, 7, 3 | **7**, —, sin tabla | no |
| Estado cta | 1, 2 | 1, 5 | 5, **6** | no |

Los números de "página completa" son mediciones de la fase 0 y quedan
pinneados como test de regresión de `detect`. **No son la verdad del
documento**: las palabras del metadato superior tienden un puente entre
columnas contiguas y el merge por solapamiento las funde. En el auxiliar
p1 fusionan FOLIO/FECHA con TIPO; en edocta p2 fusionan Día con
Descripción. Ambas separaciones son correctas y coinciden con la salida
canónica de la sección 1.2.

**El pipeline correcto de la fase 2 en adelante es
`group → find_table_region → detect`.** Detectar sobre la página completa
solo sirve como regresión histórica.

Tres conclusiones que condicionan el diseño:

1. **La detección de columnas debe correr solo sobre la región de la
   tabla.** La página 1 del estado de cuenta reportó 1 sola columna porque
   el algoritmo analizó encabezados, domicilio y sello digital. De ahí sale
   `layout/region.py`.
2. **Las pólizas traen líneas de tabla dibujadas** (`lines=36`). Para su
   parser, usar esas líneas como frontera de fila es exacto; el
   solapamiento vertical es la solución general para los otros tres.
3. **El auxiliar cambia de estructura dentro del mismo documento.** El
   parser tiene que detectar bloques, no asumir un layout único.

### Variantes descubiertas (documentos de otras empresas)

Los cuatro fixtures originales resultaron ser un solo dialecto. Estos
formatos, de empresas distintas, cambian vocabulario, semántica y estructura.

**Balanza GUME** (tercera variante, misma empresa que mayor-gume)
- Cuentas de **21 dígitos sin separadores**: `112000100100000000003`.
  Estructura medida sobre 734 renglones: posiciones 1–6 cuenta de mayor,
  7–9 subcuenta, 10–12 sub-subcuenta, 13–18 relleno constante, **19–21
  marcador de nivel** (001/002/003).
- **El nivel viene declarado, y el marcador NO es redundante.** Contra la
  indentación: 734/734 (con 2pt de tolerancia). Contra deducirlo de los
  ceros finales: 680/734, **fallan 54** — existe el sub-subnivel numerado
  `000`. Sin el marcador, 54 cuentas quedarían en el nivel equivocado.
- Cuarta forma de columnas: `Saldo inicial | Debe | Haber | Saldo final`.
  Estructuralmente es `saldo_con_signo` sin la columna SALDO MES.
- Jerarquía por prefijo: 71 cuentas con hijas, 71/71 cuadran.
- **Normalización de cuentas entre reportes** (verificado, no supuesto):
  la misma cuenta es `1120-001-001` en mayor-gume y `112000100100000000003`
  aquí. Los cortes de segmento no coinciden (4-3-3 vs 6-3-3) pero la cadena
  de dígitos sí. `canon(t, ancho=18) = re.sub(r"\D","",t)[:ancho].ljust(ancho,"0")`,
  **quitando antes el marcador de nivel (posiciones 19–21)**. Cruzan 49/49
  de mayor-gume y 7/7 de la muestra de auxiliar-gume; las 734 canónicas son
  734 distintas, sin colisiones.

**Balanza «Business Pro»**
- Cuentas `0400-0000-0000-0000`: base de 4 dígitos, **cuatro** segmentos.
- Vocabulario: `CARGOS`/`CREDITOS` en vez de Debe/Haber;
  `SALDO ANTERIOR`/`SALDO ACTUAL` en vez de Inicial/Final.
- **Semántica distinta**: no hay columnas deudor/acreedor separadas, hay una
  sola columna con signo (`-25,142,979.83`).
- **Medido sobre el documento completo (224 renglones, 0 contradicciones):**
  el signo sí se invierte entre familias de cuenta.
  - `0400,0401,0402,0410,0430` → `actual = anterior + creditos − cargos` (35)
  - `0500..0880` → `actual = anterior + cargos − creditos` (120)
  - `0850..0951` → indeterminados (`cargos == creditos`, casi todos 0.00) (68)
- **La regla que se implementa NO es la agrupación por prefijo.** Se midió
  también que `saldo_mes = cargos − creditos` en **224 de 224**, sin
  depender de la naturaleza. De ahí la naturaleza se deriva por renglón:
  ```
  actual == anterior + saldo_mes  -> deudora
  actual == anterior - saldo_mes  -> acreedora
  cargos == creditos              -> indeterminado (hereda del padre)
  ```
  Esto se transfiere a documentos nuevos; «04xx es acreedora» es
  conocimiento de este catálogo y no se transfiere.
- Lo medido es que la identidad se invierte entre familias, **no** el
  nombre contable de cada familia. Eso sigue siendo convención y lo debe
  confirmar un contador.
- **Columna `N` = ACUM/DETA: confirmado**, correlación 224/224. ACUM (24
  renglones) son exactamente los que tienen hijas; DETA (200) ninguno.
  No marca nivel: ACUM aparece en niveles 0, 1 y 2. 21 de 24 cuentas ACUM
  son la suma exacta de sus hijas directas (las 3 restantes trazan a
  errores del extractor, no del documento).
  **Las filas ACUM son subtotales**: sumarlas junto con las DETA cuenta
  doble. Aquí el documento lo declara explícitamente, a diferencia de la
  balanza original donde había que inferirlo del número de cuenta.

**Regla general que sale de esto: preferir el marcador explícito cuando
exista, derivarlo cuando no.** `es_acumulativa` pasa a ser campo del
contrato `FilaBalanza`, porque de él depende contra qué suma cuadran los
totales.

**La geometría sola no puede separar las columnas de este documento.** La
descripción se encima físicamente sobre las columnas numéricas en 142 de
224 renglones, y `extract_words` pega glifos de corridas de texto distintas
(`A4N1,608,185.15` = descripción `AN` intercalada con `41,608,185.15`).
`region+detect` reporta 5 columnas cuando el documento tiene 8. Requiere un
extractor **a nivel de carácter**, que corte por corrida del content stream
y valide contra el ancla derecha. Medido: ventanas-x sola 224/225,
corridas sola 213/225, ambas combinadas 224/225. Las dos fallas son
ortogonales.

**Diario General**
- Bloques por póliza cerrados con `TOTAL POLIZA:`.
- Columnas: POLIZA / CUENTA / DESCRIPCION / CONCEPTO / CARGOS / ABONOS.
- La columna DESCRIPCION **se ve recortada visualmente**. Averiguar si el
  texto completo sigue en el PDF o se perdió al generarlo.

**Auxiliar GUME**
- Cuentas `1110-000-000`. Filas `Total de CARGOS, ABONOS Y SALDO`
  intercaladas entre secciones. Columna `Tipo` con `Eg`/`Ig`.
- Bloques anidados, más complejos que el auxiliar original.

**Libro Mayor GUME** (tipo nuevo)
- Bloques: `cuenta + nombre` → `Inicial <monto>` → encabezado → 12 filas
  (ENERO..DICIEMBRE). Varios bloques por página.
- **Las secciones se parten entre páginas**: la pág 2 arranca con `Inicial`
  sin número de cuenta, porque quedó en el último renglón de la pág 1
  (y=718.7). Hay que arrastrar la identidad de la cuenta a través del salto
  de página. Ningún otro documento tiene esto.
- **Encabezado agrupado**: `Acumulados` está en su propio renglón (y=119.4,
  x=481) y abarca dos columnas del renglón de abajo. `headers.py` no lo
  maneja.
- 6 columnas: Periodo, Cargos, Abonos, Saldo, Acum-Cargos, Acum-Abonos.
- `lines=0, rects=323`: usa rectángulos, no líneas. Otra estrategia de borde.
- Checksum verificado con datos reales:
  ```
  saldo[mes]       = saldo[mes-1] + cargos - abonos   (saldo[0] = Inicial)
  acum_cargos[mes] = acum_cargos[mes-1] + cargos
  ```

**Conteos medidos con `find_table_region` + `detect`** (vs. el dumper):

| Documento | Páginas | Dumper | region+detect | Real |
|---|---|---|---|---|
| balanza-businesspro | 1, 2, 4 | 5, 6, 5 | 5, 6, 5 | **8** |
| diario-general | 1, 2, 200 | 4, 4, 3 | 6, 6, 4 | |
| auxiliar-gume | 1, 2, 400 | 4, 5, 5 | 7, 6, 7 | |
| mayor-gume | 1, 2, 17 | 4, 4, 6 | **6, 6, 6** | 6 |

Business Pro es el caso donde ni la región salva la detección: ahí el
problema no son las secciones sino el texto encimado (ver arriba).

**Los conteos de columnas del dumper no son fiables en documentos con
secciones.** El Libro Mayor reporta 4 en pág 1-2 y 6 en la 17: los nombres
largos de cuenta se extienden sobre las columnas numéricas y encadenan la
fusión (x=148 a x=301). La medición válida viene de `find_table_region` +
`detect`, no del dumper.

### Principio: nunca reportar un resultado sin su cobertura

Medido sobre `balanza-gume`: el parser reportó `734 filas, 0 discrepancias`
cuando en realidad **casi ninguna regla llegó a correr** (jerarquía perdida
por falta de guiones, fila de totales no detectada, partida doble pasando
trivialmente por doble conteo simétrico, checksum por renglón cumpliéndose
de gracia en 687 filas en ceros).

Un `0 discrepancias` sin cobertura es el peor resultado posible: un Excel
con cara de validado que nadie comprobó.

**Tres estados por regla, no dos:**

| Estado | Significado | Acción |
|---|---|---|
| `cuadra` | La regla corrió y pasó | Entrega |
| `falla` | La regla corrió y no pasó | No entrega limpio (§1.3) |
| `no_verificable` | La regla no pudo correr | Entrega **con cobertura visible** |

Toda salida incluye la cobertura: «4 reglas, 1 corrió, 3 no comprobables».
Y distingue «cuadró exacto» de «cuadró dentro de tolerancia»: cuando la
tolerancia de ±0.01 se consume, hay que decirlo.

**Caso aparte: la orientación debe/haber.** No es solo no verificable, es
*consecuente*: si estuviera invertida, la naturaleza pasa de D=725/A=9 a
D=9/A=725 — un Excel incorrecto, no incompleto. Medido en `balanza-gume`:
solo 45 de 734 renglones tienen `debe != haber`, y al invertir el mapeo los
45 siguen cuadrando porque la naturaleza derivada se invierte con ellos. La
fila de totales tampoco orienta (Debe = Haber). Lo único que orienta es el
vocabulario del encabezado.

Por eso cada mapeo registra **sobre qué se apoya**: `verificado_por:
aritmetica` o `verificado_por: vocabulario`. Un mapeo aceptado solo por
vocabulario es el que el asistente de la fase 4 hace confirmar al humano una
vez; la plantilla guarda esa confirmación y las cargas siguientes del mismo
formato ya no preguntan.

### Principio: la aritmética manda sobre el vocabulario

Un diccionario de sinónimos de encabezado (`CARGOS`↔Debe,
`CREDITOS`/`ABONOS`↔Haber, `SALDO ANTERIOR`↔Saldo Inicial) sirve como
**pista**, nunca como fuente de verdad.

El flujo correcto es: proponer el mapeo por vocabulario → **verificarlo con
el checksum del documento** → aceptarlo solo si la aritmética cuadra. Si no
cuadra, el mapeo está mal: avisar, no entregar.

Esto es lo que hace seguro el aprendizaje de formatos nuevos (fase 4): una
plantilla solo se guarda si su aritmética cuadró.

**La plantilla guarda también qué extractor usar.** Business Pro demostró
que el extractor no es una constante del sistema: hay documentos donde
`extract_words` no alcanza y hace falta extracción a nivel de carácter. La
estrategia de extracción es parte de lo que se aprende por formato, junto
con el mapeo de columnas y las reglas de validación.

**Las reglas de validación contable deben ser confirmadas por un contador
antes de darse por buenas.** Medir que cuadran no prueba que signifiquen lo
correcto, y estos documentos tienen uso fiscal.

### Anonimización

`scripts/dump_layout.py` produce los fixtures enmascarados. Requiere
`CONTAPDF_SALT` en el entorno (vive en `~/.bashrc`, **fuera del repo**).
Trae auditoría automática: si un token conserva dígitos reales, escribe un
`.LEAKS.txt` y avisa. **No commitear fixtures con fugas pendientes.**

Cuentas contables (`101-01`) se conservan legibles a propósito: son
estructurales, no PII. RFC, UUID y CLABE se reemplazan por pseudónimos
estables con sal, para poder probar cruces entre documentos.

---

## 3. Estructura del repo

```
cp-pdf/
├── src/contapdf/
│   ├── ir.py                  # Word, Line, Document, ColumnSpec
│   ├── extract/
│   │   ├── pdf_text.py        # pdfplumber -> IR (generador por pagina)
│   │   └── ocr.py             # (fase 6)
│   ├── layout/
│   │   ├── lines.py           # words -> lines por solapamiento vertical
│   │   ├── columns.py         # clustering x1 (montos) / x0 (texto)
│   │   ├── region.py          # acota el analisis a la zona de tabla
│   │   └── headers.py         # etiqueta columnas (encabezados multilinea)
│   ├── parsers/
│   │   ├── base.py
│   │   ├── balanza.py
│   │   ├── auxiliar.py
│   │   ├── polizas.py
│   │   └── estado_cuenta.py
│   ├── templates/
│   │   ├── fingerprint.py     # huella del formato (ligada al tenant)
│   │   └── store.py
│   ├── validate/rules.py
│   └── export/excel.py
├── tests/
├── fixtures/
│   ├── layouts/               # JSON enmascarados — SI se versionan
│   ├── synthetic/             # PDFs sinteticos — SI se versionan
│   ├── real/                  # PDFs reales — GITIGNORED
│   │   ├── 1-Balanza/
│   │   ├── 2-Libro-Diario/
│   │   ├── 3-Auxiliares/
│   │   └── 4-Estados-Cuenta/
│   └── golden/                # CSV esperado por fixture
├── scripts/
│   ├── dump_layout.py         # herramienta de anonimizacion — NO tocar
│   └── dump_all.sh
└── PLAN.md
```

`.gitignore` incluye `fixtures/real/` desde el primer commit.

---

## 4. Fases

| # | Fase | Entregable | Estado |
|---|---|---|---|
| 0 | Reconocimiento | layouts enmascarados + auditoría | **hecho** |
| 1 | IR + layout | `ir.py`, `pdf_text.py`, `lines.py`, `columns.py`, `region.py` | **hecho** (71 tests) |
| 2 | Balanza E2E | parser balanza + validación + Excel | **hecho** (153 tests) |
| 3 | Balanza variante | Generalizar balanza a «Business Pro»: sinónimos de encabezado + validación que varía por formato | siguiente |
| 3b | Auxiliar | Parser con arrastre de sección y bloques | |
| 4a | Cobertura de validación | Tres estados por regla, `verificado_por`, jerarquía y totales parametrizados por formato | siguiente |
| 4b | Plantillas | Fingerprint + store + asistente de mapeo, ligado al tenant | |
| 5 | Pólizas | Parser de bloques usando las líneas del PDF | |
| 6 | OCR | `ocr.py` + preprocesado | |
| 7 | Estado de cuenta | Multilínea + variación por banco | |
| 7b | Libro Mayor | Bloques con sección partida entre páginas + encabezado agrupado | |
| 8 | Capa web | Upload + cola + worker + aislamiento por tenant | |

La fase 3 es la balanza variante y no el auxiliar **a propósito**:
generalizar un parser que ya funciona para cubrir una segunda variante real
del mismo tipo es la forma más barata de descubrir qué debe abstraer el
sistema de plantillas. Ir al auxiliar cambiaría dos variables a la vez
(esquema de salida nuevo y layout nuevo) y se aprende menos.

**No construir la fase 4 antes de la 3.** Abstraer el sistema de plantillas
con un solo parser de referencia garantiza rediseño.

---

## 5. Cómo orquestar Claude Code

Una sesión por fase. El prompt siempre lleva: contexto, objetivo, contrato,
fixtures, criterios de aceptación verificables, y restricciones.

La restricción que más ahorra: *"si el fixture no alcanza para decidir algo,
PREGUNTA en vez de asumir"*. Sin ella, se inventa un caso de borde plausible
y lo descubres tres fases después.

Dos cosas que no debe tocar Claude Code:

- `scripts/dump_layout.py` — ya cumplió su función y es la herramienta de
  privacidad. Si se refactoriza y se rompe el enmascarado, se nota tarde.
- Los números de la sección 2 — son mediciones, no metas ajustables.

### Prompt de la fase 1

```
CONTEXTO
  Proyecto nuevo en Python para convertir PDFs contables a Excel.
  Lee PLAN.md secciones 0, 1 y 2 antes de escribir codigo.
  Hay fixtures enmascarados en fixtures/layouts/*.layout.json con la
  estructura real de 4 tipos de documento. Los montos son 9s y los
  nombres X: la ESTRUCTURA y las COORDENADAS son reales.

OBJETIVO
  src/contapdf/ir.py               -> Word, Line, Document, ColumnSpec
  src/contapdf/extract/pdf_text.py -> extract(path) -> Iterator[Page]
  src/contapdf/layout/lines.py     -> group(words, tol) -> list[Line]
  src/contapdf/layout/columns.py   -> detect(lines) -> list[ColumnSpec]
  src/contapdf/layout/region.py    -> find_table_region(lines) -> (top, bottom)

CONTRATOS
  Los dataclasses de PLAN.md 1.1, literales.
  Respeta las dos reglas de PLAN.md 1.1 (solapamiento vertical para
  renglones; x1 para montos, x0 para texto).
  scripts/dump_layout.py sirve de referencia: ahi ya estan resueltos el
  agrupamiento y el clustering, pero de forma monolitica y con estado
  global. NO lo copies tal cual ni lo modifiques.

CRITERIOS DE ACEPTACION
  1. balanza paginas 1 y 2 -> 9 columnas
  2. edocta pagina 2       -> 5 columnas
  3. auxiliar pagina 1     -> 6 columnas
  4. edocta pagina 1: find_table_region acota a la zona de movimientos
     (abajo de 'DETALLE DE OPERACIONES') y ahi detecta >= 4 columnas,
     no 1 como sale al analizar la pagina completa
  5. En polizas, la etiqueta '401-01 ...' y sus dos importes quedan
     en UN solo Line
  6. pytest tests/ pasa

RESTRICCIONES
  - Aplica las restricciones de arquitectura de PLAN.md seccion 0.
  - Escribe los tests PRIMERO y muestrame que fallan antes de implementar.
  - Solo pdfplumber como dependencia nueva.
  - snake_case, type hints en firmas publicas.
  - Comentarios solo donde el POR QUE no sea obvio.
  - Si un fixture no alcanza para decidir algo, PREGUNTA en vez de asumir.
```

---

## 5.1 Deuda técnica conocida

Registrada a propósito, con la fase en que toca resolverla.

- **`headers.py` fusiona `'FOLIO FECHA'` en el auxiliar.** En esas páginas
  FOLIO no trae datos, así que no genera columna propia y su etiqueta cae
  en la vecina. Es una lectura honesta del documento, pero el parser de la
  fase 3 necesita `folio` y `fecha` separados. **Resolver en fase 3.**
- **`pitch_factor=1.3` en `headers.py`** distingue una etiqueta partida en
  dos renglones de un título de sección, midiendo si el interlineado es
  más apretado que el de los datos. Está afinado sobre cuatro documentos.
  Debe seguir siendo parámetro configurable, nunca constante enterrada.
- **`headers.py` no maneja encabezados agrupados** (`Acumulados` abarcando
  dos columnas, en el Libro Mayor). **Resolver en fase 7b.**
- **La jerarquía necesita el ancho de segmento por nivel** (6/9/12 en
  GUME, guiones en los otros). Es parámetro del formato. **Fase 4a.**
- **La detección de la fila de totales no puede depender de que la etiqueta
  esté al inicio de la celda de nombre.** En GUME el renglón es
  `734 | Cuentas reportadas | Totales: | ...` y nunca se detectó. **Fase 4a.**
- **Dinero siempre en `Decimal`, nunca `float`.** Verificado por test AST.
  Aplica a todo parser nuevo.

---

## 6. Pendiente de infraestructura

Sin resolver, bloquea la fase 8. Conviene ir cerrándolo en paralelo:

- ¿Qué es la máquina servidor? SO, y si hay acceso root para instalar
  Python, Tesseract y un servicio en segundo plano.
- Hosting compartido con panel **no sirve** para esto: hace falta ejecución
  de Python, binarios de OCR y procesos largos con cola de trabajos.
- Límite de trabajos concurrentes, o varios usuarios subiendo a la vez
  tiran el servidor.