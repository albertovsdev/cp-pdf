"""Recalculo del saldo corrido cuando el documento no lo dejo leer.

El defecto 3b -- digitos que nunca se dibujaron -- no lo recupera ningun
OCR. Pero la aritmetica del auxiliar es cerrada y el documento declara sus
extremos: el saldo inicial de la seccion y el subtotal del cierre.
Encadenar entre esas dos anclas COMPROBADAS no es inventar dato.

Tres condiciones, y si alguna falla el saldo se queda en None:

  1. el saldo inicial de la seccion es legible;
  2. todos los debe/haber de la cadena son legibles;
  3. la suma de los movimientos coincide EXACTO con el subtotal declarado
     -- que es lo que prueba que no falta ningun renglon -- y, cuando el
     subtotal declara saldo, la cadena aterriza exactamente ahi.

Nunca se recalcula en silencio: cada saldo queda marcado con su
procedencia y la cobertura la reporta.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from contapdf.parsers.auxiliar import (
    IMPRESO,
    RECALCULADO,
    Auxiliar,
    FilaAuxiliar,
)
from contapdf.validate.rules import naturaleza_por_cuenta

_LOG = logging.getLogger(__name__)


def ancla_de_seccion(movimientos: Sequence[FilaAuxiliar],
                      subtotal: FilaAuxiliar | None,
                      signo: Decimal) -> bool:
    """Si la cadena esta completa y sus dos extremos son comprobables."""
    if subtotal is None or not movimientos:
        return False
    if movimientos[0].saldo_inicial_cuenta is None:
        return False
    if any(f.debe is None or f.haber is None for f in movimientos):
        return False
    if subtotal.debe is None or subtotal.haber is None:
        return False

    # Que la suma cuadre con el subtotal es lo que prueba que no falta
    # ningun movimiento: sin eso, encadenar sobre un hueco desplazaria
    # todos los saldos siguientes sin que nada avisara.
    if sum((f.debe for f in movimientos), Decimal(0)) != subtotal.debe:
        return False
    if sum((f.haber for f in movimientos), Decimal(0)) != subtotal.haber:
        return False

    if subtotal.saldo is not None:
        final = movimientos[0].saldo_inicial_cuenta
        for fila in movimientos:
            final = final + signo * (fila.debe - fila.haber)
        if final != subtotal.saldo:
            return False
    return True


def recalcular_saldos(auxiliar: Auxiliar) -> Auxiliar:
    """Rellena los saldos ilegibles de las secciones con ancla verificada.

    Devuelve un Auxiliar nuevo; el que recibe no se toca. Las secciones sin
    ancla salen igual que entraron.
    """
    por_seccion: dict[str, list[int]] = {}
    subtotales: dict[str, FilaAuxiliar] = {}
    for indice, fila in enumerate(auxiliar.filas):
        if fila.es_subtotal:
            subtotales.setdefault(fila.cuenta, fila)
        else:
            por_seccion.setdefault(fila.cuenta, []).append(indice)

    # El signo NO se cablea aqui tampoco: encadenar una cuenta acreedora con
    # la identidad deudora produce saldos incorrectos MARCADOS COMO BUENOS,
    # que es peor que dejarlos vacios.
    naturalezas = naturaleza_por_cuenta(auxiliar)

    filas = list(auxiliar.filas)
    recalculadas = 0
    for cuenta, indices in por_seccion.items():
        movimientos = [filas[i] for i in indices]
        naturaleza = naturalezas.get(cuenta, "")
        if not naturaleza:
            # Sin saber de que lado corre el saldo no se puede encadenar.
            continue
        signo = Decimal(-1) if naturaleza == "A" else Decimal(1)
        if not ancla_de_seccion(movimientos, subtotales.get(cuenta), signo):
            continue
        corriente = movimientos[0].saldo_inicial_cuenta
        for indice in indices:
            fila = filas[indice]
            corriente = corriente + signo * (fila.debe - fila.haber)
            if fila.saldo is None:
                filas[indice] = replace(fila, saldo=corriente,
                                        saldo_origen=RECALCULADO)
                recalculadas += 1
            else:
                corriente = fila.saldo

    if recalculadas:
        _LOG.info("saldos recalculados con ancla verificada: %s", recalculadas)
    return replace(auxiliar, filas=tuple(filas))


# Nombre viejo, por si algo externo lo usaba. Se retira en la fase 8.
_ancla_verificada = ancla_de_seccion
