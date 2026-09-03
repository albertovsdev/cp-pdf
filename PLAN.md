# cp-pdf — Plan de construcción

Sistema de conversión de PDFs contables a Excel, con mapeo por plantillas y
validación aritmética.

**Regla de oro:** ningún parser se escribe sin un fixture que lo pruebe
primero. Fixture → test que falla → parser → test que pasa.

Estado: **núcleo cerrado, fases 0 a 7h completadas.** Los cinco parsers
existen (balanza, auxiliar, pólizas, estado de cuenta, libro mayor), los
cinco salen a Excel, los cinco tienen comando de CLI, toda regla de
validación declara su denominador, el signo de las identidades de saldo se
deriva por cuenta y las exactas impresas se distinguen de las recalculadas.
711 tests verdes + 15 lentos. Cuatro de los cinco tipos aprenden plantilla;
pólizas sale en 1 por 53 CFDI que el documento no trae, declarados como
falla a propósito.
Siguiente: **fase 8a** (interfaz mínima), luego la **8b** (capa web completa).

> Esta línea se quedó desactualizada desde la fase 2 mientras la tabla de
> §4 sí se mantenía. Actualízala junto con la tabla, no en vez de.

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

**Estado de cuenta** — dos tablas relacionadas + metadata del documento
(contrato de la fase 7d; el anterior asumía una sola cuenta):

```
MetaEstadoCuenta(banco, rfc, periodo_ini, periodo_fin)
CuentaBancaria(num_cuenta, clabe, producto, moneda,
               saldo_inicial, depositos, retiros, saldo_corte)
MovimientoBancario(num_cuenta, dia, fecha, descripcion, referencia,
                   deposito, retiro, saldo, pagina)
EstadoCuenta(meta, cuentas, movimientos, mapeo)
```

Los saldos del resumen son propiedad de la **cuenta**, no del documento:
tenerlos en `meta` es lo que forzaba el singular. Un estado de una cuenta
queda con `cuentas` de longitud 1, sin caso especial.

Checksums **por cuenta**, no por documento. Y una regla más: cuando el
documento imprime una fila `TOTAL` (Banorte julio), `Σ saldos por cuenta ==
TOTAL declarado` es un cruce verificable con datos.

Con 2+ cuentas y sin desglose por cuenta, los saldos van a `None` y la
cobertura lo declara. **No se reparte el total.**

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

**Los 9 bancos, medidos (fase 7d).** De 11 fixtures:

- **Con tabla de movimientos (7 documentos, 6 bancos)**: AFIRME,
  Santander abril, Santander integral, Banorte julio, Bajío, Inbursa, BBVA. Todos comparten la
  misma forma —fecha, descripción, uno de {depósito, retiro}, saldo
  corrido, descripción envuelta, fila nueva marcada por la fecha— que es la
  que ya resuelve `EstadoCuentaParser`.
  Difieren en cuatro ejes absorbibles por vocabulario y anclas:
  vocabulario (`Depósitos/Retiros` vs `Cargos/Abonos` vs una sola columna
  `Depósito-Retiro` en Santander), formato de fecha (`01`, `01-ABR-2025`,
  `01-JUL-23` pegada, `1 SEP`, `JUL. 03`, `05/DIC`), número de columnas de
  fecha (BBVA trae dos: operación y liquidación) y presencia del símbolo
  `$`.
- **Sin tabla de movimientos (3)**: Scotiabank, Monex y Multiva. **No
  fallan: son otro tipo de reporte.** El parser lanza `ReporteNoEsperado`
  —un `LayoutDesconocido` con `clave`, `etiqueta` y `evidencia`— consumible
  por la capa web, no un error genérico. Los tres resultan ser lo mismo y
  el propio resumen lo dice: **depósitos 0.00 y retiros 0.00**, o sea una
  cuenta sin movimientos en el período. La clave es `sin_movimientos`, y no
  se apoya en "no encontré la tabla" sino en lo que el banco declara.

- **CORRECCIÓN (fase 7d): el Santander «inversión a plazo» SÍ trae tabla.**
  La medición anterior se hizo sobre las 3 páginas volcadas al fixture, y el
  documento tiene 10. En la página 2 arranca `DETALLE DE MOVIMIENTOS CUENTA
  DE CHEQUES`. Es un `ESTADO DE CUENTA INTEGRAL` con **cuatro productos**:
  cheques, dinero creciente, inversiones a plazo (con otro encabezado:
  `DÍAS PLAZO`, `TASA`, `SALDO INVERTIDO`) y un **crédito** con `CARGOS /
  ABONOS`. Sale con 3 cuentas y 14 movimientos, la regla del TOTAL cuadra, y
  el saldo corrido **falla en 5 renglones**: los del crédito, donde el saldo
  corre al revés. Se entrega con la falla declarada, que es lo correcto —el
  sistema no modela una cuenta de crédito. **Lección: no medir sobre el
  fixture volcado cuando la pregunta es "¿qué trae el documento?".**
- **Ilegible sin OCR (1)**: HSBC, con **97% de sus palabras en CID**
  (590 de 609). Caso 6 en su forma extrema.

  **MEDIDO (fase 7d): el OCR recupera 565 de 590, o sea 95.8%** —muy por
  encima de Inbursa (35%) y Multiva (20%), y contra el pronóstico de que
  saldría bajo. La diferencia es de qué son los tokens en CID: en Inbursa y
  Multiva son el sello digital, tinta diminuta y decorativa; en HSBC es la
  página entera dibujada a tamaño normal.
  **Y no se queda en la tasa: leído por OCR, HSBC lo procesa el mismo
  parser sin tocar nada.** Su resumen sale completo (7,945.22 + 0.00 −
  2,749.62 = 5,195.60) y los tres movimientos suman exactamente los
  2,749.62 declarados. Confirma el invariante de ARQUITECTURA: un parser
  consume un `Document` venga de donde venga.
  **Falta**: `strategy.extraer()` no enruta a OCR por CID, así que hoy hay
  que pasarle el `Document` de `ocr.extract()` a mano. Cuesta ~21 s por
  documento y es una decisión de la fase 8, no de ésta.

Confirma que el eje de la plantilla es **(banco, tipo de reporte)**: los
dos Santander son el mismo banco con estructuras incomparables, y los dos
Banorte igual.

**Declarado sin cubrir** (después de la fase 7d, con seis formatos
medidos): el vocabulario del encabezado y las etiquetas de saldo son tablas
de sinónimos, y un banco que nombre distinto sus columnas necesita
agregarlos antes de leerse; la unión de continuaciones usa el separador del
formato (ver el hallazgo de abajo); la fecha se deriva del período cuando el
documento solo imprime el día, y solo si el período no cruza de mes; con dos
o más cuentas los depósitos y retiros por cuenta se leen solo si el
documento los desglosa.

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

**Una regla declara sobre cuántos casos pudo correr.** `ResultadoRegla`
lleva `aplicables` además de `comprobaciones`: cuántos casos existían en el
documento y sobre cuántos corrió efectivamente. Un `cuadra` con
`comprobaciones=5, aplicables=116` no es el mismo resultado que uno con
`5/5`, y hasta la fase 7f el sistema no sabía distinguirlos: la tabla de la
7d aprobó BBVA con el saldo corrido verificado en el 4% de la tabla.

`Cobertura.resumen()` imprime siempre las dos cifras. Un `aplicables` que
no se puede determinar es `None` y la regla se reporta `no_verificable`,
nunca `cuadra`. **Un porcentaje sin denominador es la misma mentira que el
`0 discrepancias`.**

`comprobaciones` se renombró a `evaluados`, porque el nombre viejo
significaba dos cosas distintas según la regla: en unas era el universo y en
otras solo lo que corrió. `comprobaciones` sobrevive como propiedad de solo
lectura, deprecada, y se retira en la fase 8.

**Tres decisiones sobre qué entra al universo** (fase 7f). Las tres siguen la
misma regla: ante la duda, el caso entra al denominador. Elegir la
interpretación que sube el porcentaje es como se llegó al `5/5` de BBVA.

- **El renglón que siembra una cadena de saldo es aplicable**, aunque no se
  pueda evaluar. BBVA son 116 movimientos, no 115. Un movimiento que la
  regla no verificó es un movimiento no verificado, sea cual sea el motivo.
- **Una póliza incompleta es aplicable y no evaluada, con motivo.** §1.2 dice
  que la cobertura las declara, y declarar algo exige que esté en el
  denominador; sacarlas lo vuelve invisible.
- **El universo de `jerarquia` son las filas que deberían tener padre**, no
  los pares que se lograron formar. Esta decisión destapó en la 7f cuentas
  padre que ninguna fila del documento contiene —2 en balanza, 1 en business
  pro— invisibles durante nueve fases porque el conteo de pares encogía en
  silencio y la regla se veía cubierta al 100%.

**Lo que `aplicables` NO resuelve: una regla que corre sobre casos vacíos.**
`balanza-gume` reporta `renglon: 734 de 734, 732 exactas` —cobertura
perfecta— y de esas 734 filas **687 están en ceros** y cumplen el checksum de
gracia. La regla corre sobre todo y prueba el 6% del documento. Hace falta
una tercera cifra, casos no triviales, y es una fase aparte. Hasta entonces:
**un 100% de cobertura no significa que el documento esté verificado.**

**Un saldo recalculado no verifica la cadena que lo produjo.** Si el sistema
calculó un saldo encadenando `anterior + debe − haber`, comprobar después
que ese saldo cumple `anterior + debe − haber` es una tautología. En la 7g,
`auxiliar-gume/saldo_corrido` pasó a «47,965 de 47,987 cuadra» y 26,032 de
esas exactas son saldos que el propio sistema generó. La verificación real
de una sección recalculada es **el ancla**: que la cadena aterrice en el
subtotal declarado. Eso es una comprobación por sección, no una por
movimiento.

`ResultadoRegla` separa por tanto `exactas_impresas` de
`exactas_recalculadas`, y `Cobertura.resumen()` las imprime aparte. Un
`cuadra` cuyas exactas sean mayoritariamente recalculadas no significa que
el documento esté verificado.

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

**Muestrear páginas 1 y 2 es insuficiente para estados de cuenta.** La
tabla de movimientos puede empezar después, y un estado integral cambia de
producto a mitad del documento. Muestrear al menos una página del medio, o
la conclusión sobre qué trae el documento será falsa. Se descubrió al
declarar erróneamente que un Santander no tenía tabla de movimientos.

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
   letras. Medido en Inbursa, Multiva y HSBC. **Es un subcaso de 3a: la
   tinta sí está dibujada**, así que el OCR lo recupera — a diferencia del
   3b de GUME.

   **Lo que fija la tasa de recuperación es el TAMAÑO DE LA TINTA, no el
   porcentaje de CID.** Medido:

   | Documento | palabras en CID | recuperadas | qué son |
   |---|---|---|---|
   | Inbursa | 20 (0.8%) | 7 (35%) | sello digital |
   | Multiva | 5 (0.5%) | 1 (20%) | sello digital |
   | HSBC | 590 (97%) | 565 (**95.8%**) | la página entera |

   El sello digital es tinta diminuta y decorativa, y ahí el OCR falla aunque
   la tinta exista; una página dibujada a tamaño normal se recupera casi
   entera. La conclusión práctica: **un documento mayoritariamente en CID es
   un buen candidato a OCR, y unos pocos tokens en CID no lo son** — cuestan
   21 s para recuperar seis tokens decorativos.
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

### Resultados de la fase 7d (generalización de estados de cuenta)

Cobertura medida, documento por documento. Ninguno entrega con una regla en
falla salvo el integral, que la declara:

| Documento | cuentas | movs | resumen | resumen_movs | saldo_corrido | total |
|---|---|---|---|---|---|---|
| AFIRME | 1 | 45 | cuadra | cuadra | 45/45 | no verificable |
| Santander abril | 1 | 110 | cuadra | cuadra | 110/110 | cuadra |
| Banorte julio | 2 | 283 | no verif. | no verif. | 283/283 | **cuadra** |
| Bajío | 1 | 67 | cuadra | cuadra | 65/65 | no verificable |
| Inbursa | 1 | 44 | cuadra | cuadra | 44/44 | no verificable |
| BBVA | 1 | 116 | cuadra | cuadra | 5/5 | no verificable |
| Santander integral | 3 | 14 | no verif. | no verif. | **falla 5** | cuadra |

Los cinco con resumen completo suman **exactamente** lo declarado, sin
tolerancia consumida. BBVA además declara sus propios contadores
(`Depósitos / Abonos (+) 53`, `Retiros / Cargos (-) 63`) y salen 53 y 63.

> **Anotación de la fase 7f: los conteos de `saldo_corrido` de esta tabla
> son numeradores sin denominador.** La columna dice sobre cuántos renglones
> corrió la regla, no sobre cuántos podía correr, y las dos cifras se
> imprimen igual. Medido en 7f, fila por fila:
>
> | Fila de la tabla | dice | aplicables reales | cobertura |
> |---|---|---|---|
> | AFIRME | 45/45 | 45 | 100% |
> | Santander abril | 110/110 | 110 | 100% |
> | Banorte julio | 283/283 | 283 | 100% |
> | Bajío | 65/65 | **67** | 97% |
> | Inbursa | 44/44 | 44 | 100% |
> | **BBVA** | 5/5 | **116** | **4.3%** |
>
> Cuatro de las seis filas son honestas; dos exageran, y una de ellas por un
> factor de 23. BBVA imprime el saldo corrido una sola vez por día, así que
> 111 de sus 116 movimientos no tienen contra qué encadenarse — la regla se
> aprobó habiendo corrido en el 4% de la tabla. **Esta tabla no se puede usar
> como evidencia de cobertura**; la fase 7f agrega `aplicables` para que no
> vuelva a pasar.

**Lo que generaliza no es una rama por banco.** Un test lee el módulo y
prohíbe que nombre a ninguno. Lo que cubre los seis formatos:

- **El encabezado manda, y ancla por el borde derecho.** Los importes se
  alinean a la derecha con su etiqueta en los seis, con desviaciones de 0 a
  30pt, siempre menores que media separación entre columnas. Tomar "las tres
  más a la derecha" mete el retiro en la casilla del depósito.
- **Encabezado agrupado**: `SALDO` arriba abarcando `OPERACIÓN` y
  `LIQUIDACIÓN`. Se consulta el renglón de arriba **solo** cuando la
  subetiqueta no significa nada por sí sola; así `DESCRIPCIÓN DE LA
  OPERACIÓN` no se confunde con un saldo.
- **Seis formatos de fecha** (`03`, `01-ABR-2025`, `01-JUL-23`, `1 SEP`,
  `JUL. 03`, `01/DIC`) normalizados a `dd/mm/aaaa`. El año sale del período
  declarado, que cada banco escribe distinto; alcanza con extraerle el año.
- **Las cuentas son secciones**, reconocidas por cómo abre el renglón y no
  por igualdad: el documento repite el nombre del producto y a veces le pega
  detrás el número de cuenta o la CLABE.

**Tres bugs que la generalización destapó, los tres con checksum que lo
prueba:**

1. **`find_table_region` no sirve para acotar estos documentos.** Deja
   páginas enteras fuera: BBVA página 2 devuelve `None` con 40 movimientos
   impresos, y Bajío pierde las páginas 9-11. La tabla se acota ahora con lo
   que el documento garantiza —los seis **reimprimen el encabezado en cada
   página de tabla**— y una continuación tiene que venir a menos de 12pt del
   renglón anterior (dentro de la tabla van de 2 a 4pt; el pie de página cae
   a 19pt o más).
2. **`extract/tokens.py` aprendía mal el ancho del año.** `\d+` era codicioso,
   así que `11-JUL-2320230711400140BET…` se leía como un año de **dieciséis
   dígitos** y contaminaba lo aprendido para toda la página. Banorte perdía
   6 páginas de 13. La corrida de dígitos tiene que medir 2 o 4.
3. **El signo puede ir detrás, o en su propio token.** La reversa de un
   cargo se imprime `287,000.00-`, y un saldo negativo como `-$ 34,791.58`
   con el `-$` suelto. Sin las dos cosas, Banorte perdía 590,653.00 en
   retiros y Bajío fallaba el saldo corrido en el único renglón negativo del
   documento. `parse_monto` acepta ahora el signo al final; el símbolo y el
   signo sueltos se pegan al importe antes de repartir la fila.

**Lo que NO se pudo decidir con los datos: el separador de continuación.**
Hay documentos que envuelven partiendo palabras a la mitad (`CON` +
`CEPTO:`) y otros que envuelven por palabra entera (`CVE` + `RASTREO:`). Se
midió y **la geometría no los distingue**: en los dos casos el último token
llega al margen y el siguiente arranca en el borde izquierdo de la columna,
y las formas de los tokens son idénticas (`CON`/`CEPTO:` contra
`CON`/`RFC`). Por eso `separador_continuacion` es un **parámetro del
formato**, no una deducción, y su valor por omisión es el medido en el
primer formato de la fase 7 (`""`). Con ese default, cinco de los seis
formatos quedan con las palabras pegadas dentro de la descripción. **No
afecta ningún importe, saldo ni checksum**; solo el texto de la descripción.
**Decisión pendiente del cliente.**

### Resultados de la fase 7e (cierre del núcleo)

**El discriminador del separador de continuación NO existe. Medido.**

La hipótesis era buena: si el corte es por carácter, el renderizador corta
exactamente en el margen y el borde derecho del último token debería ser
idéntico en todas las líneas llenas; si es por palabra, varía hasta el ancho
de una palabra. Se midió sobre las líneas de continuación de cada bloque,
excluyendo la última de cada uno (esa termina donde termina el texto, no en
el margen — sin esa corrección la medición no significa nada).

| Documento | bloques | líneas llenas | desv. de x1 | llegan al margen (≤1 carácter) |
|---|---|---|---|---|
| **AFIRME** (parte palabras) | 13 | 91 | 29.5 | **3%** |
| Santander abril | 63 | 378 | 52.0 | 38% |
| Banorte julio | 158 | 294 | 38.2 | 100% (n=2) |
| Bajío | 56 | 280 | 43.6 | 26% |
| Inbursa | 32 | 95 | 60.7 | 50% (n=2) |
| BBVA | 15 | 43 | 50.7 | 50% (n=6) |

**Sale al revés de lo esperado**: el único documento del que se sabe que
parte palabras es el que PEOR puntúa. La razón, al mirarlo de cerca: el
bloque de continuación de AFIRME no es un párrafo re-fluido contra un
margen, es un **registro de ancho fijo** con campos rellenados a columna
(`CUENTA:…`, `HORA:… DESTINATARIO:…`), y solo se parte el campo que no cabe
entero. La mayoría de sus líneas terminan donde termina su campo, en ningún
lugar cercano al margen. La señal que la hipótesis suponía —un párrafo
contra una pared— no existe en ese documento.

**Queda como pregunta sin propuesta.** `Plantilla.pendientes()` la expone con
`se_propone: None` y dice por qué no propone: fingir una propuesta sin
evidencia es la misma mentira que un `0 discrepancias` sin cobertura. El
humano contesta una vez por formato y la plantilla lo guarda.

**El umbral de CID, medido sobre los 27 fixtures.** El documento ilegible da
**98.8%** de su muestra en CID y el siguiente da **0.55%**; los otros 25 dan
cero exacto. No hay nada en medio, así que cualquier umbral entre los dos
separa. Se puso en **0.50** a propósito: expresa que lo que justifica releer
todo el documento por OCR es que sea ilegible, no que traiga un sello digital
en CID. Los seis tokens de Inbursa y Multiva siguen siendo trabajo del carril
de `reintento.reintentar_cid`, página por página.

**Corrección: eran DOS los parsers sin salida a Excel, no uno.** Al conectar
el CLI apareció que `exportar_auxiliar` tampoco existía. Los cinco tipos
salen ahora a Excel.

**El `guardar()` que rechaza lo que no cuadró se nota al conectar el CLI.**
De los cinco fixtures de referencia, tres cuadran y aprenden plantilla
(balanza, estado de cuenta, mayor) y dos no (auxiliar con 1 regla en falla,
pólizas con 3). Los dos salen con código 1 y sin plantilla, que es
exactamente lo que ese código y esa regla significan. No es una regresión:
es la primera vez que se ve de punta a punta.


### Resultados de la fase 7f (cada conteo con su denominador)

**El defecto.** `ResultadoRegla` guardaba cuántas comprobaciones corrieron
pero no cuántas **podía** haber corrido, así que un 5 sobre 116 casos y un
116 sobre 116 se imprimían igual. Peor: el campo `comprobaciones`
significaba cosas distintas según la regla. En unas era el universo
(`renglon`, `jerarquia`, `totales`, `cfdi`, `saldo_mensual`, `acumulados`) y
en otras sólo lo que alcanzó a correr (`saldo_corrido`, `subtotales`,
`partida_doble` de pólizas, `cfdi_cruzado`, `resumen`, `total_declarado`,
`cruce_balanza`). Las de la segunda familia siempre se veían al 100%.

Es el mismo modo de falla del `734 filas, 0 discrepancias` de
`balanza-gume`, sobrevivido a la fase 4a.

**La tabla, regla por regla y documento por documento.** `apl` es el
universo de casos que el documento contiene; `eval` cuántos recibieron
veredicto. Medida primero fuera del código y regenerada después desde él.

| Documento | Regla | apl | eval | % | exactos | tol | Estado |
|---|---|---|---|---|---|---|---|
| balanza | renglon | 475 | 475 | 100% | 475 | 0 | cuadra |
| balanza | jerarquia | 56 | 52 | 93% | 52 | 0 | cuadra |
| balanza | totales | 2 | 2 | 100% | 2 | 0 | cuadra |
| balanza | partida_doble | 1 | 1 | 100% | 1 | 0 | cuadra |
| balanza-businesspro | renglon | 225 | 225 | 100% | 225 | 0 | cuadra |
| balanza-businesspro | jerarquia | 48 | 46 | 96% | 46 | 0 | cuadra |
| balanza-businesspro | totales | 2 | 2 | 100% | 2 | 0 | cuadra |
| balanza-businesspro | partida_doble | 1 | 0 | 0% | 0 | 0 | no verificable |
| balanza-gume | renglon | 734 | 734 | 100% | 732 | 2 | cuadra |
| balanza-gume | jerarquia | 126 | 126 | 100% | 126 | 0 | cuadra |
| balanza-gume | totales | 2 | 2 | 100% | 2 | 0 | cuadra |
| balanza-gume | partida_doble | 1 | 1 | 100% | 1 | 0 | cuadra |
| auxiliar | saldo_corrido | 6783 | 6783 | 100% | 3198 | 0 | falla |
| auxiliar | subtotales | 0 | 0 | — | 0 | 0 | no verificable |
| **auxiliar-gume** | **saldo_corrido** | **57024** | **21757** | **38%** | 15177 | 19 | falla |
| **auxiliar-gume** | **subtotales** | **1470** | **344** | **23%** | 341 | 2 | falla |
| poliza | partida_doble | 1944 | 1944 | 100% | 1941 | 0 | falla |
| poliza | totales | 3888 | 3888 | 100% | 3885 | 0 | falla |
| poliza | cfdi | 1942 | 1942 | 100% | 1942 | 0 | cuadra |
| poliza | cfdi_cruzado | 1942 | 1942 | 100% | 917 | 0 | falla |
| diario-general | partida_doble | 5302 | 5302 | 100% | 5202 | 0 | falla |
| diario-general | totales | 10604 | 10604 | 100% | 10499 | 0 | falla |
| diario-general | cfdi / cfdi_cruzado | 0 | 0 | — | 0 | 0 | no verificable |
| edocta | resumen / resumen_movs / saldo_corrido | 1 / 2 / 45 | = | 100% | = | 0 | cuadra |
| edocta | total_declarado | 2 | 0 | 0% | 0 | 0 | no verificable |
| edocta-abril-santander | los cuatro | 1 / 2 / 110 / 2 | = | 100% | = | 0 | cuadra |
| edocta-julio-banorte | resumen / resumen_movs | 2 / 4 | 0 | 0% | 0 | 0 | no verificable |
| edocta-julio-banorte | saldo_corrido / total_declarado | 283 / 2 | = | 100% | = | 0 | cuadra |
| **edocta-bajio** | **saldo_corrido** | **67** | **65** | **97%** | 65 | 0 | cuadra |
| edocta-bajio | total_declarado | 2 | 0 | 0% | 0 | 0 | no verificable |
| edocta-inbursa | resumen / resumen_movs / saldo_corrido | 1 / 2 / 44 | = | 100% | = | 0 | cuadra |
| edocta-inbursa | total_declarado | 2 | 0 | 0% | 0 | 0 | no verificable |
| **edocta-bbva** | **saldo_corrido** | **116** | **5** | **4%** | 5 | 0 | cuadra |
| edocta-bbva | total_declarado | 2 | 0 | 0% | 0 | 0 | no verificable |
| mayor-gume | saldo_mensual | 588 | 588 | 100% | 584 | 4 | cuadra |
| mayor-gume | acumulados | 1176 | 1176 | 100% | 1171 | 5 | cuadra |
| **mayor-gume** | **cruce_balanza** | **49** | **0** | **0%** | 0 | 0 | no verificable |

**Sólo dos reglas cuadraban con hueco**: BBVA (5 de 116, 4%) y Bajío (65 de
67, 97%). Los demás huecos ya salían `no_verificable`, que era honesto. Pero
el peor caso en cifras absolutas no es BBVA sino **auxiliar-gume**, que
declaraba 21 757 comprobaciones sobre un documento de 57 024 renglones: quien
leyera «15 177 exactas de 21 757» calculaba 70% cuando la cobertura real es
27%.

**Tres decisiones de universo, todas hacia el denominador más grande.** Ante
la duda, el caso entra al denominador; elegir la interpretación que sube el
porcentaje es como se llegó al 5/5.

1. **El renglón que siembra la cadena es aplicable**, aunque no se pueda
   evaluar. BBVA son 116, no 115.
2. **Las pólizas incompletas son aplicables**, no evaluadas, con motivo. El
   PLAN dice que la cobertura las declara, y declarar exige estar en el
   denominador.
3. **El universo de `jerarquia` son los padres que alguna fila declara**
   (`cuenta_padre` no vacía), no los pares que se lograron formar. Destapó
   huérfanos que no se veían: `balanza` tiene **2 cuentas padre que ninguna
   fila del documento contiene** (28 referidas, 26 formadas) y
   `balanza-businesspro` **1** (24 referidas, 23 formadas). `balanza-gume` no
   tiene ninguna. Ninguna cambia de estado, pero la cobertura baja de un 100%
   falso a 93% y 96% reales.

**Tres diferencias entre la medición externa y la regenerada desde el
código, las tres explicadas:**

| Regla | Fuera | Código | Por qué |
|---|---|---|---|
| `balanza / jerarquia` | 52/52 | 56/52 | la decisión 3 de arriba: padres referidos, no pares formados |
| `balanza-businesspro / jerarquia` | 46/46 | 48/46 | igual |
| `auxiliar-gume / subtotales` | 735/344 | 1470/344 | la medición externa mezcló unidades: contó el universo en subtotales (735) y lo evaluado en subtotal×campo (344). El universo va en las unidades de `exactas`: 735 × debe/haber |

**Por qué la partición del auxiliar no tiene cubo de ambiguos.** En el
diagnóstico del signo salieron 3 198 deudoras + 3 585 acreedoras = 6 783
exacto, sin renglones que cumplieran las dos identidades. No es casualidad ni
un artefacto de resolver por cuenta: un renglón cumple ambas si y sólo si
`debe == haber`, y en este documento **ningún renglón tiene `debe == haber`**
(cero de 6 783; tampoco ninguno con los dos en cero). Cada movimiento del
auxiliar carga un solo lado, así que la clasificación se hizo **por renglón,
independiente**, sin necesidad de desempatar con los demás renglones de su
cuenta. Es lo que lo distingue de `mayor-gume`, donde 25 de 49 cuentas quedan
sin determinar porque un mes agrega muchos movimientos y `cargos == abonos`
sí ocurre.

**Denominadores que no se habían escrito.** Dos cifras del propio PLAN
resultaron ser de ventanas distintas a las que sugerían:

- Las tres tasas de CID de HSBC son el mismo documento en tres ventanas:
  **590/609 (96.9%)** el documento entero de 4 páginas, **248/251 (98.8%)**
  una muestra de 3 páginas, **204/205 (99.5%)** la muestra de 2 páginas que
  usa `decidir()` y que por eso sale en el CLI. Por página: 131/132, 73/73,
  44/46, 342/358.
- El «2 509 de 7 762 (32%) sin saldo legible» de `auxiliar-gume` es de **una
  sección de 118 páginas**. Sobre el documento completo son **35 045 de
  57 024 (61%)**.
- `_UMBRAL_CID = 0.5` es una **fracción de 0 a 1**, no un porcentaje, y la
  unidad ya está escrita en el código. El documento del 0.55% vale 0.0055 y
  **no** se enruta a OCR, que es lo correcto.

**Hallazgo colateral: `recalculo.recalcular_saldos` no está conectado.**
Existe y está probado, pero `pipeline.py` no lo llama nunca. El PLAN mide que
ese carril deja `auxiliar-gume` en «5 253 impresos, 2 509 recalculados, 0 sin
saldo»; el pipeline entrega hoy **35 045 sin saldo**. Registrado en §5.1.

### Resultados de la fase 7g (los tres defectos diagnosticados en la 7f)

**Las cifras de §5.1 se verificaron antes de tocar nada y salieron
idénticas**: 3,198 deudoras / 3,585 acreedoras / 0 ambiguos / 0 sin
explicar; 396 D y 44 A sin mezcla; 1,025 fallas por igualdad, 162 por
contención, 101 artefacto, 61 sin explicar.

**Tres celdas de la tabla de cobertura cambiaron, y sólo tres.** Ninguna se
movió sin querer:

| Documento / regla | 7f | 7g | Qué lo movió |
|---|---|---|---|
| `auxiliar / saldo_corrido` | 3,198 exactas de 6,783 — **falla** | 6,783 de 6,783 — **cuadra** | el signo derivado |
| `auxiliar-gume / saldo_corrido` | 15,177 exactas de 21,757 evaluados — **falla** | 47,965 de 47,987 — **cuadra** | el signo + 26,032 saldos recalculados |
| `poliza / cfdi_cruzado` | 917 exactas de 1,942 — falla | 1,780 de 1,942 — falla | la contención |

`auxiliar-gume / subtotales` **no** cambió (344 de 1,470), y es lo esperado:
los subtotales se comprueban contra debe y haber, que siempre fueron
legibles; el defecto estaba en los saldos.

#### 1. El signo del saldo corrido se deriva por cuenta

Cuarta aparición del principio «nunca fijar el signo de una identidad de
saldo». La naturaleza se decide **por mayoría de los renglones que la
revelan**, el mismo criterio que ya usaba `MayorParser._naturaleza`, con dos
fuentes de evidencia:

1. los renglones con saldo impreso: cuál identidad los encadena;
2. **el aterrizaje**: encadenar la sección entera desde su saldo inicial y
   ver cuál signo cae exacto en el saldo del subtotal declarado.

La fuente 2 no estaba prevista y resultó decisiva: funciona aunque **todos**
los saldos intermedios sean ilegibles, que es el caso de `auxiliar-gume`.
Sin ella quedaban 29 secciones sin determinar; con ella, ninguna.

Un renglón con `debe == haber` no vota, porque las dos identidades lo
cumplen. Medido: **ninguna sección de ninguno de los dos fixtures tiene
votos de los dos lados**, así que hoy mayoría y unanimidad coinciden — la
mayoría está ahí para que un solo saldo mal leído no voltee una cuenta
entera, no para tapar un conflicto.

| Fixture | secciones | D | A | sin determinar |
|---|---|---|---|---|
| `auxiliar` | 440 | 396 | 44 | 0 |
| `auxiliar-gume` | 172 | 99 | 73 | 0 |

El recálculo **también tenía el signo cableado**, y eso era peor que la
regla: encadenar una cuenta acreedora con la identidad deudora produce
saldos incorrectos **marcados como buenos**. Las dos usan ahora la misma
`naturaleza_por_cuenta`.

#### 2. El recálculo, conectado al pipeline

Cuatro fases con una capacidad documentada como resuelta que en producción
no existía. Antes y después, por fixture:

| Fixture | | impresos | recalculados | sin saldo |
|---|---|---|---|---|
| `auxiliar` | antes y después | 6,783 | 0 | 0 |
| `auxiliar-gume` | antes | 21,979 | 0 | **35,045** |
| `auxiliar-gume` | después | 21,979 | **26,032** | **9,013** |

`auxiliar` no cambia y no es un fallo: **ninguna de sus 440 secciones
imprime fila de subtotal**, así que no hay ancla posible — y tampoco hace
falta, porque no tiene ni un saldo ilegible.

Por qué quedan 9,013, medido sección por sección:

| Sección | cuántas | movimientos sin saldo |
|---|---|---|
| anclada y recalculada | 168 | — |
| la suma no cuadra con el subtotal (falta algún movimiento) | 2 | **9,013** |
| la cadena no aterriza en el saldo del subtotal | 2 | 0 |
| sin naturaleza determinable | 0 | 0 |

Los 9,013 salen de **dos secciones** donde la suma de los movimientos no
cuadra con el subtotal declarado, o sea donde falta algún renglón por leer.
Ahí encadenar desplazaría todos los saldos siguientes sin que nada avisara,
así que se quedan vacíos. **Es el comportamiento correcto**, y de paso
señala un defecto de lectura en esas dos secciones que nadie había visto.

La estimación previa a implementar decía 15,950 rescatables y salieron
26,032: la estimación exigía **unanimidad** para la naturaleza y el código
usa **mayoría**, que determina más secciones y por tanto ancla más.

#### 3. `cfdi_cruzado` por contención

De 1,025 fallas a 162. Las 863 de diferencia eran falsas alarmas.

**Diagnóstico de las 61 sin explicar: son una sola familia.** Todas son
pólizas de **Pago (40), Cobro (13) y Venta (8)** — ninguna de tipo Compra,
que son justo las que sí cruzan. En ellas la `descripcion` no es el folio de
la factura sino el concepto bancario del movimiento:

| Forma | cuántas |
|---|---|
| ambos numéricos pero distintos (`16998` contra `CUENTA CLAVE DE 0126500…`) | 39 |
| la descripción no trae ningún dígito | 9 |
| el documento es sólo letras | 5 |
| otras | 8 |

No es un problema de comparación: **el documento y la descripción son datos
distintos**, no el mismo número escrito de otra forma. La regla les está
pidiendo a esas pólizas un dato que el documento no pone ahí.

#### M1: los 93 movimientos de BBVA sin saldo — y la sorpresa de Bajío

Medido sobre el layout, contando tokens en la banda del saldo:

| Documento | sin saldo | con algún token en la columna del saldo | Veredicto |
|---|---|---|---|
| BBVA | 93 de 116 | **0** | **(a) correcto**: el banco sólo imprime el saldo al cierre del día |
| Bajío | 1 de 67 | **1** | **(b) pérdida de extracción** |

La pregunta esperaba una respuesta y hay **dos**. Por eso el motivo de la
cobertura dice ahora «no traen saldo con el que encadenar» y ya no «no traen
saldo legible»: la causa varía entre documentos y esa regla no puede verla,
así que afirmar una sola sería inventarla.

### Resultados de la fase 7h (cerrar el nucleo)

#### Correccion: la explicacion de los 10 082 saldos de la 7g era falsa

La 7g afirmo dos cosas incompatibles y una era mentira. Medido ahora, con
las cuatro combinaciones sobre `auxiliar-gume`:

| Criterio | Aterrizaje | D | A | sin | secciones ancladas | saldos rescatados |
|---|---|---|---|---|---|---|
| unanimidad | no | 98 | 71 | 3 | 165 | 25 987 |
| unanimidad | sí | 99 | 73 | 0 | 168 | 26 032 |
| mayoría | no | 98 | 71 | 3 | 165 | 25 987 |
| mayoría | sí | 99 | 73 | 0 | 168 | 26 032 |

**El criterio no mueve ni un saldo.** Mayoría y unanimidad dan resultados
idénticos en las cuatro columnas, así que la afirmación «la estimación
exigía unanimidad y el código usa mayoría» no explicaba nada.

La causa real, reproducida: la estimación de la 7g dejaba **votar a los
renglones con `debe == haber`**, que cumplen las dos identidades y por tanto
votan a los dos lados. Con criterio de unanimidad, un solo renglón así
descarta la cuenta entera. Hay **147 renglones con `debe == haber`
repartidos en 30 de las 172 secciones**.

| Variante | D | A | sin | ancladas | rescatados |
|---|---|---|---|---|---|
| los empates votan (la estimación de la 7g) | 79 | 64 | 29 | 141 | **15 950** |
| los empates no votan (el código) | 98 | 71 | 3 | 165 | **25 987** |

Desglose correcto de los 10 082: **+10 037** por excluir del voto los
empates, **+45** por el aterrizaje, **0** por el criterio.

**Consecuencia que hay que decir: la regla de mayoría no está probada por
ningún fixture.** En los dos documentos disponibles ninguna sección tiene
votos de los dos lados, así que mayoría y unanimidad son indistinguibles
aquí. La mayoría se eligió por el precedente del libro mayor, no por una
medición; el primer documento que traiga una sección con votos partidos
será el que la ponga a prueba.

#### 1. La cobertura del saldo corrido era circular

`auxiliar-gume/saldo_corrido` reportaba «47 965 de 47 987 cuadra» y **26 032
de esas exactas eran saldos que el propio sistema había encadenado** con
`saldo = anterior + debe - haber`. Comprobar esa identidad sobre un saldo
producido con esa fórmula no puede fallar: no prueba nada del documento.

`ResultadoRegla` separa ahora `exactas_impresas` de `exactas_recalculadas`,
y el resumen de la cobertura lo dice en voz alta. La verificación real de
una sección recalculada es otra y va en una regla aparte, `ancla_recalculo`,
contada **por sección** y no por movimiento: 168 de 168 secciones con saldos
derivados aterrizan en el subtotal que el documento declara.

#### 2. Los renglones que el parser perdía: tres familias, tres causas

| Familia | Qué es | ¿Hay tinta? | Causa |
|---|---|---|---|
| **A** — 2 secciones de `auxiliar-gume` | retienen 9 013 saldos | sí, y se leyó | **no falta ningún movimiento**: la suma difiere del subtotal en **0.01 y 0.02 pesos** sobre 37 millones, y el ancla exige igualdad exacta |
| **B** — 3 pólizas | P00010, P01804, P01919 | sí, y se leyó | el nombre largo del banco se envuelve en 3 renglones y los importes caen en el del **medio**, que no lleva número de cuenta |
| **C** — 72 pólizas con 2 movimientos | sospecha de §5.1 | — | **no existe**: en las 968 páginas hay exactamente **3** renglones con debe y haber sin número de cuenta, y son los de la familia B |

La familia C queda **descartada por medición**: las 72 pólizas de 2
movimientos son pólizas de dos asientos, no pólizas mutiladas. Si perdieran
un movimiento habría un renglón huérfano, y no lo hay.

La familia A **no era lo que la 7g dijo**. Su diagnóstico («falta algún
movimiento») era incorrecto: no falta ninguno, la diferencia es de un
céntimo. `1190-001-000` da −0.02 en el debe y `1201-001-000` da +0.01 / −0.01.

La familia B sí se arregló: un renglón que abre con número de cuenta pero
sin importes deja el movimiento pendiente hasta que aparecen, y si no
aparecen se descarta — no se inventa un movimiento en cero. Resultado:
`partida_doble` 1 944 de 1 944 y `totales` 3 888 de 3 888, las dos cuadran.

#### 3. `cfdi_cruzado`: los 101 eran 112, y mi caracterización de los 61 era falsa

**Los CFDI inventados por el parser son 112, no 101.** Los 101 eran sólo los
que además fallaban el cruce; los otros 11 no eran comparables por otra vía.
Y de los 1 780 cruces que la 7g daba por buenos, **12 eran falsos positivos**:
el documento inventado coincidía por casualidad con la descripción.

Marcador inequívoco y medido: **los inventados son exactamente los que no
traen UUID**. Su renglón es `fecha | Diario | (Manual)`, sin folio fiscal ni
RFC — pólizas manuales sin comprobante. El parser tomaba la primera palabra
que quedara. El criterio no mira el resultado del cruce, así que no vuelve
tautológica a la regla.

**Corrección sobre los 61: el tipo de póliza NO es el discriminante.** La
7g dijo que eran «una familia: Pago, Cobro y Venta». Medido por tipo:

| Tipo de póliza | cruzan | fallan |
|---|---|---|
| Cobro | 817 | 13 |
| Compra | 76 | 0 |
| Venta | 853 | 8 |
| Pago | 31 | 40 |
| Nota | 3 | 0 |

**1 701 pólizas de esos mismos tipos sí cruzan.** Sacarlas todas del
numerador habría perdido 1 701 comprobaciones válidas para tapar 53 fallas:
exactamente «elegir la interpretación que sube el porcentaje». Quedan **53**
discrepancias con folio fiscal cuya descripción no lo contiene, y no se
tocaron: el único criterio que las separa de las que cruzan es *que fallan*,
y usar eso como filtro es la misma circularidad que esta fase vino a quitar.

#### Estado de los cinco tipos

| Comando | Código de salida | Qué queda |
|---|---|---|
| `balanza` | 0 | — |
| `auxiliar` | 0 | — |
| `estado-cuenta` | 0 | — |
| `mayor` | 0 | — |
| `polizas` | **1** | 53 `cfdi_cruzado`, sin decidir |

Tres celdas de la tabla de cobertura cambiaron respecto a la 7g, las tres de
`poliza`: `partida_doble` (1 941 → 1 944 exactas, pasa a cuadra), `totales`
(3 885 → 3 888, pasa a cuadra) y `cfdi_cruzado` (1 942 → 1 821 evaluados,
1 780 → 1 768 exactas). Ninguna otra se movió.

### Dos documentos, sin solapamiento

| Archivo | Contiene | Lo mantiene |
|---|---|---|
| `PLAN.md` | Decisiones, mediciones, contratos, principios, el *porqué* | El orquestador, con cada reporte |
| `ARQUITECTURA.md` | Qué existe en código hoy: módulos, firmas públicas, flujo, invariantes | Claude Code, al cerrar cada fase |

**Quién escribe qué dentro de `PLAN.md`.** La regla original («solo el
orquestador lo toca») no aguantó y era peor: quien mide es Claude Code, y
que el orquestador transcriba sus mediciones pierde precisión — pasó con el
Santander integral y con las cifras de HSBC. Regla nueva, por sección:

- **§2 (hallazgos medidos): Claude Code escribe.** Agrega lo que midió, con
  sus números. No reescribe principios ni decisiones.
- **§0, §1, §4, §5, §6 y los principios: el orquestador.** Restricciones,
  contratos, tabla de fases, deuda técnica e infraestructura.
- Al cerrar una fase, Claude Code reporta qué secciones tocó, para que el
  orquestador no sobrescriba sus mediciones con una versión vieja.

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

Vive en `ARQUITECTURA.md` §1, que es donde se mantiene. Aquí duplicaba y se
quedó atrás cuatro fases seguidas.

`.gitignore` incluye `fixtures/real/` desde el primer commit — eso sí es
decisión, no descripción, y se queda aquí.

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
| 7d | Generalizar estados de cuenta | Contrato multi-cuenta + los 6 formatos con tabla, mismo parser | **hecho** (581 tests + 9 lentos) |
| 7e | Cerrar el núcleo | `exportar_estado_cuenta` + `exportar_auxiliar`, los 5 comandos del CLI, enrutamiento CID→OCR, separador de continuación como pregunta | **hecho** (635 tests + 11 lentos) |
| 7f | Cobertura con denominador | `aplicables` en `ResultadoRegla`; diagnóstico de las 4 reglas en falla de auxiliar y pólizas | **hecho** (673 tests + 12 lentos) |
| 7g | Arreglar lo que midió la 7f | Signo derivado por cuenta, `recalculo` conectado, `cfdi_cruzado` por contención | **hecho** (691 tests + 14 lentos) |
| 7h | Cerrar pólizas y deshacer la circularidad | Separar exactas impresas de recalculadas; renglones perdidos por el parser; los 101 y los 61 de `cfdi_cruzado` | **hecho** (711 tests + 15 lentos) |
| 8a | Interfaz mínima | Subir PDF → Excel + cobertura en el navegador, sin cola ni multi-tenant | siguiente |
| 8b | Capa web completa | Cola, worker, aislamiento por tenant, SERVIDORSIST | |
| 8c | Residuos del ancla | Medir la distribución de residuos de aterrizaje y decidir si hay tolerancia defendible | |

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

**Las cifras de un prompt se copian del archivo, nunca de memoria.** Pasó
dos veces en direcciones opuestas: un número del dumper metido en un prompt
como si fuera medición del sistema, y el `5/5` de BBVA citado como `45/45`
—que es la fila de AFIRME— en el prompt de la 7f. Un número equivocado en
el CONTEXTO hace que Claude Code mida la cosa correcta sobre el caso
equivocado, y eso cuesta una sesión entera. Antes de pegar un prompt,
`grep` la cifra en `PLAN.md`.

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
- **La familia A: 2 secciones de `auxiliar-gume` cuya cadena no aterriza.**
  Medido en la 7h y corrigiendo lo que dijo la 7g: **no falta ningún
  movimiento**. La suma difiere en 0.01 y 0.02 pesos sobre 37 millones, y el
  ancla exige igualdad exacta. Un movimiento faltante mueve pesos, no
  céntimos, así que es redondeo del documento origen. Retiene 9,013 saldos
  sin recalcular.
  No se relaja el ancla eligiendo un número: `±0.01` no alcanza y subirlo a
  `±0.02` es ajustar el umbral hasta que pase el caso. **Fase 8c: medir la
  distribución completa de residuos sobre las 172 secciones y buscar el hueco,
  como se hizo con el umbral de CID. Sin hueco no hay tolerancia defendible.**
  Y si se admite: una sección anclada con residuo no es igual a una anclada
  exacta, la cobertura las separa, y el residuo nunca se distribuye entre los
  saldos.
- **53 pólizas fallan `cfdi_cruzado` y se quedan como falla declarada.**
  Medido en la 7h: no hay criterio no circular que las separe de las que
  cruzan. Por tipo, Cobro 817 cruzan / 13 fallan, Venta 853 / 8, Pago 31 / 40;
  1,701 pólizas de esos mismos tipos sí cruzan, así que **no son una familia**.
  El comando `polizas` sale con código 1 a propósito: 53 renglones marcados en
  el Excel son revisables por un contador; un porcentaje inflado no. **Sin
  fase: es el resultado correcto, no deuda.**
- **La regla de mayoría para determinar la naturaleza no está probada.**
  Medido en la 7h: el criterio no mueve ni un saldo —unanimidad y mayoría dan
  165 secciones ancladas sin aterrizaje y 168 con él, idénticas—. Los dos
  documentos disponibles no lo distinguen. Se eligió por el precedente del
  libro mayor, no por una medición. **Sin fase; volver a medirlo cuando entre
  un fixture nuevo de auxiliar.**
- **20 CFDI traen el RFC pegado al tipo** (`'ROTG870907QC5Ingreso'`). No
  afecta al cruce; el campo `tipo` sale sucio. **Sin fase asignada.**
- **`Bajío`: 1 movimiento con tinta en la columna del saldo que no se leyó.**
  Único caso (b) de M1 en la 7g; los 93 de BBVA son (a), el banco solo
  imprime el saldo al cierre del día. **Sin fase asignada.**
- **El enrutamiento CID→OCR corre en el carril normal.** Añade ~21 s a una
  llamada síncrona sin avisar, y esos 21 s se midieron en la máquina de
  desarrollo. El PLAN lo exige en el carril lento con tiempo estimado
  visible. **Resolver en fase 8b.**
- **Ninguna medición de tiempo se ha hecho en SERVIDORSIST.** Los 0.1 s por
  página y los 21 s de OCR salen de un i5-1335U con SSD; el destino es un
  i5-3470 de 2012 sin AVX2 con disco mecánico compartido con Apache y
  MySQL. La memoria pico (543 MB) sí traslada; el tiempo no. **Medir en la
  máquina objetivo antes de dimensionar la cola de la fase 8b.**

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

- **Memoria pico, MEDIDA (fase 7d).** Peor caso `auxiliar-gume` (886 págs,
  57,759 filas): **543 MB**. Le siguen `diario-general` 259 MB, `poliza`
  109 MB, el resto por debajo de 60 MB. Descomposición del peor caso:
  190 MB es piso de pdfplumber (no baja con streaming), +317 MB por
  `list(open_pages())`, +36 MB por las filas del resultado.
  **Con ~11 GB libres y un trabajo a la vez, cabe con holgura: no hay que
  convertir a streaming antes de la fase 8.** Convertirlo bajaría el pico
  a ~225 MB. **Esta es la cifra que decide si la fase 8 puede correr dos
  trabajos en paralelo**: 543 MB × N.
- (histórico) **MEDIR ANTES DE LA FASE 8: memoria pico por documento.** Cuatro de los
  cinco parsers hacen `list(document.open_pages())` — solo `BalanzaParser`
  transmite página por página. Eso contradice §0. Con un solo trabajo a la
  vez probablemente aguante, pero hay que medir el pico real del auxiliar
  de 886 páginas contra los ~11 GB que quedarán libres tras la ampliación.
  Si son cientos de MB, se sigue; si son varios GB, el worker deja
  inusable a MySQL y hay que convertir los parsers a streaming primero.
- **El umbral de CID vive en `strategy.py` con una constante sin unidad
  documentada.** El hueco medido sobre 27 fixtures es enorme (98.8% contra
  0.55% contra 25 en cero exacto), así que el umbral es defendible; lo que
  falta es dejar escrito qué unidad usa y que la fracción está a mitad del
  hueco, no pegada al borde inferior.
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