"""Linea de comandos para correr el pipeline sobre un PDF.

    python -m contapdf.cli <comando> <pdf> [-o salida.xlsx]

Cinco comandos, uno por tipo de documento -- balanza, auxiliar, polizas,
estado-cuenta, mayor -- mas `confirmar`. Todos tienen la misma forma y todos
reportan cobertura: es el contrato que la capa web va a envolver.

Es el punto de entrada, no el nucleo: aqui si se le habla al usuario. Aun
asi escribe sobre un stream que entra por parametro, nunca a stdout
directo, para que el reporte se pueda testear y para que la capa web de la
fase 8 lo pueda redirigir a un log por trabajo.

Codigos de salida: 0 el documento cuadra, 1 hay discrepancias, 2 no se
pudo procesar. Asi se encadena en un script sin leer el texto.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from contapdf.export.excel import (
    exportar_auxiliar,
    exportar_balanza,
    exportar_estado_cuenta,
    exportar_mayor,
    exportar_polizas,
)
from contapdf.parsers.balanza import Balanza, LayoutDesconocido
from contapdf.parsers.estado_cuenta import ReporteNoEsperado
from contapdf.pipeline import (
    procesar_auxiliar,
    procesar_balanza,
    procesar_estado_cuenta,
    procesar_mayor,
    procesar_polizas,
)
from contapdf.templates.store import AlmacenPlantillas, Plantilla
from contapdf.validate.rules import NO_VERIFICABLE, Cobertura


def _monto(valor: Decimal) -> str:
    return f"{valor:,.2f}"


def codigo_de_salida(cobertura: Cobertura) -> int:
    return 1 if cobertura.fallan else 0


def reportar(fuente: str, paginas: int, estrategia: str, balanza: Balanza,
             cobertura: Cobertura, destino: Path | None, salida: TextIO, *,
             plantilla: Plantilla | None = None,
             reutilizada: bool = False, motivo: str = "") -> None:
    """Escribe el resumen que se compara contra el documento fisico.

    Recibe la cobertura, no una lista de discrepancias: un resultado sin
    saber contra que se comprobo no se puede reportar (PLAN 2).
    """
    escribir = salida.write
    escribir(f"{fuente}\n")
    escribir(f"  paginas   : {paginas}\n")
    escribir(f"  extraccion: {estrategia}"
             + (f"   forma: {balanza.forma}\n" if balanza.forma else "\n"))
    if motivo:
        escribir(f"              {motivo}\n")
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

    escribir(f"  naturaleza: {cobertura.resumen_naturaleza()}\n")
    _cola(cobertura, destino, salida, plantilla=plantilla,
          reutilizada=reutilizada)


def reportar_documento(fuente: str, paginas: int, estrategia: str, motivo: str,
                       renglones: Sequence[tuple[str, str]],
                       cobertura: Cobertura, destino: Path | None,
                       salida: TextIO, *, plantilla: Plantilla | None = None,
                       reutilizada: bool = False) -> None:
    """El reporte que comparten los cinco comandos.

    `renglones` es lo propio de cada tipo de documento; todo lo demas --
    estrategia con su porque, cobertura, reglas, discrepancias y plantilla --
    es igual para todos, y es lo que la capa web va a mostrar.
    """
    escribir = salida.write
    escribir(f"{fuente}\n")
    escribir(f"  paginas   : {paginas}\n")
    escribir(f"  extraccion: {estrategia}\n")
    if motivo:
        escribir(f"              {motivo}\n")
    # Un renglon sin etiqueta es el detalle del anterior: se sangra en vez
    # de repetir los dos puntos.
    ancho = max((len(e) for e, _ in renglones), default=10)
    for etiqueta, valor in renglones:
        separador = ": " if etiqueta else "  "
        escribir(f"  {etiqueta:<{ancho}}{separador}{valor}\n")
    _cola(cobertura, destino, salida, plantilla=plantilla,
          reutilizada=reutilizada)


def _cola(cobertura: Cobertura, destino: Path | None, salida: TextIO, *,
          plantilla: Plantilla | None, reutilizada: bool) -> None:
    escribir = salida.write
    fallas = len(cobertura.discrepancias)
    escribir("  validacion: "
             + (f"{fallas} discrepancias\n" if fallas else "sin discrepancias\n"))
    escribir(f"  cobertura : {cobertura.resumen()}\n")
    for regla in cobertura.reglas:
        escribir(f"    {regla.regla:<20} {regla.estado:<15} {_detalle(regla)}\n")
        if regla.motivo:
            escribir(f"    {'':<20} {'':<15} {regla.motivo}\n")

    for d in cobertura.discrepancias:
        escribir(f"    ! {d.fila:<16} {d.regla:<18} "
                 f"esperado {_monto(d.esperado):>16}"
                 f"   obtenido {_monto(d.obtenido):>16}\n")

    if plantilla is not None:
        estado = ("reutilizada" if reutilizada else "aprendida")
        if plantilla.pendiente_de_confirmacion:
            estado += ", pendiente de confirmacion"
        escribir(f"  plantilla : {plantilla.huella} ({estado})\n")
        for pendiente in plantilla.pendientes():
            if reutilizada:
                break
            escribir(f"              confirmar {pendiente['campo']}: "
                     f"{pendiente['consecuencia']}\n")
            if pendiente["se_propone"] is None:
                escribir(f"              sin propuesta -- {pendiente['se_apoya_en']}\n")

    if destino is not None:
        escribir(f"  -> {destino}\n")


def _detalle(regla) -> str:
    """Lo que corrio de una regla, NUNCA sin decir sobre cuanto.

    Un '5 exactas' sobre 116 casos y uno sobre 5 se leian igual; asi se
    aprobo BBVA con la regla corriendo en el 4% de la tabla.
    """
    if regla.aplicables is None:
        return "universo sin determinar"
    partes = [f"{regla.evaluados} de {regla.aplicables} evaluados"]
    if regla.exactas:
        partes.append(f"{regla.exactas} exacta"
                      + ("s" if regla.exactas != 1 else ""))
    if regla.con_tolerancia:
        partes.append(f"{len(regla.con_tolerancia)} dentro de tolerancia")
    if regla.discrepancias:
        partes.append(f"{len(regla.discrepancias)} con diferencia")
    return ", ".join(partes)


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
    reportar(str(pdf), _paginas(pdf),
             resultado.estrategia, resultado.balanza, resultado.cobertura,
             destino, salida, plantilla=resultado.plantilla,
             reutilizada=resultado.reutilizada,
             motivo=resultado.motivo_estrategia)
    return codigo_de_salida(resultado.cobertura)


def _resumen_balanza(balanza) -> "list[tuple[str, str]]":
    niveles = sorted({f.nivel for f in balanza.filas})
    reparto = "  ".join(
        f"nivel {n}: {sum(1 for f in balanza.filas if f.nivel == n)}"
        for n in niveles)
    renglones = [("filas", f"{len(balanza.filas)}")]
    if balanza.totales is not None:
        renglones.append(("totales", f"debe {_monto(balanza.totales.debe)}"
                                     f"   haber {_monto(balanza.totales.haber)}"))
    else:
        renglones.append(("totales", "sin fila de totales en el PDF"))
    if reparto:
        renglones.append(("jerarquia", reparto))
    return renglones


def _resumen_auxiliar(auxiliar) -> "list[tuple[str, str]]":
    subtotales = sum(1 for f in auxiliar.filas if f.es_subtotal)
    sin_saldo = sum(1 for f in auxiliar.filas if f.saldo is None)
    return [("filas", f"{len(auxiliar.filas)}   secciones: {auxiliar.secciones}"
                      f"   subtotales: {subtotales}"),
            ("saldos", f"{len(auxiliar.filas) - sin_saldo} legibles, "
                       f"{sin_saldo} sin saldo en el PDF")]


def _resumen_polizas(libro) -> "list[tuple[str, str]]":
    incompletas = sum(1 for p in libro.polizas if not p.completa)
    return [("polizas", f"{len(libro.polizas)}"
                        + (f"   {incompletas} sin cerrar en lo leido"
                           if incompletas else "")),
            ("movimientos", f"{len(libro.movimientos)}"),
            ("cfdi", f"{len(libro.cfdi)}")]


def _resumen_estado_cuenta(estado) -> "list[tuple[str, str]]":
    renglones = [("cuentas", f"{len(estado.cuentas)}"),
                 ("movimientos", f"{len(estado.movimientos)}")]
    for cuenta in estado.cuentas:
        propios = len(estado.movimientos_de(cuenta.num_cuenta))
        etiqueta = cuenta.producto or cuenta.num_cuenta or "(sin identificar)"
        saldo = ("" if cuenta.saldo_corte is None
                 else f"   saldo al corte {_monto(cuenta.saldo_corte)}")
        renglones.append(("", f"{etiqueta}: {propios} movimientos{saldo}"))
    return renglones


def _resumen_mayor(mayor) -> "list[tuple[str, str]]":
    sin_naturaleza = sum(1 for c in mayor.cuentas if not c.naturaleza)
    return [("cuentas", f"{len(mayor.cuentas)}"
                        + (f"   {sin_naturaleza} sin naturaleza determinable"
                           if sin_naturaleza else "")),
            ("meses", f"{len(mayor.meses)}")]


@dataclass(frozen=True)
class _Comando:
    """Lo unico que cambia de un tipo de documento a otro en el CLI."""

    nombre: str
    ayuda: str
    procesar: Callable
    exportar: Callable
    campo: str            # como se llama el dato dentro del Resultado*
    resumir: Callable
    vacio: Callable


# Tupla y no diccionario: un test de arquitectura prohibe estado mutable a
# nivel de modulo, y con razon -- un dict aqui lo podria mutar cualquiera.
_TIPOS = (
    _Comando("balanza", "balanza de comprobacion", procesar_balanza,
             exportar_balanza, "balanza", _resumen_balanza,
             lambda b: not b.filas),
    _Comando("auxiliar", "auxiliar de cuentas", procesar_auxiliar,
             exportar_auxiliar, "auxiliar", _resumen_auxiliar,
             lambda a: not a.filas),
    _Comando("polizas", "libro diario / polizas", procesar_polizas,
             exportar_polizas, "libro", _resumen_polizas,
             lambda l: not l.polizas),
    _Comando("estado-cuenta", "estado de cuenta bancario",
             procesar_estado_cuenta, exportar_estado_cuenta, "estado",
             _resumen_estado_cuenta, lambda e: not e.movimientos),
    _Comando("mayor", "libro mayor", procesar_mayor, exportar_mayor, "mayor",
             _resumen_mayor, lambda m: not m.cuentas),
)


def _tipo_de(comando: str) -> "_Comando | None":
    return next((t for t in _TIPOS if t.nombre == comando), None)


#: Los tipos de documento que el sistema sabe procesar. Es la lista que la
#: capa web ofrece en su selector, para no mantener dos copias.
TIPOS_DE_DOCUMENTO = tuple((t.nombre, t.ayuda) for t in _TIPOS)


class DocumentoNoReconocido(ValueError):
    """El PDF no es del tipo que se pidió, o no se pudo leer como tal.

    Traduce las excepciones del nucleo a algo que se le pueda ense~nar a un
    humano. `detalle` trae lo que el propio documento dice, cuando lo dice.
    """

    def __init__(self, mensaje: str, *, detalle: Sequence[str] = (),
                 clave: str = "") -> None:
        super().__init__(mensaje)
        self.detalle = tuple(detalle)
        self.clave = clave


@dataclass(frozen=True)
class ResultadoDocumento:
    """Todo lo que hay que saber de un documento procesado.

    Es la superficie que comparten el CLI y la capa web: los dos llaman a
    `procesar_documento()` y despues cada uno lo presenta a su manera. Sin
    esto, la web tendria que repetir la orquestacion y las dos versiones se
    separarian en la primera correccion.
    """

    tipo: str
    fuente: str
    paginas: int
    estrategia: str
    motivo_estrategia: str
    cobertura: Cobertura
    plantilla: Plantilla | None
    reutilizada: bool
    resumen: tuple[tuple[str, str], ...]
    datos: object
    destino: Path | None = None

    @property
    def cuadra(self) -> bool:
        return not self.cobertura.fallan


def procesar_documento(tipo: str, pdf: Path, destino: Path | None = None, *,
                       paginas_muestra: int = 3,
                       tenant_id: str | None = None,
                       plantillas: Path | None = None) -> ResultadoDocumento:
    """Procesa un PDF y devuelve los DATOS, sin imprimir nada.

    Lanza `DocumentoNoReconocido` cuando el documento no es del tipo que se
    pidio: quien llama decide como decirlo.
    """
    comando = _tipo_de(tipo)
    if comando is None:
        raise DocumentoNoReconocido(
            f"tipo de documento desconocido: {tipo!r}; los que se pueden "
            f"procesar son {', '.join(n for n, _ in TIPOS_DE_DOCUMENTO)}")
    if not Path(pdf).exists():
        raise DocumentoNoReconocido(f"no existe: {pdf}")

    almacen = AlmacenPlantillas(plantillas) if plantillas is not None else None
    try:
        resultado = comando.procesar(pdf, tenant_id=tenant_id, almacen=almacen,
                                     paginas_muestra=paginas_muestra)
    except ReporteNoEsperado as exc:
        raise DocumentoNoReconocido(exc.tipo.etiqueta,
                                    detalle=exc.tipo.evidencia,
                                    clave=exc.tipo.clave) from exc
    except LayoutDesconocido as exc:
        raise DocumentoNoReconocido(
            f"no se pudo leer como {tipo}: {exc}") from exc

    datos = getattr(resultado, comando.campo)
    if comando.vacio(datos):
        raise DocumentoNoReconocido(
            f"no se encontro ninguna tabla de {tipo} en el documento")

    if destino is not None:
        comando.exportar(datos, resultado.cobertura, destino)

    return ResultadoDocumento(
        tipo=tipo, fuente=str(pdf), paginas=_paginas(pdf),
        estrategia=resultado.estrategia,
        motivo_estrategia=resultado.motivo_estrategia,
        cobertura=resultado.cobertura, plantilla=resultado.plantilla,
        reutilizada=resultado.reutilizada,
        resumen=tuple(comando.resumir(datos)), datos=datos, destino=destino)


def ejecutar(comando: str, pdf: Path, destino: Path | None, *,
             paginas_muestra: int, salida: TextIO,
             tenant_id: str | None = None,
             plantillas: Path | None = None) -> int:
    """Los cuatro comandos que no son la balanza, con la misma forma.

    Procesa con `procesar_documento` -- la misma puerta que usa la capa
    web -- y aqui solo se ocupa de contarlo por pantalla.
    """
    try:
        resultado = procesar_documento(
            comando, pdf, destino, paginas_muestra=paginas_muestra,
            tenant_id=tenant_id, plantillas=plantillas)
    except DocumentoNoReconocido as exc:
        # La clave va primero: es lo que un script puede leer sin parsear
        # la frase, y lo que la capa web usa para decidir como mostrarlo.
        salida.write(f"{pdf}: {exc.clave or 'no_reconocido'}\n  {exc}\n")
        for linea in exc.detalle[:4]:
            salida.write(f"    segun el documento: {linea}\n")
        return 2

    reportar_documento(resultado.fuente, resultado.paginas,
                       resultado.estrategia, resultado.motivo_estrategia,
                       resultado.resumen, resultado.cobertura, destino, salida,
                       plantilla=resultado.plantilla,
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

    # Los cinco se registran desde _TIPOS: una sola lista, sin copias.
    for tipo in _TIPOS:
        sub = comandos.add_parser(tipo.nombre, help=tipo.ayuda)
        sub.add_argument("pdf", type=Path)
        sub.add_argument("-o", "--out", type=Path, default=None,
                         help="ruta del .xlsx; sin esto solo reporta")
        sub.add_argument("--paginas-muestra", type=int, default=3,
                         help="paginas que se guardan para deducir el layout")
        sub.add_argument("--tenant", default=None, help="ID del despacho")
        sub.add_argument("--plantillas", type=Path, default=None,
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
    if args.comando == "balanza":
        # La balanza conserva su reporte propio: trae jerarquia, totales y
        # procedencia de la naturaleza, que los otros cuatro no tienen.
        return ejecutar_balanza(args.pdf, args.out,
                                paginas_muestra=args.paginas_muestra,
                                salida=salida, tenant_id=args.tenant,
                                plantillas=args.plantillas)
    if _tipo_de(args.comando) is not None:
        return ejecutar(args.comando, args.pdf, args.out,
                        paginas_muestra=args.paginas_muestra, salida=salida,
                        tenant_id=args.tenant, plantillas=args.plantillas)
    return ejecutar_balanza(args.pdf, args.out,
                            paginas_muestra=args.paginas_muestra, salida=salida,
                            tenant_id=args.tenant, plantillas=args.plantillas)


if __name__ == "__main__":
    import sys

    sys.exit(main())
