"""Fase 8f, objetivo 2: ir al DOCUMENTO a comprobar cada motivo.

El motivo que imprime el sistema es una HIPOTESIS. «ninguna cuenta trae el
resumen completo» significa que el parser no lo encontro, no que el
documento no lo tenga. Este guion va al documento y busca el dato.

No vuelca contenido: imprime CUANTAS veces aparece cada etiqueta y en que
pagina. Los PDFs de fixtures/real/ son de clientes.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests"))

from conftest import REAL_PDFS  # noqa: E402

from contapdf.extract import strategy  # noqa: E402
from contapdf.layout.lines import group  # noqa: E402


def _plano(texto: str) -> str:
    quitado = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in quitado if not unicodedata.combining(c))


def renglones(nombre: str):
    """(pagina, texto plano del renglon) de todo el documento."""
    documento, _ = strategy.extraer(REAL_PDFS[nombre])
    for page in documento.open_pages():
        for line in group(page.words):
            yield page.number, _plano(" ".join(w.text for w in line.words))


def buscar(nombre: str, etiquetas, *, arranca=False) -> dict[str, list[int]]:
    """Paginas donde aparece cada etiqueta. Cuenta, no vuelca."""
    encontrado = {e: [] for e in etiquetas}
    for pagina, texto in renglones(nombre):
        for etiqueta in etiquetas:
            hay = texto.startswith(etiqueta) if arranca else etiqueta in texto
            if hay and pagina not in encontrado[etiqueta]:
                encontrado[etiqueta].append(pagina)
    return encontrado


def informe(titulo: str, pregunta: str, nombre: str, etiquetas,
            *, arranca=False) -> None:
    print("=" * 78)
    print(titulo)
    print("=" * 78)
    print(f"  documento: {nombre}")
    print(f"  pregunta : {pregunta}")
    hallazgos = buscar(nombre, etiquetas, arranca=arranca)
    for etiqueta, paginas in hallazgos.items():
        marca = f"paginas {paginas[:6]}" if paginas else "NO APARECE"
        print(f"    {etiqueta!r:38} {marca}")
    print()


if __name__ == "__main__":
    objetivo = sys.argv[1] if len(sys.argv) > 1 else "todos"

    if objetivo in ("todos", "m01"):
        for nombre in ("edocta", "edocta-bajio", "edocta-bbva",
                       "edocta-inbursa"):
            informe("M01 -- el documento no imprime una fila TOTAL",
                    "hay una fila TOTAL en el resumen de cuentas?",
                    nombre, ("total", "totales", "resumen", "saldo total"))

    if objetivo in ("todos", "m03"):
        informe("M03 -- el documento no trae tabla de CFDI",
                "aparecen CFDI, UUID o folio fiscal en el diario?",
                "diario-general", ("cfdi", "uuid", "folio fiscal", "rfc",
                                   "comprobante"))

    if objetivo in ("todos", "m04", "m05"):
        for nombre in ("edocta-julio-banorte", "edocta-santander"):
            informe("M04/M05 -- ninguna cuenta declara resumen propio",
                    "el documento desglosa depositos/retiros POR CUENTA?",
                    nombre, ("deposito", "retiro", "abono", "cargo",
                             "saldo inicial", "saldo final", "saldo anterior",
                             "resumen"))

    if objetivo in ("todos", "m08"):
        informe("M08 -- el documento no imprime filas de subtotal",
                "hay subtotales por cuenta en el auxiliar?",
                "auxiliar", ("subtotal", "total", "suma", "totales"))

    if objetivo in ("todos", "m09"):
        informe("M09 -- el documento no declara partida doble",
                "la fila de totales trae debe y haber, y cuadran?",
                "balanza-businesspro", ("total", "suma", "debe", "haber",
                                        "cargo", "abono"))


def contexto(nombre: str, etiqueta: str, *, paginas=None, limite=8,
             palabras=9) -> None:
    """Los renglones que contienen la etiqueta, CON LOS NUMEROS TAPADOS.

    Se ven las etiquetas del documento y no los importes ni las cuentas:
    la pregunta es si el dato EXISTE, no cuanto vale.
    """
    import re
    tapa = re.compile(r"\d")
    print(f"--- {nombre}: renglones con {etiqueta!r} ---")
    vistos = 0
    for pagina, texto in renglones(nombre):
        if etiqueta not in texto or (paginas and pagina not in paginas):
            continue
        recorte = " ".join(tapa.sub("9", texto).split()[:palabras])
        print(f"    p{pagina:<3} {recorte}")
        vistos += 1
        if vistos >= limite:
            break
    if not vistos:
        print("    (ninguno)")
    print()
