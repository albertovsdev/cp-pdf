# cp-pdf — Plan de construcción

Sistema de conversión de PDFs contables a Excel, con mapeo por plantillas y
validación aritmética.

**Regla de oro:** ningún parser se escribe sin un fixture que lo pruebe
primero. Fixture → test que falla → parser → test que pasa.

Estado: **fase 8e cerrada.** Cinco parsers, cinco exportadores, CLI de seis
comandos, interfaz web con cola persistente en SQLite, worker secuencial y
aislamiento por despacho.
**747 tests rápidos + 124 lentos.**
De los 27 fixtures: **16 producen Excel**, 7 no tienen parser, 3 son estados
de cuenta sin tabla de movimientos, y `mayor-proactivity` **sale con código 2
y motivo escrito** desde la 8e — antes contaba entre los que procesaban
porque no reventaba. Cuatro de los cinco tipos aprenden plantilla; pólizas
sale con discrepancias por **53 CFDI sobre 50 pólizas** cuyo folio no aparece
en la descripción del asiento, declarados a propósito.

**Las tres salidas —CLI, Excel y web— dicen lo mismo del mismo caso desde la
8e.** La hoja `Auxiliar` declara qué saldos derivó el sistema (26,032 de
57,759 en `auxiliar-gume`), las hojas `Cuentas` de mayor y estado de cuenta
llevan declarado y leído, y la `Discrepancia` declara si compara importes en
vez de que cada salida lo deduzca. Queda un hueco: **`balanza` no exporta
`naturaleza_origen`** (§5.1).

**SERVIDORSIST está medido.** La corrida es del orquestador por Escritorio
Remoto (no hay SSH y no se va a montar); la transcribió Claude Code a §2 en
la 8d desde
`scripts/mediciones/mediciones-ServidorSist-20260904-1757.txt`.

- **Factor 3.40× sobre los 15 documentos comunes**: 17m36s allá contra 5m10s
  aquí. (La medición original comparó 16 y dio 3.44×; desde la 8e
  `mayor-proactivity` se rechaza y sale de las dos sumas. Las tablas de §2
  conservan las cifras de entonces, que siguen siendo ciertas para aquel
  momento.) Por documento va de 2.29× a 4.03×, pero **los cinco que en desarrollo
  pasan de 15 s caen todos entre 3.35× y 3.64×**, que es donde el factor
  importa —son los que bloquean la cola—. Debajo de 4 s el cociente es ruido
  de reloj. `auxiliar-gume` tarda **10m40s** allá contra 3m08s aquí.
- **El «3.4–3.7× consistente» que circuló en tres documentos no existe.** El
  3.7 salía de dividir el total de SERVIDORSIST entre el tiempo de *sólo
  leer* de desarrollo, y el 3.31 de dividir 16 documentos entre 17. Las dos
  cifras son del orquestador y las dos comparan cosas distintas.
- **La memoria no es restricción, pero lo medido es la holgura y no el
  consumo**: el mínimo de RAM libre durante la corrida entera fue 2,809 MB de
  8,078, con Apache y MySQL activos. **El pico del proceso allí no se pudo
  leer.** Los «~400 MB de consumo» que decía antes esta línea eran una resta
  contra el libre inicial, no una medición.
- **El disco tampoco**: 328 GB libres contra un techo extrapolado de 266 MB
  al día.

**El OCR nunca ha funcionado en SERVIDORSIST y la 8d arregló la causa**:
`ocr.py` lanzaba Tesseract sin `encoding`, y un Windows en español decodifica
con cp1252, que no admite los bytes de las comillas tipográficas que Tesseract
imprime. **El arreglo NO está verificado en la máquina objetivo** —la suite
corre en WSL— y verificarlo exige volver a correr `medir_servidorsist.py`
allí con Tesseract en el PATH. Es tarea del orquestador, que es quien tiene
acceso. Ver §5.1.

Siguiente: **8f** (el diario, el IR y el texto de los estados de cuenta) y
**8g** (residuos del ancla).

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

**Una regla que no evaluó nada no puede cuadrar.** `evaluados == 0` junto con
`estado == CUADRA` es una combinación prohibida, igual que
`aplicables is None` con `CUADRA`. Una regla sin comprobaciones es
`no_verificable` con motivo, siempre. La fase 7f prohibió la primera
combinación y no la segunda, y por ese hueco `mayor-proactivity` reporta
`saldo_mensual 0 de 48 → cuadra` y `acumulados 0 de 96 → cuadra`, con un
encabezado que dice literalmente «0 de 145 casos evaluados; 2 cuadran».
Es el `0 discrepancias` de balanza-gume en su tercera forma.

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

**Una medición de tiempo se hace con la invocación completa que usa el
sistema real.** Los `3m57s` de `auxiliar-gume` que circularon por PLAN.md,
USO.md y el prompt de la 8a se midieron **sin `-o`**, así que nunca
escribieron el `.xlsx`; la capa web lo escribe siempre. El total verdadero
era 23m45s: 182 s de leer y validar contra 1,243 s de exportar. Medir un
pipeline que nadie ejecuta escondió durante nueve fases que el exportador era
cuadrático —`hoja[hoja.max_row]` dentro del bucle por renglón, en los cinco
exportadores—.

De ahí la regla operativa: **el reloj se reporta siempre partido**, leer y
validar por un lado, exportar por otro. Un número único no permite distinguir
en qué mitad está el problema, y por eso nadie lo buscó. Este error es del
orquestador, y es la segunda aparición del mismo patrón que ya está
registrado: una cifra obtenida en condiciones que no son las del sistema,
insertada en el PLAN como si lo fueran.

**Un mecanismo correcto no es una explicación suficiente: hay que contar los
casos.** La 8d diagnosticó que `mayor-proactivity` inventa meses porque
`normalizar()` quita la puntuación y `_orden_de('(ENERO')` devuelve 1, y
escribió que ese paréntesis suelto «no es un adorno del defecto, es el
defecto». El mecanismo era cierto. La magnitud, no: la 8e contó y son **2 de
50**; los otros 48 son nombres de mes limpios dentro de descripciones. Con la
magnitud mal, la conclusión sobre qué tocar también estaba mal — endurecer
`_orden_de` habría quitado 2 y dejado 48.

El orquestador copió esa frase a §5.1, a `CLAUDE.md` y a `USO.md` la misma
tarde, sin que nadie hubiera contado los casos. **Es el mismo error que ya
está registrado dos veces —citar una cifra que no se midió— y esta vez el
vehículo fue un mecanismo bien descrito**, que es más convincente que un
número suelto y por eso pasa más fácil. La regla: un mecanismo se acepta
cuando viene con su denominador.

**Un umbral por presupuesto no es un umbral por medición.** El corte de 3 s
que reparte los tests entre rápidos y lentos se eligió para que la suite baje
de 5 minutos, no porque los datos muestren un hueco ahí —el hueco natural
está entre 14.25 s y 6.74 s—. Cuando un número se elige por conveniencia hay
que decirlo, para que nadie lo cite después como si lo defendieran los datos,
que es lo que sí ocurre con el umbral de CID.

**Un estado que no se mide no se muestra.** La página de progreso de la 8a
reporta `procesando`, `listo` y `error`, y nada más. No dice «validando» ni
«escribiendo» porque `procesar_documento()` es una llamada opaca y la capa
web no puede observar en qué etapa va; tampoco muestra porcentaje, porque no
hay forma de saber cuánto falta. Muestra el reloj, que sí es un dato. Un
test falla si aparece cualquier `NN%` en el cuerpo visible.

El prompt de esa fase pedía las dos cosas a la vez —mostrar «validando» y no
inventar datos— y Claude Code lo detectó al implementarlo. **Una instrucción
del orquestador que contradice un principio del PLAN se resuelve a favor del
principio.**

**Las dos salidas del sistema no pueden contradecirse.** En `diario-general`,
`partida_doble` reporta P00096 con debe 55.17 contra haber 64.00, y la hoja
`Polizas` del Excel muestra la misma póliza con 64.00 y 64.00 y
`completa = VERDADERO`. Medido en la 8b: **la hoja toma el TOTAL declarado por
el documento, no la suma de los movimientos leídos**, y por eso se ve correcta
justo cuando el importe se leyó mal, que es el único caso donde importa. En
`poliza.pdf` no hay una sola discrepancia entre declarado y leído; en
`diario-general` son 100.

De ahí la regla: **la hoja lleva las dos cifras en columnas separadas —
declarado y leído — y `completa` es verdadero solo cuando coinciden.** Mostrar
únicamente lo declarado es la misma mentira que un porcentaje sin denominador:
repite lo que el documento afirma en vez de lo que el sistema pudo comprobar.

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

### Resultados de la fase 8a (interfaz minima)

#### La medicion que cambio el diseno

> **CORREGIDO EN LA 8c.** Los 3m57s miden media operacion: se tomaron con
> `time contapdf auxiliar <pdf>` **sin `-o`**, asi que nunca escribieron el
> `.xlsx`, y la capa web lo escribe siempre. El tiempo real de punta a
> punta era **23m45s** (182 s de lectura + 1 243 s de exportacion), porque
> el exportador era cuadratico. Arreglado en la 8c: ahora son **188.5 s**.
> Y los 1 576 s de la primera pasada no eran solo contaminacion --
> incluian la exportacion. Ver «Resultados de la fase 8c».

`auxiliar-gume.pdf` tarda **3m57s** (medido en aislamiento, i5-1335U con
SSD). Los 1 576 s que reporte en la primera pasada eran contaminacion por
correr la suite en paralelo — un factor de ~6.6, no un comportamiento
cuadratico. La leccion se repite: **una medicion de tiempo con otra cosa
corriendo no es una medicion**.

| | Documentos | Tiempo |
|---|---|---|
| Mediana de los 17 que procesan | 17 | ~3 s |
| Por encima de 5 s | 7 de 17 | — |
| Peor caso, `auxiliar-gume` | 886 pags | **3m57s** |

Con ese numero **la pagina no puede ser sincrona**, y ese fue el unico
cambio de alcance de la fase: un hilo por trabajo, un id devuelto al
instante y una pagina que se refresca sola. Sigue fuera todo lo demas —
cola persistente, Redis, Celery, mas de un trabajo a la vez, multi-tenant.

**El xlsx no es problema**: maximo **3.5 MB** (`auxiliar-gume`), mediana
28 KB. Ninguno pasa de 10 MB, asi que servirlo por HTTP no necesita nada
especial.

#### Lo que la pagina de estado NO dice

Muestra el tiempo transcurrido y nada mas. No hay porcentaje ni barra
porque no hay forma de saber cuanto falta, y fabricar esa cifra seria
inventar un dato — el mismo error que el `0 discrepancias` sin cobertura.

Tampoco dice «leyendo / parseando / validando / escribiendo»:
`procesar_documento()` es una sola llamada opaca y la capa web no puede
observar en que etapa va. Afirmar una etapa que no se mide es inventarla.
Para tenerlas de verdad haria falta que el nucleo aceptara un callback de
progreso, y el nucleo no se toco en esta fase.

#### H1. Los 563 subtotales «que no corresponden a ninguna seccion»

El mensaje describe el sintoma y sugiere una causa falsa. Medido:

| | |
|---|---|
| subtotales | 735, de **732 cuentas distintas** |
| movimientos | 57 024, de solo **172 cuentas distintas** |
| subtotales que emparejan | 172 |
| subtotales huerfanos | **563** |

> **CORREGIDO EN LA 8b (M1).** Este párrafo está mal. Lo deduje de tres
> ejemplos que resultaron ser los tres primeros en orden numérico:
> clasificados los 563, **378 son cuentas de detalle** y solo 185
> acumulativas. La conclusión de fondo —que no falta extracción— sí se
> sostiene, pero por otra razón: los 378 están en ceros. Ver «Resultados de
> la fase 8b».

**No faltan secciones: sobran subtotales de cuentas acumulativas.** Los 563
huerfanos son cuentas de nivel superior — `1110-000-000`, `1120-000-000`,
`1120-001-000` — mientras que las que traen movimientos son de detalle:
`1120-001-003`, `1150-001-003`. Una cuenta acumulativa no tiene movimientos
propios; su total es la suma de sus hijas.

Es la misma trampa que la balanza, y el docstring de `_subtotales` ya la
nombra: «sumar los subtotales junto con los movimientos cuenta dos veces».
Lo que falta es que la regla distinga una cuenta acumulativa de una de
detalle en vez de saltarsela con un `continue`. **No se arreglo en esta
fase.** Dato adicional: 3 cuentas traen mas de un subtotal.

#### H2. Los siete fixtures sin parser

Ninguno es regresion — nunca tuvieron parser — y **los siete dan un mensaje
legible, no una traza**, que es lo que la interfaz necesita:

| Fixture | Tipo | Pags | Que responde |
|---|---|---|---|
| `balanza-fd` | balanza | 12 | el layout no parece una balanza; faltan columnas |
| `balanza-manufacturas` | balanza | 5 | idem |
| `balanza-proactivity` | balanza | 12 | idem |
| `auxiliar-manufacturas` | auxiliar | 161 | ninguno de los 60 mapeos propuestos cuadra |
| `polizas-manufacturas` | polizas | 494 | no se encontro ninguna poliza |
| `mayor-manufacturas` | mayor | 15 | no se encontro ninguna cuenta |
| `mayor-fd` | mayor | 6 | no se encontro ninguna cuenta |

De los 27 fixtures: 17 procesan, 7 no tienen parser y 3 son estados de
cuenta sin tabla de movimientos (`monex`, `multiva`, `scotiabank`), que
salen con su `ReporteNoEsperado` identificado desde la fase 7d.

#### El hueco que destapo la capa web

**No existe forma de deducir el TIPO de documento desde el PDF.** El
fingerprint identifica el *formato* (el vocabulario del encabezado), no si
el documento es una balanza o un auxiliar. El selector se queda sin
preseleccion y lo elige el humano. Es el mismo tipo de hallazgo que la 7e
—donde conectar el CLI destapo los dos exportadores que faltaban—: conectar
capas revela huecos, y taparlos sobre la marcha con un criterio no medido
es la forma de error que mas ha costado en este proyecto.

#### Borrado de los documentos del cliente

Tres redes, no una: el PDF se borra en cuanto el nucleo termina de leerlo,
el Excel al descargarse, y **todo lo que lleve mas de 30 minutos se barre**
al servir cualquier peticion, lo descargue alguien o no. Sin scheduler ni
proceso aparte. El barrido tambien limpia directorios sueltos que hayan
sobrevivido a un reinicio del proceso. Son documentos contables de clientes
de un despacho, y en 8b esto corre en un servidor que tambien sirve
produccion y que nadie reinicia en semanas.

### Resultados de la fase 8b (cola, worker y despachos)

#### La premisa del objetivo 5 era falsa, y la culpa fue de mi medición

El prompt pedía darle a `no_reconocido` un código de salida propio porque
«hoy sale con código 0, igual que un éxito». **No es cierto.** Medido:

| Fixture | Tipo pedido | Código |
|---|---|---|
| `balanza` | balanza | **0** (cuadra) |
| `poliza` | polizas | **1** (con discrepancias) |
| `edocta-multiva` | estado-cuenta | **2** (no reconocido) |
| `balanza-fd` | balanza | **2** (no reconocido) |

De dónde salió el 0: mi primera pasada usaba
`echo "$1 $(basename $2) -> codigo $?"`, y la sustitución de comando
**resetea `$?` antes de que `echo` lo lea**. Todos salían 0 porque el 0 era
el de `basename`. Es la tercera vez en el proyecto que una medición
contaminada por su propio instrumento produce una conclusión falsa —
después de los 1 576 s de la 8a y de la muestra de 3 subtotales de la H1.

Lo que sí es cierto, en versión más débil: **el 2 no es de
`no_reconocido`, es un «no se pudo» genérico**. Lo comparten cinco
situaciones (`cli.py:185, 193, 197, 411, 434`) — el archivo no existe,
`LayoutDesconocido`, no se encontró tabla, `DocumentoNoReconocido`, huella
desconocida al confirmar — y encima argparse usa el 2 para errores de uso.
Un script no puede distinguir «este PDF no es una balanza» de «me
equivoqué de ruta». **No se cambió**: partir el 2 toca `cli.py`, que es
superficie compartida, y la fase tenía prohibido tocar el núcleo. Queda
como pregunta: ¿código propio para `no_reconocido`, o basta con la `clave`
que ya se imprime en la primera línea?

En la cola, en cambio, los tres finales **sí** están separados desde el
principio: `listo`, `con_discrepancias` y `no_reconocido` son estados
distintos, más `error` e `interrumpido`.

#### M1. Los 563 subtotales huérfanos: no hay defecto, y mi diagnóstico de la 8a estaba mal

En la 8a afirmé que los 563 huérfanos «son cuentas de nivel superior».
Lo deduje de **tres ejemplos** que resultaron ser los tres primeros en
orden numérico. Clasificados **los 563**:

| | Cuentas | Con importe | En ceros |
|---|---|---|---|
| Acumulativas (`XXXX-000-000`, `XXXX-YYY-000`) | 185 | 37 | 148 |
| **De detalle** | **378** | **0** | **378** |

O sea: **378 de los 563 son cuentas de detalle**, justo lo contrario de lo
que declaré. Pero la segunda medición cierra el caso:

> **Cuentas de detalle con importe en el subtotal y sin ningún movimiento
> leído: 0. Importe total no leído por esta vía: 0.00.**

Los 378 son cuentas **sin movimientos en el periodo**: el documento imprime
su renglón de subtotal en ceros y no hay nada que leer. Los 37 acumulativos
con importe son la suma de sus hijas, que ya se leyeron por separado —
sumarlos sería contar dos veces, que es exactamente lo que el `continue` de
`_subtotales` evita.

**No hay extracción perdida.** Lo que hay que arreglar es el mensaje, que
dice «no corresponden a ninguna sección» y sugiere una causa que no
existe. Dos errores míos en la misma H1: concluir desde una muestra parcial,
y **suponer que un mensaje raro significa un defecto** sin medir el importe
en juego, que es el único número que decide si algo se perdió.

#### M2. La hoja `Polizas` toma el TOTAL declarado, no la suma de lo leído

Medido con `procesar_polizas()` sobre los dos fixtures de libro diario,
comparando `Poliza.total_debe/total_haber` —lo que sale a la hoja
`Polizas`— contra la suma de los movimientos que salen a la hoja
`Movimientos`:

| | `poliza.pdf` | `diario-general` |
|---|---|---|
| pólizas | 1 944 | 5 302 |
| movimientos | 6 783 | 24 821 |
| **pólizas donde difieren** | **0** | **100** |
| el declarado supera lo leído | 0 | 92 |
| lo leído supera al declarado | 0 | 8 |

**El defecto no está en todos los documentos: está en `diario-general`**, el
que se extrae con `pdf_chars` y tiene 21.9% de palabras traslapadas. En
`poliza.pdf` las dos hojas dicen lo mismo hasta el último centavo.

El testigo de la 8a se confirma. Póliza `COMPRA OTROS CONCEPTOS MATRIZ`:

| | debe | haber |
|---|---|---|
| Hoja `Polizas` (declarado por el documento) | 64.00 | 64.00 |
| Suma de la hoja `Movimientos` (leído) | **55.17** | 64.00 |

Y el hallazgo que no esperaba: **esas 100 pólizas son las mismas 100 fallas
de `partida_doble`** que la tabla de la 7f reporta sobre `diario-general`
(5 202 exactas de 5 302). PLAN §5.1 las lleva como dos pendientes
separados —«la hoja y la regla se contradicen» y «las 100 fallas nunca se
diagnosticaron»— y **son el mismo fenómeno contado dos veces**: la regla
falla exactamente cuando la hoja y los movimientos discrepan.

**No se arregló.** Cambiar de dónde sale esa columna es tocar el
exportador, y antes hay que decidir qué debe decir: lo declarado, lo leído,
o las dos cosas en columnas separadas. Lo que no puede seguir es que el
Excel se vea correcto justo cuando falta un importe.

#### M3. Dónde se pierden los importes: no son renglones, son importes

La pregunta era si los importes perdidos caen en zonas de traslape.
**No se puede contestar tal cual**: el IR del diario no guarda la página.
`Movimiento` es `(poliza_id, orden, cuenta, nombre_cuenta, debe, haber)` y
`Poliza` tampoco la trae, así que no hay forma de cruzar un importe perdido
con la geometría de su página sin cambiar el contrato. (El auxiliar sí:
`FilaAuxiliar` lleva `pagina` y `top`.) **Es un hueco de contrato, y por eso
paro aquí en vez de agregarle un campo al IR.**

Lo que sí se midió, y descarta la hipótesis de la 7c:

| Medición | `diario-general` |
|---|---|
| Renglones que abren cuenta → movimientos producidos | 24 821 → **24 821** |
| Pólizas sin ningún movimiento | **0** |
| Declarado − leído, **debe** | **+659 304.42** |
| Declarado − leído, **haber** | **−106 873.98** |

**No se pierden renglones enteros: se leen mal los importes.** Si faltaran
renglones, en el haber también faltaría; se lee de MÁS. La forma exacta de
las 100:

| debe | haber | pólizas |
|---|---|---|
| corto | ok | **88** |
| ok | corto | 6 |
| corto | **sobra** | 4 |
| sobra | sobra | 1 |
| sobra | ok | 1 |

Y el dato que señala el mecanismo: **22 movimientos traen `debe` y `haber`
distintos de cero a la vez**, cosa que en un libro diario no existe —un
renglón es cargo o abono, nunca los dos—, y **los 22 caen dentro de las 100
pólizas fallidas**. Un renglón se está tragando el importe del vecino.

Las fallidas además son pólizas **pequeñas**: mediana de 3 movimientos
contra 4 del total, máximo 14 contra 114. No es que las pólizas largas se
desborden.

Hipótesis viva, ya no refutada: **el importe se asigna a la columna
equivocada o lo absorbe el renglón contiguo**, que es justo lo que produce
el texto encimado del 21.9% de traslapes. La medición que la cerraría
—cruzar cada importe perdido con la zona de traslape de su página— necesita
que el diario conserve la página, y eso es cambiar el contrato del IR.
**No lo hice: es la pregunta que dejo abierta.**

#### Los tres guiones quedan en el repo

Las mediciones de esta fase están en `scripts/mediciones/`
(`fase8b_m1_subtotales.py`, `fase8b_m2_declarado_vs_leido.py`,
`fase8b_m3_forma_de_la_perdida.py`). No son tests: necesitan los PDFs
reales, que están en `.gitignore`. Se guardan porque en esta misma fase
estuve a punto de escribir en el PLAN las cifras de `diario-general`
atribuidas a `poliza.pdf`, de memoria; volver a correr el guion lo
descubrió. Una cifra que no se puede reproducir no es una medición.

#### Por qué SQLite y no ficheros JSON

Tres razones contra el problema real, no por gusto:

1. **Transaccional.** El worker escribe el estado mientras las peticiones
   lo leen. Con ficheros habría que inventar bloqueo, y una escritura
   interrumpida a las 21:00 deja un JSON roto — justo el caso que la fase
   viene a resolver.
2. **Consultar por despacho es una operación**, no recorrer un directorio.
   El aislamiento se implementa poniendo el `tenant` en el `WHERE`, no en
   un `if` posterior que alguien puede olvidar.
3. **Viene en la stdlib.** §0 pide no sumar dependencias que no hagan
   falta, y aquí no hace falta ninguna. Sin Redis ni Celery.

El estado `interrumpido` existe porque SERVIDORSIST se apaga a las 21:00.
Al abrir la base, todo lo que quedó en `procesando` pasa a `interrumpido`
con su motivo. Antes eso daba un 404, que confunde «nunca existió» con «se
murió a medias» — y le dice al usuario que su documento desapareció cuando
lo que pasó es que el servidor se apagó.

#### Qué significa y qué NO significa el aislamiento por despacho

El despacho llega **por la ruta** (`/t/<despacho>/…`), no por un login:
esta fase no trae autenticación, y el prompt pedía preguntar antes de
agregarla. Con eso, lo que se garantiza y lo que no:

| | |
|---|---|
| **Sí** | Un id de trabajo **no sirve fuera de su despacho**: el `tenant` va en el `WHERE`, así que adivinar un id ajeno da 404. Es lo que evita que una URL compartida por error entregue el documento de otro cliente. |
| **Sí** | Cada despacho aprende **sus** plantillas, en su propio directorio. |
| **Sí** | La lista de trabajos y las descargas solo muestran lo propio. |
| **No** | **No es una barrera de seguridad.** Quien escriba el nombre de otro despacho en la URL entra en su área. Sin login, el nombre del despacho es el único secreto, y no es un secreto. |

**Esta es la pregunta de la fase**: en una red local acotada donde las 15
personas del despacho son de confianza, ¿basta con la separación
organizativa, o hace falta login para que el aislamiento signifique algo?
No lo agregué porque no lo decido yo — pero mientras no lo haya, el
aislamiento hay que describirlo al cliente como «cada quien ve lo suyo», no
como «nadie puede ver lo ajeno».

#### La descarga sigue siendo de un solo uso

Se conservó la decisión de la 8a: en cuanto el Excel sale hacia el
navegador, el trabajo y su directorio se borran. Sobre la cola eso es
`Cola.olvidar(id, tenant=…)`, con el `tenant` en el `WHERE` por lo mismo
que en `buscar`. El barrido de 30 minutos sigue siendo la red de atrás, y
ahora también limpia los directorios sin trabajo en la base — los que deja
un proceso que murió antes de registrar.

### Resultados de la fase 8c (medir la máquina, e instalar)

#### El hallazgo que se llevó la fase por delante: los 3m57s eran de otra cosa

`auxiliar-gume` no tardaba 3m57s. **Tardaba 23m45s.** La cifra del PLAN se
midió con `time contapdf auxiliar <pdf>` **sin `-o`**, así que nunca
escribió el `.xlsx`. La capa web escribe siempre.

Medido, solo y en frío, con el reloj partido:

| `auxiliar-gume`, 886 págs, 57 759 renglones | antes |
|---|---|
| leer y validar | 182.3 s |
| **escribir el .xlsx** | **1 243.0 s (20m43s)** |
| total real de punta a punta | **23m45s** |

**La causa: el exportador era cuadrático.** `hoja[hoja.max_row]` estaba
dentro del bucle por renglón, y eso recorre la hoja entera **dos** veces
por renglón: una en `max_row`, y otra en el `max_column` que `hoja[n]` usa
por dentro (`__getitem__` → `iter_rows(..., max_col=self.max_column)`).
Bucle lineal × dos llamadas lineales = cuadrático.

Las tres mediciones que lo establecen, cada una descartando una explicación
más cómoda:

| Medición | Resultado | Qué descarta |
|---|---|---|
| `max_row` sobre hojas de 1 000 a 8 000 renglones | 0.040 s → 0.300 s por cada 1 000 llamadas | Que `max_row` sea O(1) |
| Exportar 1 000 / 2 000 / 4 000 renglones | 0.35 s → 1.22 s → 4.28 s (**3.5x por duplicación**) | Que sea lineal con constante alta |
| `auxiliar-gume` la primera vez contra sola y en frío | 1 429 s en las dos | Que fuera bajada de frecuencia por carga sostenida |

Esa tercera importa: la primera corrida puso `auxiliar-gume` al final de 32
minutos de trabajo continuo, y el PLAN §6 advierte que el i5-1335U es de
15 W y baja frecuencia. Era la hipótesis cómoda. Repetirlo en frío la mató.

**Estaba en tres bucles y afectaba a los cinco exportadores:** `_hoja` lo
usan pólizas, mayor, estado de cuenta y auxiliar; `exportar_balanza` tiene
el suyo; y la hoja `Validacion` la escriben los cinco. Un solo arreglo
—llevar el número de renglón en una variable y usar `hoja.cell()`, que es
O(1)— los cubre a los cinco.

Verificado **byte a byte**, comparando cada miembro del zip contra el
exportador de `HEAD` (fuera `docProps/core.xml`, que lleva la fecha):

| documento | antes | ahora | factor | idéntico |
|---|---|---|---|---|
| `balanza` | 0.11 s | 0.04 s | 2.6x | sí |
| `edocta` | 0.01 s | 0.01 s | 1.0x | sí |
| `mayor-gume` | 0.25 s | 0.09 s | 2.7x | sí |
| `auxiliar` | 14.22 s | 0.64 s | **22.1x** | sí |
| `poliza` | 20.86 s | 1.36 s | **15.3x** | sí |

El ahorro crece con el tamaño, que es lo que predice un término cuadrático.

Dos guardas nuevas en `tests/test_export_escala.py`. La estructural cuenta
los accesos a `max_row` y `max_column` y exige que **no crezcan** con los
renglones —exacta, milisegundos, va en la suite rápida—; la de escalado
mide tiempo y va marcada `lento`, por si un cuadrático vuelve por otra
puerta. Con el defecto, la estructural daba `[205, 805, 3205]` para 100,
400 y 1 600 renglones: dos recorridos por renglón, contados.

**La lección es de método, no de openpyxl.** El reloj se reporta desde
ahora SIEMPRE partido —leer+validar por un lado, exportar por otro— porque
un total único escondió esto durante nueve fases, y porque el número que
se citó en tres documentos medía media operación.

#### M1. Coste de la suite

| | tests | tiempo |
|---|---|---|
| Antes de la fase | 786 rápidos | **23m31s** |
| Solo con el exportador arreglado | 788 rápidos | 20m03s |
| **Después de marcar** | **701 rápidos** | **4m21s** |
| `pytest -m lento` | 111 | 32m41s |

**5.4x en el ciclo.** El arreglo del exportador puso 3m28s; el resto lo
puso el marcado, porque el grueso del coste no era exportar sino **volver
a parsear el mismo documento**: `poliza.pdf` se abre **26 veces** en la
suite, `auxiliar-gume` 11 y `auxiliar` 10.

Los cuatro ficheros que se llevaban el 67% del tiempo:

| fichero | antes | qué hace |
|---|---|---|
| `test_cobertura_aplicables.py` | 332 s | recorre los cinco tipos con el documento grande de cada uno |
| `test_cli_comandos.py` | 286 s | parametrizado sobre los cinco comandos |
| `test_cfdi_sin_folio.py` | 179 s | cinco tests, cada uno reparsea `poliza.pdf` |
| `test_movimiento_envuelto.py` | 141 s | ídem |

**El criterio de marcado, dicho como lo que es.** Ordenados por coste
medido, el corte natural está entre 14.25 s y 6.74 s —un hueco de 2.1x—,
pero marcar solo por encima de él deja la suite en 6m33s y **no cumple el
objetivo de 5 minutos**. El umbral está en 3 s porque es lo que baja de 5
minutos con margen. Es un reparto de presupuesto, no un hallazgo sobre los
datos, y se declara así para que nadie lo lea como un umbral defendible
del tipo del de CID.

Se marcó **caso por caso, no fichero por fichero**, donde el parametrizado
mezclaba documentos caros y baratos. La suite rápida sigue corriendo los
cinco comandos de punta a punta y los cinco exportadores; lo que se fue es
la repetición sobre los documentos grandes. Seis ficheros sí van enteros,
porque todos sus tests reparsean `poliza.pdf` o `auxiliar.pdf`.

**Dos cosas que la medición destapó y conviene no olvidar:**

1. **El coste de los fixtures compartidos se mueve, no desaparece.** Al
   deseleccionar tests, `test_el_libro_diario_sale_en_cuatro_hojas` pasó de
   ~1 s a 15.97 s: ya no encontraba `poliza.pdf` parseado por un fixture de
   sesión de otro test. Por debajo de ~4 s, lo que queda en la suite rápida
   es coste de fixture compartido, que marcar no quita: solo lo reubica.
2. **El total empeoró.** Rápida más lenta son 37m02s contra los 20m03s de
   correrlo todo junto, porque los fixtures de sesión se construyen dos
   veces. Se optimizó el ciclo —lo que se corre en cada cambio— a costa de
   la entrega. **No aislé la causa**; es la explicación que encaja, no una
   medición.

**Dispersión.** Dos corridas idénticas de la suite rápida dieron 358 s y
283 s: **27%**. Este disco es `/mnt/c` sobre NTFS bajo WSL2 y la caché de
páginas pesa. El 4m21s es de una corrida en caliente; en frío hay que
contar con más.

#### M2, M3 y M4: la línea base, y el hueco de SERVIDORSIST

**No hay acceso a SERVIDORSIST desde la sesión de desarrollo**: se entra
por Escritorio Remoto, no hay SSH y no se va a montar en esta fase. Lo que
se hizo fue dejar `scripts/medir_servidorsist.py`, que corre en Windows 10
con Python 3.12 usando **solo la stdlib más el repo** —la memoria por
`ctypes` contra `psapi`, no `psutil`— y que corre **igual en las dos
máquinas**, para que el factor salga del mismo instrumento y no de dos.

##### M2. Tiempo por documento (máquina de desarrollo, i5-1335U con SSD)

Los 17 fixtures que producen Excel, uno a uno, en frío, sin plantilla
aprendida, con el exportador ya arreglado:

| documento | tipo | págs | leer s | exportar s | total s | estrategia | xlsx MB |
|---|---|---|---|---|---|---|---|
| `edocta-bbva` | estado-cuenta | 11 | 0.6 | 0.0 | 0.6 | pdf_text | 0.02 |
| `edocta` | estado-cuenta | 6 | 0.7 | 0.0 | 0.7 | pdf_chars | 0.02 |
| `edocta-inbursa` | estado-cuenta | 8 | 0.8 | 0.0 | 0.8 | pdf_text | 0.02 |
| `balanza-businesspro` | balanza | 4 | 0.9 | 0.0 | 0.9 | pdf_chars | 0.02 |
| `edocta-santander` | estado-cuenta | 10 | 0.9 | 0.0 | 0.9 | pdf_text | 0.01 |
| `edocta-abril-santander` | estado-cuenta | 13 | 1.2 | 0.0 | 1.2 | pdf_chars | 0.03 |
| `balanza` | balanza | 9 | 1.3 | 0.0 | 1.4 | pdf_text | 0.03 |
| `edocta-bajio` | estado-cuenta | 11 | 1.4 | 0.0 | 1.4 | pdf_text | 0.02 |
| `edocta-julio-banorte` | estado-cuenta | 16 | 1.4 | 0.1 | 1.5 | pdf_text | 0.06 |
| `mayor-gume` | mayor | 17 | 2.2 | 0.1 | 2.3 | pdf_text | 0.07 |
| `balanza-gume` | balanza | 12 | 3.1 | 0.1 | 3.1 | pdf_text | 0.04 |
| `edocta-hsbc` | estado-cuenta | 4 | 14.7 | 0.0 | **14.7** | **ocr** | 0.01 |
| `auxiliar` | auxiliar | 398 | 14.4 | 0.6 | 15.0 | pdf_text | 0.45 |
| `poliza` | polizas | 968 | 26.7 | 1.1 | 27.8 | pdf_text | 0.83 |
| `mayor-proactivity` | mayor | 276 | 60.5 | 0.0 | 60.5 | pdf_text | 0.01 |
| `diario-general` | polizas | 431 | 60.7 | 3.4 | 64.1 | pdf_chars | 2.34 |
| `auxiliar-gume` | auxiliar | 886 | 183.4 | 5.2 | **188.5** | pdf_text | 3.55 |

| | total | leer | exportar |
|---|---|---|---|
| mínimo | 0.6 s | 0.6 s | 0.0 s |
| **mediana** | **1.5 s** | 1.4 s | 0.0 s |
| máximo | 3m08s | 3m03s | 5.2 s |
| suma de los 17 | **6m25s** | 6m14s | 10.6 s |

Antes del arreglo, esa misma suma era **32m06s**. Y una anomalía que queda
apuntada sin diagnosticar: **`mayor-proactivity` tarda 60.5 s con 276
páginas**, mientras `poliza` tarda 26.7 s con 968. Casi ocho veces más por
página que el documento más grande del proyecto. No es el exportador —su
`.xlsx` son 0.01 MB y 0.0 s—, es la lectura.

**El factor contra SERVIDORSIST, MEDIDO** (fase 8d). La corrió el
orquestador por Escritorio Remoto con el mismo `medir_servidorsist.py`, y el
fichero está en `scripts/mediciones/mediciones-ServidorSist-20260904-1757.txt`.
Midió **16 de los 17**: `edocta-hsbc` quedó fuera porque en esa sesión
Tesseract no estaba en el PATH.

| documento | desarrollo | SERVIDORSIST | factor |
|---|---|---|---|
| mediana de los **16 comunes** | 1.45 s | 5.15 s | 3.55x |
| `auxiliar` | 15.0 s | 51.9 s | 3.46x |
| `poliza` | 27.8 s | 99.1 s | 3.56x |
| `diario-general` | 64.1 s | 3m34s | 3.35x |
| `mayor-proactivity` | 60.5 s | 3m40s | 3.64x |
| `auxiliar-gume` | 188.5 s | **10m40s** | **3.40x** |
| `edocta-hsbc` (OCR, sin AVX2 allí) | 14.7 s | **no se pudo** | — |
| suma de los **16 comunes** | 6m11s | **21m16s** | **3.44x** |
| — de eso, leer y validar | 6m00s | 20m35s | 3.43x |
| — de eso, exportar | 10.6 s | 41.1 s | 3.88x |

> **Dos correcciones del orquestador sobre esta tabla, hechas contra el
> `.txt` y no de memoria.** La medición es mía y la transcripción es de
> Claude Code, así que la corrijo yo y lo digo aquí para que nadie la
> sobrescriba con la versión anterior. (1) La suma de exportar del fichero es
> **41.1 s**, no 41.3, y el factor **3.88×**, no 3.90. (2) La fila de la
> mediana decía `1.4 s → 5.2 s = 3.71×`, que es dividir dos cifras redondeadas
> a un decimal: las medianas exactas de los 16 son **1.45 s** y **5.15 s**, o
> sea **3.55×**. Esa fila cae además en el régimen que el propio párrafo de
> abajo declara ruidoso, así que **no debe citarse como el factor**; el factor
> es el de la suma, 3.44×. El 3.71 es la última descendencia del «3.7» que
> nunca tuvo una fila medida detrás. (3) El párrafo de abajo abría diciendo
> «el 3.4–3.7x es de los documentos grandes» y dos renglones después medía que
> caen entre 3.35x y 3.64x: se cambió el titular para que diga lo que mide su
> propio cuerpo.

**El factor se calcula sobre los MISMOS documentos, y por eso 3.31 no
existe.** Dividir los 21m16s de SERVIDORSIST (16 documentos) entre los
6m25s de desarrollo (17, con `edocta-hsbc` dentro) da 3.31x, y ese número
no mide nada: son denominadores distintos. Sacando `edocta-hsbc` de las dos
sumas, desarrollo son 6m11s y el factor **3.44x**. Es la cuarta vez en el
proyecto que un instrumento contamina su propia medición, y la primera en
que la contaminación es aritmética y no de shell.

**El factor estable es 3.35–3.64x, y es el de los documentos GRANDES.** Por documento el
factor va de **2.29x** (`edocta`, 0.7 s) a **4.03x** (`balanza-gume`,
3.1 s). Los cinco documentos que en desarrollo pasan de 15 s caen todos
entre **3.35x y 3.64x**; los de menos de 4 s se dispersan porque un reloj
de pared de 0.6 s no resuelve la diferencia. Donde el factor importa —los
documentos que bloquean la cola— es donde es estable.

**Consecuencia operativa, con los números ya medidos.** `auxiliar-gume`
tarda **10m40s** en la máquina objetivo, no los ~12 minutos que la 8c
estimó suponiendo 4x. Con la máquina apagándose a las 21:00 y el worker
secuencial, **un `auxiliar-gume` subido después de las 20:49 no termina**;
el checklist de despliegue de la 8c lo lleva como punto 3.

**El `edocta-hsbc` de SERVIDORSIST sigue sin medirse, y no por falta de
Tesseract.** Hay una segunda corrida, del mismo día a las 17:41, hecha en
modo rápido y **con Tesseract v5.4.0 presente**: ahí `edocta-hsbc` no se
saltó, **reventó a los 7.0 s**. Es el único fichero que respalda «el OCR
nunca funcionó allí» con Tesseract presente, y por eso vive con el resto en
`scripts/mediciones/mediciones-ServidorSist-20260904-1741-metodoRAPIDO.txt`
(estuvo en la raíz del repo hasta la 8e, donde se movió y se le puso un test
que impide que vuelva a quedarse suelto). La causa está diagnosticada y
arreglada más abajo, en los resultados de la 8d.

##### M3. Memoria (máquina de desarrollo)

| | |
|---|---|
| pico más alto | **658 MB**, en `auxiliar-gume` |
| RAM libre mínima mientras corría | 6 238 MB de 7 785 MB |

Coherente con los 543 MB que la 7d midió con otro instrumento; la
diferencia es que aquí se mide el `WorkingSetSize` del proceso entero,
incluido el intérprete.

**MEDIDO en SERVIDORSIST** (fase 8d), que es donde importa: allí hay 8 GB
compartidos con Apache y MySQL, y el PLAN §6 estima ~4.5 GB ocupados en
reposo.

| | desarrollo | SERVIDORSIST |
|---|---|---|
| RAM total | 7 785 MB | 8 078 MB |
| RAM libre antes de empezar | 6 832 MB | 3 205 MB |
| **RAM libre mínima, durante `auxiliar-gume`** | 6 238 MB | **2 809 MB** |
| pico del proceso | 658 MB | **no se pudo leer** |

**La memoria no es una restricción.** En el peor momento de la corrida
entera quedaban 2 809 MB libres, y el documento que lo produce es el más
grande del proyecto. La caída de RAM libre durante `auxiliar-gume` fue de
**396 MB** (3 205 → 2 809).

Dos advertencias sobre esas cifras, porque miden cosas distintas:

- **El pico del proceso no se midió en Windows.** El instrumento lee el
  `WorkingSetSize` por `ctypes` contra `psapi` y en esa corrida devolvió
  vacío; el fichero lo dice («No se pudo leer la memoria en esta
  plataforma») en vez de rellenar la columna. Los 658 MB son de desarrollo.
- **396 MB de caída no son 658 MB de pico.** La RAM libre del sistema y el
  working set del proceso no son la misma magnitud: el sistema cede caché
  de páginas mientras el proceso crece. Lo que la corrida establece es la
  holgura —hay de sobra—, no el consumo del proceso allí.

##### M4. Disco (medido en desarrollo, extrapolado a un día)

Medido:

| | |
|---|---|
| `.xlsx` generados, 17 | mínimo 0.01 MB, mediana **0.03 MB**, máximo **3.55 MB** |
| PDFs de entrada | mediana 0.49 MB, máximo 7.61 MB |
| base de la cola con 75 trabajos terminados | **0.17 MB** |

La base se llenó con resúmenes de cobertura **reales**, no con un
diccionario de relleno: el resumen es lo que ocupa.

**Lo mismo, medido en SERVIDORSIST** (fase 8d). Coincide hasta el decimal,
que es lo esperable: un `.xlsx` pesa lo que pesa en cualquier disco.

| | desarrollo | SERVIDORSIST |
|---|---|---|
| `.xlsx` generados | 17 | 16 (falta `edocta-hsbc`) |
| mediana del `.xlsx` | 0.03 MB | **0.03 MB** |
| máximo | 3.55 MB | **3.55 MB** |
| PDFs de entrada, mediana | 0.49 MB | 0.47 MB |
| base de la cola, 75 trabajos | 0.17 MB | **0.17 MB** |
| **disco libre en la máquina** | 71.9 GB de 474.1 GB | **328.3 GB de 464.8 GB** |

**El disco no es una restricción, ahora medido y no supuesto**: el techo
extrapolado de un día entero sin barrido son 266 MB, contra 328 GB libres.
Tres órdenes de magnitud.

**Extrapolado** —y se dice que es extrapolación— a los 75 documentos al día
del PLAN §6 (15 personas × 5):

| | |
|---|---|
| `.xlsx` de un día, con la mezcla de los fixtures | ~2 MB |
| si los 75 fueran como el mayor | 266 MB |
| PDFs subidos en un día | ~37 MB, borrados al terminar cada uno |
| base de la cola | 0.17 MB al día, ~42 MB al año si nada se borrara |

**Lo que ocupa en un momento dado es mucho menos**: el barrido de 30
minutos borra cada trabajo terminado y la descarga lo borra antes, así que
el pico real es lo que quepa en media hora, no un día. Las cifras de
arriba son el techo si el barrido no existiera. Con eso, **el disco no es
una restricción**: ni el peor día se acerca a los 328 GB libres de esa
máquina (464.8 GB de disco, medidos en la corrida del 4 de septiembre; los
«466 GB» que decía esta línea eran de memoria, no de la medición).

#### El `-o` con un directorio inexistente: peor de lo que parecía

No solo reventaba con una traza de siete niveles desde `zipfile`. **Salía
con código 1**, y en este CLI el 1 significa «hay discrepancias que
revisar»: para cualquier guion, un `-o` mal escrito era indistinguible de
un documento que no cuadra.

Y reventaba **al ir a guardar**, con el documento ya procesado. Sobre
`auxiliar-gume` eso eran 24 minutos tirados por una letra.

Se decidió **avisar y no crear el directorio**, y sobre todo **comprobarlo
antes de trabajar**:

- Crear lo que nadie pidió esconde el error: con una letra cambiada, el
  Excel acabaría en un directorio nuevo y el usuario lo buscaría donde
  creía haberlo escrito.
- El argumento a favor de crearlo era no perder el trabajo ya hecho, y se
  cae solo en cuanto la comprobación ocurre antes de empezar.
- Sale con **código 2**, que es el que este CLI usa para «no se pudo
  procesar».

```
$ contapdf balanza balanza.pdf -o /tmp/no-existe/x.xlsx
/tmp/no-existe: el directorio no existe.
  Crealo primero, o apunta -o a uno que ya exista.
$ echo $?
2
```

El test que asegura el ORDEN no mide tiempo: manda un fichero que no es un
PDF y comprueba que el mensaje habla del directorio y no del documento. Si
la comprobación llegara tarde, hablaría del documento.

#### `pypdfium2` no estaba declarado

`extract/ocr.py` hace `import pypdfium2`, pero no estaba en las
dependencias de `pyproject.toml`. En la máquina de desarrollo estaba
instalado de antes, así que **nueve fases no lo notaron**. En una máquina
limpia, `pip install -e .` no lo trae y el OCR falla al importar el módulo.
Se declaró. Es el tipo de cosa que solo aparece cuando se instala de cero,
que es justo lo que esta fase vino a hacer.

`pypdfium2` es un binding de PDFium y no necesita AVX2, así que sirve en el
i5-3470. No hay ningún otro obstáculo de instalación conocido.

#### Checklist de despliegue: lo que falta antes de que el despacho lo use

Enumerado, no resuelto.

1. **Autenticación.** Cualquiera en la red de la oficina puede subir y
   descargar cualquier documento; el nombre del despacho es el único
   separador y no es un secreto. §5.1 lo deja como decisión del dueño del
   despacho, no técnica. **Es lo primero: los documentos son de clientes de
   terceros.**
2. **Respaldo.** Un solo disco mecánico de 2012, sin redundancia. §5.1 lo
   llama el riesgo más grande del despliegue. Lo medido en la 8c lo acota:
   el volumen es pequeño —~2 MB de Excel al día, 0.17 MB de base de cola—,
   así que **el respaldo es barato de hacer**; lo que falta es decidir a
   dónde y cada cuánto.
3. **Un trabajo en curso a las 21:00.** La máquina se apaga y el trabajo
   muere. La cola lo marca `interrumpido` al arrancar y lo dice (8b), pero
   **no lo reanuda**: hay que volver a subir el documento. Con los números
   de la 8c eso importa más de lo que parecía: si el factor de SERVIDORSIST
   es 4x, `auxiliar-gume` allí ronda los 12 minutos, así que **cualquier
   documento grande subido después de las 20:45 se pierde**. Falta decidir
   si se avisa en pantalla a partir de cierta hora, si se rechaza, o si no
   se hace nada.
4. **Ventana de uso acordada con el personal.** La máquina está encendida
   de 8:00 a 21:00 y el worker es secuencial. Con la mediana de 1.5 s los
   75 documentos del día caben de sobra, pero **un solo `auxiliar-gume`
   bloquea la cola varios minutos** y quien esté detrás espera. Falta
   acordar si los documentos grandes van a una hora concreta.
5. **Servidor de producción.** Hoy se arranca el servidor de desarrollo de
   Flask a mano, en una consola que alguien puede cerrar. Falta decidir
   entre un servidor WSGI (waitress) y un proxy de Apache — y lo segundo
   toca la configuración de Apache, que esta fase tenía prohibido tocar.
6. **Los PDFs de prueba en SERVIDORSIST.** Para medir hay que copiar allí
   los fixtures reales, que son documentos de clientes. Falta borrarlos
   cuando la medición termine.

### Resultados de la fase 8d (los defectos que destapó comparar salidas)

Cuatro defectos de correctitud, cada uno con su arreglo y su suite verde
entre uno y otro, más cuatro mediciones que no se arreglaron.

#### Objetivo 1. Una regla que no evaluó nada ya no puede cuadrar

La 7f prohibió `aplicables is None` con `CUADRA` y no `evaluados == 0`, y
por ese hueco `mayor-proactivity` reportaba `saldo_mensual 0 de 48 → cuadra`
y `acumulados 0 de 96 → cuadra`, con el encabezado «0 de 145 casos
evaluados; 2 cuadran».

Lo impide ahora `ResultadoRegla.__post_init__`, que **lanza**, igual que con
`aplicables`. No es una conversión silenciosa a `no_verificable`: una regla
sin veredictos tiene que decir POR QUÉ no los tiene, y una democión
automática no sabe el motivo. `_resultado()` devuelve `no_verificable` con
el motivo ya escrito.

**Barrido de los 27 fixtures, antes y después**, con
`scripts/mediciones/fase8d_reglas_sin_evaluar.py`: 17 procesan y 10 salen
por `LayoutDesconocido` o `ReporteNoEsperado`, que es lo correcto y no
cambió.

| | antes | después |
|---|---|---|
| reglas con `evaluados == 0` | 18 | 18 |
| de esas, en `CUADRA` | **2** | **0** |
| documentos afectados | 1 (`mayor-proactivity`) | 0 |

Las otras **16 ya eran `no_verificable`**, así que el hueco era exactamente
de dos reglas en un documento. **Ninguna otra medición de esta sección se
movió**: el diff de los resúmenes de los 17 documentos tiene una sola línea,
la de `mayor-proactivity`, y **ningún conteo cambió** — sigue diciendo 0 de
145. Lo que cambió es que ya no lo llama cuadrar.

| `mayor-proactivity` | antes | después |
|---|---|---|
| resumen | 2 cuadran, 0 fallan, 1 no verificable | **0 cuadran, 0 fallan, 3 no verificables** |
| casos | 0 de 145 | 0 de 145 |

#### Objetivo 2. El OCR nunca funcionó en Windows, y la causa no era la que se leyó

`ocr.py` lanzaba Tesseract con `text=True` y **sin `encoding`**, así que
`subprocess` decodificaba con el default del sistema. En Linux ese default
es UTF-8 y no se nota; en un Windows en español es cp1252.

La cadena completa, ya reproducida en un test:

1. Tesseract en español imprime comillas tipográficas. `”` es U+201D, que
   en UTF-8 son los bytes `E2 80 9D`.
2. **El byte 0x9D no existe en cp1252.** Decodificar ahí lanza
   `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d`, que es
   literalmente el error de SERVIDORSIST.
3. El error ocurre **dentro del hilo lector** de `subprocess`. `communicate()`
   hace `stdout = stdout[0] if stdout else None` sobre un búfer que quedó
   vacío, así que devuelve `stdout=None` **sin propagar la excepción**.
4. `_tsv_a_palabras(None, …)` estalla con `AttributeError: 'NoneType' object
   has no attribute 'splitlines'`.

Los pasos 3 y 4 no son deducción: están en `subprocess.py` de la stdlib
—`_readerthread` hace `buffer.append(fh.read())`, y la rama Windows de
`_communicate` cierra con `stdout = stdout[0] if stdout else None`—, así
que un búfer que quedó vacío porque el hilo murió sale como `None`.

**El AttributeError es el paso 4 de una cadena de cuatro**, y es lo único
que aparecía en la traza. Se interpretó mal dos veces. El paso 3 es lo que
hace invisible la causa: `subprocess` convierte un error de decodificación
en un `None` silencioso.

Dos cambios: la codificación va **declarada** (`encoding="utf-8"`,
`errors="replace"` — un glifo ilegible es una palabra sucia, no un documento
perdido), y una salida vacía o `None` con código 0 lanza `TesseractSinSalida`
nombrando la página, en vez de reaparecer dos capas más abajo.

**El mismo defecto estaba en el instrumento de medición.**
`scripts/medir_servidorsist.py` lanza `tesseract --version` y
`--list-langs` igual, y corre precisamente en Windows: podía reportar una
versión en blanco o un «falta el idioma spa» falso. Arreglado en la misma
pieza.

**Ningún test podía cubrir esto, porque la suite corre en WSL.** Los que
hay ahora fuerzan la CONDICIÓN y no la plataforma: uno comprueba que esos
bytes UTF-8 **no** se pueden decodificar en cp1252 —la premisa, en código, y
sin ella los demás no prueban nada—, otro corre un subproceso de verdad que
los emite y exige que vuelvan íntegros, y dos más simulan `stdout` en `None`
y en blanco y exigen el error con nombre propio.

**Lo que esto NO verifica.** `edocta-hsbc` sigue procesándose bien aquí
—4 páginas, 3 movimientos, saldo al corte 5 195.60, código 0, idéntico a lo
que la 7d midió— pero **eso ya funcionaba antes del arreglo**: en Linux el
defecto no se manifiesta. **Que `edocta-hsbc` procese en SERVIDORSIST está
sin verificar y hay que probarlo allí**, volviendo a correr
`medir_servidorsist.py` con Tesseract en el PATH. Es el único criterio de
esta fase que no se puede cerrar desde la sesión de desarrollo.

#### Objetivo 3. La hoja `Polizas` llevaba una cifra y la regla otra

Medido otra vez en la 8d antes de tocar nada, y confirmando la 8b:

| | `poliza.pdf` | `diario-general` |
|---|---|---|
| pólizas | 1 944 | 5 302 |
| movimientos | 6 783 | 24 821 |
| con `completa = False` por bloque cortado | **0** | **0** |
| sin totales declarados | **0** | **0** |
| sin ningún movimiento leído | **0** | **0** |
| **declarado ≠ leído** | **0** | **100** |
| fallas de `partida_doble` | 0 | 100 |
| ¿son las mismas 100? | — | **sí, conjuntos idénticos** |

Que las cuatro primeras filas salgan en cero es lo que permitió decidir sin
suponer: en los dos documentos completos **el único motivo por el que una
póliza puede no cuadrar es que el importe se leyera mal**.

La hoja lleva ahora `total_debe_declarado`, `total_debe_leido`,
`total_haber_declarado` y `total_haber_leido`, y `completa` es VERDADERO
solo cuando el bloque cerró **y** las dos cifras coinciden. Verificado:
`diario-general` saca **100 pólizas con `completa = FALSO`**, y las 100 de
`partida_doble` están dentro. Un test lo exige — que la hoja no pueda verse
correcta donde la regla encontró un descuadre.

Tres decisiones que conviene dejar dichas:

- **`Poliza.completa` NO cambió.** Sigue significando «el bloque cerró
  dentro de lo leído», que es lo que `partida_doble` usa para excluir
  pólizas cortadas. Redefinirlo habría sacado las 100 del denominador y
  **habría hecho desaparecer las 100 fallas**: el defecto se taparía en vez
  de verse. Lo que cambia es la columna del Excel, que es una salida.
- **La suma leída vive en `LibroDiario.totales_leidos()`**, no en el
  exportador. Si la hoja y la regla la derivaran cada una por su cuenta,
  se separarían en la primera corrección — que es exactamente el defecto
  que esta pieza viene a cerrar.
- **Sin cifra declarada, `completa` es FALSO.** No hay con qué comparar, y
  no se afirma lo que no se comprobó. El caso no existe en ningún fixture
  completo; sí aparece leyendo rangos de páginas.

**El mismo patrón en los otros cuatro exportadores: medido, no arreglado**
(`scripts/mediciones/fase8d_m6_declarado_en_los_otros_cuatro.py`).

| exportador | ¿enseña declarado sin lo leído? | ¿difieren hoy? |
|---|---|---|
| **mayor** | **sí**: `Cuentas` lleva `saldo_final`, `total_cargos` y `total_abonos`, que se LEEN del último mes, y `Meses` los movimientos | **sí: 1 de 49 cuentas** en `mayor-gume` |
| **estado de cuenta** | **sí**: `Cuentas` lleva `depositos`, `retiros` y `saldo_corte` del resumen; `Movimientos` los leídos | no en los 4 fixtures medidos (0 de 5 cuentas); 2 sin desglose ya salen en `None` |
| **auxiliar** | **variante distinta**: la hoja **no exporta `saldo_origen`**, así que un saldo recalculado se ve idéntico a uno impreso | en `auxiliar-gume`, **26 032 de 57 759 saldos son recalculados** (22 713 impresos, 9 014 sin saldo) y la hoja no lo dice |
| **balanza** | **no**: la fila `Totales` que el documento declara **no se exporta**; la hoja solo lleva `balanza.filas` | declarado y leído coinciden exacto (26 956 489.26 en los dos lados) |

El del **mayor** es el mismo defecto con otro documento y ya tiene un caso
real. El del **auxiliar** es más grave de lo que parece: `Cobertura` separa
`exactas_impresas` de `exactas_recalculadas` desde la 7h precisamente
porque comprobar un saldo derivado con la fórmula que lo derivó es una
tautología, y el Excel entrega los 26 032 sin marca alguna. **No se
arreglaron: son otra fase.**

> **Los tres se cerraron en la 8e**, más abajo: la hoja `Auxiliar` exporta
> `saldo_origen`, y `mayor` y `estado-cuenta` llevan sus totales partidos en
> declarado y leído. **`balanza` sigue igual**, porque no exporta la fila
> `Totales` y ahí no hay contradicción posible — pero tampoco exporta
> `naturaleza_origen`, que es el mismo invariante de procedencia en otra
> hoja, y eso sigue abierto.

#### Objetivo 4. `Movimiento` gana `pagina`

Aditivo, con `0` por defecto. Lo llena la página del renglón que trae los
**importes**, que en un movimiento envuelto no es la que abrió la cuenta.
Sale a las hojas `Movimientos` y `Plana` del Excel de pólizas, igual que en
el auxiliar y el estado de cuenta. Con esto **deja de estar bloqueado** el
cruce de un importe mal leído con la zona de traslape de su página, que es
lo que la 8b no pudo medir y lo que hace falta para la segunda mecánica de
`diario-general`.

#### M1. `mayor-proactivity` no es un libro mayor

Diagnosticado por capas, que es lo que la pregunta pedía separar:

| capa | veredicto |
|---|---|
| **estrategia** | **correcta.** `pdf_text`, con 0 tokens contaminados, 0 palabras traslapadas y 0.0 de fracción CID sobre 652 palabras de muestra. El texto sale legible: `'Libro mayor ene. 2026 PRO ACTIVITY BUSINESS Diarios: EGRESOS, CHEQUES, ACTINVER, S.A. #19342757 - BCO7, …'` |
| **layout** | **síntoma, no causa.** Detecta 8 columnas y 3 de monto, y le pone a la columna de texto el encabezado `'OSCAR CH.3711 GARCIA BCO4. (CAJA JOSE CHICA MARTINEZ…'` — o sea, etiqueta tomada de datos porque no hay fila de encabezado que tomar |
| **parser** | **la causa** |

**El documento no es un libro mayor: es un reporte de movimientos por
cuenta.** Sus renglones son `folio | fecha | concepto | cargo | abono |
saldo`, la forma de un auxiliar. No imprime meses, y `MayorParser` está
construido sobre el mes: `_es_mes` mira si el primer token del renglón es
un nombre de mes. **En las 8 primeras páginas hay 0 renglones así.**

Los 48 «meses» que sí aparecen en las 276 páginas son **falsos positivos de
`_orden_de`**, que compara con `normalizar()` y `normalizar()` **quita la
puntuación**: `_orden_de('(ENERO')` devuelve 1. Un `(ENERO` suelto dentro
de una descripción se convierte en el mes de enero. La prueba está en la
forma de los 48:

- salen de páginas dispersas (45, 52, 55, 109, 110, 152) y en orden
  desordenado (5, 2, 5, 9, 1, 1) — un mayor de verdad los da 1..12 seguidos
  por cuenta;
- **los 48 traen cargos, abonos y saldo todos en cero o `None`**;
- el documento entero produce **1 sola cuenta**, contra las 49 que
  `mayor-gume` produce en 17 páginas;
- esa única cuenta sale con `naturaleza=''` y `nombre_cuenta='Puebla, PUE
  BANCOMER #0194515218 - BNK4, BBVA USD #0125318289 - BNK8, CHEQUES GTO -'`,
  que es el bloque de bancos del encabezado de página, impreso a la derecha
  (x 549–818) y arrastrado por el renglón que abre la cuenta.

Es el mismo modo de falla que esta fase persigue en el objetivo 1, un piso
más abajo: no una regla que cuadra sin evaluar, sino **un parser que
entrega sin haber leído**.

> **CORRECCIÓN (fase 8e): esta sección decía que el `(ENERO` «no es un
> adorno del defecto: es el defecto», y eso es falso.** Lo escribí en la 8d
> desde el mecanismo, sin contar los casos. Contados en la 8e
> (`scripts/mediciones/fase8e_m2_meses_con_puntuacion.py`): de los **50**
> renglones que `_orden_de` acepta en `mayor-proactivity`, **solo 2 traen
> puntuación** (`'(ENERO'` y `'(SEPTIEMBRE'`). Los otros **48 traen el
> nombre del mes LIMPIO** —`DICIEMBRE`, `ENERO`, `FEBRERO`, `MAYO`,
> `SEPTIEMBRE`— dentro de descripciones. Endurecer `_orden_de` quitaría 2 y
> dejaría 48: **no arregla nada**. El falso positivo del paréntesis es real
> y el mecanismo estaba bien descrito; **la magnitud estaba mal**, y con
> ella la conclusión de qué hay que tocar. Es la tercera vez en el proyecto
> que un mecanismo correcto se toma por explicación suficiente sin medir
> cuántos casos cubre — después de los 563 subtotales de la 8a y de la
> mecánica de `diario-general` en la 8b.
>
> De paso queda medido que **endurecer `_orden_de` no es gratis**:
> `mayor-gume` trae sus **588 de 588** renglones de mes con el nombre
> limpio, así que hoy no rompería nada, pero es cambiar una función que
> acierta al 100% en el único mayor bueno para arreglar el 4% de los falsos
> positivos del malo. Se deja **medido y sin tocar**; lo que se hizo en su
> lugar es la guarda del objetivo 3 de la 8e.

Y por eso `mayor-proactivity` **no debe contar como uno de «los 17 que
procesan»**: 220 s en SERVIDORSIST para no producir nada utilizable.

#### M2. Los tres números de `jerarquia` sí se explican, y el 4 es correcto

| | `balanza` | `balanza-businesspro` |
|---|---|---|
| padres distintos referidos por alguna fila | 28 | 24 |
| **aplicables** (×2, debe y haber) | **56** | **48** |
| padres presentes en el documento y con hijas | 26 | 23 |
| **evaluados** (×2) | **52** | **46** |
| **sin evaluar** | **4** | **2** |
| padres referidos que NO aparecen | 2 (`100`, `200`) | 1 (`0500-0001-0421`) |
| padres presentes pero sin hijas | **0** | **0** |

`28 − 26 = 2 = len(huérfanos)`, y `2 × 2 = 4`. **El 4 es correcto** y no hay
un segundo hueco escondido: no existe ni un padre presente sin hijas, así
que la única fuente de casos sin evaluar son los huérfanos.

**Y las «2 filas» del filtro también.** `100` y `200` no existen como
cuenta; lo que sale al filtrar son las filas que las **declaran padre**:
`100-01` y `200-01`, una cada una. La confusión es de lectura, no del
conteo: el motivo nombra **las cuentas padre que faltan**, y el filtro
encuentra **las hijas que las echan de menos**. Son dos cosas distintas con
el mismo número. La unidad de `aplicables` es la comprobación
(padre × campo), no la fila.

#### M3. El arreglo de `cfdi_cruzado` llegó a la web y a ningún otro sitio

Las 53 discrepancias de `cfdi_cruzado` en `poliza.pdf` traen **las 53**
`esperado == obtenido == 0`. Las tres salidas del sistema formatean esa
misma `Discrepancia` así:

| salida | qué escribe |
|---|---|
| web (`vista.py`) | `numerica: False`, `esperado: ''`, `obtenido: ''` |
| **CLI** (`cli.py:141`) | `! P00041  cfdi_cruzado  esperado 0.00   obtenido 0.00` |
| **Excel** (`excel.py`, bloque de detalle de `Validacion`) | `esperado=0  obtenido=0` |

O sea: no es que el arreglo llegara solo al camino de la web y le faltara el
Excel. **Llegó solo a la web, y le faltan los otros dos.**

**Por qué no se puede unificar copiándolo.** Lo que hace `vista.py` es una
**inferencia**: `numerica = d.esperado != d.obtenido`. Funciona, pero
deduce desde el valor lo que la regla sabía y no pudo declarar, porque
`Discrepancia.esperado`/`obtenido` son `Decimal` **obligatorios** y una
regla que cruza identidades no tiene dónde decir «aquí no hay importe»:
rellena los dos con cero. Copiar la inferencia a `cli.py` y a `excel.py`
serían tres sitios deduciendo lo mismo, y la próxima corrección volvería a
llegar a uno solo.

**Lo que haría falta**: que la `Discrepancia` lo DECLARE en vez de que cada
salida lo adivine — `esperado`/`obtenido` como `Decimal | None`, con `None`
significando «esta regla no compara importes», o un campo que diga qué tipo
de comprobación es. Con eso las tres salidas leen el mismo dato y ninguna
decide por su cuenta. Es un cambio de contrato del IR de validación, y por
eso se mide y se deja propuesto, no hecho.

#### M4. `P00476` son dos comprobantes, no un doble conteo

| | |
|---|---|
| discrepancias de `poliza.pdf` | 53 |
| **filas distintas** | **50** |
| filas que salen más de una vez | **3**: `P00476`, `P01494`, `P01495`, las tres ×2 |

Las dos apariciones de `P00476` vienen las dos de `cfdi_cruzado`, y la
póliza tiene **dos CFDI distintos** —`000007831684` y `000007795808`, con
UUID distintos— y **ninguno de los dos** cruza contra su descripción
(`COBRO POR TASA DE DESCUENTO AFIL.-009378824`). **Son dos comprobantes
fallando por separado. No hay doble conteo.**

**Pero destapa un error de unidad en §5.1**, que dice «53 pólizas fallan
`cfdi_cruzado`». No son 53 pólizas: son **53 CFDI sobre 50 pólizas**. La
regla cuenta CFDI —su `aplicables` es `len(libro.cfdi)`—, así que el 53 es
correcto y la palabra «pólizas» no. Lo mismo vale para la frase del
checklist: lo que el contador revisa son 53 renglones de comprobante.

### Resultados de la fase 8e (que las tres salidas digan lo mismo)

El hilo es uno solo: el sistema entrega por CLI, Excel y web, y hasta esta
fase las tres no decían lo mismo del mismo caso. Cinco piezas, cada una con
su rojo antes de implementar y la suite verde entre una y otra.

#### Objetivo 0. La evidencia del fallo del OCR, donde se la puede encontrar

`mediciones-ServidorSist-20260904-1741-metodoRAPIDO.txt` estaba en la raíz
del repo. Es el único fichero que documenta el fallo **con Tesseract
presente** (v5.4.0, `edocta-hsbc` revienta a los 7.0 s), o sea la única
evidencia reproducible de «el OCR nunca funcionó allí». Movido a
`scripts/mediciones/`, con un test que falla si vuelve a aparecer un
`mediciones-*.txt` suelto en la raíz y otro que comprueba que el fichero
sigue conteniendo la traza — porque lo que respalda la afirmación es el
contenido, no el nombre.

#### Objetivo 1. La hoja `Auxiliar` dice qué saldos calculó el sistema

`ARQUITECTURA.md` §4 impone que un valor derivado declare su procedencia, y
`FilaAuxiliar.saldo_origen` lo hacía — pero la hoja no lo exportaba. En
`auxiliar-gume` eso son **26,032 de 57,759 saldos** que el sistema encadenó
y que en el Excel se veían idénticos a los impresos. El invariante se
cumplía en el dato y se rompía justo en la salida que ve el contador.

| `auxiliar-gume` | filas |
|---|---|
| `impreso` | **22,713** |
| `recalculado` | **26,032** |
| `sin_saldo` | **9,014** |
| **suma** | **57,759** |

`auxiliar` sale con 6,783 impresos y **0 recalculados**: el documento
imprime todos sus saldos y no hay nada que derivar. Ninguna cobertura se
movió — `saldo_corrido` sigue en 47,987 de 57,024 con 26,032 exactas
recalculadas.

**Por qué columna propia y no un `saldo` partido en dos.** El patrón de la
hoja `Polizas` —declarado y leído en columnas separadas— no aplica aquí:
allí hay **dos cifras que existen a la vez** y aquí hay **una cifra y su
procedencia**. Un saldo es impreso o recalculado, nunca los dos, así que
partirlo dejaría siempre una columna vacía, representaría una procedencia
como si fueran dos magnitudes y rompería a quien suma `saldo`. Va **pegada
a `saldo`** y no al final: la procedencia lejos del dato obliga a cruzar dos
columnas para leer una sola cosa.

**Lo que sigue roto y no se tocó**: `FilaBalanza.naturaleza_origen` tampoco
se exporta, y hay un test de la fase 4 que lo exige así («duplica el ancho
de la hoja y el contador la ignora»). No es lo mismo —una naturaleza
derivada es una etiqueta, un saldo recalculado es dinero que el sistema
fabricó— pero es el mismo invariante en otra hoja. Medido, no resuelto.

#### Objetivo 2. Declarado contra leído en `mayor` y `estado-cuenta`

El mismo defecto que la 8d cerró en la hoja `Polizas`, en dos hojas más.
Medido campo por campo antes de tocar nada
(`scripts/mediciones/fase8e_m1_declarado_vs_leido_mayor_edocta.py`):

| `mayor-gume`, 49 cuentas | difieren |
|---|---|
| `total_cargos` | **1** (`1190-000-000`: declarado 37,398,127.31 contra 37,398,127.32 leído) |
| `total_abonos` | 0 |
| `saldo_final` | 4 (`1190`, `1201`, `1215`, `3400`, todas por ±0.01) |

| estados de cuenta | cuentas | difieren |
|---|---|---|
| `edocta`, `edocta-bbva`, `edocta-julio-banorte`, `edocta-bajio` | **5** | **0** |

Se partieron `total_cargos`/`total_abonos` y `depositos`/`retiros`, con las
sumas leídas en `Mayor.totales_leidos()` y `EstadoCuenta.totales_leidos()`
—en el objeto de dominio, no en el exportador, por lo mismo que en pólizas—.

**`saldo_final` y `saldo_corte` NO se partieron, y la razón importa.** El
saldo del último mes **ya es** el declarado (`_cerrar` lo toma de ahí), así
que la única cifra contrastable es una que el sistema encadena. Una columna
`_leido` tiene que significar lo mismo en las tres hojas —lo que se leyó del
documento— y un saldo encadenado no es eso. Y sobre todo: **las 4 cuentas
donde difiere son exactamente las 4 que `saldo_mensual` reporta `dentro de
tolerancia`** (`1190-000-000 DICIEMBRE`, `1201-000-000 FEBRERO`,
`1215-000-000 AGOSTO`, `3400-000-000 ENERO`) — verificado, conjuntos
idénticos. Exportarlo haría que la hoja `Cuentas` enseñara en crudo cuatro
diferencias de un céntimo que `Validacion` reporta como cuadradas: la
contradicción entre salidas que esta fase viene a cerrar, reintroducida por
el otro lado.

**Y la comprobación simétrica, que es la que faltaba hacer.** Si la hoja
enseña una diferencia que ninguna regla menciona, la contradicción es la
misma en la otra dirección. Medido: la identidad que sí se exporta —el total
declarado contra la suma de los meses— **la evalúa `acumulados`**, que
comprueba `acum[n] == acum[n-1] + movimiento[n]` encadenado desde cero, y
`1190-000-000` está nombrada en su lista de `con_tolerancia`. Un test lo
amarra: toda cuenta que la hoja marque como distinta tiene que estar
nombrada por alguna regla de `Validacion`.

La correspondencia **no es 1:1** como en pólizas (100 = 100): `acumulados`
roza en 5 renglones de 4 cuentas y solo una tiene el total descuadrado. Lo
que se exige es la dirección que importa — que la hoja no enseñe nada que la
cobertura calle —, no la igualdad de los dos conjuntos.

#### Objetivo 3. `mayor-proactivity` falla limpio

```
$ contapdf mayor fixtures/real/5-Libro-Mayor/mayor-proactivity.pdf
fixtures/real/5-Libro-Mayor/mayor-proactivity.pdf: no_reconocido
  no se pudo leer como mayor: se detectaron 48 renglones de mes y ninguno
  trae cargos, abonos ni saldo; el documento no parece un libro mayor
$ echo $?
2
```

La guarda es `_sin_un_solo_importe(meses)`, a nivel de **documento** y sobre
el **dato**: si ningún renglón de mes de todo el documento trajo cargos,
abonos, saldo ni acumulados, no se leyó nada. Con un solo importe en
cualquier mes no dispara.

| | meses | con importe no nulo ni cero | con acumulado |
|---|---|---|---|
| `mayor-gume` | 588 | **303** | 294 |
| `mayor-proactivity` | 48 | **0** | 0 |

**Un cero no cuenta como importe**: un mes en ceros es un mes sin leer, no
un mes leído que vale cero. `mayor-gume` tiene 285 así y pasa igual — dato
que conecta con el hallazgo de §1.3 sobre reglas que corren sobre casos
vacíos: casi la mitad de sus meses no prueban nada.

**Tres criterios que se descartaron, y por qué.** No se eligió el que
parecía obvio:

- **Endurecer `_orden_de`** para que rechace `'(ENERO'`: quita 2 de los 50
  candidatos y deja 48. **No arregla nada** —ver la corrección de M1 de la
  8d, más arriba— y cambia una función que acierta en los 588 renglones del
  único mayor bueno sin un caso que lo pida.
- **Más de 12 meses por cuenta** (`mayor-gume` máx 12, `proactivity` 48):
  discrimina, pero es un criterio de forma con un solo fixture detrás — el
  mismo defecto que se está rechazando.
- **`orden` repetido dentro de una cuenta** (0 contra 43): igual de fuerte,
  pero no detecta nada que la guarda elegida no detecte ya, y **un mayor
  legítimo leído por rango de páginas puede empezar en septiembre y repetir
  meses entre cuentas**.

El elegido no cuenta meses ni exige orden: solo afirma lo que se ve, que no
se leyó ni una cifra. **No es el arreglo de `_es_mes`**, que sigue aceptando
un nombre de mes al principio de cualquier renglón de descripción; es una
guarda para fallar limpio.

`mayor-gume` sigue intacto: 49 cuentas, `saldo_mensual` 588 de 588 y
`acumulados` 1,176 de 1,176.

**Y esta guarda rompió un test de la 8d, que es exactamente para lo que
sirven los lentos.** El de la 8d comprobaba que `mayor-proactivity` saliera
con `saldo_mensual` y `acumulados` en `no_verificable` — y ahora el parser
lo rechaza **antes de producir una sola regla**, así que ya no hay cobertura
que mirar. La suite rápida pasó verde las cinco veces —una por pieza—; el
fallo apareció en la corrida de `pytest -m lento` previa a la entrega, 52
minutos después. Reescrito para
que afirme lo que ahora es cierto: que `procesar_mayor` lanza
`LayoutDesconocido`. El invariante que defendía no se queda sin guardia —lo
imponen `__post_init__` y `test_ninguna_regla_cuadra_sin_haber_evaluado`
sobre los cinco tipos, y ninguno de los dos depende de este documento—.

Es la primera vez que el reparto rápido/lento cobra su factura en la
dirección útil: **un test caro fue el único que vio una consecuencia real de
un cambio**, tres fases después de escribirse. El coste de correrlos aparte
(§5.1) tiene esto en el otro platillo.

**«Los 17 que producen Excel» son 16.** `mayor-proactivity` contaba entre
ellos por procesar sin reventar, y ahora sale con código 2. Las tablas de M2
de la 8c **no se reescriben** —son mediciones de aquel momento y siguen
siendo ciertas—, pero lo que hay que citar de aquí en adelante es esto:

| | con `mayor-proactivity` | sin él |
|---|---|---|
| suma en desarrollo, los que producen Excel | 6m25s (17) | **5m25s** (16) |
| suma en desarrollo, solo los comunes con SERVIDORSIST | 6m11s (16) | **5m10s** (15) |
| suma en SERVIDORSIST | 21m16s (16) | **17m36s** (15) |
| factor, sobre los comunes | 3.44x | **3.40x** |

> **Fila añadida por el orquestador.** La tabla original tenía tres filas y
> el factor no se podía derivar de ellas: dividir 17m36s entre 5m25s da 3.25x,
> no 3.40x, porque la suma de desarrollo incluía `edocta-hsbc` y la de
> SERVIDORSIST no. Es la tercera vez que un agregado pierde su denominador al
> transcribirse —el 3.31x y el 3.71x fueron las dos anteriores—, siempre en la
> misma dirección: la fila del cociente sobrevive y la fila que lo explica se
> queda fuera. El conjunto comparable ahora son **15 documentos**.

Quitar el documento que no producía nada utilizable **no mueve el factor**
—3.44x contra 3.40x, dentro del rango estable de 3.35–3.64x— pero sí quita
**220 s de cada corrida en la máquina objetivo**, que era el tiempo que se
gastaba en no leer nada.

#### Objetivo 4. La `Discrepancia` declara si compara importes

Las 53 discrepancias de `cfdi_cruzado` en `poliza.pdf` traían
`esperado == obtenido == 0` porque la regla cruza identidades y los dos
campos eran `Decimal` obligatorios: no había dónde decir «aquí no hay
importe». La web lo resolvía **infiriendo** (`numerica = esperado !=
obtenido`) y el CLI y el Excel escribían los ceros.

**Medido antes de elegir la forma**
(`scripts/mediciones/fase8e_m4_quien_toca_discrepancia.py`):

| | sitios |
|---|---|
| construyen una `Discrepancia` | **17**, los 17 en `validate/rules.py` (+2 en tests) |
| de esos, cruzan identidades | **2** (`_cfdi_atados`, `_cfdi_cruzado`) |
| leen `esperado`/`obtenido` | **3 en el núcleo**: `cli.py`, `export/excel.py`, `web/vista.py` |

Con 3 lectores y 2 constructores a cambiar, el cambio de contrato es
pequeño. Se eligió **`Decimal | None`** sobre un campo que dijera el tipo de
comprobación, y la razón es la que separa un invariante de una convención:
**`None` hace IMPOSIBLE el modo de falla** —no queda un cero que alguien
pueda imprimir—, mientras que un campo de tipo lo deja ahí, evitable pero
presente, y la próxima salida que olvide mirarlo vuelve a escribir `0.00`.
ARQUITECTURA §4 recoge invariantes que impone el tipo, no que se recuerdan.

`None` no significa aquí «no se pudo leer el importe»: una discrepancia
numérica sin cifra no puede existir, porque sin las dos cifras la regla no
habría podido detectarla. Y `__post_init__` **lanza** si va un lado con
cifra y el otro sin ella: media comparación no es un caso, es un error.

Las tres salidas, sobre el mismo caso:

| salida | antes | ahora |
|---|---|---|
| CLI | `! P00041  cfdi_cruzado  esperado 0.00   obtenido 0.00` | `! P00041  cfdi_cruzado  no cuadra el dato, no el importe` |
| Excel | `esperado=0  obtenido=0` | las dos celdas **vacías**, y sin formato de monto |
| web | `numerica: False`, campos vacíos (lo **deducía**) | igual, pero **leyendo** `compara_importes` |

Y lo que no cambió: las 15 reglas que sí comparan importes siguen
imprimiendo sus dos cifras con el formato de siempre. Un test lo exige sobre
`auxiliar-gume`, recorriendo **todas** sus discrepancias numéricas.

**Lo que no se hizo, y se deja dicho**: el Excel deja las celdas vacías,
pero no dice *por qué* están vacías. El porqué está en el `motivo` de la
regla, arriba en esa misma hoja. Añadir una columna `nota` al bloque de
detalle cambiaría la forma de la hoja para dos reglas de diecisiete; queda
como decisión del orquestador, no como deuda.

#### Objetivo 5. Los dos documentos, con lo que ocurrió

`INSTALACION.md`: la tabla de «qué está verificado» pasa de una previsión a
un acta —§2 y §3 se **ejecutaron** en SERVIDORSIST—; el repo va a
`C:\proyectos\cp-pdf` y **sí hay git** en la máquina; el Tesseract de
`winget` **no ofrece la pantalla de idiomas** y hay que bajar
`spa.traineddata` aparte; la forma canónica del CLI es `contapdf` /
`.venv\Scripts\contapdf`, y se dice explícitamente que
`python -m contapdf.cli` **nunca se ha ejecutado en Windows**. §5 gana el
fallo del OCR con su cadena de cuatro pasos y la advertencia de que el
arreglo **sigue sin verificar allí**.

Y una cosa que la corrección destapó: las dos corridas del 4 de septiembre
—17:41 con Tesseract y 17:57 sin él— **son la misma máquina con dos consolas
distintas**. El instalador no marca el PATH, y una consola abierta antes no
lo ve. Por eso la corrida buena midió 16 documentos en vez de 17.

`ARQUITECTURA.md`: §5 decía que `exportar_estado_cuenta` no existe —existe
desde la 7e y su propio §2 lo lista— y contaba «6 formatos, 5 bancos» cuando
§1.2 mide 6 bancos. Corregidos los dos, más la guarda del mayor, las firmas
nuevas de dominio y los dos invariantes que esta fase añade a la tabla de §4.

#### El coste de la suite al cerrar la fase

| | tests | tiempo |
|---|---|---|
| rápidos | **747** (eran 731) | ~4m30s |
| `pytest -m lento` | **124** (eran 116) | 1h00m23s |

**Ninguno de los dos relojes es una medición limpia**: las corridas de esta
fase compartieron máquina con ediciones y con otras invocaciones. Se anotan
como orden de magnitud, no como cifra citable — y la de los lentos sube
porque los 8 tests nuevos reparsean `auxiliar-gume`, `mayor-proactivity` y
`diario-general`, que son tres de los cuatro documentos más caros del
proyecto. Medirlo en aislamiento es trabajo de quien quiera citarlo.

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
| 8a | Interfaz mínima | Subida, procesamiento en segundo plano, descarga y cobertura en el navegador | **hecho** (765 tests) |
| 8b | Cola persistente y tenants | Trabajos que sobreviven un reinicio; aislamiento por despacho | **hecho** (786 tests + 8 lentos) |
| 8c | Preparar la medición | Coste de la suite, exportador cuadrático, arreglo del `-o`, `INSTALACION.md`, guion de medición | **hecho** (710 rápidos + 111 lentos) |
| 8c-bis | Medición en SERVIDORSIST | Correr `scripts/medir_servidorsist.py` allí y llenar las columnas vacías de M2, M3 y M4 | **hecho** (corrida del orquestador; transcrita a §2 por Claude Code en la 8d) |
| 8d | Correcciones de correctitud | `cuadra` con cero evaluados; `encoding` del OCR en Windows; declarado contra leído en la hoja `Polizas`; `pagina` en `Movimiento` | **hecho** (731 rápidos + 116 lentos) |
| 8e | Que las tres salidas digan lo mismo | `saldo_origen` a la hoja `Auxiliar`; declarado contra leído en `mayor` y `estado-cuenta`; que la `Discrepancia` declare si compara importes, para que CLI, Excel y web dejen de deducirlo; `mayor-proactivity` falla limpio; corregir `INSTALACION.md` y `ARQUITECTURA.md` con lo ocurrido | **hecho** (747 rápidos + 124 lentos) |
| 8f | El diario, el IR y el texto de los estados de cuenta | La segunda mecánica de pérdida de importes en `diario-general`, ahora que `Movimiento` guarda la página; y medir qué pasa con la `referencia` y los espacios dentro de las palabras en la `descripcion` de Bajío y Santander, visto en la demostración | siguiente |
| 8g | Residuos del ancla | Medir la distribución de residuos de aterrizaje y decidir si hay tolerancia defendible | |

> **Renumeración de la 8d en adelante.** Lo que la 8d midió y no arregló —el
> mismo defecto de «declarado contra leído» en otros tres exportadores, y el
> `esperado 0.00 / obtenido 0.00` que resultó faltar en dos salidas y no en
> una— pesa más que el diagnóstico del diario, que además ya está
> desbloqueado y puede esperar una fase. La antigua 8e se parte: su mitad de
> `mayor-proactivity` entra en la 8e nueva (el diagnóstico ya lo hizo la 8d;
> queda hacerlo fallar limpio) y su mitad del diario pasa a la 8f. Los
> residuos del ancla corren un lugar, a 8g.

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

Registrada a propósito, con la fase en que toca resolverla. **Una entrada
sale de aquí cuando se mide que ya no ocurre, no cuando se cierra la fase que
la tenía asignada.**

### Bloqueantes de corrección

Cosas que hacen que el sistema afirme algo que no comprobó. Van primero
porque son el argumento entero del proyecto.

**Vivas hoy**: `naturaleza_origen` en balanza, la `referencia` y los espacios
de los estados de cuenta, y la verificación del OCR en SERVIDORSIST. Las
tachadas las cerró la 8e; se quedan en su sitio, con su texto original
debajo, porque el patrón que las produjo se repite y moverlas rompe las
referencias de los prompts anteriores.

- **`balanza` no exporta `naturaleza_origen`.** Es el último hueco del
  invariante «un valor derivado declara su procedencia» en las salidas: la
  8e lo cerró en `Auxiliar` con `saldo_origen` y en las hojas `Cuentas` con
  declarado contra leído, pero la hoja `Balanza` sigue sin decir cuándo la
  naturaleza de una cuenta la dedujo el sistema en vez de leerla. **Sin fase
  asignada.**
- **La `referencia` de los estados de cuenta aparece pegada al principio de
  la `descripcion`, y hay espacios dentro de palabras.** Visto en la
  demostración sobre `edocta-bajio` y `edocta-santander`, **no medido**: en la
  hoja `Movimientos` salen celdas como `9462491DEPÓSITO SPEI:REACTIVOS...`
  cuando el PDF imprime `NO. REF./DOCTO` en una columna aparte, y otras como
  `C O MISION CUOTA MENSUAL` con espacios donde la palabra no los lleva.
  `MovimientoBancario` **sí tiene campo `referencia`** (§1.1), así que hay al
  menos dos explicaciones posibles y ninguna medida: que el campo esté vacío y
  el valor se haya quedado en la descripción, o que se rellene y además se
  duplique. Los espacios dentro de palabras son un fenómeno distinto del
  separador de continuación y no está descrito en ninguna parte. **Fase 8f,
  midiendo antes de tocar nada.**
- ~~**La hoja `Auxiliar` no exporta `saldo_origen`.**~~ **Resuelto en la 8e.** En `auxiliar-gume`,
  **26,032 de 57,759 saldos los derivó el sistema** encadenando (22,713
  impresos, 9,014 sin saldo) y en el Excel se ven idénticos a los que el
  documento imprimió. `Cobertura` separa `exactas_impresas` de
  `exactas_recalculadas` desde la 7h precisamente porque comprobar un saldo
  derivado con la fórmula que lo derivó es una tautología, y el invariante
  «un valor derivado declara su procedencia» está en `ARQUITECTURA.md` §4 —
  pero se rompe justo en la salida que ve el contador. Es la deuda más grave
  abierta. **Fase 8e.**
- ~~**`mayor` y `estado-cuenta` muestran el declarado sin lo leído.**~~
  **Resuelto en la 8e**, con dos hallazgos que conviene no perder: las 4
  cuentas donde `saldo_final` difería son exactamente las 4 que
  `saldo_mensual` ya contaba como «dentro de tolerancia», así que exportar un
  `saldo_final_leido` habría puesto a la hoja a contradecir a la cobertura; y
  la correspondencia entre hoja y regla **no es 1:1** como en pólizas
  —`acumulados` roza en 5 renglones de 4 cuentas y solo una tiene el total
  descuadrado—, así que lo que el test exige es la dirección que importa:
  toda cuenta que la hoja marque distinta tiene que estar nombrada por alguna
  regla. Texto original abajo, por el patrón.
  <br>Decía: **el mismo defecto que la 8d cerró en la hoja `Polizas`**, el mismo
  defecto que la 8d cerró en la hoja `Polizas`. Medido en la 8d
  (`scripts/mediciones/fase8d_m6_declarado_en_los_otros_cuatro.py`): en
  `mayor`, la hoja `Cuentas` lleva `saldo_final`, `total_cargos` y
  `total_abonos` leídos del último mes, y **1 de las 49 cuentas de
  `mayor-gume` ya difiere**; en `estado-cuenta`, `Cuentas` lleva `depositos`,
  `retiros` y `saldo_corte` del resumen, y hoy no difiere en ninguno de los
  4 fixtures medidos. `balanza` no lo tiene: no exporta la fila `Totales`.
  **Fase 8e.**
- ~~**La `Discrepancia` no declara si compara importes.**~~ **Resuelto en la
  8e** con `Decimal | None`, elegido sobre un campo de tipo porque hace
  imposible el modo de falla en vez de dejarlo evitable: no queda un cero que
  imprimir. 17 constructores, 2 de ellos de identidades, y 3 lectores. Texto
  original abajo.
  <br>Decía: **por eso dos de las tres salidas mienten.** Las 53 discrepancias de `cfdi_cruzado` en
  `poliza.pdf` traen `esperado == obtenido == 0`, porque la regla cruza
  identidades y `Discrepancia.esperado/obtenido` son `Decimal`
  obligatorios. Medido en la 8d: la web lo resuelve **infiriendo**
  (`numerica = esperado != obtenido`), y **el CLI y el Excel escriben los
  ceros**. O sea que el arreglo de la 8a no llegó «a la web y no al Excel»:
  llegó solo a la web y le faltan los otros dos. Copiar la inferencia a tres
  sitios no vale —la próxima corrección volvería a llegar a uno—: hace falta
  que el dato lo declare la `Discrepancia` (`Decimal | None`, o un campo de
  tipo de comprobación). Cambio de contrato del IR de validación, medido y
  propuesto en la 8d, no hecho. **Fase 8e.**
- **No hay parser para un reporte de movimientos por cuenta**, que es lo que
  resultó ser `mayor-proactivity`. Desde la 8e sale con código 2 y el motivo
  escrito, que es lo correcto mientras no exista; pero es alcance pendiente,
  no un documento roto. Y queda **medido y no arreglado**: `_es_mes` sigue
  aceptando un nombre de mes al principio de cualquier renglón de
  descripción. La guarda que evita el desastre es de documento —ningún mes
  con importes— y no arregla la detección. **Sin fase asignada.**
- ~~**`mayor-proactivity` entrega sin haber leído.**~~ **Resuelto en la 8e.** Diagnosticado por capas en
  la 8d: la estrategia es correcta y el layout es síntoma; **la causa es el
  parser**. El documento no es un libro mayor sino un reporte de movimientos
  por cuenta, no imprime meses, y los 48 «meses» que el parser cree ver son
  falsos positivos de `_orden_de`, que compara tras `normalizar()` y
  `normalizar()` quita la puntuación: `_orden_de('(ENERO') == 1`. Con eso
  produce 1 cuenta, 48 renglones en cero y una cobertura sobre 145 casos.
  Sin ese falso positivo daría 0 meses y fallaría limpio. Es el mismo modo de
  falla que el objetivo 1 de la 8d, un piso más abajo: no una regla que
  cuadra sin evaluar, sino un parser que entrega sin leer. **Fase 8e: que
  falle limpio, y sacarlo de «los 17 que procesan».**
- **El arreglo del OCR en Windows no está verificado en la máquina
  objetivo.** La 8d encontró y corrigió la causa —`ocr.py` lanzaba Tesseract
  sin `encoding`, Windows en español decodifica con cp1252 y el byte `0x9D`
  de las comillas tipográficas no existe ahí; el `AttributeError:
  'NoneType' object has no attribute 'splitlines'` es el síntoma dos capas
  después y se interpretó mal dos veces—. Los tests fuerzan la condición
  (bytes que cp1252 no decodifica, un subproceso real que los emite), pero
  **la suite corre en WSL y ningún test cubre Windows**. La verificación es
  volver a correr `scripts/medir_servidorsist.py` en SERVIDORSIST con
  Tesseract en el PATH y ver `edocta-hsbc` completo. **Tarea del
  orquestador**, que es quien tiene acceso por Escritorio Remoto.
- ~~**`INSTALACION.md` y `ARQUITECTURA.md` describen cosas que ya no son
  ciertas.**~~ **Resuelto en la 8e**, y la corrección destapó por qué la
  medición buena midió 16 y no 17: **las corridas de las 17:41 y las 17:57 son
  la misma máquina con dos consolas distintas.** El instalador de Tesseract no
  marca el PATH y una consola abierta antes del cambio no lo ve. Texto
  original abajo.
  <br>Decía: `INSTALACION.md` §2 dice que no hay git en la máquina y que el
  repo va a `C:\contapdf`; en la instalación real se instaló git y quedó en
  `C:\proyectos\cp-pdf`. §4 documenta `python -m contapdf.cli`, que no está
  verificado en Windows; lo verificado en las dos plataformas es `contapdf`
  en Linux y `.venv\Scripts\contapdf` en Windows, y esa es la forma
  canónica. El instalador de Tesseract por `winget` no ofrece la pantalla de
  idiomas, así que hay que bajar `spa.traineddata` aparte. `ARQUITECTURA.md`
  §5 dice que `exportar_estado_cuenta` no existe —existe desde la 7e y su
  propio §2 lo lista— y cuenta «6 formatos, 5 bancos» cuando §1.2 mide 6
  bancos. **Fase 8e.**
- ~~**`mediciones-ServidorSist-20260904-1741-metodoRAPIDO.txt` está en la
  raíz del repo.**~~ **Resuelto en la 8e**: movido a `scripts/mediciones/`,
  con un test que falla si vuelve a aparecer un `mediciones-*.txt` suelto en
  la raíz y otro que comprueba que el fichero sigue conteniendo la traza,
  porque lo que respalda la afirmación es el contenido y no el nombre. Texto
  original abajo.
  <br>Decía: Es el único fichero que documenta
  el fallo del OCR con Tesseract presente (v5.4.0, revienta a los 7.0 s) y el
  único que respalda «el OCR nunca funcionó allí». Si se pierde, esa
  afirmación se queda sin evidencia reproducible. **Fase 8e: moverlo.**

### Medidas y sin resolver

- **`diario-general` lee mal los importes; no pierde renglones.** Medido en
  la 8b: 24,821 renglones producen 24,821 movimientos y no hay pólizas
  vacías. Faltan 659,304.42 en el debe y **sobran** 106,873.98 en el haber, y
  22 movimientos traen debe y haber a la vez —imposible en un diario—, los 22
  dentro de las 100 pólizas que fallan `partida_doble`, que son las mismas
  100 donde el declarado difiere de lo leído. **La mecánica propuesta —un
  renglón que se traga el importe del vecino— no explica la magnitud**: eso
  haría que el haber ganara lo que el debe pierde, y quedan 552,430.44 sin
  aparecer en ningún lado. Hay al menos dos mecánicas. Se extrae con
  `pdf_chars` y el 21.9% de sus palabras se traslapan. **Desbloqueado por la
  8d**, que le dio `pagina` a `Movimiento`: ya se puede cruzar cada importe
  perdido con la zona de traslape de su página. **Fase 8f: medir la segunda
  mecánica antes de arreglar.**
- **La familia A: 2 secciones de `auxiliar-gume` cuya cadena no aterriza.**
  Medido en la 7h, corrigiendo lo que dijo la 7g: **no falta ningún
  movimiento**. La suma difiere en 0.01 y 0.02 pesos sobre 37 millones y el
  ancla exige igualdad exacta; un movimiento faltante mueve pesos, no
  céntimos, así que es redondeo del documento origen. Retiene 9,013 saldos
  sin recalcular. No se relaja el ancla eligiendo un número: `±0.01` no
  alcanza y subirlo a `±0.02` es ajustar el umbral hasta que pase el caso.
  **Fase 8g: medir la distribución completa de residuos sobre las 172
  secciones y buscar el hueco, como se hizo con el umbral de CID. Sin hueco
  no hay tolerancia defendible.** Y si se admite: una sección anclada con
  residuo no es igual a una anclada exacta, la cobertura las separa, y el
  residuo nunca se distribuye entre los saldos.
- **La regla de mayoría para determinar la naturaleza no está probada.**
  Medido en la 7h: el criterio no mueve ni un saldo —unanimidad y mayoría dan
  165 secciones ancladas sin aterrizaje y 168 con él, idénticas—. Los dos
  documentos disponibles no lo distinguen. Se eligió por el precedente del
  libro mayor, no por una medición. **Sin fase; volver a medirlo cuando entre
  un fixture nuevo de auxiliar.**
- **`mayor-proactivity` tarda 60.5 s con 276 páginas** contra 26.7 s de
  `poliza` con 968: ocho veces más por página, y no es el exportador. Medido
  en la 8c. La 8d explicó **qué** produce (nada utilizable) pero no **por
  qué** cuesta tanto producirlo. **Sin fase asignada.**
- **La colocación del saldo sigue apoyada en la convención que se quitó de
  `naturaleza`.** La hipótesis «positivo → deudora» se **midió y se
  descartó**: falla en 56 de 236 renglones determinados (24%). Tanto
  deudoras como acreedoras se imprimen en positivo — en Business Pro, 35 de
  36 acreedoras derivadas tienen saldo positivo, y de los 6 saldos negativos
  3 son A y 3 son D. **El signo no dice la naturaleza de la cuenta; dice que
  ese saldo va contra su naturaleza.** Es propiedad del saldo, no de la
  cuenta. Opción honesta pendiente: cuando la forma es `saldo_con_signo`,
  exportar las columnas con signo **tal como las presenta el documento** y
  llenar deudor/acreedor solo donde la naturaleza está fundamentada. **Sin
  fase asignada.**
- **El enrutamiento CID→OCR no avisa de lo que cuesta.** Añade ~21 s medidos
  en desarrollo, y en la máquina objetivo no hay cifra porque el OCR nunca
  corrió allí. La cola de la 8b quitó la mitad del problema —ya nadie espera
  en una petición síncrona—, pero sigue sin haber tiempo estimado visible
  para el carril de OCR. **Sin fase asignada.**
- **El reparto rápido/lento abarató el ciclo y encareció la entrega.** La
  suite rápida bajó de 23m31s a ~4m20s, pero el total partido supera al total
  junto (20m03s), y al deseleccionar se mueve el coste de los fixtures
  compartidos: un test pasó de ~1 s a 15.97 s. La causa no se aisló. El
  umbral de 3 s **es un reparto de presupuesto, no un hallazgo**: el hueco
  natural de los datos está entre 14.25 s y 6.74 s (2.1x) y cortar ahí deja
  6m33s. No se lea como el umbral de CID, que sí lo defienden los datos.
  **Sin fase asignada.**
  <br>**Contrapeso medido en la 8e**: la guarda de `mayor-proactivity` dejó
  obsoleto un test de la 8d que esperaba cobertura de ese documento, y **el
  único que lo vio fue un test lento**, a los 52 minutos de `pytest -m lento`,
  tres fases después de escribirse. Las cinco corridas rápidas pasaron verdes.
  El coste de correrlos aparte tiene esto en el otro platillo: separarlos
  también significa que una consecuencia real puede tardar una fase entera en
  aparecer.
- **20 CFDI traen el RFC pegado al tipo** (`'ROTG870907QC5Ingreso'`). No
  afecta al cruce; el campo `tipo` sale sucio. **Sin fase asignada.**
- **`Bajío`: 1 movimiento con tinta en la columna del saldo que no se leyó.**
  Único caso (b) de M1 en la 7g; los 93 de BBVA son (a), el banco solo
  imprime el saldo al cierre del día. **Sin fase asignada.**
- **`_subtotales` salta las cuentas acumulativas con `continue` en vez de
  distinguirlas.** Su propio docstring nombra la trampa. Los 563 subtotales
  huérfanos de `auxiliar-gume` quedaron explicados en la 8b y **no son un
  defecto**: 378 son de detalle y 185 acumulativas —lo contrario de lo que la
  8a declaró desde tres ejemplos—, pero los 378 están en ceros, y cuentas de
  detalle con importe y sin movimientos hay 0, por 0.00 no leídos. Extra: 3
  cuentas traen más de un subtotal. **Sin fase asignada.**
- **Cruce contra los CFDI timbrados: no existe.** `cfdi_cruzado` verifica
  consistencia interna del PDF —que el folio declarado aparezca en la
  descripción del asiento—, no contra comprobantes reales. Los XML están en
  el repo (`fixtures/real/XML R Y E/`) y nunca se han leído. Cruzar póliza
  contra CFDI timbrado detectaría comprobantes inexistentes, importes que no
  coinciden y CFDI cancelados aún contabilizados. Lo mismo aplica a cruzar
  mayor contra balanza: la regla `cruce_balanza` ya existe y sale
  `no_verificable` porque ningún comando acepta dos documentos a la vez.
  **Es un producto distinto y más valioso que la conversión. Sin fase;
  decidir cuándo.**

### Decisiones que no son técnicas

- **El separador de continuación de los estados de cuenta.** Cuando una
  descripción se envuelve en varios renglones, unirlos con `""` o con `" "`
  cambia el texto y nada más: **no afecta a ningún importe, saldo ni
  checksum**. Y no se puede deducir: la 7e midió que la geometría **no**
  distingue un documento que parte palabras a la mitad (`CON` + `CEPTO:`) de
  uno que envuelve por palabra entera (`CVE` + `RASTREO:`) — en los dos casos
  el último token llega al margen y el siguiente arranca en el borde
  izquierdo, y las formas de los tokens son idénticas. Por eso
  `separador_continuacion` es un **parámetro del formato** con valor por
  omisión `""`, el medido en el primer formato de la fase 7, y con ese valor
  **cinco de los seis formatos salen con las palabras pegadas**
  (`MEXICOORDENANTE`). El sistema no lo inventa: lo declara como "falta
  confirmar" y espera al comando `confirmar`. **Lo decide quien conoce los
  documentos, por formato, no el orquestador ni Claude Code.**

- **El sistema no tiene autenticación.** Cualquiera en la red de la oficina
  puede subir y descargar cualquier documento; el nombre del despacho es el
  único separador y no es un secreto. En red local con un solo despacho la
  separación organizativa alcanza, pero **es una decisión del dueño del
  despacho, no técnica**, y hay que preguntársela antes de poner documentos
  de clientes en SERVIDORSIST. Va con el resto del checklist de despliegue en
  §2, «Resultados de la fase 8c»: respaldo, arranque como servicio, ventana
  de uso, y qué hacer con un trabajo grande subido después de las 20:49.

### Restricciones permanentes, no deuda

- **Dinero siempre en `Decimal`, nunca `float`.** Verificado por test AST.
  Aplica a todo parser nuevo.
- **`pitch_factor=1.3` en `headers.py`** distingue una etiqueta partida en
  dos renglones de un título de sección, midiendo si el interlineado es más
  apretado que el de los datos. Está afinado sobre cuatro documentos. Debe
  seguir siendo parámetro configurable, nunca constante enterrada.

### Cerradas, y por qué se quedan escritas

Ninguna es trabajo pendiente. Se conservan porque el patrón que las produjo
sí se repite.

- **`pypdfium2` no estaba declarado en `pyproject.toml`.** `ocr.py` lo
  importa y nueve fases no lo notaron porque estaba instalado de antes en la
  máquina de desarrollo. Resuelto en la 8c. **El patrón: una dependencia que
  solo existe en la máquina de quien programa es invisible hasta el primer
  despliegue.**
- **El CLI reventaba con una traza de `zipfile` si el directorio de `-o` no
  existía**, y salía con código 1, que aquí significa «hay discrepancias».
  Resuelto en la 8c: se comprueba antes de procesar, avisa, sale con 2 y no
  crea el directorio.
- **Una regla decía `cuadra` habiendo evaluado cero casos** (`mayor-proactivity`,
  `saldo_mensual 0 de 48` y `acumulados 0 de 96`). Resuelto en la 8d:
  `__post_init__` lanza, y `_resultado()` devuelve `no_verificable` con
  motivo. Barrido de los 27 fixtures: eran 2 reglas en 1 documento, y ninguna
  otra medición se movió.
- **`jerarquia` reportaba 4 sin evaluar, el motivo nombraba 2 cuentas y el
  filtro daba 2 filas.** Medido en la 8d: los tres números son correctos y
  distintos. 28 padres referidos × 2 campos = 56 aplicables; 26 presentes con
  hijas × 2 = 52 evaluados; 2 huérfanos × 2 = 4 sin evaluar. El motivo nombra
  **los padres que faltan** (`100`, `200`) y el filtro encuentra **las hijas
  que los declaran** (`100-01`, `200-01`). No hay padres presentes sin hijas,
  así que no hay un segundo hueco.
- **`P00476` no es un doble conteo.** Medido en la 8d: son dos CFDI distintos
  de la misma póliza, con UUID distintos, y ninguno cruza. Hay 3 casos así.
  **Y destapa un error de unidad que estaba en este documento**: no son «53
  pólizas» las que fallan `cfdi_cruzado`, son **53 CFDI sobre 50 pólizas** —
  el `aplicables` de la regla es `len(libro.cfdi)`. Corregido aquí y donde
  aparezca.
- **Las 53 discrepancias de `cfdi_cruzado` no son deuda, son el resultado
  correcto.** Medido en la 7h: no hay criterio no circular que las separe de
  las que cruzan. Por tipo, Cobro 817 cruzan / 13 fallan, Venta 853 / 8, Pago
  31 / 40; 1,701 pólizas de esos mismos tipos sí cruzan, así que no son una
  familia. El comando `polizas` sale con código 1 a propósito: 53 renglones
  marcados que un contador puede revisar valen más que un porcentaje inflado.

### Asignadas a fases ya cerradas: verificar antes de borrar

Estas cinco entradas nombran una fase que ya pasó y probablemente estén
resueltas, pero **nadie lo ha medido después**, y borrarlas sin comprobar es
declarar un éxito sin checksum.

- `headers.py` fusiona `'FOLIO FECHA'` en el auxiliar; el parser necesita
  `folio` y `fecha` separados. **Decía fase 3.**
- `headers.py` no maneja encabezados agrupados (`Acumulados` abarcando dos
  columnas, en el Libro Mayor). **Decía fase 7b.**
- La jerarquía necesita el ancho de segmento por nivel (6/9/12 en GUME,
  guiones en los otros). **Decía fase 4a.**
- La detección de la fila de totales no puede depender de que la etiqueta
  esté al inicio de la celda de nombre (en GUME el renglón es
  `734 | Cuentas reportadas | Totales: | ...`). **Decía fase 4a.**
- `balanza-fd` detecta 4 columnas y tiene 6 subetiquetas de encabezado
  agrupado. **Decía fase 7c**, y §2 de la 7c dice que se resolvió
  deduplicando, pero la entrada nunca se cerró.

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
- ~~**Puerto**~~: **decidido en la 8c.** Apache ocupa el 80, así que el
  servicio Python va en el **8080** (`INSTALACION.md` §2.6). Poner un proxy
  de Apache delante sigue abierto y toca configuración de Apache.
- ~~**Apagado diario a las 21:00**~~: **resuelto a medias en la 8b.** La cola
  persiste en SQLite y lo que quedó en `procesando` pasa a `interrumpido` al
  arrancar, con su motivo. **No se reanuda**: hay que volver a subir el
  documento. Con `auxiliar-gume` en 10m40s medidos, cualquier documento
  grande subido después de las **20:49** se pierde, y falta decidir si se
  avisa, se rechaza o no se hace nada (checklist de la 8c, punto 3).
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