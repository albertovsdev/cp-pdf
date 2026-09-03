"""Un movimiento cuyo nombre de cuenta se envuelve no se pierde.

Fase 7h, objetivo 2 (familia B). Medido: en las 968 paginas del fixture hay
exactamente TRES renglones con debe y haber pero sin numero de cuenta, y
son las tres polizas que fallaban la partida doble. El nombre largo del
banco se envuelve en tres renglones visuales y los importes caen en el del
MEDIO, que no lleva el numero de cuenta:

    119-01      IVA pendiente de pago              $336.00      $0.00
    201-01-101  BANCO SANTANDER MEXICO S.A.,
                INSTITUCION DE BANCA MULTIPLE,       $0.00  $2,436.00
                GRUPO FINANCIERO SANTANDER MEXICO
    701-10      Comisiones bancarias             $2,100.00      $0.00

Hay tinta y se leyo: lo que fallaba era la ASOCIACION. Es el mismo
mecanismo de las continuaciones del estado de cuenta.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import requires_real_pdf

from contapdf.pipeline import procesar_polizas
from contapdf.validate.rules import CUADRA


def _regla(cobertura, nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


def test_las_tres_polizas_recuperan_su_movimiento():
    libro = procesar_polizas(requires_real_pdf("poliza")).libro
    for pid, cuantos in (("P00010", 3), ("P01804", 3), ("P01919", 4)):
        movs = [m for m in libro.movimientos if m.poliza_id == pid]
        assert len(movs) == cuantos, (pid, [m.cuenta for m in movs])


def test_el_movimiento_recuperado_lleva_su_cuenta_y_su_nombre():
    libro = procesar_polizas(requires_real_pdf("poliza")).libro
    movs = [m for m in libro.movimientos if m.poliza_id == "P00010"]
    banco = next(m for m in movs if m.haber == Decimal("2436.00"))
    assert banco.cuenta == "201-01-101"
    assert "SANTANDER" in banco.nombre_cuenta.upper()
    assert banco.debe == Decimal("0.00")


def test_la_partida_doble_de_esas_tres_cuadra():
    libro = procesar_polizas(requires_real_pdf("poliza")).libro
    for pid in ("P00010", "P01804", "P01919"):
        movs = [m for m in libro.movimientos if m.poliza_id == pid]
        assert sum(m.debe for m in movs) == sum(m.haber for m in movs), pid


def test_el_documento_entero_deja_de_tener_esas_fallas():
    r = procesar_polizas(requires_real_pdf("poliza"))
    assert _regla(r.cobertura, "partida_doble").estado == CUADRA
    assert _regla(r.cobertura, "totales").estado == CUADRA


def test_no_aparecen_movimientos_de_mas():
    """6,780 leidos + 3 recuperados. Ni uno mas."""
    libro = procesar_polizas(requires_real_pdf("poliza")).libro
    assert len(libro.movimientos) == 6783
    assert len(libro.polizas) == 1944
