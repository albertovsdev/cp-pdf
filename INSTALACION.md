# Instalación

Cómo poner `contapdf` en una máquina, y cómo medirla. Escrito en la fase 8c
mientras se preparaba la instalación en SERVIDORSIST.

Esto **no** es un procedimiento de puesta en producción: no cubre
autenticación, respaldo ni arranque automático. Esos siguen abiertos; están
al final, en el checklist.

## Qué de esto está verificado y qué no

Hay que decirlo antes que nada, porque cambia cuánto se puede confiar en
cada sección. **No hay acceso a SERVIDORSIST desde la sesión de
desarrollo**: se entra por Escritorio Remoto, no hay SSH, y no se va a
montar. Lo que sigue se corrigió en la fase 8e **con lo que ocurrió de
verdad** al instalar y medir allí el 4 de septiembre de 2026.

| Sección | Estado |
|---|---|
| §1 dependencias, y que faltaba `pypdfium2` | **Verificado.** Se encontró leyendo `ocr.py` contra `pyproject.toml`, se corrigió, y la instalación real en Windows no volvió a tropezar con ello |
| §2 los pasos de Windows | **EJECUTADOS.** Se instaló y se corrió en SERVIDORSIST. Corregidos aquí con las desviaciones reales: se instaló git y el repo quedó en `C:\proyectos\cp-pdf`, y el Tesseract de `winget` no ofrece la pantalla de idiomas |
| §3 el guion de medición | **EJECUTADO en las dos plataformas.** En SERVIDORSIST midió 16 de 17 documentos; los números están en PLAN §2 y el reporte en `scripts/mediciones/` |
| §4 uso desde la línea de comandos | **Verificado en las dos**, pero solo en la forma `contapdf` / `.venv\Scripts\contapdf`. El `python -m contapdf.cli` que decía antes **no se ha ejecutado nunca en Windows** |
| §5 los fallos | Ya no son previsiones: los de Tesseract ocurrieron. Y se suma uno que nadie previó — **el OCR nunca funcionó en esa máquina** |

**Lo que sigue SIN verificar allí es el OCR.** La fase 8d encontró y
corrigió su causa, pero el arreglo no se ha probado en SERVIDORSIST: la
suite corre en WSL y ningún test cubre Windows. Ver §5.

---

## 1. Qué hace falta

| | Versión | Por qué |
|---|---|---|
| Python | 3.11 o más (`requires-python` en `pyproject.toml`) | El sistema usa `X \| None` y `match` |
| pdfplumber | cualquiera reciente | extracción principal |
| openpyxl | cualquiera reciente | escribir el `.xlsx` |
| Flask | 3.x | solo para la capa web |
| **pypdfium2** | cualquiera | **rasterizar para OCR** |
| Tesseract | 4 o 5, con idioma `spa` | OCR |

### La trampa: `pypdfium2` no estaba declarado

`src/contapdf/extract/ocr.py` hace `import pypdfium2 as pdfium`, pero
`pypdfium2` **no estaba en las dependencias de `pyproject.toml`**. En la
máquina de desarrollo estaba instalado de antes, así que nadie lo notó
durante nueve fases. En una máquina limpia, `pip install -e .` no lo trae
y el OCR falla al primer estado de cuenta escaneado — el módulo entero no
importa.

Se detectó al preparar esta instalación y **se agregó a
`pyproject.toml`**. Si se instala desde un `pyproject.toml` anterior a la
8c, hay que añadirlo a mano:

```
pip install pypdfium2
```

`pypdfium2` es un binding de PDFium y **no necesita AVX2**, así que corre
en el i5-3470 de SERVIDORSIST. Las librerías que sí lo asumen —PaddleOCR,
Surya, PyTorch reciente— están descartadas desde la fase 6; por eso el OCR
es Tesseract.

---

## 2. Instalación en Windows 10 (SERVIDORSIST)

SERVIDORSIST solo se alcanza por Escritorio Remoto: no hay SSH y no se va a
montar. Todo lo de abajo se teclea en esa sesión.

### 2.1 Traer el repositorio

**Corregido en la 8e con lo que se hizo de verdad.** Esta sección decía que
no había git en la máquina y que el repo iba a `C:\contapdf`. Las dos cosas
resultaron falsas: **se instaló git** y el repo quedó en
`C:\proyectos\cp-pdf`, que es la ruta que aparece en los reportes de
medición y la que hay que usar.

```
C:\proyectos\cp-pdf\
    src\  tests\  scripts\  fixtures\  pyproject.toml  ...
```

Con git instalado se clona y se actualiza con `git pull`, que es mejor que
copiar la carpeta: una copia manual no dice qué versión es. Si en otra
máquina no hubiera git, copiar la carpeta sigue sirviendo — se pueden dejar
fuera `.venv\`, `.git\` y `salida\`, que no hacen falta y pesan.

### 2.2 Copiar los PDFs de prueba

**Solo si se va a medir.** Los fixtures reales están en `.gitignore` porque
llevan datos de clientes; hay que copiarlos aparte a:

```
C:\proyectos\cp-pdf\fixtures\real\
    1-Balanza\  2-Libro-Diario\  3-Auxiliares\
    4-Estados-Cuenta\  5-Libro-Mayor\
```

> Son documentos contables de clientes reales. Van a una máquina que ya
> guarda documentos de esos mismos clientes, así que no cambian el
> perímetro — pero conviene borrarlos cuando la medición termine, porque
> ahí no los protege nada más que el sistema de ficheros.

### 2.3 Python

Windows 10 no trae Python. Instalador oficial de python.org, marcando
**«Add python.exe to PATH»**. Comprobar:

```
py -3.12 --version
```

Si `py` no existe, el instalador no puso el lanzador; entonces se usa la
ruta completa, algo como
`C:\Users\<usuario>\AppData\Local\Programs\Python\Python312\python.exe`.

### 2.4 Entorno virtual y dependencias

```
cd C:\proyectos\cp-pdf
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m pip install pypdfium2
```

El último no hace falta si el `pyproject.toml` es de la 8c o posterior; se
deja escrito porque es el paso que faltaba.

Comprobar que el núcleo importa:

```
.venv\Scripts\python -c "import contapdf.cli; print('ok')"
```

### 2.5 Tesseract

Solo para documentos escaneados.

**OJO con `winget`, corregido en la 8e.** Si se instala con
`winget install UB-Mannheim.TesseractOCR`, **el instalador no ofrece la
pantalla de componentes**, así que no hay dónde marcar el idioma español y
Tesseract queda solo con inglés. Hay dos salidas:

- ejecutar el instalador gráfico de UB Mannheim
  (`tesseract-ocr-w64-setup-*.exe`) en vez de `winget`, y marcar **español
  (`spa`)** en «Additional language data»; o
- dejar el `winget` y **bajar `spa.traineddata` aparte**, desde
  `github.com/tesseract-ocr/tessdata`, copiándolo a
  `C:\Program Files\Tesseract-OCR\tessdata\`.

Sin `spa`, el guion de medición avisa con `OJO: falta el idioma 'spa'`.

`ocr.py` invoca el binario por nombre, así que tiene que estar en el
`PATH`:

```
tesseract --version
tesseract --list-langs
```

Si `tesseract` no está en el `PATH`, el sistema **no revienta**:
`hay_tesseract()` devuelve `False` y el documento sale con su motivo
declarado. Se pierde el OCR, no la ejecución.

### 2.6 Arrancar el servidor web

No hay servicio de Windows en esta fase: se arranca a mano y se ve la
consola.

```
cd C:\proyectos\cp-pdf
.venv\Scripts\python -m flask --app contapdf.web:crear_app run --host 0.0.0.0 --port 8080
```

**El puerto 8080, no el 80**: Apache ya ocupa el 80 en esa máquina (PLAN
§6). `--host 0.0.0.0` hace que se vea desde la red local; sin eso solo
responde en la propia máquina. Desde otro equipo de la oficina:

```
http://SERVIDORSIST:8080/
```

que redirige a `http://SERVIDORSIST:8080/t/general/`.

> El servidor de desarrollo de Flask **no** es un servidor de producción.
> Para la demostración de esta fase alcanza. Para uso diario habría que
> ponerlo detrás de algo (waitress, o un proxy de Apache), y eso toca
> configuración de Apache, que esta fase tiene prohibido tocar.

---

## 3. Medir la máquina

```
cd C:\proyectos\cp-pdf
.venv\Scripts\python scripts\medir_servidorsist.py --rapido
```

`--rapido` saltea `auxiliar-gume` y `diario-general`, que son los dos
largos. Sirve para descubrir problemas de instalación sin esperar. Si sale
bien, la medición de verdad:

```
.venv\Scripts\python scripts\medir_servidorsist.py
```

Deja un fichero `mediciones-SERVIDORSIST-<fecha>.txt` en el directorio
actual, además de imprimirlo. **Ese `.txt` es lo que hay que traer de
vuelta.**

El guion no aborta por nada: si falta Tesseract, si falta un PDF o si un
documento revienta, lo escribe y sigue con el resto. Y va volcando a disco
conforme mide, así que una corrida cortada a la mitad deja lo que llevaba.

**Mientras mide, no correr nada más.** Es el error que invalidó la primera
medición de la fase 8a. (Con lo que se supo en la 8c, aquellos 1 576 s no
eran solo contaminación: incluían la exportación, que entonces era
cuadrática. Dos errores sumados dieron un número que parecía explicado.)

---

## 4. Uso desde la línea de comandos

Cinco comandos, la misma forma. **La forma canónica es el ejecutable
`contapdf` que instala `pip install -e .`**, y es la única verificada en
las dos plataformas:

```
# Linux
contapdf balanza /ruta/balanza.pdf -o /salida/balanza.xlsx
contapdf auxiliar      ...
contapdf polizas       ...
contapdf estado-cuenta ...
contapdf mayor         ...

# Windows
.venv\Scripts\contapdf balanza C:\ruta\balanza.pdf -o C:\salida\balanza.xlsx
.venv\Scripts\contapdf auxiliar      ...
.venv\Scripts\contapdf polizas       ...
.venv\Scripts\contapdf estado-cuenta ...
.venv\Scripts\contapdf mayor         ...
```

**Corregido en la 8e.** Esta sección documentaba
`.venv\Scripts\python -m contapdf.cli`, que **nunca se ha ejecutado en
Windows**. Debería funcionar —`cli.py` tiene su `__main__`— pero no está
verificado, y una guía de instalación no puede recomendar lo que nadie ha
corrido en la máquina de la que habla. Lo que sí se probó allí es
`.venv\Scripts\contapdf`.

Códigos de salida: **0** cuadra, **1** hay discrepancias que un contador
tiene que revisar, **2** no se pudo procesar. El 2 no distingue por qué;
la primera línea del mensaje sí (pendiente registrado en `ARQUITECTURA.md`
§7).

---

## 5. Lo que falla y cómo se resuelve

**Actualizado en la 8e**: los tres primeros ya ocurrieron de verdad en
SERVIDORSIST, y hay uno más que nadie había previsto y que es el más grave
de todos.

**`ModuleNotFoundError: pypdfium2`** al procesar un estado de cuenta
escaneado. *(Este ocurrió.)* Es la dependencia que faltaba declarar (§1). `pip install
pypdfium2`.

**`tesseract no esta en el PATH`** en el reporte del guion de medición.
*(Este ocurrió.)* De las dos corridas del 4 de septiembre, la de las 17:41
vio `tesseract v5.4.0` y la de las 17:57 lo dio por ausente: es la misma
máquina con dos consolas distintas. Se añade
`C:\Program Files\Tesseract-OCR` al PATH del sistema y se abre una consola
nueva — **la sesión abierta no lo ve**, y por eso la segunda corrida se
saltó `edocta-hsbc` y midió 16 documentos en vez de 17.

**`OJO: falta el idioma 'spa'`.** Tesseract instalado sin el paquete de
español. Con el instalador gráfico se marca en «Additional language data»;
**con `winget` esa pantalla no aparece** y hay que bajar `spa.traineddata`
a mano (§2.5).

**`AttributeError: 'NoneType' object has no attribute 'splitlines'`** al
procesar `edocta-hsbc` por OCR. *(Este ocurrió, y es el peor.)* **El OCR
nunca ha funcionado en esa máquina.** La traza señalaba `_tsv_a_palabras`,
y ese es el síntoma dos capas después de la causa; se interpretó mal dos
veces antes de medirlo. Lo que pasa de verdad:

1. `ocr.py` lanzaba Tesseract con `text=True` y **sin `encoding`**, así que
   `subprocess` decodificaba con el default del sistema.
2. En Linux ese default es UTF-8 y no se nota. En un **Windows en español
   es cp1252**, que no tiene el byte `0x9D` — el de la comilla tipográfica
   `”` que Tesseract produce en español.
3. El `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d` ocurre
   **dentro del hilo lector** de `subprocess`, que no lo propaga:
   `communicate()` devuelve `stdout=None` en silencio.
4. `_tsv_a_palabras(None, …)` estalla con el `AttributeError`.

**Corregido en la fase 8d**: la codificación va declarada, y una salida
vacía da un error con nombre propio en vez de reaparecer dos capas abajo.
**Pero el arreglo NO está verificado en SERVIDORSIST**: la suite corre en
WSL y ningún test cubre Windows. La verificación es volver a correr el
guion de medición allí **con Tesseract en el PATH** y ver `edocta-hsbc`
completo, con sus 3 movimientos y saldo al corte 5,195.60.

**El puerto 8080 ocupado.** Cualquier otro por encima de 1024 sirve; el 80
no, que es de Apache.

**`pytest tests/` tarda más de la cuenta.** Es lo normal: la suite rápida
son ~4m30s en la máquina de desarrollo, y SERVIDORSIST va **3.44x más
lento** (PLAN §2). Los tests que abren documentos
reales grandes van marcados `lento` y se corren aparte, antes de entregar:

```
.venv\Scripts\python -m pytest tests\ -m lento
```

---

## 6. Lo que esta fase NO dejó resuelto

Está en el checklist de despliegue del PLAN, §2, «Resultados de la fase
8c». Resumido: no hay autenticación, no hay respaldo, no hay arranque como
servicio, y un trabajo en curso a las 21:00 se pierde cuando la máquina se
apaga. Ninguno es un problema de instalación; los cuatro son decisiones
que hay que tomar antes de que el despacho use esto a diario.
