"""El auxiliar tambien se aprende como plantilla."""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.pipeline import procesar_auxiliar
from contapdf.templates.store import AlmacenPlantillas


# --- Criterio 5 ---------------------------------------------------------
def test_cada_variante_aprende_su_propia_plantilla(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    a = procesar_auxiliar(requires_real_pdf("auxiliar"), tenant_id="t",
                          almacen=almacen, page_numbers=[1, 2, 3])
    b = procesar_auxiliar(requires_real_pdf("auxiliar-gume"), tenant_id="t",
                          almacen=almacen, page_numbers=[1, 2, 3])

    assert a.plantilla is not None and b.plantilla is not None
    assert a.plantilla.huella != b.plantilla.huella
    assert a.plantilla.tipo == "auxiliar" == b.plantilla.tipo
    assert len(almacen.listar("t")) == 2


def test_la_segunda_carga_reutiliza(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    pdf = requires_real_pdf("auxiliar-gume")
    primera = procesar_auxiliar(pdf, tenant_id="t", almacen=almacen,
                                page_numbers=[1, 2, 3])
    segunda = procesar_auxiliar(pdf, tenant_id="t", almacen=almacen,
                                page_numbers=[1, 2, 3])
    assert segunda.reutilizada is True
    assert [f.cuenta for f in segunda.auxiliar.filas] == \
           [f.cuenta for f in primera.auxiliar.filas]


def test_la_plantilla_no_se_guarda_si_la_validacion_falla(tmp_path, monkeypatch):
    import contapdf.pipeline as pipeline

    almacen = AlmacenPlantillas(tmp_path)
    real = pipeline.evaluar_auxiliar

    def rota(aux, **kw):
        cobertura = real(aux, **kw)
        import dataclasses
        reglas = tuple(dataclasses.replace(r, estado="falla") if i == 0 else r
                       for i, r in enumerate(cobertura.reglas))
        return dataclasses.replace(cobertura, reglas=reglas)

    monkeypatch.setattr(pipeline, "evaluar_auxiliar", rota)
    r = procesar_auxiliar(requires_real_pdf("auxiliar"), tenant_id="t",
                          almacen=almacen, page_numbers=[1, 2])
    assert r.plantilla is None
    assert almacen.listar("t") == []


def test_sin_almacen_funciona_igual():
    r = procesar_auxiliar(requires_real_pdf("auxiliar"), page_numbers=[1, 2])
    assert r.plantilla is None
    assert r.auxiliar.filas
