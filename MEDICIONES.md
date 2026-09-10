# Mediciones

Los resultados de las fases **cerradas**, tal como se escribieron al
cerrarlas. Salieron de `PLAN.md` §2 en la fase 8g, cuando ese documento
llegó a los 197 KB y sus dos tercios eran fases ya superadas.

**Qué es esto.** Cada bloque es lo que se midió en una fase: las cifras con
su denominador, las hipótesis que una medición refutó, y lo que se decidió
por qué. No es un historial de cambios —eso lo lleva git— sino el registro
de los números que el proyecto puede citar.

**Quién escribe aquí.** Claude Code, al cerrar cada fase. `PLAN.md` §2
conserva únicamente la fase en curso y una línea de índice por cada fase
movida; esa línea **no lleva cifras a propósito**, para que citar un número
obligue a abrir este fichero y leerlo.

**El orden es cronológico**, de la fase más antigua a la más reciente.

**No se resume nada al mover.** Un resumen de una medición pierde el
denominador, que es lo único que la hace defendible. Los bloques se
trasladan carácter por carácter, y un test lo comprueba
(`tests/test_traslado_mediciones.py`).

---

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

