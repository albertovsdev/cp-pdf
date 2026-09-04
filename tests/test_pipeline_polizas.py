"""El libro diario tambien se aprende como plantilla."""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.pipeline import procesar_polizas
from contapdf.templates.store import AlmacenPlantillas


# --- Criterio 5 ---------------------------------------------------------
@pytest.mark.lento          # 4 s
def test_cada_variante_aprende_su_plantilla_con_huella_distinta(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    a = procesar_polizas(requires_real_pdf("poliza"), tenant_id="t",
                         almacen=almacen, page_numbers=[1, 2, 3, 4])
    b = procesar_polizas(requires_real_pdf("diario-general"), tenant_id="t",
                         almacen=almacen, page_numbers=[1, 2, 3])

    assert a.plantilla.huella != b.plantilla.huella
    assert a.plantilla.tipo == "polizas" == b.plantilla.tipo
    assert len(almacen.listar("t")) == 2


@pytest.mark.lento          # 6 s
def test_la_segunda_carga_reutiliza(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    pdf = requires_real_pdf("poliza")
    primera = procesar_polizas(pdf, tenant_id="t", almacen=almacen,
                               page_numbers=[1, 2])
    segunda = procesar_polizas(pdf, tenant_id="t", almacen=almacen,
                               page_numbers=[1, 2])
    assert segunda.reutilizada is True
    assert segunda.libro.movimientos == primera.libro.movimientos


def test_la_estrategia_queda_registrada(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    r = procesar_polizas(requires_real_pdf("diario-general"), tenant_id="t",
                         almacen=almacen, page_numbers=[1, 2])
    assert r.plantilla.estrategia in ("pdf_text", "pdf_chars")
    assert r.cobertura.fallan == 0


def test_sin_almacen_funciona_igual():
    r = procesar_polizas(requires_real_pdf("poliza"), page_numbers=[1, 2])
    assert r.plantilla is None
    assert r.libro.polizas
