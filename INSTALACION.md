# Instalación

Cómo poner `contapdf` en una máquina, y cómo medirla. Escrito en la fase 8c
mientras se preparaba la instalación en SERVIDORSIST.

Esto **no** es un procedimiento de puesta en producción: no cubre
autenticación, respaldo ni arranque automático. Esos siguen abiertos; están
al final, en el checklist.

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

### 2.1 Copiar el repositorio

No hay git en esa máquina, así que se copia la carpeta. A `C:\contapdf`:

```
C:\contapdf\
    src\  tests\  scripts\  fixtures\  pyproject.toml  ...
```

Se puede dejar fuera `.venv\`, `.git\` y `salida\`: no hacen falta y pesan.

### 2.2 Copiar los PDFs de prueba

**Solo si se va a medir.** Los fixtures reales están en `.gitignore` porque
llevan datos de clientes; hay que copiarlos aparte a:

```
C:\contapdf\fixtures\real\
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
cd C:\contapdf
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

Solo para documentos escaneados. Instalador de UB Mannheim
(`tesseract-ocr-w64-setup-*.exe`), marcando el idioma **español (`spa`)**
en la pantalla de componentes. `ocr.py` invoca el binario por nombre, así
que tiene que estar en el `PATH`:

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
cd C:\contapdf
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
cd C:\contapdf
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
medición de la fase 8a: 1 576 s que resultaron ser 237 s cuando se midió
sola.

---

## 4. Uso desde la línea de comandos

Cinco comandos, la misma forma:

```
.venv\Scripts\python -m contapdf.cli balanza C:\ruta\balanza.pdf -o C:\salida\balanza.xlsx
.venv\Scripts\python -m contapdf.cli auxiliar      ... 
.venv\Scripts\python -m contapdf.cli polizas       ...
.venv\Scripts\python -m contapdf.cli estado-cuenta ...
.venv\Scripts\python -m contapdf.cli mayor         ...
```

Códigos de salida: **0** cuadra, **1** hay discrepancias que un contador
tiene que revisar, **2** no se pudo procesar. El 2 no distingue por qué;
la primera línea del mensaje sí (pendiente registrado en `ARQUITECTURA.md`
§7).

---

## 5. Lo que falla y cómo se resuelve

Lo encontrado de verdad, no una lista teórica.

**`ModuleNotFoundError: pypdfium2`** al procesar un estado de cuenta
escaneado. Es la dependencia que faltaba declarar (§1). `pip install
pypdfium2`.

**`tesseract no esta en el PATH`** en el reporte del guion de medición. El
instalador de UB Mannheim no marca la casilla de PATH por defecto. Se
añade `C:\Program Files\Tesseract-OCR` al PATH del sistema y se abre una
consola nueva — la sesión abierta no lo ve.

**`OJO: falta el idioma 'spa'`.** Tesseract instalado sin el paquete de
español. Se vuelve a correr el instalador y se marca en «Additional
language data».

**El puerto 8080 ocupado.** Cualquier otro por encima de 1024 sirve; el 80
no, que es de Apache.

**`pytest tests/` tarda más de la cuenta.** Es lo normal: la suite rápida
son ~4m20s en la máquina de desarrollo. Los tests que abren documentos
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
