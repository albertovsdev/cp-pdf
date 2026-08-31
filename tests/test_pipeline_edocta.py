"""El estado de cuenta tambien se aprende como plantilla."""

from __future__ import annotations

from conftest import requires_real_pdf

from contapdf.pipeline import procesar_estado_cuenta
from contapdf.templates.store import AlmacenPlantillas


# --- Criterio 5 ---------------------------------------------------------
def test_aprende_la_plantilla_y_declara_lo_no_cubierto(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    r = procesar_estado_cuenta(requires_real_pdf("edocta"), tenant_id="t",
                               almacen=almacen)
    assert r.plantilla is not None
    assert r.plantilla.tipo == "estado_cuenta"
    # Solo hay un banco en los fixtures: la plantilla lo dice en vez de
    # fingir que cubre "los estados de cuenta".
    assert r.plantilla.cobertura["sin_cubrir"]
    assert any("banco" in s.lower() for s in r.plantilla.cobertura["sin_cubrir"])


def test_la_segunda_carga_reutiliza(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    pdf = requires_real_pdf("edocta")
    primera = procesar_estado_cuenta(pdf, tenant_id="t", almacen=almacen)
    segunda = procesar_estado_cuenta(pdf, tenant_id="t", almacen=almacen)
    assert segunda.reutilizada is True
    assert segunda.estado.movimientos == primera.estado.movimientos


def test_sin_almacen_funciona_igual():
    r = procesar_estado_cuenta(requires_real_pdf("edocta"))
    assert r.plantilla is None
    assert len(r.estado.movimientos) == 45
    assert r.cobertura.fallan == 0
