"""Almacen de plantillas: persistencia y aislamiento por tenant."""

from __future__ import annotations

import json

import pytest

from contapdf.templates.store import (
    AlmacenPlantillas,
    Plantilla,
    PlantillaRechazada,
    TenantInvalido,
)


def _plantilla(**kw) -> Plantilla:
    base = dict(
        tenant_id="despacho-a", huella="abc123", tipo="balanza",
        estrategia="pdf_text", mapeo={"cuenta": 0, "debe": 4, "haber": 5},
        forma="saldo_con_signo", verificado_por="vocabulario",
        orientacion_verificada=False, filas_afectadas=96,
        esquema={"separador": "", "anchos": [4, 7, 10], "marcador": [18, 21]},
        reglas={"tolerancia": "0.01", "subconjunto_totales": "nivel_1",
                "exige_partida_doble": True},
        cobertura={"cuadran": 4, "fallan": 0, "no_verificables": 0},
        pendiente_de_confirmacion=True,
    )
    base.update(kw)
    return Plantilla(**base)


def test_guarda_y_recupera(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    almacen.guardar(_plantilla())
    recuperada = almacen.buscar("despacho-a", "abc123")
    assert recuperada == _plantilla()


def test_lo_guardado_es_json_legible(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    ruta = almacen.guardar(_plantilla())
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["huella"] == "abc123"
    assert datos["mapeo"]["debe"] == 4


def test_buscar_lo_que_no_existe_devuelve_none(tmp_path):
    assert AlmacenPlantillas(tmp_path).buscar("despacho-a", "nada") is None


# --- Criterio 5: aislamiento por tenant ---------------------------------
def test_dos_tenants_con_la_misma_huella_no_se_pisan(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    almacen.guardar(_plantilla(tenant_id="despacho-a", mapeo={"debe": 4}))
    almacen.guardar(_plantilla(tenant_id="despacho-b", mapeo={"debe": 9}))

    assert almacen.buscar("despacho-a", "abc123").mapeo == {"debe": 4}
    assert almacen.buscar("despacho-b", "abc123").mapeo == {"debe": 9}


def test_un_tenant_no_ve_las_plantillas_del_otro(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    almacen.guardar(_plantilla(tenant_id="despacho-a"))
    assert almacen.listar("despacho-b") == []
    assert len(almacen.listar("despacho-a")) == 1


@pytest.mark.parametrize("tenant", ["../otro", "a/b", "", "con espacio", "."])
def test_un_tenant_id_no_puede_escaparse_del_directorio(tmp_path, tenant):
    # La ruta se deriva del ID, no de nada que suba el usuario (PLAN 0).
    with pytest.raises(TenantInvalido):
        AlmacenPlantillas(tmp_path).guardar(_plantilla(tenant_id=tenant))


# --- Criterio 4: no se guarda lo que no cuadro --------------------------
def test_una_plantilla_con_validacion_fallida_no_se_guarda(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    mala = _plantilla(cobertura={"cuadran": 3, "fallan": 1, "no_verificables": 0})
    with pytest.raises(PlantillaRechazada):
        almacen.guardar(mala)
    assert almacen.buscar("despacho-a", "abc123") is None


def test_una_plantilla_con_reglas_no_verificables_si_se_guarda(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    parcial = _plantilla(cobertura={"cuadran": 3, "fallan": 0, "no_verificables": 1})
    almacen.guardar(parcial)
    assert almacen.buscar("despacho-a", "abc123").cobertura["no_verificables"] == 1


# --- Confirmacion humana ------------------------------------------------
def test_confirmar_deja_constancia_de_quien_y_cuando(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    almacen.guardar(_plantilla())
    confirmada = almacen.confirmar("despacho-a", "abc123", por="contadora")

    assert confirmada.pendiente_de_confirmacion is False
    assert confirmada.confirmada_por == "contadora"
    assert confirmada.confirmada_en
    assert almacen.buscar("despacho-a", "abc123").confirmada_por == "contadora"


def test_confirmar_lo_que_no_existe_avisa(tmp_path):
    with pytest.raises(KeyError):
        AlmacenPlantillas(tmp_path).confirmar("despacho-a", "nada", por="x")
