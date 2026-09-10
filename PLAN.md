# cp-pdf — Plan de construcción

Sistema de conversión de PDFs contables a Excel, con mapeo por plantillas y
validación aritmética.

**Regla de oro:** ningún parser se escribe sin un fixture que lo pruebe
primero. Fixture → test que falla → parser → test que pasa.

Estado: **fase 8f cerrada.** Cinco parsers, cinco exportadores, CLI de seis
comandos, interfaz web con cola persistente en SQLite, worker secuencial y
aislamiento por despacho.
**762 tests rápidos + 125 lentos.**
De los 27 fixtures: **16 producen Excel**, 7 no tienen parser, 3 son estados
de cuenta sin tabla de movimientos, y `mayor-proactivity` **sale con código 2
y motivo escrito** desde la 8e — antes contaba entre los que procesaban
porque no reventaba. Pólizas sale con discrepancias por **53 CFDI
sobre 50 pólizas** cuyo folio no aparece en la descripción del asiento,
declarados a propósito.

**Existe un inventario, en §2, generado por `scripts/inventario.py` y
regenerable.** Una línea por fixture: qué produce, con qué estrategia, con
qué cobertura y si deja plantilla. Tres cosas salieron a la luz solo por
escribirlo: el sistema **no lee el emisor de ningún documento contable** (7
columnas vacías), el banco que sí lee viene sucio, y **solo 3 de los 16
formatos dejan plantilla aprendida** — no es un defecto del aprendizaje, es
la consecuencia de no aprender de lo que no cuadra, pero desmiente la frase
«la segunda vez entra sin intervención» tal como estaba escrita en `USO.md`.

**El barrido de la 8f clasificó lo que no cuadra**, y es el trabajo que
ordena las fases siguientes. De 61 reglas, 20 no cuadran, con 11 motivos
distintos; se fue al documento a comprobar cada motivo y **seis resultaron
REFUTADOS**: el dato sí estaba y el sistema decía que no. A nivel de
documento, los **7 fixtures «sin parser» son todos de su tipo**, así que no
son alcance pendiente sino documentos que no sabemos leer. Los dos
denominadores no se mezclan: 20 casos sobre 61 reglas por un lado, 7
documentos sobre 27 fixtures por el otro.

**Las tres salidas —CLI, Excel y web— dicen lo mismo del mismo caso desde la
8e.** La hoja `Auxiliar` declara qué saldos derivó el sistema (26,032 de
57,759 en `auxiliar-gume`), las hojas `Cuentas` de mayor y estado de cuenta
llevan declarado y leído, y la `Discrepancia` declara si compara importes en
vez de que cada salida lo deduzca. Queda un hueco: **`balanza` no exporta
`naturaleza_origen`** (§5.1).

**SERVIDORSIST está medido, y la 8f midió también el instrumento.** Las
corridas son del orquestador por Escritorio Remoto (no hay SSH y no se va a
montar); están en `scripts/mediciones/` y la buena es la del **9 de
septiembre**, con Tesseract en el PATH y los 16 documentos que producen
Excel.

- **El factor es «unas tres veces», entre 2.7× y 3.0×, y no admite
  decimales.** No porque la medición saliera mal: porque **el denominador
  tiene ±28% de ruido y nadie lo había repetido nunca**. Dos corridas
  consecutivas en la máquina de desarrollo, sin tocar una línea, dieron
  373.5 s y 415.8 s —un 11%—, y `poliza` sola se movió un 26%. SERVIDORSIST,
  en cambio, varía **2.4%** entre corridas separadas por cinco días. El ruido
  está entero en el denominador.
- **Y por eso mueren, de una vez, el 3.4–3.7×, el 3.31×, el 3.44×, el 3.40×
  y el 3.48×.** Cada uno corrigió al anterior en un decimal; los cinco eran
  divisiones sobre un denominador que nadie había medido dos veces. Las
  cifras siguen en las tablas de §2 porque son ciertas para su momento, pero
  **la que se cita es «unas tres veces»**.
- **Los tiempos absolutos de SERVIDORSIST sí son firmes**, y de ahí sale todo
  lo operativo: `auxiliar-gume` 10m54s, `diario-general` 3m40s, `poliza`
  1m43s, `edocta-hsbc` por OCR 48.8s, suma de los 16 **18m49s**.
- **Separar código de máquina, con el instrumento estable**: donde el ruido
  es del 2.4%, el cambio de la 8c a la 8e costó **+1.8% en leer y +14.8% en
  exportar** — la lectura no se tocó y la exportación subió por las columnas
  nuevas. El +28% de desarrollo no es del código: si lo fuera, SERVIDORSIST
  lo habría visto.
- **La memoria no es restricción, pero lo medido es la holgura y no el
  consumo**: mínimo de 2,978 MB libres de 8,078 durante la corrida, con
  Apache y MySQL activos. **El pico del proceso allí no se puede leer**: el
  instrumento no obtiene el `WorkingSetSize` en Windows.
- **El disco tampoco**: 327 GB libres contra un techo extrapolado de 281 MB
  al día.

**El OCR funciona en SERVIDORSIST y está verificado allí.** La 8d encontró la
causa —`ocr.py` lanzaba Tesseract sin `encoding` y un Windows en español
decodifica con cp1252, que no admite los bytes de las comillas tipográficas
que Tesseract imprime— y el 9 de septiembre `edocta-hsbc` completó por OCR
con su `.xlsx` escrito. **Cuesta 48.8 s allí contra ~15 s aquí.** Aun así
ningún test cubre Windows: la suite corre en WSL.

Siguiente: **8g** (los seis motivos refutados), **8h** (el diario) y **9**
(los siete formatos, el emisor y el modo diagnóstico).

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

**Un cociente no vale más que su denominador, y un denominador que nadie
repitió no vale nada.** Durante cinco fases se citó el factor contra
SERVIDORSIST con dos decimales, y cada corrección afinaba la anterior:
3.4–3.7×, luego 3.31×, luego 3.44×, luego 3.40×, luego 3.48×. La 8f repitió
por primera vez la medición del **denominador** —la máquina de desarrollo—
minutos después y sin tocar código: **11% de diferencia en la suma, 26% en un
documento**. El numerador, SERVIDORSIST, varía 2.4%. O sea que se estuvo
discutiendo el segundo decimal de un número cuyo primer decimal no está
determinado.

Dos de esas correcciones son del orquestador y las dos son del mismo tipo:
arreglar la aritmética de la división sin preguntar nunca cuánto vale cada
lado. **La regla: antes de publicar un cociente, medir dos veces el
denominador.** Y si el instrumento es un portátil con turbo y gestión
térmica, decirlo, porque no es un instrumento estable.

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

## 2. Hallazgos, principios y la fase en curso

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

### Resultados de las fases cerradas — el índice

Los resultados de las fases 7c a 8e viven en **`MEDICIONES.md`**, en
orden cronológico y sin una coma cambiada. Se movieron en la 8g: eran
dos tercios de este documento y ninguna fase abierta las consulta.

**Este índice no lleva cifras, y es a propósito.** Para citar un número
hay que abrir `MEDICIONES.md` y leerlo ahí. El error más repetido del
proyecto es citar cifras que nadie leyó del fichero —el `(ENERO` de la 8d
llegó así a tres documentos—, y un índice con números es una invitación a
repetirlo.

- **fase 7c** — la extracción transversal: tokens duplicados, el enrutamiento de CID a OCR y la fecha pegada a la descripción → `MEDICIONES.md`
- **fase 7d** — la generalización de los estados de cuenta: los formatos con tabla de movimientos, y los que resultaron ser otro tipo de reporte → `MEDICIONES.md`
- **fase 7e** — el cierre del núcleo: los exportadores que faltaban, los comandos del CLI y el separador de continuación como pregunta al cliente → `MEDICIONES.md`
- **fase 7f** — cada conteo con su denominador: `aplicables` en cada regla, y el diagnóstico de las reglas que fallaban sin decir sobre cuánto → `MEDICIONES.md`
- **fase 7g** — el signo de las identidades de saldo derivado por cuenta, el recálculo conectado al pipeline y `cfdi_cruzado` por contención → `MEDICIONES.md`
- **fase 7h** — separar las comprobaciones sobre dato impreso de las que caen sobre un saldo que el sistema derivó, y cerrar las pólizas → `MEDICIONES.md`
- **fase 8a** — la interfaz mínima: subida, procesamiento en segundo plano, descarga de un solo uso y cobertura en el navegador → `MEDICIONES.md`
- **fase 8b** — la cola persistente en SQLite, el worker secuencial y el aislamiento por despacho, con lo que ese aislamiento no es → `MEDICIONES.md`
- **fase 8c** — medir la máquina objetivo y preparar la instalación: el coste de la suite, el exportador cuadrático y el `-o` que reventaba → `MEDICIONES.md`
- **fase 8d** — los defectos de correctitud que destapó comparar las dos salidas del sistema entre sí, y el OCR que nunca funcionó en Windows → `MEDICIONES.md`
- **fase 8e** — que el CLI, el Excel y la web digan lo mismo del mismo caso: la procedencia de un saldo, el declarado contra el leído y la `Discrepancia` que declara si compara importes → `MEDICIONES.md`

La fase en curso se queda aquí abajo, entera. Al cerrar la siguiente,
esta baja a `MEDICIONES.md` y deja su línea de índice.


### Resultados de la fase 8f (qué cubrimos, y por qué no cuadra lo que no cuadra)

**Esta fase no arregló nada.** Mide, clasifica y reporta. Los defectos que
encontró están al final, sin fase asignada y sin numerar.

#### El factor, por fin con la misma versión en las dos máquinas — y por qué no admite decimales

La corrida del 9 de septiembre en SERVIDORSIST cierra dos cosas que venían
de la 8d y la 8e:

| | resultado |
|---|---|
| `edocta-hsbc` | **COMPLETO**: 4 págs, 48.7 s leer + 0.1 exportar, estrategia `ocr`, `.xlsx` escrito |
| `mayor-proactivity` | `LayoutDesconocido` con el mensaje entero, y no produce Excel |

**El arreglo del `encoding` de la 8d queda VERIFICADO en la máquina
objetivo**, que era el último bloqueante abierto de aquella fase; y la
guarda de la 8e también. Y una cifra nueva: **el OCR allí cuesta 48.8 s, no
los ~21 s de desarrollo** — 2.8x, en el rango del resto.

Hasta hoy las dos columnas del factor eran de **versiones distintas**: la de
desarrollo se midió en la 8c y el código cambió en la 8d y la 8e. Los
`.xlsx` crecieron —`diario-general` 2.34 → 2.68 MB, `auxiliar-gume` 3.55 →
3.75, `poliza` 0.83 → 0.92— así que la columna de exportar comparaba dos
versiones y no dos máquinas. Se volvió a medir en desarrollo con el código
de hoy:

| los 16 documentos comunes | dev (10 sep) | SERVIDORSIST (9 sep) | factor |
|---|---|---|---|
| suma total | 6m55s | **18m49s** | **2.72x** |
| — leer y validar | 6m42s | 18m01s | 2.69x |
| — exportar | 13.0 s | 47.6 s | 3.66x |
| `auxiliar-gume` | 251.8 s | **654.4 s** | 2.60x |
| `edocta-hsbc` (OCR) | 17.3 s | 48.8 s | 2.82x |
| mediana | 1.6 s | 5.3 s | 3.31x |

**Y ahí es donde el número se cae.** Repetida la misma medición en
desarrollo, minutos después y sin cambiar una línea, la suma dio **373.5 s
contra 415.8 s**: un 11% entre dos corridas consecutivas. `poliza` solo se
movió un **26%** (41.9 s contra 33.3 s). Con el otro denominador, el mismo
numerador da **3.02x**.

| denominador | factor |
|---|---|
| dev 10 sep, primera corrida | 2.72x |
| dev 10 sep, repetida | **3.02x** |
| media de las dos | 2.86x |
| dev 4 sep (código de la 8c) | 3.48x |

**El ruido no es simétrico, y eso es el hallazgo.** Sobre los 15 documentos
que las dos corridas de SERVIDORSIST comparten, esa máquina varió **+2.4%**
entre septiembre 4 y septiembre 9 (1 055.8 s → 1 080.7 s; el orquestador
calculó 1 055.6 y 1 080.2 sobre lo mismo, y la diferencia es de sumar
valores ya redondeados a un decimal — cambia el 2.3% por el 2.4%, y nada
más). La máquina de
desarrollo varía **10–26%** entre corridas consecutivas. El denominador es
el que hace ruido, no el numerador — coherente con lo que la 8c ya había
medido en la suite (358 s contra 283 s, 27%) y con la causa que apuntó:
`/mnt/c` sobre NTFS bajo WSL2, donde la caché de páginas pesa.

De ahí lo que hay que citar: **el factor es «unas tres veces», entre 2.7x y
3.0x con la misma versión de código, y no admite dos decimales.** El 3.44x
que este documento publicaba no era falso: era una división cuyo
denominador tenía ±28% de dispersión sin que nadie lo supiera. **Se ha
discutido al segundo decimal un número cuyo primer decimal no está
determinado.**

**Lo que el cambio de código sí costó, medido donde el ruido es del 2.4%.**
Entre la versión de la 8c y la de la 8e, SERVIDORSIST midió **+1.8% en leer
y +14.8% en exportar** sobre los mismos 15 documentos. La lectura no se
tocó; la exportación subió porque la 8d y la 8e le añadieron columnas
—declarado y leído, `saldo_origen`, `pagina`— y los ficheros engordaron. Es
la explicación que encaja y la única máquina con ruido bajo la respalda. **La
subida del 28% en desarrollo NO es del código**: si lo fuera, SERVIDORSIST
la habría visto también.

#### M3 y M4 de la corrida del 9 de septiembre

| | 4 sep | 9 sep |
|---|---|---|
| RAM libre antes de medir | 3 205 MB | 3 376 MB |
| **RAM libre mínima, durante `auxiliar-gume`** | 2 809 MB | **2 978 MB** |
| pico del proceso | no se pudo leer | no se pudo leer |
| disco libre | 328.3 GB de 464.8 | **327.1 GB de 464.8** |
| `.xlsx`: mediana / máximo | 0.03 / 3.55 MB | 0.03 / **3.75 MB** |
| base de la cola, 75 trabajos | 0.17 MB | 0.17 MB |

Sigue sin ser restricción, con más holgura que en la corrida anterior. El
pico del proceso **sigue sin poder leerse en Windows**: lo medido allí es la
holgura del sistema, no el consumo.

#### El inventario de cobertura

Vive en **`INVENTARIO.md`**, en la raíz del repo, y **lo genera
`scripts/inventario.py`**:

```
.venv/bin/python scripts/inventario.py
```

Estaba aquí dentro hasta la 8g, y salió por lo que es: un artefacto
**generado** metido en un documento escrito a mano se queda obsoleto en la
primera fase que nadie lo regenere. `INVENTARIO.md` lleva su fecha y su
commit, así que se puede ver si caducó. Es el fichero que se le enseña al
despacho.

**Tres cosas que el inventario destapa por el hecho de existir:**

1. **El sistema no sabe de quién es un documento contable.** La columna
   `EMISOR` sale vacía en los 7 fixtures de balanza, auxiliar, mayor y
   pólizas: **ningún parser contable lee la empresa**. Solo los estados de
   cuenta lo traen, por `MetaEstadoCuenta.banco`. El guion tiene prohibido
   deducirlo del nombre del fichero, y un test lo impone.
2. **Y el `banco` que sí lee viene sucio.** Arrastra el domicilio
   (`…Banorte, Av. Revolución No. 3000, Colonia La Primavera C.P.64830…`),
   la etiqueta (`Emitido por: HSBC México…`) y, en Bajío, **el titular de la
   cuenta delante del banco** (`KARLDOR SA DE CV BANCO DEL BAJIO S.A.…`). El
   inventario lo recorta para que la tabla se lea; el dato sigue sucio.
3. **Solo 3 de 16 formatos quedan aprendidos.** Nueve salen `pendiente` de
   confirmación y cuatro no dejan plantilla, porque `AlmacenPlantillas.
   guardar()` rechaza lo que no cuadró. O sea que **la promesa de «la
   segunda vez entra sin intervención» hoy se cumple en 3 de 16**.

#### Por qué no cuadra lo que no cuadra

De las **61 reglas** que corren sobre los 27 fixtures, **20 no cuadran**, y
dan **11 motivos distintos**. La regla de esta fase: *el motivo que imprime
el sistema es una hipótesis, no un hallazgo*. Cada uno se fue a comprobar
contra el documento.

| | casos | qué significa |
|---|---|---|
| **A** — no_verificable y el documento no trae el dato | **9** | correcto |
| **B** — no_verificable pero el dato SÍ está | **6** | **defecto** |
| **C** — falla y el documento descuadra de verdad | **3** | correcto |
| **D** — falla porque leímos mal | **2** | **defecto** |

Las dos calibraciones caen donde debían: `poliza` con sus 53 CFDI sobre 50
pólizas es **C**, y los 552 430.42 de `diario-general` son **D**.

##### Los 11 motivos, con su etiqueta

| # | motivo del sistema | casos | etiqueta | contra qué se miró | cajón |
|---|---|---|---|---|---|
| M01 | «el documento no imprime una fila TOTAL con la que cruzar la suma de los saldos por cuenta» | 5 | **CONFIRMADO** en `edocta`, `edocta-bbva`, `edocta-hsbc` | los únicos «total» del documento son «ganancia anual total» y «total de comisiones», sin fila de saldos (p1 y p6 / p1 y p10 / p4) | A |
| M01 | ídem | | **REFUTADO** en `edocta-inbursa` | **p5 imprime `TOTALES` con cinco importes** | **B** |
| M01 | ídem | | **REFUTADO** en `edocta-bajio` | **p9 imprime `SALDO TOTAL`, y su importe COINCIDE con el `saldo_corte` que el parser leyó** | **B** |
| M02 | *(sin motivo)* | 3 | ver C y D | las tres son `falla`, y una regla que falla no lleva motivo: el detalle son sus discrepancias | C, D |
| M03 | «el documento no trae tabla de CFDI» | 2 | **CONFIRMADO** | ni `cfdi`, ni `uuid`, ni `folio fiscal`, ni `rfc`, ni `comprobante` aparecen en las 431 páginas | A |
| M04 | «ninguna cuenta declara depósitos y retiros propios; con dos o más cuentas el total del documento no se reparte» | 2 | **REFUTADO** | en `edocta-julio-banorte` p1, `+ TOTAL DE DEPÓSITOS` y `- TOTAL DE RETIROS` traen **dos importes cada uno, uno por cuenta**; en `edocta-santander` p1 el resumen trae un bloque por producto | **B** |
| M05 | «ninguna de las N cuenta(s) trae el resumen completo; falta: …» | 2 | **REFUTADO** | mismo sitio: `SALDO INICIAL DEL PERIODO` con tres importes en Banorte, y `saldo inicial` por producto en Santander p1 y p3 | **B** |
| M06 | «N de N CFDI sin número de documento con el que cruzar…» | 1 | **CONFIRMADO** | medido en la 7h: no hay criterio no circular que separe los 53 de los que cruzan | C |
| M07 | «N de N subtotales no corresponden a ninguna sección leída» | 1 | **CONFIRMADO** con matiz | medido en la 8b: los 563 huérfanos existen, pero **0.00 pesos no leídos**; el mensaje sugiere una causa que no hay | C |
| M08 | «el documento no imprime filas de subtotal» | 1 | **CONFIRMADO** | `subtotal` no aparece, y los `total` de p3, p8, p14… son **`TOTAL WINE`, un tercero**, no una fila de subtotal | A |
| M09 | «el documento no la declara: su fila de totales no cuadra debe contra haber» | 1 | **CONFIRMADO** | el parser sí lee la fila `SUMAS:` de p4, y **debe − haber = 802 416.67** sobre cifras de 8 dígitos | A |
| M10 | «ningún saldo se derivó: no hay ancla que comprobar» | 1 | **CONFIRMADO** | se deriva de M08: sin subtotales impresos no hay ancla que verificar | A |
| M11 | «no se recibió una balanza con la que cruzar…» | 1 | **CONFIRMADO** | correcto por diseño: ningún comando acepta dos documentos a la vez | A |

##### Y los 11 que no producen Excel

| motivo | documentos | comprobación | veredicto |
|---|---|---|---|
| «no trae tabla de movimientos porque la cuenta no tuvo ninguno» | `edocta-monex`, `edocta-multiva`, `edocta-scotiabank` | verificado en la 7d contra el propio resumen: depósitos 0.00 y retiros 0.00 | **A** — correcto |
| «el layout no parece una balanza», «no se encontró ninguna cuenta», «ninguno de los 60 mapeos…», «no se encontró ninguna póliza» | `balanza-fd`, `balanza-manufacturas`, `balanza-proactivity`, `mayor-fd`, `mayor-manufacturas`, `auxiliar-manufacturas`, `polizas-manufacturas` | **los 7 SÍ son de su tipo**: los siete traen la palabra que los nombra en su página 1, y los contables sus encabezados —`cargos`/`abonos` en las balanzas, `enero`/`febrero`/`acumulado` en los mayores, `concepto`/`movimiento` en el auxiliar, `diario` en las pólizas— | **B** — defecto, a nivel de documento entero |
| «se detectaron 48 renglones de mes y ninguno trae cargos, abonos ni saldo» | `mayor-proactivity` | el documento **no es un libro mayor** sino un reporte de movimientos por cuenta (8d) | **alcance pendiente**, no defecto: no existe parser para ese tipo |

#### Los defectos, ordenados por lo que le cuestan al contador

Solo cajones B y D. El orden es por consecuencia, no por dificultad: **un
dato leído mal que se ve correcto pesa más que uno que no se lee y se
declara**, y un documento del que no sale nada pesa más que una comprobación
que no corre.

**1. `diario-general` lee mal los importes.** Cajón **D**.

| | |
|---|---|
| reglas | `partida_doble` **100 de 5 302** pólizas, `totales` **105 de 10 604** |
| dinero | faltan 659 304.42 en el debe, **sobran** 106 873.98 en el haber; **552 430.42 sin aparecer en ningún lado** |
| por qué pesa lo que pesa | es el único caso donde el Excel se veía correcto con el importe mal leído; la 8d lo hizo visible partiendo declarado y leído, pero **el importe sigue mal** |
| qué tendría que cambiar | el **parser de pólizas** (`parsers/polizas.py`), en el reparto de importes por anclas: 22 movimientos traen debe y haber a la vez, imposible en un diario. Se extrae con `pdf_chars` y el 21.9% de sus palabras se traslapan. `Movimiento.pagina` (8d) ya permite cruzar cada importe perdido con la zona de traslape de su página |

**2. Siete documentos que son de su tipo y no se leen.** Cajón **B**.

| | |
|---|---|
| documentos | 3 balanzas (`fd`, `manufacturas`, `proactivity`), 2 mayores (`fd`, `manufacturas`), 1 auxiliar (`manufacturas`), 1 de pólizas (`manufacturas`) |
| coste | **el documento entero**: el contador no obtiene nada y lo captura a mano |
| qué tendría que cambiar | la **detección de layout** (`parsers/base.detectar_layout` y el `RE_CUENTA` de cada parser). §1.2 ya tiene medida al menos una causa: Proactivity numera `101.01.01` con punto y `balanza-fd` usa `000-000-100-000` de cuatro grupos, formas que el reconocedor de cuentas no acepta, así que la columna de cuenta desaparece y con ella la tabla |
| lo que lo hace menos grave que el 1 | **se declara**: salen con código 2 y su motivo. El sistema no finge haberlos leído |

**3. Seis comprobaciones que el documento permite y no corren.** Cajón **B**.

| | |
|---|---|
| casos | `edocta-inbursa` y `edocta-bajio` en `total_declarado` (0 de 2 cada uno); `edocta-julio-banorte` y `edocta-santander` en `resumen` (0 de 2 y 0 de 3) y en `resumen_movimientos` (0 de 4 y 0 de 6) |
| coste | el Excel sale, pero **con menos verificación de la que el documento permite**. `resumen_movimientos` es precisamente la regla que prueba que se leyeron TODOS los movimientos (§1.2): el resumen puede cuadrar consigo mismo y faltar media tabla |
| qué tendría que cambiar | el **parser de estados de cuenta** (`parsers/estado_cuenta.py`): `_CAMPOS_CUENTAS` para reconocer la fila `TOTALES` de Inbursa y el `SALDO TOTAL` de Bajío, y el reparto por columnas del bloque de resumen para leer **un importe por cuenta** cuando el documento imprime varios en el mismo renglón |
| lo que lo hace el menos grave | se declara `no_verificable` con motivo — pero **el motivo dice que el documento no trae el dato, y el documento sí lo trae**. Esa es la parte que hay que corregir aunque no se toque el parser |

**Coste de la suite al cerrar la fase**: **762 rápidos** (eran 747) en
~4m25s y **125 lentos** (eran 124) en 1h16m05s. El test nuevo del inventario
es el que sube el lento: abre los 27 documentos de una pasada. Como en la
8e, ninguno de los dos relojes es una medición limpia —la máquina de esta
fase resultó tener 10–26% de dispersión, que es precisamente lo que se midió
arriba—.

**Y dos defectos de forma que no entran en ningún cajón porque no son
reglas:**

- El campo `MetaEstadoCuenta.banco` **arrastra domicilio, etiqueta y —en
  Bajío— el titular de la cuenta**. Sale a la hoja `Cuentas` del Excel tal
  cual. No afecta a ninguna comprobación; sí a lo que el contador lee.
- `scripts/medir_servidorsist.py` **escribe su reporte en la raíz del
  repo**, no en `scripts/mediciones/`. Lo destapó el test que la 8e dejó
  puesto, que falló en esta fase las dos veces que se corrió la medición.
  El test hace su trabajo; el guion obliga a moverlo a mano cada vez.

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
| 8f | Inventario y barrido | Qué cubrimos, una línea por fixture; y por qué no cuadra lo que no cuadra, clasificado en cuatro cajones con el motivo comprobado contra el documento | **hecho** (762 rápidos + 125 lentos) |
| 8g | Los seis motivos refutados | Que el parser de estados de cuenta lea los totales y los resúmenes que el documento sí imprime; `MetaEstadoCuenta.banco` sin domicilio ni titular; `medir_servidorsist.py` deja de escribir en la raíz | siguiente |
| 8h | El diario | La segunda mecánica de pérdida de importes en `diario-general`. **Se ha pospuesto tres veces; no se pospone más** | |
| 9 | Cobertura de formatos | Los 7 fixtures que sí son de su tipo y no se leen; leer el emisor; modo diagnóstico que convierta cada rechazo en una petición concreta de documento | |
| 10 | Cruce contra comprobantes | CFDI timbrados de `fixtures/real/XML R Y E/`, y mayor contra balanza | |

> **Sin fase todavía**: los residuos del ancla (la antigua 8g), la
> `referencia` pegada y los espacios dentro de las palabras de los estados de
> cuenta, y `naturaleza_origen` en balanza. El barrido de la 8f los dejó
> compitiendo por prioridad con lo que encontró, que es para lo que se hizo.

> **Por qué la 8g va antes que el diario.** La 8f midió que seis motivos son
> **falsos sobre el documento**: el sistema imprime «el documento no trae el
> dato» y el dato está impreso, a veces en la misma cifra que el parser ya
> había leído. Eso no es dejar de verificar; es afirmar algo sobre el PDF que
> no es cierto, y es más grave que no leer un documento —que el sistema
> declara— aunque moleste menos. Además está todo localizado en un parser,
> con la página y la evidencia ya escritas en §2: es la fase más barata de
> las tres.

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
- Los números de la sección 2 y de `MEDICIONES.md` — son mediciones, no
  metas ajustables.

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

**Vivas hoy**: los seis motivos refutados, los siete documentos que no
sabemos leer, `naturaleza_origen` en balanza, y la `referencia` y los
espacios de los estados de cuenta. Las tachadas las cerraron la 8e y la 8f;
se quedan en su sitio, con su texto original debajo, porque el patrón que las
produjo se repite y moverlas rompe las referencias de los prompts anteriores.

- **Seis motivos afirman algo falso sobre el documento.** Medido en la 8f
  yendo al PDF, motivo por motivo: `edocta-inbursa` imprime `TOTALES` con
  cinco importes en la p5; `edocta-bajio` imprime `SALDO TOTAL` en la p9 **y
  su importe coincide con el `saldo_corte` que el parser ya había leído**;
  `edocta-julio-banorte` trae `+ TOTAL DE DEPÓSITOS` y `- TOTAL DE RETIROS`
  con un importe por cuenta, de modo que el motivo «el total del documento no
  se reparte» describe un problema que no existe; y `edocta-santander` trae
  el resumen en un bloque por producto. **Un motivo es una frase sobre el
  PDF, y lo estaba emitiendo el parser sobre sí mismo.** Es el defecto más
  grave abierto: no deja de verificar, afirma. **Fase 8g.**
- **Siete documentos que sí son de su tipo y no sabemos leer.** `balanza-fd`,
  `balanza-manufacturas`, `balanza-proactivity`, `mayor-fd`,
  `mayor-manufacturas`, `auxiliar-manufacturas` y `polizas-manufacturas`.
  Hasta la 8f figuraban como «alcance pendiente»; la 8f fue a mirar y **los
  siete traen en su página 1 la palabra que los nombra y sus encabezados
  contables**. Así que no es alcance: es cajón B a nivel de documento entero.
  Denominador propio: 7 de 27 fixtures, que no se suma a los 20 casos sobre
  61 reglas del barrido. **Fase 9.**
- **El sistema no lee el emisor de ningún documento contable.** Siete
  columnas del inventario vacías. Para un despacho con varias empresas
  cliente, el emisor es lo que separa las plantillas; hoy esa separación es
  el `--tenant` que teclea quien sube el documento. Y el único emisor que sí
  se lee, el banco de los estados de cuenta, **viene sucio**: con domicilio,
  con la etiqueta pegada, y en Bajío con el titular delante. **Fase 9 el
  emisor; el banco sucio, fase 8g, que es una línea del mismo parser.**
- **`medir_servidorsist.py` escribe su `.txt` en la raíz del repo.** Lo
  destapó el test que la 8e dejó puesto para impedir exactamente eso, y falló
  las dos veces que se corrió la medición. **Fase 8g.**
- **Solo 3 de los 16 formatos dejan plantilla aprendida.** No es un defecto:
  es la consecuencia directa de no aprender de documentos que no cuadran, que
  es la regla que impide propagar un error a todos los documentos futuros de
  un cliente. Pero **desmiente la promesa tal como estaba escrita** —«la
  segunda vez entra sin intervención»— y hay que decirlo antes de prometerlo
  a un contador. Corregido en `USO.md`. **Sin fase: se arregla solo según
  bajen los defectos.**

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
  `MEDICIONES.md`, «Resultados de la fase 8c»: respaldo, arranque como
  servicio, ventana
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
  agrupado. **Decía fase 7c**, y `MEDICIONES.md`, en la 7c, dice que se
  resolvió
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