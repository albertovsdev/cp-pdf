"""Reglas aritmeticas: cada documento trae su propio checksum.

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


def _saldo(deudor: Decimal, acreedor: Decimal) -> Decimal:
    """Saldo con signo, independiente de la naturaleza de la cuenta."""
    return deudor - acreedor


def _difieren(a: Decimal, b: Decimal, tolerancia: Decimal) -> bool:
    return abs(a - b) > tolerancia


def _hijas_directas(filas: Sequence[FilaBalanza],
                    padre: FilaBalanza) -> list[FilaBalanza]:
    return [f for f in filas
            if f.cuenta_padre == padre.cuenta and f.nivel == padre.nivel + 1]


def validar_balanza(balanza: Balanza, *,
                    tolerancia: Decimal = TOLERANCIA) -> list[Discrepancia]:
    """Aplica los checksums de PLAN 1.3 a una balanza ya parseada.

    Cuatro reglas: el saldo de cada renglon, la suma de las hijas contra su
    cuenta padre, la fila 'Totales' del PDF y la identidad de partida doble.
    """
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

    # Verificado contra el documento real: la fila 'Totales' suma las
    # cuentas de NIVEL 1, no todas las filas ni solo las hojas. Sumar todas
    # contaria dos veces a las cuentas padre, que ya agregan a sus hijas.
    nivel_1 = [f for f in filas if f.nivel == 1]
    if balanza.totales is not None and nivel_1:
        for campo in ("debe", "haber"):
            suma = sum((getattr(f, campo) for f in nivel_1), Decimal(0))
            declarado = getattr(balanza.totales, campo)
            if _difieren(suma, declarado, tolerancia):
                discrepancias.append(Discrepancia(
                    fila="Totales", indice=-1, regla=f"totales_{campo}",
                    esperado=suma, obtenido=declarado))

    if nivel_1:
        debe = sum((f.debe for f in nivel_1), Decimal(0))
        haber = sum((f.haber for f in nivel_1), Decimal(0))
        if _difieren(debe, haber, tolerancia):
            # Los dos lados vienen del documento: aqui 'esperado' es el debe.
            discrepancias.append(Discrepancia(
                fila="Totales", indice=-1, regla="partida_doble",
                esperado=debe, obtenido=haber))

    return discrepancias
