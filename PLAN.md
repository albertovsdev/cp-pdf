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
    run: int = 0        # corrida del content stream

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

`run` identifica la corrida del content stream. Se agregó en la fase 5 y es
una corrección de la fase 1: `_iter_pages` ordenaba por `x` al final y
volvía a intercalar corridas que `pdf_chars` sí había separado. **Sin `run`,
ninguna columna sobreimpresa es legible en ningún documento.** `pdf_text`
lo deja en 0; solo `pdf_chars` lo llena.

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
`saldo_fin_deudor`, `saldo_fin_acreedor`, `es_acumulativa`

`nivel` y `cuenta_padre` se derivan del número de cuenta, no vienen del PDF.

`BalanzaParser.parse()` devuelve un objeto `Balanza` con `.filas` y
`.totales`, no una lista. La fila «Totales» no cabe en una `FilaBalanza`
(no tiene cuenta ni naturaleza) y el validador la necesita. `Balanza` es
iterable, así que `list(parse(doc))` sí entrega `list[FilaBalanza]`.

**Libro diario / pólizas** — tres tablas relacionadas, NO una tabla plana:

```
polizas(poliza_id, tipo, naturaleza, fecha, descripcion, folio,
        total_debe, total_haber, completa)
movimientos(poliza_id, orden, cuenta, nombre_cuenta, debe, haber)
cfdi(poliza_id, fecha, documento, uuid, rfc, tipo)
```

**`poliza_id` es una clave de unión, NO un identificador de la póliza.**
Ninguna de las variantes imprime un identificador único, así que se usa un
consecutivo (`P00001…`) determinista dentro de una extracción. Cambia según
el rango de páginas que se lea: la misma póliza sale con otro número si se
procesa el documento completo o solo unas páginas. Sirve para unir las tres
tablas y para nada más; quien compare dos corridas o deduplique debe usar
los campos propios del documento (tipo, fecha, descripción/folio), que se
exportan en las hojas.

`completa` marca las pólizas que no cerraron dentro de lo leído: se excluyen
de la partida doble y la cobertura lo declara. No se valida lo que no se
leyó entero.

**Verificación de la asociación CFDI→póliza.** Que cada póliza reciba un
CFDI no prueba que sea el suyo: ocho cruzados dan el mismo conteo 8/8. La
comprobación con datos existe — el `documento` del CFDI trae el mismo
número que la `descripcion` de la póliza (`18243`) — y debe ser una regla
de validación con su cobertura, no una verificación por posición.

Al Excel salen como 3 hojas + una hoja plana denormalizada (encabezado
repetido en cada movimiento), que es la que el contador va a filtrar.

**Auxiliar de cuentas** — tabla con la cuenta arrastrada desde el
encabezado de sección:

`cuenta`, `nombre_cuenta`, `saldo_inicial_cuenta`, `folio`, `fecha`,
`tipo_movimiento`, `documento`, `tercero`, `concepto`, `debe`, `haber`,
`saldo`

`concepto` es texto crudo, para fuentes que no separan referencia y
contraparte (GUME imprime `PAGO F-6287 DESARROLLO HUMANO PROFESIONAL AMT
SA DE CV` en una sola columna). Cuando la fuente no los separa,
`documento` y `tercero` van vacíos: no se fabrica una división que la
fuente no da. `saldo` puede ser `None` si el documento no lo trae legible.

**Libro Mayor** — dos tablas relacionadas:

```
mayor_cuentas(cuenta, nombre_cuenta, naturaleza, saldo_inicial,
              saldo_final, total_cargos, total_abonos, pagina_inicio)
mayor_meses(cuenta, orden, periodo, cargos, abonos, saldo,
            acum_cargos, acum_abonos, pagina)
```

La unidad natural es la cuenta-año, no el mes: aplanarlo repetiría
`saldo_inicial` doce veces. `orden` (1..12) va explícito para no depender
de parsear nombres de mes. `saldo_final` y los totales se **leen** del
último mes —el documento ya imprime acumulados— y el checksum los verifica.
Al Excel: Cuentas | Meses | Plana | Validación, igual que pólizas.

Que las dos tablas estén relacionadas hace verificable el corte entre
páginas: «ninguna fila huérfana» se vuelve el invariante «todo mes apunta a
una cuenta existente».

**Estado de cuenta** — metadata + movimientos.

Hallazgos medidos (fase 7, AFIRME):
- El nombre del banco va **bajo el sello digital, sobreimpreso**, y sale
  entrelazado con el domicilio. Se separa por `run` (fase 5).
- **Las anclas de importe salen del encabezado, no de la posición.** Los
  símbolos `$` forman columnas propias; tomar «las tres más a la derecha»
  metía el retiro en la casilla de depósito.
- **La continuación se pega sin separador**: el documento envuelve
  partiendo palabras (`CON`+`CEPTO:`, `DESTINATARIO:HIL`+`ARIO`).
  Concatenar con espacio produce `CON CEPTO:`.
- Regla añadida: `resumen_movimientos`, que cuadra los totales declarados
  contra los movimientos leídos. El resumen puede cuadrar consigo mismo y
  faltar media tabla; esto prueba que se leyeron todos.

**Variantes medidas (3 documentos nuevos, fase 7 tardía):**

- **Santander (abril)**: glifos duplicados (caso 5 arriba). Página 2 con
  `lines=105` — primer estado de cuenta con líneas de tabla reales.
- **Banorte (anual)**: **la fecha va pegada a la descripción sin
  separador** (`99-XXX-99XXXXX` = `01-JUL-25DEPOSITO`). Hay que partir por
  patrón de fecha. Vocabulario propio: `MONTO DEL DEPÓSITO` / `MONTO DEL
  RETIRO` contra `Depósitos` / `Retiros` de AFIRME.
- **Banorte (julio)**: **DOS cuentas en un mismo estado**, con bloque
  RESUMEN que las lista y una fila TOTAL. Rompe el contrato de §1.2, que
  asume una sola cuenta: `meta` debe volverse una lista y cada movimiento
  saber a cuál pertenece.
- **Los dos Banorte son distintos entre sí**: el anual arranca directo en
  `DETALLE DE MOVIMIENTOS`, el de julio trae el resumen multi-cuenta antes.
  **El eje de la plantilla no es el banco, es (banco, tipo de reporte).**
- Continuaciones más pesadas que AFIRME: cada movimiento de Banorte
  arrastra 4–5 líneas con CLABE, RFC, CONCEPTO, REFERENCIA e IVA — más
  líneas de continuación que de movimiento.

**Segunda tanda de fixtures (15 documentos, 5 empresas, 9 bancos).**
Hallazgos que aplican a todo el sistema, no solo a estados de cuenta:

- **Duplicación de tokens generalizada** (ver caso 5 arriba). Afecta a
  balanza, auxiliar, pólizas y mayor de «manufacturas», más Santander.
  La fase 7c deja de ser un arreglo de un banco y pasa a ser requisito de
  extracción para 5 documentos de 2 empresas.
- **Encabezados agrupados fuera del Libro Mayor**: `balanza-fd` tiene
  `SaldoAnterior` abarcando `Deudor`/`Acreedor`, y `SaldoActual` igual. Lo
  que resuelva la fase 7b sirve aquí.
- **Cuentas con punto como separador**: Proactivity usa `101.01.01`.
  `RE_CUENTA` no las reconoce, se enmascaran como montos y la columna de
  cuenta desaparece. Afecta al dumper y al parser.
- **Cuentas de 4 grupos**: `balanza-fd` usa `000-000-100-000`.
- **Páginas apaisadas**: Monex es 792×612 y Proactivity llega a x=818.
  Nada asume tamaño de página, pero falta un test que lo fije.
- **`$` como columna propia** (Proactivity, Banorte julio): ya resuelto en
  AFIRME tomando anclas del encabezado, no de la posición.
- **Inbursa página 2 detecta 6 columnas limpias**
  (`FECHA | REFERENCIA | CONCEPTO | CARGO | ABONO | SALDO`): es el estado
  de cuenta mejor estructurado de los nueve.

**Declarado sin cubrir** (una sola muestra, AFIRME): otro banco puede
nombrar distinto el resumen, la tabla y el bloque de identificación; el
pegado sin separador está medido en este formato y un banco que envuelva
por palabra saldría con las palabras pegadas; la fecha se deriva del
período y solo cuando no cruza de mes.
**Antes de poner esto en producción hacen falta muestras de otros bancos.**

Contrato:

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
  marcador de nivel** (001/002/003). El ancho de prefijo por nivel se
  **deriva de los datos** (última posición con dígito distinto de cero),
  no se fija por tamaño de grupo: sale 4/7/10 y reconstruye las 734 sin
  huérfanas.
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
- Checksum, **corregido tras medirlo sobre las 49 cuentas**:
  ```
  acum_cargos[mes] = acum_cargos[mes-1] + cargos          (siempre)
  saldo[mes]       = saldo[mes-1] ± (cargos - abonos)      (según naturaleza)
  ```
  La verificación original a mano usó BANCOS, una cuenta deudora, y se
  generalizó de más. Medido: 34 de 49 cuentas siguen `+ cargos − abonos`;
  las otras 11 —todas pasivo 2xxx más 1360— encadenan con el signo
  invertido. Cablear una sola identidad producía 87 fallas en 12 cuentas.
  La naturaleza se deriva por cuenta de sus doce meses: 12 D, 12 A, 25 sin
  determinar (meses con `cargos == abonos`, donde ambas identidades
  coinciden).

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

### Hallazgo: la capa de texto puede estar incompleta

Medido en `auxiliar-gume`: la página 3 imprime el saldo como `-` sin
dígitos y la página 4 lo corta (`1,892,606.3`). Verificado a nivel de
carácter con pdfplumber: **los caracteres no están en el archivo.**

Rompe la clasificación binaria que traíamos desde la fase 0. Hay tres
casos, no dos:

1. Texto nativo completo → `pdf_text` / `pdf_chars`
2. Sin capa de texto (escaneo) → OCR
3. **Texto nativo mutilado**, en dos subcasos que se distinguen midiendo
   la tinta del render:
   - **3a — texto perdido, tinta presente**: el OCR sí lo recupera. Es el
     caso para el que existe ese carril.
   - **3b — tinta nunca dibujada**: el documento está defectuoso. Medido en
     `auxiliar-gume`: una celda ilegible tiene **24 píxeles** (solo el
     signo `-`) contra 1,153–2,619 en una legible. A 400 DPI el resultado
     no mejora. **Ningún OCR —local, neuronal o en nube— recupera tinta
     que no existe**; pedir aprobación de nube por privacidad aquí no
     serviría de nada.
6. **Texto en CID sin mapa ToUnicode** → el extractor devuelve
   `(cid:123)(cid:45)…` porque el PDF no trae la tabla que traduce glifos a
   letras. Medido en Inbursa y Multiva. **Es un subcaso de 3a: la tinta sí
   está dibujada**, así que el reintento por OCR debe recuperarlo — a
   diferencia del 3b de GUME, aquí sí va a funcionar.
5. **Glifos duplicados** → el documento dibuja el mismo contenido varias
   veces. **No es un caso aislado**: medido en Santander (×2, con
   desplazamiento) y en toda la familia «manufacturas» (×5 en balanza,
   pólizas y mayor; **×25** en el auxiliar, en coordenadas idénticas).
   La duplicación ahoga el clustering: `polizas-manufacturas` y
   `mayor-manufacturas` detectan **1 sola columna**. Medido en Santander:
   `999999,,999999..9999` es `999,999.99` y `9999--XXXXXX--99999999` es
   `99-XXX-9999`. El mismo documento trae filas sin duplicar
   (`[32-77]99-XXX-9999`), lo que confirma la lectura. **Sin deduplicar, no
   se lee ningún monto de Santander.** Se detecta por caracteres de
   contenido idéntico en coordenadas casi idénticas.
4. **Texto sobreimpreso** → sí es recuperable, pero solo separando por
   corrida del content stream. En `diario-general` el CONCEPTO se dibuja
   encima de la cola de la DESCRIPCION. Se distingue del caso 3 por
   medición: palabras que se pisan en `x` dentro del renglón — 0.219 en
   `diario-general` contra 0.000 en los otros seis documentos.

**El detector del caso 3 es la aritmética**: un saldo corrido que se rompe
sin explicación es la señal de reintentar esa página por otra vía. Esto
convierte a la validación en el disparador del OCR, no solo en su control
de calidad. **Consecuencia para la fase 6: el OCR no es solo para
escaneos.**

Escala medida en `auxiliar-gume`: **2,509 de 7,762 movimientos (32%) no
traen saldo legible** en una sección de 118 páginas. El subtotal declarado
cuadra exacto porque debe y haber sí son legibles; lo que queda sin cubrir
es la cadena del saldo corrido, verificada solo en el 68% restante.

Regla: un dato ilegible queda en `None`, la cadena se corta ahí, y la
cobertura lo declara. Nunca descartar el renglón completo (pierde el
movimiento) ni aceptar una lectura mal formada — el OCR devuelve
`1,025,814.4` con un solo decimal en esas celdas, y **un monto truncado que
parece válido es peor que una celda vacía**: la celda vacía se ve, el
número equivocado no.

**Excepción medida: el saldo corrido sí se puede recalcular, con ancla.**
No es inferencia sino derivación verificable, y solo aplica si se cumplen
las tres condiciones, comprobadas y no supuestas:

1. el saldo inicial de la sección es legible,
2. todos los `debe`/`haber` de la cadena son legibles,
3. el encadenamiento recalculado coincide **exacto** con el subtotal
   declarado del documento.

En `auxiliar-gume` está medido, y el resultado es más fuerte que la
condición: los 7,762 movimientos suman `277,632,036.19 / 277,575,967.07`,
idénticos al subtotal impreso, el encadenamiento aterriza en el saldo
declarado (`92,100.11`), y **los 5,253 saldos que el documento sí imprime
coinciden con el recálculo, 5,253 de 5,253, sin una discrepancia**. Los
2,509 derivados salen del mismo mecanismo que acertó 5,253 veces contra
dato impreso. Resultado: `5,253 impresos, 2,509 recalculados, 0 sin saldo`.

Si alguna condición falla, el saldo se queda en `None`. **Nunca recalcular
en silencio**: `saldo_origen: impreso | recalculado` y línea de cobertura
(«saldo: 176 impresos, 74 recalculados y verificados contra el subtotal
declarado»). El contador debe poder distinguir lo que el documento imprimió
de lo que nosotros derivamos.

El recálculo hace utilizable la entrega, no arregla el origen: **hay que
pedirle al cliente el archivo regenerado**. El defecto se midió en 118
páginas de un documento de 886 y probablemente afecte a todo el archivo y a
otros reportes del mismo sistema.

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

Corrección medida en fase 4a: invertir el mapeo cambia **96 filas**, no 725
(45 que la aritmética determina + 51 que heredan). La cifra anterior salía
de una medición hecha con la jerarquía perdida.

**Lo mismo aplica a los valores del resultado, no solo a las reglas.**
`naturaleza` tiene cuatro procedencias: explícita (el documento la declara,
como la columna `Naturaleza` de la balanza original), derivada (aritmética),
heredada (de un ancestro determinado) y sin determinar. En GUME 626 de 734
no tienen nada que las sostenga.
- En el Excel, `naturaleza` va **vacía** cuando no está determinada. Un `D`
  por default es indistinguible de uno fundamentado: la misma mentira que
  el `0 discrepancias`.
- La cobertura lo reporta. Cifras **medidas** (fase 4b), no de ejemplo:

  | Documento | explícitas | derivadas | heredadas | sin determinar |
  |---|---|---|---|---|
  | balanza | 475 | 0 | 0 | 0 |
  | businesspro | 0 | 157 | 35 | 33 |
  | GUME | 0 | 45 | 51 | 638 |
- La procedencia se guarda en el dataclass pero **no se exporta**: duplica
  el ancho de la hoja y el contador la ignora. La fase 4b la necesita para
  decidir qué confirma el humano.

Por eso cada mapeo registra **sobre qué se apoya**: `verificado_por:
aritmetica` o `verificado_por: vocabulario`. Un mapeo aceptado solo por
vocabulario es el que el asistente de la fase 4 hace confirmar al humano una
vez; la plantilla guarda esa confirmación y las cargas siguientes del mismo
formato ya no preguntan.

### Principio: toda identidad de saldo depende de la naturaleza

Ocurrió tres veces, siempre igual: se verifica a mano una identidad de
saldo corrido sobre una cuenta, se generaliza, y falla en las cuentas de
naturaleza contraria.

- Balanza Business Pro: `actual = anterior + creditos − cargos` en las 35
  acreedoras, invertido en las 120 deudoras.
- Balanza GUME: la orientación debe/haber no es verificable por aritmética
  porque al invertirla la naturaleza derivada se invierte también.
- Libro Mayor: 34 de 49 cuentas siguen una identidad, 11 la contraria.

**Regla: nunca fijar el signo de una identidad de saldo. Derivar la
naturaleza por renglón o por cuenta, y dejar sin determinar lo que no se
pueda derivar.** Una verificación manual sobre una cuenta es evidencia de
que la identidad existe, no de que valga para todas.

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

### Resultados de la fase 7c (extracción transversal)

- **Deduplicación**: multiplicador medido, no listado. `manufacturas` ×5
  (balanza, pólizas, mayor) y **×25** (auxiliar); `edocta` y
  `edocta-santander` ×2 en tokens del sello digital. Criterio: mismo texto
  + misma coordenada (0.1pt) + mismo renglón. Dos renglones con `0.00` en
  la misma columna difieren en `top`, así que no se tocan.
  Columnas antes → después: mayor-manufacturas 8→6 (igual que mayor-gume),
  auxiliar-manufacturas 11→7 (igual que el auxiliar original),
  balanza-manufacturas 13→6, polizas-manufacturas 10→11 (**sin defender**:
  el documento tiene 494 páginas y las primeras son pólizas en ceros; el
  número correcto lo fijará el parser de la fase 5).
- **CID → OCR**: recupera Inbursa 7/20 y Multiva 1/5 (35% y 20%). Confirma
  cualitativamente que es caso 3a —hay tinta, a diferencia del 0/74 de
  GUME— pero la tasa es baja. El volumen es chico (0.8% y 0.5% del
  documento) y en Inbursa caen dentro de la región de tabla, así que sí
  importan.
- **Fecha pegada (Banorte)**: `03-JUL-23085901901344318433` es ambiguo (el
  año puede ser `23` o `2308`). **El ancho del año se aprende de los
  tokens donde sí es inequívoco** — los pegados a letras, donde los dígitos
  terminan donde empieza el texto. Banorte no imprime ni una fecha suelta,
  así que son la única fuente. Si el documento no da ninguna, no se parte.
- **balanza-fd**: no era detección ni agrupado. La página 3 imprime su
  encabezado dos veces y los tokens repetidos fundían las dos subcolumnas
  de saldo (x1=332 y x1=346). Deduplicando salen las 6. Cada renglón usa
  una de las dos subcolumnas, nunca ambas (272 vs 462 renglones).
- **Cuentas con punto (Proactivity)**: medido, no implementado. `is_amount`
  toma 21 de 21 como monto; el clustering produce 3 columnas falsas y el
  documento sale con 11. **La forma no alcanza**: hay un token de idéntica
  forma en x=547 que es un monto legítimo. Solución aprobada: `is_amount`
  recibe opcionalmente la columna, y un token ambiguo que cae en la columna
  de cuenta se trata como texto. Parámetro aditivo, para no romper a los
  cinco parsers.

### Dos documentos, sin solapamiento

| Archivo | Contiene | Lo mantiene |
|---|---|---|
| `PLAN.md` | Decisiones, mediciones, contratos, principios, el *porqué* | El orquestador, con cada reporte |
| `ARQUITECTURA.md` | Qué existe en código hoy: módulos, firmas públicas, flujo, invariantes | Claude Code, al cerrar cada fase |

**Un hecho, un solo hogar.** `ARQUITECTURA.md` no repite hallazgos ni
justifica decisiones; describe el sistema tal como está. Si los dos se
contradicen, `PLAN.md` manda en el *porqué* y `ARQUITECTURA.md` en el *qué*.

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
| 3 | Balanza variante | Generalizar balanza a «Business Pro»: sinónimos de encabezado + validación que varía por formato | **hecho** (225 tests) |
| 3b | Auxiliar | Parser con arrastre de sección y bloques, contra las DOS variantes | **hecho** (357 tests) |
| 4a | Cobertura de validación | Tres estados por regla, `verificado_por`, jerarquía y totales parametrizados por formato | **hecho** (275 tests) |
| 4b | Plantillas | Fingerprint + store + asistente de mapeo, ligado al tenant | **hecho** (327 tests) |
| 5 | Pólizas | Parser de bloques, contra las DOS variantes (poliza + diario-general) | **hecho** (388 tests) |
| 6 | OCR | `ocr.py` + preprocesado + fallback para texto mutilado | **hecho** (409 tests) |
| 7 | Estado de cuenta | Multilínea + variación por banco | **hecho** (436 tests) |
| 7b | Libro Mayor | Bloques con sección partida entre páginas + encabezado agrupado | **hecho** (460 tests) |
| 7c | Extracción transversal | Deduplicar tokens repetidos, CID → OCR, fecha pegada, encabezado de balanza-fd | **hecho** (508 tests) |
| 7c2 | Cuentas ambiguas + ARQUITECTURA.md | `is_amount` por posición + documento de arquitectura | **hecho** (513 tests) |
| 7d | Generalizar estados de cuenta | Contrato multi-cuenta + los 9 bancos con el mismo parser | siguiente |
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
- **La colocación del saldo sigue apoyada en la convención que se quitó de
  `naturaleza`.** La hipótesis «positivo → deudora» se **midió y se
  descartó**: falla en 56 de 236 renglones determinados (24%). Tanto
  deudoras como acreedoras se imprimen en positivo — en Business Pro, 35 de
  36 acreedoras derivadas tienen saldo positivo, y de los 6 saldos
  negativos 3 son A y 3 son D.
  **El signo no dice la naturaleza de la cuenta; dice que ese saldo va
  contra su naturaleza.** Es propiedad del saldo, no de la cuenta.
  Opción honesta pendiente: cuando la forma es `saldo_con_signo`, exportar
  las columnas con signo **tal como las presenta el documento** y llenar
  deudor/acreedor solo donde la naturaleza está fundamentada.
- **`balanza-fd` detecta 4 columnas pero tiene 6 subetiquetas de
  encabezado agrupado.** Es un problema de detección, no de agrupado.
  **Resolver en fase 7c.**
- **Dinero siempre en `Decimal`, nunca `float`.** Verificado por test AST.
  Aplica a todo parser nuevo.

---

## 6. Infraestructura y despliegue

### Máquina objetivo: SERVIDORSIST

Dell OptiPlex 7010 · Windows 10 Pro 22H2 · i5-3470 (4 núcleos, 2012) ·
8 GB RAM · HDD mecánico 466 GB · Python 3.12.2 · encendida 8:00–21:00.

**Solo red local. Regla fija, sin excepción.** Eso simplifica el diseño:
sin HTTPS público, sin exposición a internet, sin superficie de ataque
externa.

Se descartaron las alternativas: la laptop del desarrollador es más rápida
(i5-1335U, 16 GB) pero solo está disponible cuando él está presente, tiene
45 GB libres y es CPU de 15 W que baja frecuencia en carga sostenida. Un
servicio compartido intermitente entrena a la gente a no usarlo.

### La restricción que manda: coexistencia con producción

SERVIDORSIST **ya corre Apache + MySQL todo el día** con sistemas en
producción (jurídico, fiscalización, conversores CFDI). Los ~4.5 GB
ocupados en reposo son ellos. Un worker que se dispare a 2–3 GB con 3.4 GB
libres hace paginar a Windows contra un disco mecánico y **deja inusable
MySQL**.

**Requisitos previos a la fase 8:**

| Acción | Costo aprox. | Por qué |
|---|---|---|
| RAM 8 → 16 GB DDR3 | $500–800 MXN | **Obligatorio.** Sin esto el worker compite con producción. |
| SSD SATA 500 GB | $600–900 MXN | Recomendado. El HDD es el cuello de botella del OCR y de la paginación. |

El 7010 admite hasta 32 GB, así que hay margen futuro.

### Concurrencia: un worker, cola secuencial

Medido: ~0.1 s por página con capa de texto (balanza de 9 páginas en
0.96 s). Carga esperada: 15 personas × 5 documentos = 75 al día. Procesados
de uno en uno caben de sobra en la ventana de 13 horas.

**No hace falta limitar al personal por política.** La cola es el límite y
es automática: quien sube se forma y ve su turno. Una política que la gente
debe recordar es peor que un mecanismo que no pueden saltarse.

La excepción es el OCR: Tesseract en este CPU anda en 2–5 s/página, así que
un escaneo de 900 páginas puede pasar de una hora. Esos van en carril
aparte, con tiempo estimado visible.

### OCR: sin AVX2

El i5-3470 es Ivy Bridge y **no tiene AVX2** (llegó con Haswell, 2013).
PaddleOCR, Surya y PyTorch reciente lo asumen y fallan con errores
crípticos. **La fase 6 se planea con Tesseract**, que funciona sin AVX2.

Si la calidad de Tesseract no alcanza, la alternativa es OCR en la nube, y
esa decisión tiene implicaciones de privacidad que debe aprobar el cliente
antes de implementarse.

### Puntos abiertos

- **MEDIR ANTES DE LA FASE 8: memoria pico por documento.** Cuatro de los
  cinco parsers hacen `list(document.open_pages())` — solo `BalanzaParser`
  transmite página por página. Eso contradice §0. Con un solo trabajo a la
  vez probablemente aguante, pero hay que medir el pico real del auxiliar
  de 886 páginas contra los ~11 GB que quedarán libres tras la ampliación.
  Si son cientos de MB, se sigue; si son varios GB, el worker deja
  inusable a MySQL y hay que convertir los parsers a streaming primero.
- **El CLI solo expone `balanza` y `confirmar`.** Los otros cuatro parsers
  son alcanzables únicamente por API. La capa web los necesita los cinco.
- **Puerto**: Apache ya ocupa el 80. El servicio Python va en otro puerto o
  detrás de un proxy de Apache. Decidir antes de la fase 8.
- **Apagado diario a las 21:00**: la cola debe persistir en disco y los
  trabajos a medias reanudarse o marcarse como fallidos al arrancar. Nada
  puede vivir solo en memoria.
- **Servicio de Windows**: el worker corre como servicio (NSSM o Programador
  de tareas), no como una ventana de consola que alguien puede cerrar.
- **Respaldo**: un solo disco mecánico de 2012, sin redundancia, con
  documentos contables de varios clientes. Si muere, se pierde todo. Falta
  definir respaldo — es el riesgo más grande del despliegue.
- **Sin antivirus, sin firewall, Windows 10 sin actualizaciones de
  seguridad desde octubre 2025.** La red local acotada lo mitiga bastante,
  pero conviene que el cliente lo conozca por escrito antes de que la
  máquina reciba documentos fiscales de terceros.
- **Espacio libre en disco del servidor**: 331 GB de 466. Suficiente.