# USO.md — cómo se corre cp-pdf

Operación del sistema desde la línea de comandos. El *por qué* de las
decisiones vive en `PLAN.md`; el *qué* de los módulos, en `ARQUITECTURA.md`.
Aquí solo está el *cómo se usa*.

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

**Libro mayor** — `mayor-gume.pdf`, `mayor-proactivity.pdf`

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

Siete fixtures nunca tuvieron parser: `balanza-fd`, `balanza-manufacturas`,
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

| Documento | Páginas | Leer y validar | Exportar | Total |
|---|---|---|---|---|
| Mediana de los 17 que procesan | — | — | — | **1.5 s** |
| `auxiliar-gume.pdf` | 886 | 183 s | 5 s | **3m 08s** |

Suma de los 17: 6m25s. Pico de memoria: 658 MB.

> Una versión anterior de este documento decía que `auxiliar-gume` tardaba
> 3m57s. Ese número se midió **sin `-o`**, así que nunca escribía el Excel;
> el total real con el exportador de entonces era 23m45s. La 8c corrigió el
> exportador y ahora son 3m08s completos. Ver PLAN.md §1.3.

Los tiempos en SERVIDORSIST (i5-3470 de 2012, HDD) serán peores y **no se
han medido todavía**: se corren con `scripts/medir_servidorsist.py`.

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

Los tipos con tablas relacionadas (pólizas, mayor) llevan además una hoja
plana con todo junto, para filtrar y hacer tablas dinámicas.

---

## Aprendizaje de plantillas

Cuando un documento cuadra completo, el sistema guarda la plantilla del
formato: qué columnas, qué estrategia de extracción, qué reglas aplican. La
siguiente vez que llegue un documento del mismo emisor entra sin
intervención.

**No guarda plantillas de documentos que no cuadraron.** Eso es lo que evita
que un error se propague a todos los documentos futuros de ese cliente.

Consecuencia práctica: correr el mismo documento dos veces no da el mismo
camino, porque la segunda vez ya hay plantilla. Para una corrida limpia:

```bash
contapdf balanza fixtures/real/1-Balanza/balanza.pdf -o salida/balanza.xlsx \
  --plantillas /tmp/plantillas-limpias
```

---

## Tests

```bash
pytest tests/ -q            # 710 rápidos, ~4m26s
pytest tests/ -q -m lento   # 111 lentos, ~34m
pytest tests/ -q --lf       # solo los que fallaron la última vez
```