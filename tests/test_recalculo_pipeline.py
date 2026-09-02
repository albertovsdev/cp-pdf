"""El recalculo de saldos conectado al pipeline.

Fase 7g, arreglo 2. `recalculo.recalcular_saldos` existia y estaba
testeado, pero `pipeline.py` no lo llamaba nunca: `auxiliar-gume` entregaba
35,045 movimientos sin saldo mientras PLAN 2 medía «0 sin saldo» llamando
la funcion a mano.

El recalculo solo es valido anclado en los dos extremos contra el subtotal
declarado. Donde no haya ancla, el movimiento se queda sin saldo y la
cobertura lo declara: NUNCA se inventa un saldo con un solo ancla.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.parsers.auxiliar import IMPRESO, RECALCULADO, Auxiliar, FilaAuxiliar
from contapdf.pipeline import procesar_auxiliar

_CERO = Decimal("0.00")


def _fila(cuenta, debe, haber, saldo, *, inicial=_CERO, subtotal=False):
    return FilaAuxiliar(
        cuenta=cuenta, nombre_cuenta="X", saldo_inicial_cuenta=inicial,
        folio="", fecha="01/01/2025", tipo_movimiento="", documento="",
        tercero="", concepto="", debe=Decimal(debe), haber=Decimal(haber),
        saldo=None if saldo is None else Decimal(saldo),
        saldo_origen=IMPRESO, es_subtotal=subtotal)


def test_el_pipeline_recalcula_lo_que_puede_anclar():
    """Antes: la funcion existia y nadie la llamaba."""
    r = procesar_auxiliar(requires_real_pdf("auxiliar"))
    # El fixture no imprime subtotales, asi que no hay ancla posible; lo que
    # importa es que el pipeline no rompa nada y declare los tres estados.
    assert set(r.cobertura.saldos) == {"impreso", "recalculado", "sin_saldo"}
    assert sum(r.cobertura.saldos.values()) == len(r.auxiliar.filas)


def test_un_saldo_recalculado_no_se_confunde_con_uno_impreso():
    """El contrato ya existe: `saldo_origen` distingue las dos cosas."""
    from contapdf.recalculo import recalcular_saldos

    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", None),
        _fila("101-01", "250.00", "0.00", "850.00"),
        _fila("101-01", "1250.00", "400.00", "850.00", subtotal=True),
    ))
    salida = recalcular_saldos(aux)
    movimientos = [f for f in salida.filas if not f.es_subtotal]
    assert movimientos[1].saldo == Decimal("600.00")
    assert movimientos[1].saldo_origen == RECALCULADO
    assert movimientos[0].saldo_origen == IMPRESO


def test_una_cuenta_acreedora_tambien_se_recalcula_bien():
    """El recalculo tambien cableaba el signo: encadenaba siempre deudora.

    Sin derivar la naturaleza, las cuentas acreedoras salian con saldos
    recalculados INCORRECTOS y marcados como buenos, que es peor que
    dejarlos vacios.
    """
    from contapdf.recalculo import recalcular_saldos

    aux = Auxiliar(filas=(
        _fila("201-01", "0.00", "5000.00", "5000.00"),
        _fila("201-01", "1500.00", "0.00", None),
        _fila("201-01", "0.00", "800.00", "4300.00"),
        _fila("201-01", "1500.00", "5800.00", "4300.00", subtotal=True),
    ))
    salida = recalcular_saldos(aux)
    movimientos = [f for f in salida.filas if not f.es_subtotal]
    assert movimientos[1].saldo == Decimal("3500.00")   # no 6500.00
    assert movimientos[1].saldo_origen == RECALCULADO


def test_sin_ancla_no_se_inventa_el_saldo():
    """Sin subtotal declarado no hay con que comprobar la cadena."""
    from contapdf.recalculo import recalcular_saldos

    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", None),
    ))
    salida = recalcular_saldos(aux)
    assert salida.filas[1].saldo is None
    assert salida.filas[1].saldo_origen != RECALCULADO


def test_una_suma_que_no_cuadra_con_el_subtotal_no_ancla():
    """Si falta un movimiento, encadenar desplazaria todos los saldos."""
    from contapdf.recalculo import recalcular_saldos

    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", None),
        _fila("101-01", "9999.00", "0.00", "9999.00", subtotal=True),
    ))
    assert recalcular_saldos(aux).filas[1].saldo is None


@pytest.mark.lento
def test_auxiliar_gume_reporta_los_tres_estados_del_saldo():
    """Los tres estados con su conteo, y la suma cuadra con las filas."""
    r = procesar_auxiliar(requires_real_pdf("auxiliar-gume"))
    saldos = r.cobertura.saldos
    assert saldos["recalculado"] > 0, "el pipeline no esta recalculando"
    assert saldos["impreso"] > 0
    movimientos = [f for f in r.auxiliar.filas if not f.es_subtotal]
    assert (saldos["impreso"] + saldos["recalculado"]
            + saldos["sin_saldo"]) == len(movimientos)
    # Lo que no se pudo anclar sigue vacio, no inventado.
    assert sum(1 for f in movimientos if f.saldo is None) == saldos["sin_saldo"]
