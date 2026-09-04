"""El Libro Mayor tambien se aprende como plantilla."""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.pipeline import procesar_mayor
from contapdf.templates.store import AlmacenPlantillas


# --- Criterio 5 ---------------------------------------------------------
def test_aprende_su_plantilla_con_huella_propia(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    r = procesar_mayor(requires_real_pdf("mayor-gume"), tenant_id="t",
                       almacen=almacen)
    assert r.plantilla is not None
    assert r.plantilla.tipo == "mayor"
    assert len(almacen.listar("t")) == 1


@pytest.mark.lento          # 5 s
def test_la_huella_no_choca_con_las_de_los_otros_documentos(tmp_path):
    from contapdf.pipeline import procesar_balanza

    almacen = AlmacenPlantillas(tmp_path)
    a = procesar_mayor(requires_real_pdf("mayor-gume"), tenant_id="t",
                       almacen=almacen)
    b = procesar_balanza(requires_real_pdf("balanza-gume"), tenant_id="t",
                         almacen=almacen)
    assert a.plantilla.huella != b.plantilla.huella
    assert len(almacen.listar("t")) == 2


@pytest.mark.lento          # 4 s
def test_la_segunda_carga_reutiliza(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    pdf = requires_real_pdf("mayor-gume")
    primera = procesar_mayor(pdf, tenant_id="t", almacen=almacen)
    segunda = procesar_mayor(pdf, tenant_id="t", almacen=almacen)
    assert segunda.reutilizada is True
    assert segunda.mayor.meses == primera.mayor.meses


def test_sin_almacen_funciona_igual():
    r = procesar_mayor(requires_real_pdf("mayor-gume"))
    assert r.plantilla is None
    assert len(r.mayor.cuentas) == 49
    assert r.cobertura.fallan == 0
