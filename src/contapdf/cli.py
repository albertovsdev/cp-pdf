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
from contapdf.pipeline import procesar_balanza
from contapdf.templates.store import AlmacenPlantillas
from contapdf.parsers.balanza import Balanza, LayoutDesconocido
from contapdf.templates.store import Plantilla
from contapdf.validate.rules import NO_VERIFICABLE, Cobertura


def _monto(valor: Decimal) -> str:
    return f"{valor:,.2f}"


def codigo_de_salida(cobertura: Cobertura) -> int:
    return 1 if cobertura.fallan else 0


def reportar(fuente: str, paginas: int, estrategia: str, balanza: Balanza,
             cobertura: Cobertura, destino: Path | None, salida: TextIO, *,
             plantilla: Plantilla | None = None,
             reutilizada: bool = False) -> None:
    """Escribe el resumen que se compara contra el documento fisico.

    Recibe la cobertura, no una lista de discrepancias: un resultado sin
    saber contra que se comprobo no se puede reportar (PLAN 2).
    """
    escribir = salida.write
    escribir(f"{fuente}\n")
    escribir(f"  paginas   : {paginas}\n")
    escribir(f"  extraccion: {estrategia}"
             + (f"   forma: {balanza.forma}\n" if balanza.forma else "\n"))
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

    mapeo = balanza.mapeo
    if mapeo is not None and not mapeo.orientacion_verificada:
        escribir(f"  mapeo     : orientacion debe/haber apoyada solo en el "
                 f"vocabulario del encabezado\n"
                 f"              invertirla cambiaria la naturaleza de "
                 f"{mapeo.filas_afectadas} filas\n")
    elif mapeo is not None:
        escribir(f"  mapeo     : verificado_por {mapeo.verificado_por}\n")

    fallas = len(cobertura.discrepancias)
    escribir("  validacion: "
             + (f"{fallas} discrepancias\n" if fallas else "sin discrepancias\n"))
    escribir(f"  cobertura : {cobertura.resumen()}\n")
    escribir(f"  naturaleza: {cobertura.resumen_naturaleza()}\n")
    for regla in cobertura.reglas:
        detalle = regla.motivo if regla.estado == NO_VERIFICABLE else _detalle(regla)
        escribir(f"    {regla.regla:<14} {regla.estado:<15} {detalle}\n")

    for d in cobertura.discrepancias:
        escribir(f"    ! {d.fila:<16} {d.regla:<18} "
                 f"esperado {_monto(d.esperado):>16}"
                 f"   obtenido {_monto(d.obtenido):>16}\n")

    if plantilla is not None:
        estado = ("reutilizada" if reutilizada else "aprendida")
        if plantilla.pendiente_de_confirmacion:
            estado += ", pendiente de confirmacion"
        escribir(f"  plantilla : {plantilla.huella} ({estado})\n")
        pendiente = plantilla.que_confirmar()
        if pendiente and not reutilizada:
            escribir(f"              confirmar {pendiente['campo']}: "
                     f"{pendiente['consecuencia']}\n")

    if destino is not None:
        escribir(f"  -> {destino}\n")


def _detalle(regla) -> str:
    partes = []
    if regla.exactas:
        partes.append(f"{regla.exactas} exacta"
                      + ("s" if regla.exactas != 1 else ""))
    if regla.con_tolerancia:
        partes.append(f"{len(regla.con_tolerancia)} dentro de tolerancia")
    if regla.discrepancias:
        partes.append(f"{len(regla.discrepancias)} con diferencia")
    return ", ".join(partes) or f"{regla.comprobaciones} comprobaciones"


def ejecutar_balanza(pdf: Path, destino: Path | None, *, paginas_muestra: int,
                     salida: TextIO, tenant_id: str | None = None,
                     plantillas: Path | None = None) -> int:
    if not pdf.exists():
        salida.write(f"no existe: {pdf}\n")
        return 2

    almacen = AlmacenPlantillas(plantillas) if plantillas is not None else None
    try:
        resultado = procesar_balanza(pdf, tenant_id=tenant_id, almacen=almacen,
                                     paginas_muestra=paginas_muestra)
    except LayoutDesconocido as exc:
        salida.write(f"{pdf}: {exc}\n")
        return 2

    if not resultado.balanza.filas:
        salida.write(f"{pdf}: no se encontro ninguna tabla de balanza\n")
        return 2

    if destino is not None:
        exportar_balanza(resultado.balanza, resultado.cobertura, destino)
    reportar(str(pdf), 0 if resultado.balanza is None else _paginas(pdf),
             resultado.estrategia, resultado.balanza, resultado.cobertura,
             destino, salida, plantilla=resultado.plantilla,
             reutilizada=resultado.reutilizada)
    return codigo_de_salida(resultado.cobertura)


def _paginas(pdf: Path) -> int:
    from contapdf.extract import pdf_text

    return pdf_text.extract(pdf).page_count


def ejecutar_confirmar(*, tenant_id: str, plantillas: Path, huella: str,
                       por: str, salida: TextIO) -> int:
    """Deja constancia de que un humano reviso lo que no se pudo verificar."""
    try:
        plantilla = AlmacenPlantillas(plantillas).confirmar(tenant_id, huella, por=por)
    except KeyError as exc:
        salida.write(f"{exc}\n")
        return 2
    salida.write(f"plantilla {plantilla.huella} confirmada por {por}\n")
    return 0


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
    balanza.add_argument("--tenant", default=None, help="ID del despacho")
    balanza.add_argument("--plantillas", type=Path, default=None,
                         help="directorio donde viven las plantillas")

    confirmar = comandos.add_parser(
        "confirmar", help="confirma lo que no se pudo verificar solo")
    confirmar.add_argument("--tenant", required=True)
    confirmar.add_argument("--plantillas", type=Path, required=True)
    confirmar.add_argument("--huella", required=True)
    confirmar.add_argument("--por", required=True, help="quien confirma")

    args = ap.parse_args(argv)
    if args.comando == "confirmar":
        return ejecutar_confirmar(tenant_id=args.tenant, plantillas=args.plantillas,
                                  huella=args.huella, por=args.por, salida=salida)
    return ejecutar_balanza(args.pdf, args.out,
                            paginas_muestra=args.paginas_muestra, salida=salida,
                            tenant_id=args.tenant, plantillas=args.plantillas)


if __name__ == "__main__":
    import sys

    sys.exit(main())
