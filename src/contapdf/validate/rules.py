"""Reglas aritmeticas: cada documento trae su propio checksum.

Las reglas se DECLARAN por formato. Un documento con columnas deudor y
acreedor separadas y otro con una sola columna con signo no se validan
igual, y cablear uno de los dos deja al otro fuera.

Devuelve discrepancias. No lanza excepciones y no imprime: quien llama
decide si entrega el Excel marcado o rechaza el documento.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from contapdf.parsers.balanza import Balanza, FilaBalanza

TOLERANCIA = Decimal("0.01")


@dataclass(frozen=True)
class Discrepancia:
    """Una regla que no se cumplio, con el numero que se esperaba."""

    fila: str  # cuenta afectada, o 'Totales' para las reglas globales
    indice: int  # posicion en balanza.filas; -1 si la regla es del documento
    regla: str
    esperado: Decimal
    obtenido: Decimal


@dataclass(frozen=True)
class ReglasBalanza:
    """Que se le exige a una balanza. La fase 4 guardara esto por formato."""

    tolerancia: Decimal = TOLERANCIA
    subconjunto_totales: str = "nivel_1"  # 'nivel_1' | 'no_acumulativas'
    exige_partida_doble: bool = True

    @classmethod
    def para(cls, balanza: Balanza, *,
             tolerancia: Decimal = TOLERANCIA) -> "ReglasBalanza":
        """Deduce del propio documento que reglas le aplican.

        La partida doble solo se exige si el documento la declara en su
        fila de totales. Business Pro imprime unicamente la seccion de
        resultados: sus sumas no cuadran entre si por diseño, y exigirsela
        seria reportar una discrepancia que el documento no tiene.
        """
        declara = (balanza.totales is None
                   or abs(balanza.totales.debe - balanza.totales.haber) <= tolerancia)
        return cls(tolerancia=tolerancia, exige_partida_doble=declara)


def _saldo(deudor: Decimal, acreedor: Decimal) -> Decimal:
    """Saldo con signo, independiente de la naturaleza de la cuenta."""
    return deudor - acreedor


def _difieren(a: Decimal, b: Decimal, tolerancia: Decimal) -> bool:
    return abs(a - b) > tolerancia


def _hijas_directas(filas: Sequence[FilaBalanza],
                    padre: FilaBalanza) -> list[FilaBalanza]:
    return [f for f in filas
            if f.cuenta_padre == padre.cuenta and f.nivel == padre.nivel + 1]


def _subconjunto(filas: Sequence[FilaBalanza], nombre: str) -> list[FilaBalanza]:
    """Las filas contra las que cuadra la fila de totales del PDF.

    Medido: la balanza original cuadra contra el NIVEL 1 (26.9M) y no
    contra las hojas (48.9M), porque trae dos subarboles cuya cuenta padre
    no esta impresa. Business Pro cuadra contra las dos, porque ahi el
    arbol descompone completo. Por eso el default es 'nivel_1': es el
    unico que sirve para los dos.
    """
    if nombre == "no_acumulativas":
        return [f for f in filas if not f.es_acumulativa]
    return [f for f in filas if f.nivel == 1]


def validar_balanza(balanza: Balanza, *,
                    reglas: ReglasBalanza | None = None) -> list[Discrepancia]:
    """Aplica los checksums de PLAN 1.3 a una balanza ya parseada.

    Sin reglas explicitas se deducen del propio documento; la fase 4 las
    guardara en la plantilla para no volver a deducirlas.
    """
    reglas = reglas or ReglasBalanza.para(balanza)
    tolerancia = reglas.tolerancia
    discrepancias: list[Discrepancia] = []
    filas = balanza.filas

    # 'esperado' es siempre lo que dice la aritmetica y 'obtenido' lo que
    # dice el PDF: el reporte se lee "debia decir X y dice Y".
    for indice, fila in enumerate(filas):
        esperado = (_saldo(fila.saldo_ini_deudor, fila.saldo_ini_acreedor)
                    + fila.debe - fila.haber)
        obtenido = _saldo(fila.saldo_fin_deudor, fila.saldo_fin_acreedor)
        if _difieren(esperado, obtenido, tolerancia):
            discrepancias.append(Discrepancia(
                fila=fila.cuenta, indice=indice, regla="renglon",
                esperado=esperado, obtenido=obtenido))

    for indice, padre in enumerate(filas):
        hijas = _hijas_directas(filas, padre)
        if not hijas:
            continue
        for campo in ("debe", "haber"):
            suma = sum((getattr(h, campo) for h in hijas), Decimal(0))
            propio = getattr(padre, campo)
            if _difieren(suma, propio, tolerancia):
                discrepancias.append(Discrepancia(
                    fila=padre.cuenta, indice=indice, regla=f"jerarquia_{campo}",
                    esperado=suma, obtenido=propio))

    base = _subconjunto(filas, reglas.subconjunto_totales)
    if balanza.totales is not None and base:
        for campo in ("debe", "haber"):
            suma = sum((getattr(f, campo) for f in base), Decimal(0))
            declarado = getattr(balanza.totales, campo)
            if _difieren(suma, declarado, tolerancia):
                discrepancias.append(Discrepancia(
                    fila="Totales", indice=-1, regla=f"totales_{campo}",
                    esperado=suma, obtenido=declarado))

    if reglas.exige_partida_doble and base:
        debe = sum((f.debe for f in base), Decimal(0))
        haber = sum((f.haber for f in base), Decimal(0))
        if _difieren(debe, haber, tolerancia):
            # Los dos lados vienen del documento: aqui 'esperado' es el debe.
            discrepancias.append(Discrepancia(
                fila="Totales", indice=-1, regla="partida_doble",
                esperado=debe, obtenido=haber))

    return discrepancias
