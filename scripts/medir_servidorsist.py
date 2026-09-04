"""Mide la maquina objetivo: M2 (tiempo), M3 (memoria) y M4 (disco).

Fase 8c. Llevamos nueve fases dimensionando el sistema con numeros de un
i5-1335U con SSD. El destino es un i5-3470 de 2012, sin AVX2, con disco
mecanico, compartido con Apache y MySQL. Este guion produce los numeros de
ESA maquina.

COMO SE USA (ver tambien INSTALACION.md en la raiz del repo):

    python scripts\\medir_servidorsist.py --rapido      primero, ~2 min
    python scripts\\medir_servidorsist.py               completo

    El primero saltea los dos documentos largos y sirve para descubrir
    problemas de instalacion sin esperar una hora. El segundo es la
    medicion de verdad.

Escribe el reporte a `mediciones-<maquina>-<fecha>.txt` en el directorio
actual, ademas de imprimirlo. Ese .txt es lo que hay que traer de vuelta.

PRINCIPIOS DE ESTE GUION

- **Solo stdlib mas el propio repo.** Nada de psutil ni de nada que haya
  que instalar aparte: la memoria se lee con `ctypes` contra `psapi` en
  Windows y con `/proc` en Linux. Asi el MISMO instrumento corre en las dos
  maquinas y el factor entre ellas significa algo.
- **Nunca aborta.** Si falta Tesseract, si un documento revienta, si no
  esta `pypdfium2`: lo escribe y sigue con lo que si puede medir. Un
  reporte con huecos declarados vale; uno que no existe porque el guion
  murio en el tercer documento, no.
- **Escribe conforme mide.** En una maquina de 2012 esto puede tardar una
  hora. Si se corta a la mitad, lo medido hasta ahi ya esta en el fichero.
- **El codigo de salida se guarda en una variable ANTES de nada.** En la
  fase 8b un `$(basename ...)` piso `$?` y produjo una medicion falsa que
  llego hasta un objetivo del prompt. Aqui se hace explicito.

Este guion NO forma parte del nucleo y no cumple sus reglas: imprime a
stdout a proposito. Es una corrida unica, como `dump_layout.py`.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

# --- Los 17 fixtures que producen Excel --------------------------------
# De los 27 de `tests/conftest.py`, 7 no tienen parser y 3 son estados de
# cuenta sin tabla de movimientos (PLAN, resultados de la 8a). Los que
# quedan son estos, y son los que mide M2.
DOCUMENTOS = (
    ("balanza",                "balanza",       "1-Balanza/balanza.pdf"),
    ("balanza-businesspro",    "balanza",       "1-Balanza/balanza-businesspro.pdf"),
    ("balanza-gume",           "balanza",       "1-Balanza/balanza-gume.pdf"),
    ("poliza",                 "polizas",       "2-Libro-Diario/poliza.pdf"),
    ("diario-general",         "polizas",       "2-Libro-Diario/diario-general.pdf"),
    ("auxiliar",               "auxiliar",      "3-Auxiliares/auxiliar.pdf"),
    ("auxiliar-gume",          "auxiliar",      "3-Auxiliares/auxiliar-gume.pdf"),
    ("mayor-gume",             "mayor",         "5-Libro-Mayor/mayor-gume.pdf"),
    ("mayor-proactivity",      "mayor",         "5-Libro-Mayor/mayor-proactivity.pdf"),
    ("edocta",                 "estado-cuenta", "4-Estados-Cuenta/edocta.pdf"),
    ("edocta-inbursa",         "estado-cuenta", "4-Estados-Cuenta/edocta-inbursa.pdf"),
    ("edocta-santander",       "estado-cuenta", "4-Estados-Cuenta/edocta-santander.pdf"),
    ("edocta-julio-banorte",   "estado-cuenta", "4-Estados-Cuenta/edocta-julio-banorte.pdf"),
    ("edocta-abril-santander", "estado-cuenta", "4-Estados-Cuenta/edocta-abril-santander.pdf"),
    ("edocta-bajio",           "estado-cuenta", "4-Estados-Cuenta/edocta-bajio.pdf"),
    ("edocta-bbva",            "estado-cuenta", "4-Estados-Cuenta/edocta-bbva.pdf"),
    ("edocta-hsbc",            "estado-cuenta", "4-Estados-Cuenta/edocta-hsbc.pdf"),
)

# Los dos que dominan el reloj. `--rapido` los saltea para que una primera
# corrida de prueba no cueste una hora en la maquina lenta.
LARGOS = ("auxiliar-gume", "diario-general")

# El que pasa por OCR: es el unico que necesita Tesseract, y el que mas
# puede castigar a un CPU sin AVX2.
CON_OCR = "edocta-hsbc"

# Seccion 6 del PLAN: 15 personas x 5 documentos.
DOCUMENTOS_POR_DIA = 75

_MB = 1024 * 1024


# --- Memoria, sin dependencias -----------------------------------------
class _MemoriaWindows:
    """`psapi` y `kernel32` por ctypes. Sin psutil, que no es stdlib."""

    def __init__(self) -> None:
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._proceso = self._kernel.GetCurrentProcess()

        class _Contadores(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong),
                        ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t)]

        class _Estado(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        self._Contadores = _Contadores
        self._Estado = _Estado

    def del_proceso(self) -> int:
        c = self._Contadores()
        c.cb = ctypes.sizeof(c)
        self._psapi.GetProcessMemoryInfo(self._proceso, ctypes.byref(c), c.cb)
        return int(c.WorkingSetSize)

    def del_sistema(self) -> tuple[int, int]:
        e = self._Estado()
        e.dwLength = ctypes.sizeof(e)
        self._kernel.GlobalMemoryStatusEx(ctypes.byref(e))
        return int(e.ullTotalPhys), int(e.ullAvailPhys)


class _MemoriaLinux:
    """`/proc`. Existe para que la maquina de desarrollo mida IGUAL."""

    def del_proceso(self) -> int:
        for linea in Path("/proc/self/status").read_text().splitlines():
            if linea.startswith("VmRSS:"):
                return int(linea.split()[1]) * 1024
        return 0

    def del_sistema(self) -> tuple[int, int]:
        total = disponible = 0
        for linea in Path("/proc/meminfo").read_text().splitlines():
            if linea.startswith("MemTotal:"):
                total = int(linea.split()[1]) * 1024
            elif linea.startswith("MemAvailable:"):
                disponible = int(linea.split()[1]) * 1024
        return total, disponible


class _MemoriaDesconocida:
    def del_proceso(self) -> int:
        return 0

    def del_sistema(self) -> tuple[int, int]:
        return 0, 0


def _lector_de_memoria():
    try:
        if sys.platform == "win32":
            return _MemoriaWindows(), ""
        if sys.platform.startswith("linux"):
            return _MemoriaLinux(), ""
    except Exception as exc:                          # pragma: no cover
        return _MemoriaDesconocida(), f"no se pudo leer la memoria: {exc}"
    return _MemoriaDesconocida(), f"plataforma sin lector de memoria: {sys.platform}"


class _Vigia:
    """Muestrea memoria mientras corre el documento.

    El pico del proceso no basta: lo que decide si esto puede convivir con
    Apache y MySQL es cuanta RAM le queda LIBRE a la maquina mientras
    trabaja, y eso hay que verlo durante, no despues.
    """

    def __init__(self, lector, intervalo: float = 0.4) -> None:
        self._lector = lector
        self._intervalo = intervalo
        self._parar = threading.Event()
        self.pico_proceso = 0
        self.minimo_libre = None
        self._hilo = None

    def __enter__(self) -> "_Vigia":
        self._muestra()
        self._hilo = threading.Thread(target=self._correr, daemon=True)
        self._hilo.start()
        return self

    def __exit__(self, *_) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2.0)
        self._muestra()

    def _muestra(self) -> None:
        try:
            self.pico_proceso = max(self.pico_proceso, self._lector.del_proceso())
            _, libre = self._lector.del_sistema()
            if libre:
                self.minimo_libre = (libre if self.minimo_libre is None
                                     else min(self.minimo_libre, libre))
        except Exception:
            pass

    def _correr(self) -> None:
        while not self._parar.wait(self._intervalo):
            self._muestra()


# --- Reporte que se escribe conforme se mide ---------------------------
class Reporte:
    def __init__(self, destino: Path) -> None:
        self.destino = destino
        self._lineas: list[str] = []

    def __call__(self, texto: str = "") -> None:
        print(texto, flush=True)
        self._lineas.append(texto)
        # Se vuelca en cada linea: si la corrida se corta en el documento
        # doce, los once anteriores ya estan en disco.
        self.destino.write_text("\n".join(self._lineas) + "\n", encoding="utf-8")


def _tabla(reporte: Reporte, cabeceras, filas, alineado="") -> None:
    anchos = [len(str(c)) for c in cabeceras]
    for fila in filas:
        for i, celda in enumerate(fila):
            anchos[i] = max(anchos[i], len(str(celda)))
    alineado = (alineado + "i" * len(cabeceras))[:len(cabeceras)]

    def linea(celdas):
        partes = []
        for i, celda in enumerate(celdas):
            texto = str(celda)
            partes.append(texto.rjust(anchos[i]) if alineado[i] == "d"
                          else texto.ljust(anchos[i]))
        return "  ".join(partes).rstrip()

    reporte(linea(cabeceras))
    reporte("  ".join("-" * a for a in anchos))
    for fila in filas:
        reporte(linea(fila))


def _mb(octetos) -> str:
    if not octetos:
        return "-"
    return f"{octetos / _MB:,.0f}"


def _reloj(segundos) -> str:
    if segundos is None:
        return "-"
    if segundos < 60:
        return f"{segundos:.1f}s"
    return f"{int(segundos) // 60}m{int(segundos) % 60:02d}s"


# --- Comprobaciones previas --------------------------------------------
def _version_de_tesseract() -> tuple[bool, str]:
    binario = shutil.which("tesseract")
    if binario is None:
        return False, "no esta en el PATH"
    try:
        completado = subprocess.run([binario, "--version"], capture_output=True,
                                    text=True, timeout=30)
    except Exception as exc:
        return False, f"no se pudo ejecutar: {exc}"
    # El codigo de salida, a una variable ANTES de tocar nada mas. En la 8b
    # una sustitucion de comando lo piso y produjo una medicion falsa.
    codigo = completado.returncode
    primera = (completado.stdout or completado.stderr or "").splitlines()
    detalle = primera[0].strip() if primera else ""
    if codigo != 0:
        return False, f"salio con codigo {codigo}: {detalle}"
    idiomas = subprocess.run([binario, "--list-langs"], capture_output=True,
                             text=True, timeout=30)
    codigo_idiomas = idiomas.returncode
    listados = (idiomas.stdout or "").split()
    hay_espanol = "spa" in listados
    nota = "" if hay_espanol else "  OJO: falta el idioma 'spa'"
    if codigo_idiomas != 0:
        nota = "  OJO: no se pudieron listar los idiomas"
    return True, f"{detalle}{nota}"


def _preflight(reporte: Reporte, raiz: Path, lector, aviso_memoria: str) -> dict:
    reporte("=" * 72)
    reporte("MEDICION DE LA MAQUINA OBJETIVO -- cp-pdf fase 8c")
    reporte("=" * 72)
    reporte()
    reporte(f"fecha            {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    reporte(f"maquina          {socket.gethostname()}")
    reporte(f"sistema          {platform.platform()}")
    reporte(f"procesador       {platform.processor() or '(sin dato)'}")
    reporte(f"python           {platform.python_version()} ({sys.executable})")
    reporte(f"repo             {raiz}")

    total, libre = lector.del_sistema()
    reporte(f"RAM              {_mb(total)} MB totales, {_mb(libre)} MB libres "
            f"AHORA (antes de medir)")
    if aviso_memoria:
        reporte(f"  AVISO: {aviso_memoria}")
    try:
        uso = shutil.disk_usage(raiz)
        reporte(f"disco            {uso.free / (1024 ** 3):,.1f} GB libres de "
                f"{uso.total / (1024 ** 3):,.1f} GB")
    except Exception as exc:
        reporte(f"disco            no se pudo leer: {exc}")

    reporte()
    reporte("--- dependencias ---")
    estado = {}
    for modulo, para_que in (("pdfplumber", "extraccion principal"),
                             ("openpyxl", "escribir el .xlsx"),
                             ("pypdfium2", "rasterizar para OCR"),
                             ("flask", "la capa web (no hace falta para medir)")):
        try:
            importado = __import__(modulo)
            version = getattr(importado, "__version__", "?")
            reporte(f"  {modulo:<12} {version:<12} {para_que}")
            estado[modulo] = True
        except Exception as exc:
            reporte(f"  {modulo:<12} {'AUSENTE':<12} {para_que}  ({exc})")
            estado[modulo] = False

    hay_ocr, detalle = _version_de_tesseract()
    reporte(f"  {'tesseract':<12} {('OK' if hay_ocr else 'AUSENTE'):<12} {detalle}")
    estado["tesseract"] = hay_ocr
    if not hay_ocr:
        reporte(f"  -> sin Tesseract, {CON_OCR} no se puede medir. El resto si.")
    reporte()
    return estado


def _localizar_repo() -> tuple[Path, Path] | None:
    """La raiz del repo y `fixtures/real`, o None con instrucciones."""
    aqui = Path(__file__).resolve()
    for candidata in (aqui.parent.parent, Path.cwd()):
        if (candidata / "src" / "contapdf" / "cli.py").is_file():
            return candidata, candidata / "fixtures" / "real"
    return None


def _instrucciones_de_copia() -> str:
    return """
NO ENCUENTRO EL REPO.

Este guion tiene que correr desde dentro del repositorio. En la maquina
objetivo hace falta copiar dos cosas:

  1. El repositorio completo, por ejemplo a  C:\\contapdf
     (todo menos .venv, .git y salida/ -- no hacen falta)

  2. Los PDFs reales, que estan en .gitignore por llevar datos de
     clientes, a  C:\\contapdf\\fixtures\\real\\
     con sus cinco subdirectorios:
       1-Balanza  2-Libro-Diario  3-Auxiliares  4-Estados-Cuenta
       5-Libro-Mayor

Despues, desde  C:\\contapdf :

  py -3.12 -m venv .venv
  .venv\\Scripts\\python -m pip install -e .
  .venv\\Scripts\\python -m pip install pypdfium2
  .venv\\Scripts\\python scripts\\medir_servidorsist.py --rapido

El detalle completo esta en INSTALACION.md, en la raiz del repo.
"""


# --- M2 y M3 ------------------------------------------------------------
def _medir_documentos(reporte: Reporte, raiz: Path, fixtures: Path, lector,
                      estado: dict, rapido: bool, solo) -> list[dict]:
    reporte("=" * 72)
    reporte("M2 y M3 -- tiempo de pared y memoria por documento")
    reporte("=" * 72)
    reporte()
    reporte("Cada documento se procesa UNA vez, en frio: sin plantilla")
    reporte("aprendida, que es como lo ve el primer usuario que sube ese")
    reporte("formato. Una segunda subida del mismo formato cuesta menos.")
    reporte()

    try:
        sys.path.insert(0, str(raiz / "src"))
        # `_tipo_de` es privado, si: es la unica forma de cronometrar por
        # separado el leer-y-validar y el exportar. `procesar_documento`
        # hace las dos cosas en una llamada, y un solo numero total
        # escondia justo lo que la 8c encontro -- que escribir el .xlsx
        # costaba SIETE VECES mas que leer el documento.
        from contapdf.cli import DocumentoNoReconocido, _paginas, _tipo_de
    except Exception as exc:
        reporte(f"NO SE PUEDE MEDIR M2/M3: no se pudo importar contapdf ({exc})")
        reporte("Falta instalar las dependencias. Ver INSTALACION.md.")
        reporte()
        return []

    salidas = Path(tempfile.mkdtemp(prefix="contapdf-medicion-"))
    resultados = []
    pendientes = [d for d in DOCUMENTOS
                  if (not solo or d[0] in solo)
                  and not (rapido and d[0] in LARGOS)]

    if rapido:
        reporte(f"MODO RAPIDO: se saltean {', '.join(LARGOS)}.")
        reporte()

    for indice, (nombre, tipo, relativa) in enumerate(pendientes, 1):
        pdf = fixtures / relativa
        fila = {"nombre": nombre, "tipo": tipo}
        cabecera = f"[{indice}/{len(pendientes)}] {nombre} ({tipo})"

        if not pdf.is_file():
            reporte(f"{cabecera}: AUSENTE -- falta {pdf}")
            fila["error"] = "el PDF no esta en la maquina"
            resultados.append(fila)
            continue
        if nombre == CON_OCR and not estado.get("tesseract"):
            reporte(f"{cabecera}: SALTADO -- no hay Tesseract")
            fila["error"] = "sin Tesseract"
            resultados.append(fila)
            continue

        fila["pdf_mb"] = pdf.stat().st_size / _MB
        destino = salidas / f"{nombre}.xlsx"
        print(f"{cabecera} ... ", end="", flush=True)

        comando = _tipo_de(tipo)
        vigia = _Vigia(lector)
        comenzo = time.perf_counter()
        try:
            with vigia:
                resultado = comando.procesar(pdf)
                fila["leer"] = time.perf_counter() - comenzo
                datos = getattr(resultado, comando.campo)
                if comando.vacio(datos):
                    raise DocumentoNoReconocido(
                        f"no se encontro ninguna tabla de {tipo}")
                antes_de_exportar = time.perf_counter()
                comando.exportar(datos, resultado.cobertura, destino)
                fila["exportar"] = time.perf_counter() - antes_de_exportar
            fila["segundos"] = time.perf_counter() - comenzo
            fila["paginas"] = _paginas(pdf)
            fila["estrategia"] = resultado.estrategia
            fila["xlsx_mb"] = (destino.stat().st_size / _MB
                               if destino.is_file() else None)
        except DocumentoNoReconocido as exc:
            fila["segundos"] = time.perf_counter() - comenzo
            fila["error"] = f"no reconocido: {exc}"
        except Exception as exc:
            fila["segundos"] = time.perf_counter() - comenzo
            fila["error"] = f"{type(exc).__name__}: {exc}"
            fila["traza"] = traceback.format_exc(limit=3)
        finally:
            fila["pico_mb"] = vigia.pico_proceso / _MB if vigia.pico_proceso else None
            fila["libre_min_mb"] = (vigia.minimo_libre / _MB
                                    if vigia.minimo_libre else None)

        print(_reloj(fila.get("segundos")), flush=True)
        reporte(f"{cabecera}: {_reloj(fila.get('segundos'))}"
                + (f"  ERROR {fila['error']}" if "error" in fila else ""))
        resultados.append(fila)

    reporte()
    return resultados


def _resumir_documentos(reporte: Reporte, resultados: list[dict]) -> None:
    buenos = [r for r in resultados if "error" not in r]
    if not buenos:
        reporte("Ningun documento se proceso: no hay M2 ni M3 que resumir.")
        reporte()
        return

    filas = []
    for r in sorted(buenos, key=lambda r: r["segundos"]):
        filas.append((r["nombre"], r["tipo"], r.get("paginas", "-"),
                      f"{r.get('leer', 0):.1f}", f"{r.get('exportar', 0):.1f}",
                      f"{r['segundos']:.1f}", r.get("estrategia", "-"),
                      f"{r['pico_mb']:.0f}" if r.get("pico_mb") else "-",
                      f"{r['libre_min_mb']:.0f}" if r.get("libre_min_mb") else "-",
                      f"{r['xlsx_mb']:.2f}" if r.get("xlsx_mb") else "-"))
    reporte("--- M2: por documento ---")
    reporte("El reloj va SIEMPRE partido. Un total unico escondio durante")
    reporte("nueve fases que exportar costaba siete veces mas que leer.")
    reporte()
    _tabla(reporte,
           ("documento", "tipo", "pags", "leer s", "exp s", "total s",
            "estrategia", "pico MB", "libre min MB", "xlsx MB"),
           filas, alineado="iidddddddd")
    reporte()

    tiempos = sorted(r["segundos"] for r in buenos)
    leer = sorted(r.get("leer", 0) for r in buenos)
    exportar = sorted(r.get("exportar", 0) for r in buenos)
    reporte(f"documentos medidos   {len(buenos)} de {len(resultados)}")
    reporte(f"{'':<21}{'total':>10}{'leer':>10}{'exportar':>10}")
    for etiqueta, funcion in (("minimo", lambda v: v[0]),
                              ("mediana", statistics.median),
                              ("maximo", lambda v: v[-1]),
                              ("suma", sum)):
        reporte(f"{etiqueta:<21}{_reloj(funcion(tiempos)):>10}"
                f"{_reloj(funcion(leer)):>10}{_reloj(funcion(exportar)):>10}")
    reporte()

    fallidos = [r for r in resultados if "error" in r]
    if fallidos:
        reporte("--- lo que no se pudo medir ---")
        for r in fallidos:
            reporte(f"  {r['nombre']:<24} {r['error']}")
        reporte()

    reporte("--- M3: memoria ---")
    picos = [r for r in buenos if r.get("pico_mb")]
    if not picos:
        reporte("No se pudo leer la memoria en esta plataforma.")
        reporte()
        return
    peor = max(picos, key=lambda r: r["pico_mb"])
    reporte(f"pico mas alto        {peor['pico_mb']:.0f} MB  ({peor['nombre']})")
    if peor.get("libre_min_mb"):
        reporte(f"RAM libre minima     {peor['libre_min_mb']:.0f} MB "
                f"mientras corria ese documento")
    for r in picos:
        if r["nombre"] == "auxiliar-gume":
            reporte(f"auxiliar-gume        {r['pico_mb']:.0f} MB de pico, "
                    f"{r.get('libre_min_mb') or 0:.0f} MB libres en el peor momento")
    reporte()


# --- M4 -----------------------------------------------------------------
def _medir_disco(reporte: Reporte, raiz: Path, resultados: list[dict]) -> None:
    reporte("=" * 72)
    reporte("M4 -- espacio en disco")
    reporte("=" * 72)
    reporte()

    buenos = [r for r in resultados if "error" not in r]
    xlsx = sorted(r["xlsx_mb"] for r in buenos if r.get("xlsx_mb"))
    pdfs = sorted(r["pdf_mb"] for r in buenos if r.get("pdf_mb"))

    if xlsx:
        reporte("--- medido ---")
        reporte(f"xlsx generados       {len(xlsx)}: minimo {xlsx[0]:.2f} MB, "
                f"mediana {statistics.median(xlsx):.2f} MB, "
                f"maximo {xlsx[-1]:.2f} MB")
    if pdfs:
        reporte(f"PDFs de entrada      mediana {statistics.median(pdfs):.2f} MB, "
                f"maximo {pdfs[-1]:.2f} MB")

    # La base de la cola con un dia entero de trabajos dentro. Se llena con
    # resumenes REALES -- el resumen de cobertura es lo que ocupa-- y no con
    # un diccionario de mentira, que daria una cifra optimista.
    tamano_base = None
    try:
        sys.path.insert(0, str(raiz / "src"))
        from contapdf.web.cola import LISTO, Cola

        temporal = Path(tempfile.mkdtemp(prefix="contapdf-cola-"))
        cola = Cola(temporal / "cola.sqlite3", raiz=temporal)
        muestra = _resumen_de_muestra(raiz, buenos)
        for i in range(DOCUMENTOS_POR_DIA):
            trabajo = cola.encolar(tenant="despacho", tipo="balanza",
                                   archivo=f"documento-{i}.pdf")
            cola.marcar_terminado(trabajo.identificador, estado=LISTO,
                                  resumen=muestra, nombre_xlsx=f"{i}.xlsx")
        tamano_base = (temporal / "cola.sqlite3").stat().st_size / _MB
        cola.cerrar()
        shutil.rmtree(temporal, ignore_errors=True)
        reporte(f"base de la cola      {tamano_base:.2f} MB con "
                f"{DOCUMENTOS_POR_DIA} trabajos terminados dentro")
    except Exception as exc:
        reporte(f"base de la cola      no se pudo medir: {exc}")
    reporte()

    if not xlsx:
        reporte("Sin documentos procesados no hay de donde extrapolar.")
        reporte()
        return

    reporte("--- EXTRAPOLADO (no medido: se proyecta lo de arriba) ---")
    reporte(f"Supuesto: {DOCUMENTOS_POR_DIA} documentos al dia (PLAN seccion 6:")
    reporte("15 personas x 5 documentos), con la mezcla de tamanos de los")
    reporte("fixtures. Es una proyeccion, no una medicion.")
    reporte()
    mediana_x = statistics.median(xlsx)
    mediana_p = statistics.median(pdfs) if pdfs else 0.0
    reporte(f"xlsx de un dia       {mediana_x * DOCUMENTOS_POR_DIA:,.0f} MB "
            f"({DOCUMENTOS_POR_DIA} x {mediana_x:.2f} MB de mediana)")
    reporte(f"  con el peor caso   {xlsx[-1] * DOCUMENTOS_POR_DIA:,.0f} MB "
            f"si todos fueran como el mayor")
    reporte(f"PDFs subidos         {mediana_p * DOCUMENTOS_POR_DIA:,.0f} MB, "
            f"pero se borran al terminar cada uno")
    if tamano_base is not None:
        reporte(f"base de la cola      {tamano_base:,.2f} MB al dia, "
                f"{tamano_base * 250:,.0f} MB al ano si nada se borrara")
    reporte()
    reporte("Lo que de verdad ocupa en un momento dado es MUCHO menor: el")
    reporte("barrido de 30 minutos borra cada trabajo terminado, y la")
    reporte("descarga lo borra antes. El pico real es lo que quepa en media")
    reporte("hora de trabajo, no un dia entero. La cifra de arriba es el")
    reporte("techo si el barrido no existiera.")
    reporte()


def _resumen_de_muestra(raiz: Path, buenos: list[dict]) -> dict:
    """Un resumen realista para llenar la base, o uno declarado como pobre."""
    try:
        from contapdf.cli import procesar_documento
        from contapdf.web import vista

        for r in buenos:
            if r["nombre"] == "balanza":
                pdf = raiz / "fixtures" / "real" / "1-Balanza" / "balanza.pdf"
                return vista.como_diccionario(procesar_documento("balanza", pdf))
    except Exception:
        pass
    return {"nota": "resumen de relleno: la cifra de la base queda por lo bajo"}


# --- Entrada ------------------------------------------------------------
def main(argv=None) -> int:
    analizador = argparse.ArgumentParser(
        description="Mide tiempo, memoria y disco en la maquina objetivo.")
    analizador.add_argument("--rapido", action="store_true",
                            help=f"saltea {' y '.join(LARGOS)}; para una "
                                 "primera corrida de prueba")
    analizador.add_argument("--solo", nargs="*", metavar="NOMBRE",
                            help="mide solo estos documentos")
    analizador.add_argument("--salida", type=Path, default=None,
                            help="fichero del reporte (por defecto, uno con "
                                 "el nombre de la maquina y la fecha)")
    opciones = analizador.parse_args(argv)

    ubicacion = _localizar_repo()
    if ubicacion is None:
        print(_instrucciones_de_copia())
        return 2
    raiz, fixtures = ubicacion

    destino = opciones.salida or Path(
        f"mediciones-{socket.gethostname()}-"
        f"{datetime.datetime.now():%Y%m%d-%H%M}.txt")
    reporte = Reporte(destino)
    lector, aviso = _lector_de_memoria()

    estado = _preflight(reporte, raiz, lector, aviso)
    if not fixtures.is_dir():
        reporte(f"NO ESTAN LOS PDFs: falta el directorio {fixtures}")
        reporte("Sin ellos no hay M2, M3 ni M4. Ver INSTALACION.md.")
        reporte()
        resultados = []
    else:
        resultados = _medir_documentos(reporte, raiz, fixtures, lector, estado,
                                       opciones.rapido, set(opciones.solo or ()))
        _resumir_documentos(reporte, resultados)
    _medir_disco(reporte, raiz, resultados)

    reporte("=" * 72)
    reporte(f"Reporte escrito en: {destino.resolve()}")
    reporte("Ese es el fichero que hay que traer de vuelta.")
    reporte("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
