# USO.md — cómo se corre cp-pdf

Operación del sistema desde la línea de comandos. El *por qué* de las
decisiones vive en `PLAN.md`; el *qué* de los módulos, en `ARQUITECTURA.md`;
las mediciones de las fases cerradas, en `MEDICIONES.md`; y **qué documentos
cubre el sistema hoy, en `INVENTARIO.md`**, que se regenera con
`python scripts/inventario.py`. Aquí solo está el *cómo se usa*.

---

## Instalación

Desde la raíz del repo, con el venv activado:

```bash
cd /mnt/c/proyectos/cp-pdf
source .venv/bin/activate
pip install -e .
```

`pip install -e .` instala el paquete en modo editable y registra el comando
`contapdf`. Hay que repetirlo cada vez que se recrea el venv. **No funciona
`python -m contapdf`**: el paquete no tiene `__main__.py` y no lo necesita,
porque el CLI se expone como script en `[project.scripts]` de
`pyproject.toml`.

Comprobación:

```bash
contapdf --help
```

En Windows, el ejecutable queda en `.venv\Scripts\contapdf` y se invoca por
esa ruta. `python -m contapdf` tampoco funciona allí.

---

## Forma de los comandos

Los cinco subcomandos de procesamiento tienen la misma firma:

```
contapdf <tipo> [-o SALIDA.xlsx] [--tenant ID] [--plantillas DIR] archivo.pdf
```

| Argumento | Qué hace |
|---|---|
| `<tipo>` | `balanza`, `auxiliar`, `polizas`, `estado-cuenta`, `mayor` |
| `archivo.pdf` | Posicional, obligatorio, va al final |
| `-o`, `--out` | Ruta del `.xlsx`. **Sin esto solo reporta; no genera archivo.** |
| `--tenant` | ID del despacho. Aísla las plantillas aprendidas por cliente. |
| `--plantillas` | Directorio donde viven las plantillas aprendidas |

Hay un sexto subcomando, `confirmar`, que cierra el bucle de aprendizaje:
confirma manualmente lo que la validación no pudo verificar sola.

### Códigos de salida

| Código | Significa |
|---|---|
| `0` | Todas las reglas cuadran. El sistema aprende la plantilla del formato. |
| `1` | Alguna regla falla. Se genera el Excel igual, pero **no** aprende plantilla. |
| `2` | Error de uso: el documento no se reconoció, el directorio de `-o` no existe, argumentos mal. |

Que un documento salga en `1` no es un error de la herramienta: es su
producto. Ver «Cómo leer el reporte» abajo.

El `2` se comprueba **antes** de procesar, no al guardar: si el directorio de
`-o` no existe, el comando avisa y no trabaja en balde. No lo crea a
propósito — crear lo que nadie pidió esconde el error.

Para verlo:

```bash
contapdf polizas fixtures/real/2-Libro-Diario/poliza.pdf -o salida/polizas.xlsx
echo "código: $?"
```

---

## Los cinco comandos, con documentos reales del repo

```bash
mkdir -p salida

contapdf balanza       fixtures/real/1-Balanza/balanza.pdf              -o salida/balanza.xlsx
contapdf auxiliar      fixtures/real/3-Auxiliares/auxiliar.pdf          -o salida/auxiliar.xlsx
contapdf polizas       fixtures/real/2-Libro-Diario/poliza.pdf          -o salida/polizas.xlsx
contapdf estado-cuenta fixtures/real/4-Estados-Cuenta/edocta.pdf        -o salida/edocta.xlsx
contapdf mayor         fixtures/real/5-Libro-Mayor/mayor-gume.pdf       -o salida/mayor.xlsx
```

### Variantes por formato

El mismo parser cubre varios formatos del mismo tipo. No hay una rama por
empresa ni por banco.

**Balanzas** — `balanza.pdf`, `balanza-businesspro.pdf`, `balanza-gume.pdf`

**Auxiliares** — `auxiliar.pdf`, `auxiliar-gume.pdf`

**Pólizas** — `poliza.pdf`, `diario-general.pdf`

**Libro mayor** — `mayor-gume.pdf`. **`mayor-proactivity.pdf` sale con
código 2 y el motivo escrito**, desde la 8e:

```
se detectaron 48 renglones de mes y ninguno trae cargos, abonos ni saldo;
el documento no parece un libro mayor
```

No es un libro mayor: es un reporte de movimientos por cuenta, y no imprime
meses. Antes de la 8e producía un Excel vacío con cara de resultado
—`nombre_cuenta` con el bloque de bancos pegado, `naturaleza` vacía,
importes en cero— y contaba entre los documentos que procesan. **Un reporte
de movimientos por cuenta no tiene parser todavía**; eso es alcance
pendiente, no una regresión.

**Estados de cuenta** — seis formatos verificados:

```bash
contapdf estado-cuenta fixtures/real/4-Estados-Cuenta/edocta.pdf                  -o salida/afirme.xlsx
contapdf estado-cuenta fixtures/real/4-Estados-Cuenta/edocta-abril-santander.pdf  -o salida/santander.xlsx
contapdf estado-cuenta fixtures/real/4-Estados-Cuenta/edocta-julio-banorte.pdf    -o salida/banorte.xlsx
contapdf estado-cuenta fixtures/real/4-Estados-Cuenta/edocta-bajio.pdf            -o salida/bajio.xlsx
contapdf estado-cuenta fixtures/real/4-Estados-Cuenta/edocta-inbursa.pdf          -o salida/inbursa.xlsx
contapdf estado-cuenta fixtures/real/4-Estados-Cuenta/edocta-bbva.pdf             -o salida/bbva.xlsx
```

**El caso de OCR automático** — `edocta-hsbc.pdf` no trae la tabla que
traduce glifos a letras (99.5% en CID sin mapa ToUnicode), así que el
sistema lo detecta y lo relee por OCR sin que nadie se lo pida:

```bash
contapdf estado-cuenta fixtures/real/4-Estados-Cuenta/edocta-hsbc.pdf -o salida/hsbc.xlsx
```

Tarda ~21 s más que los demás. Es el precio del OCR.

### Documentos que todavía no tienen parser

> **El inventario completo, con sus dos tablas y el motivo exacto de cada
> rechazo, está en `INVENTARIO.md`.** Lo de aquí abajo es el resumen; si no
> coinciden, manda el inventario, que lo genera un guion.

La 8f fue a mirarlos y **los siete son de su tipo**: traen en la página 1 la
palabra que los nombra y sus encabezados contables. Así que no es alcance
pendiente, es cobertura que falta. Son: `balanza-fd`, `balanza-manufacturas`,
`balanza-proactivity`, `auxiliar-manufacturas`, `polizas-manufacturas`,
`mayor-manufacturas` y `mayor-fd`. No es una regresión; es alcance pendiente.
Los tres restantes de los 27 son estados de cuenta sin tabla de movimientos
(`multiva`, `monex`, `scotiabank`): no hay nada que extraer, y el sistema lo
dice en vez de inventarlo.

Todos ellos salen con `no_reconocido` y código `2`, con el motivo impreso —
nunca con una traza.

---

## Tiempos medidos

Máquina de desarrollo (i5-1335U, SSD), sin nada más corriendo:

El reloj va siempre partido: leer y validar por un lado, exportar por otro.
Un total único escondió durante nueve fases que el exportador era cuadrático.

> **Estas cifras son indicativas, no mediciones firmes.** La 8f corrió la
> misma medición dos veces seguidas en esta máquina, sin tocar una línea de
> código, y la suma salió **11% distinta**; `poliza` sola se movió un **26%**.
> Un portátil con turbo y gestión térmica no es un instrumento estable. Úsalas
> para ver órdenes de magnitud —qué documento es caro y cuál no— y nunca para
> comparar al segundo decimal.

| Documento | Páginas | Leer y validar | Exportar | Total |
|---|---|---|---|---|
| Mediana de los que producen Excel | — | 1.4 s | 0.0 s | **1.5 s** |
| `auxiliar-gume.pdf` | 886 | 183.4 s | 5.2 s | **3m 08s** |

**Suma de los 16 que producen Excel: 5m25s.** Eran 17 y 6m25s hasta la 8e,
cuando `mayor-proactivity` pasó a rechazarse: se dejaba un minuto entero en
no leer nada. Pico de memoria del proceso: 658 MB, en `auxiliar-gume`.

> Una versión anterior de este documento decía que `auxiliar-gume` tardaba
> 3m57s. Ese número se midió **sin `-o`**, así que nunca escribía el Excel;
> el total real con el exportador de entonces era 23m45s. La 8c corrigió el
> exportador y ahora son 3m08s completos. Ver PLAN.md §1.3.

### SERVIDORSIST (i5-3470 de 2012, HDD, con Apache y MySQL activos)

Medido con `scripts/medir_servidorsist.py`, el mismo guion en las dos
máquinas. Ficheros en `scripts/mediciones/`; la corrida buena es la del **9 de
septiembre**, con Tesseract en el PATH y los 16 documentos que producen Excel.

**Los tiempos absolutos de esta máquina son firmes.** Dos corridas separadas
por cinco días quedaron a **2.4%** una de otra:

| Documento | Páginas | Leer y validar | Exportar | Total |
|---|---|---|---|---|
| Mediana de los 16 | — | 5.1 s | 0.2 s | **5.3 s** |
| `edocta-hsbc` (OCR) | 4 | 48.7 s | 0.1 s | **48.8 s** |
| `auxiliar` | 398 | 50.5 s | 2.4 s | **52.9 s** |
| `poliza.pdf` | 968 | 97.7 s | 5.2 s | **1m 43s** |
| `diario-general` | 431 | 203.1 s | 16.5 s | **3m 40s** |
| `auxiliar-gume.pdf` | 886 | 633.5 s | 20.8 s | **10m 54s** |
| **Suma de los 16** | — | 18m01s | 47.6 s | **18m49s** |

**El factor contra desarrollo es «unas tres veces», y no admite decimales.**
Está entre **2.7× y 3.0×** según con cuál de las dos corridas de desarrollo se
divida. No es que la medición saliera mal: **el denominador tiene ±28% de
ruido y nadie lo sabía**. SERVIDORSIST varía un 2.4% entre corridas; el
portátil de desarrollo, entre un 11% y un 26%. Se estuvo discutiendo el
segundo decimal de un número cuyo primer decimal no está determinado.

> Versiones anteriores de esta tabla dijeron «3.4–3.7× consistente», luego
> 3.44×, luego 3.40×, y cada corrección afinaba un decimal. Las tres eran
> divisiones sobre un denominador ruidoso. **Lo citable es «unas tres veces
> más lento».**

**El OCR funciona en esa máquina desde la 8d, y está verificado allí**:
`edocta-hsbc` completó por OCR el 9 de septiembre, con su `.xlsx` escrito.
Antes reventaba con `UnicodeDecodeError: 'charmap' codec` porque `ocr.py`
lanzaba Tesseract sin declarar la codificación y Windows en español decodifica
con cp1252. **Cuesta 48.8 s allí contra ~15 s aquí**: es el documento más caro
por página del proyecto.

**El disco no es restricción**: 327 GB libres de 464.8 GB, contra un techo de
281 MB al día si el barrido no existiera.

**La memoria tampoco, pero lo medido es la holgura**: el mínimo de RAM libre
durante la corrida fue 2,978 MB de 8,078, con Apache y MySQL activos. El pico
del proceso allí **no se pudo leer** —el instrumento no obtiene el
`WorkingSetSize` en Windows—, así que los 658 MB de pico son de desarrollo y
no se han confirmado en la máquina objetivo.

**Consecuencia operativa:** SERVIDORSIST se apaga a las 21:00 y la cola es
secuencial. Con `auxiliar-gume` en 10m54s, un documento grande subido después
de las **20:49** no termina, y si alguien sube algo detrás, ese también se
pierde aunque tardara segundos. Esta cuenta sí es fiable: sale de los tiempos
de SERVIDORSIST, que son los estables.

---

## Cómo leer el reporte

Salida real de `contapdf auxiliar fixtures/real/3-Auxiliares/auxiliar-gume.pdf`:

```
  paginas    : 886
  extraccion : pdf_text
               texto nativo limpio en la muestra
  filas: 57759   secciones: 732   subtotales: 735
  saldos: 48745 legibles, 9014 sin saldo en el PDF
  validacion: 1 discrepancias
  cobertura : 3 reglas: 2 cuadran, 1 fallan, 0 no verificables;
              48355 de 58518 casos evaluados
```

**`extraccion`** — qué estrategia usó y por qué. `pdf_text` es texto nativo;
`pdf_chars` reconstruye desde caracteres sueltos; `ocr` significa que la capa
de texto no servía y se releyó la imagen.

**`cobertura`** — la cifra que importa. Cada regla reporta **dos números**:

```
  saldo_corrido   cuadra   47987 de 57024 evaluados, 47965 exactas, 22 dentro de tolerancia
                           9013 de 57024 movimientos no traen saldo legible en la capa de texto
                           24 de 57024 abren cadena y no tienen contra qué encadenarse
```

`47987 de 57024` no es lo mismo que `47987`. El denominador es cuántos casos
**existían**; el numerador, sobre cuántos **corrió** la regla. Un conteo sin
su denominador puede esconder que la regla casi no se ejecutó.

**Los tres estados de una regla:**

| Estado | Significa |
|---|---|
| `cuadra` | La identidad se cumple en todos los casos evaluados |
| `falla` | Hay diferencias, y se listan |
| `no_verificable` | El documento no trae el dato para comprobarlo |

`no_verificable` **no** es un error: es el sistema diciendo que no puede
probar algo, en vez de afirmarlo.

**El aviso de circularidad:**

```
  OJO: 26032 de esas comprobaciones cayeron sobre saldos recalculados
       por el sistema, no sobre dato impreso
```

Cuando un saldo lo calculó el propio sistema encadenando, comprobar después
que cumple esa misma fórmula no prueba nada. El reporte lo declara para que
nadie lea el resultado como si fuera verificación contra el documento.

**Las discrepancias, con nombre y cifras:**

```
  ! 1190-001-000   subtotal_debe   esperado 37,398,127.33   obtenido 37,398,127.31
```

---

## El Excel que genera

Una hoja por tabla del documento, más una hoja `Validacion` con la cobertura
completa: cada regla, su estado, sus dos cifras y el motivo de lo que no se
pudo evaluar.

Los tipos con tablas relacionadas —pólizas, estado de cuenta, mayor— llevan
además una hoja `Plana` con todo junto, para filtrar y hacer tablas dinámicas
sin fórmulas de búsqueda.

| Tipo | Hojas | Clave de cruce |
|---|---|---|
| Balanza | `Balanza` · `Validacion` | `cuenta` |
| Auxiliar | `Auxiliar` · `Validacion` | `cuenta` |
| Pólizas | `Polizas` · `Movimientos` · `CFDI` · `Plana` · `Validacion` | `poliza_id` |
| Estado de cuenta | `Cuentas` · `Movimientos` · `Plana` · `Validacion` | `num_cuenta` |
| Libro mayor | `Cuentas` · `Meses` · `Plana` · `Validacion` | `cuenta` |

> **La hoja `Polizas` lleva las dos cifras.** `total_debe_declarado` y
> `total_haber_declarado` son lo que el documento afirma;
> `total_debe_leido` y `total_haber_leido`, la suma de los movimientos que el
> sistema leyó. **`completa` es VERDADERO solo si el bloque cerró y las dos
> coinciden.** En `poliza.pdf` no difiere ninguna; en `diario-general.pdf`
> difieren 100, que son exactamente las 100 que fallan `partida_doble`.
> Corregido en la 8d: antes la hoja mostraba solo lo declarado y se veía
> correcta justo cuando un importe se había leído mal.

> **La hoja `Auxiliar` dice qué saldos calculó el sistema.** Cuando el
> documento no imprime un saldo legible, el sistema lo deriva encadenando y
> solo lo entrega si la cadena aterriza exacta en el subtotal declarado; la
> columna `saldo_origen` dice cuál es cuál. En `auxiliar-gume`: **22,713
> impresos, 26,032 recalculados y 9,014 sin saldo**. Un saldo recalculado es
> coherencia interna, no verificación contra el documento. Añadido en la 8e.

> **Las hojas `Cuentas` de mayor y de estado de cuenta llevan declarado y
> leído**, como `Polizas`. En `mayor-gume` hay 1 cuenta de 49 donde difieren
> (`1190-000-000`, por 0.01) y `acumulados` la nombra; en los cuatro estados
> de cuenta medidos no difiere ninguna. Añadido en la 8e.

> **Cuidado con la hoja `Balanza`: todavía no dice cuándo dedujo la
> naturaleza.** Es el último sitio donde un valor derivado se ve igual que uno
> leído. PLAN §5.1, sin fase asignada.

---

## Aprendizaje de plantillas

Cuando un documento cuadra completo, el sistema guarda la plantilla del
formato: qué columnas, qué estrategia de extracción, qué reglas aplican. La
siguiente vez que llegue un documento del mismo formato entra sin
intervención.

**No guarda plantillas de documentos que no cuadraron.** Eso es lo que evita
que un error se propague a todos los documentos futuros de ese cliente.

> **Y por eso hoy aprende poco: 3 de los 16 formatos.** Lo midió el inventario
> de la 8f. No es un defecto del aprendizaje — es la consecuencia directa de
> la regla de arriba: mientras un formato tenga una regla que falla o que no
> se puede verificar, no deja plantilla. Conviene saberlo antes de prometer
> que «la segunda vez entra solo», porque hoy eso se cumple en 3 de 16.

Consecuencia práctica: correr el mismo documento dos veces no da el mismo
camino, porque la segunda vez ya hay plantilla. Para una corrida limpia:

```bash
contapdf balanza fixtures/real/1-Balanza/balanza.pdf -o salida/balanza.xlsx \
  --plantillas /tmp/plantillas-limpias
```

---

## Tests

```bash
pytest tests/ -q            # 804 rápidos, ~4m09s
pytest tests/ -q -m lento   # 125 lentos, ~1h03m
pytest tests/ -q --lf       # solo los que fallaron la última vez
```

El reloj de los lentos no se ha medido en aislamiento: es orden de magnitud,
no cifra.

**Los lentos hay que correrlos antes de entregar, no «si da tiempo».** En la
8e, un cambio dejó obsoleto un test escrito tres fases antes y **el único que
lo vio fue un test lento**, a los 52 minutos de corrida, con las cinco
corridas rápidas en verde.