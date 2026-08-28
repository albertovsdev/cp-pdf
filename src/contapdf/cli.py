"""Linea de comandos para correr el pipeline sobre un PDF.

    python -m contapdf.cli balanza <pdf> [-o salida.xlsx]

Es el punto de entrada, no el nucleo: aqui si se le habla al usuario. Aun
asi escribe sobre un stream que entra por parametro, nunca a stdout
directo, para que el reporte se pueda testear y para que la capa web de la
fase 8 lo pueda redirigir a un log por trabajo.

Codigos de salida: 0 el documento cuadra, 1 hay discrepancias, 2 no se
pudo procesar. Asi se encadena en un script sin leer el texto.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from contapdf.export.excel import exportar_balanza
from contapdf.extract.pdf_text import extract
from contapdf.parsers.balanza import Balanza, BalanzaParser, LayoutDesconocido
from contapdf.validate.rules import Discrepancia, validar_balanza


def _monto(valor: Decimal) -> str:
    return f"{valor:,.2f}"


def codigo_de_salida(discrepancias: Sequence[Discrepancia]) -> int:
    return 1 if discrepancias else 0


def reportar(fuente: str, paginas: int, balanza: Balanza,
             discrepancias: Sequence[Discrepancia], destino: Path | None,
             salida: TextIO) -> None:
    """Escribe el resumen que se compara contra el documento fisico."""
    escribir = salida.write
    escribir(f"{fuente}\n")
    escribir(f"  paginas   : {paginas}\n")
    escribir(f"  filas     : {len(balanza.filas)}\n")

    if balanza.totales is None:
        escribir("  totales   : sin fila de totales en el PDF\n")
    else:
        escribir(f"  totales   : debe {_monto(balanza.totales.debe)}"
                 f"   haber {_monto(balanza.totales.haber)}\n")

    niveles = sorted({f.nivel for f in balanza.filas})
    reparto = "  ".join(
        f"nivel {n}: {sum(1 for f in balanza.filas if f.nivel == n)}"
        for n in niveles)
    if reparto:
        escribir(f"  jerarquia : {reparto}\n")

    if not discrepancias:
        escribir("  validacion: sin discrepancias\n")
    else:
        escribir(f"  validacion: {len(discrepancias)} discrepancias\n")
        for d in discrepancias:
            escribir(f"    {d.fila:<16} {d.regla:<18} "
                     f"esperado {_monto(d.esperado):>16}"
                     f"   obtenido {_monto(d.obtenido):>16}\n")

    if destino is not None:
        escribir(f"  -> {destino}\n")


def ejecutar_balanza(pdf: Path, destino: Path | None, *, paginas_muestra: int,
                     salida: TextIO) -> int:
    if not pdf.exists():
        salida.write(f"no existe: {pdf}\n")
        return 2

    documento = extract(pdf)
    try:
        balanza = BalanzaParser(paginas_muestra=paginas_muestra).parse(documento)
    except LayoutDesconocido as exc:
        salida.write(f"{pdf}: {exc}\n")
        return 2

    if not balanza.filas:
        salida.write(f"{pdf}: no se encontro ninguna tabla de balanza\n")
        return 2

    discrepancias = validar_balanza(balanza)
    if destino is not None:
        exportar_balanza(balanza, discrepancias, destino)
    reportar(str(pdf), documento.page_count, balanza, discrepancias, destino, salida)
    return codigo_de_salida(discrepancias)


def main(argv: Sequence[str] | None = None, *, salida: TextIO | None = None) -> int:
    if salida is None:
        import sys

        salida = sys.stdout

    ap = argparse.ArgumentParser(prog="contapdf", description=__doc__.split("\n")[0])
    comandos = ap.add_subparsers(dest="comando", required=True)

    balanza = comandos.add_parser("balanza", help="balanza de comprobacion")
    balanza.add_argument("pdf", type=Path)
    balanza.add_argument("-o", "--out", type=Path, default=None,
                         help="ruta del .xlsx; sin esto solo reporta")
    balanza.add_argument("--paginas-muestra", type=int, default=3,
                         help="paginas que se guardan para deducir el layout")

    args = ap.parse_args(argv)
    return ejecutar_balanza(args.pdf, args.out,
                            paginas_muestra=args.paginas_muestra, salida=salida)


if __name__ == "__main__":
    import sys

    sys.exit(main())
