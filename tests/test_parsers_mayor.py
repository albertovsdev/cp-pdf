"""Libro Mayor: cuenta + 12 meses, en dos tablas relacionadas.

Las secciones se parten entre paginas: la pagina 2 arranca con 'Inicial'
sin numero de cuenta porque quedo en el ultimo renglon de la anterior.
Ningun otro documento del sistema tiene eso.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.mayor import MayorParser


@pytest.fixture(scope="module")
def mayor():
    doc, _ = extraer(requires_real_pdf("mayor-gume"))
    return MayorParser().parse(doc)


# --- Criterio 1: secciones partidas entre paginas -----------------------
def test_lee_todas_las_cuentas(mayor):
    assert len(mayor.cuentas) == 49
    assert all(c.cuenta and c.nombre_cuenta for c in mayor.cuentas)


def test_cada_cuenta_trae_sus_doce_meses(mayor):
    por_cuenta: dict[str, int] = {}
    for m in mayor.meses:
        por_cuenta[m.cuenta] = por_cuenta.get(m.cuenta, 0) + 1
    assert set(por_cuenta.values()) == {12}
    assert len(por_cuenta) == 49


def test_ninguna_fila_queda_huerfana(mayor):
    # El invariante que justifica las dos tablas: todo mes apunta a una
    # cuenta que existe. Es la leccion del CFDI aplicada aqui.
    cuentas = {c.cuenta for c in mayor.cuentas}
    assert all(m.cuenta in cuentas for m in mayor.meses)


def test_arrastra_la_cuenta_a_traves_del_salto_de_pagina(mayor):
    # 1150-000-000 CLIENTES abre en el ultimo renglon de la pagina 1 y sus
    # meses estan en la pagina 2.
    clientes = next(c for c in mayor.cuentas if c.cuenta == "1150-000-000")
    assert clientes.nombre_cuenta == "CLIENTES"
    assert clientes.saldo_inicial == Decimal("263498.86")
    meses = [m for m in mayor.meses if m.cuenta == "1150-000-000"]
    assert len(meses) == 12
    assert {m.pagina for m in meses} == {2}


def test_los_meses_van_en_orden(mayor):
    meses = [m for m in mayor.meses if m.cuenta == "1120-000-000"]
    assert [m.orden for m in meses] == list(range(1, 13))
    assert meses[0].periodo == "ENERO"
    assert meses[-1].periodo == "DICIEMBRE"


def test_los_importes_de_un_mes_verificado_a_mano(mayor):
    enero = next(m for m in mayor.meses
                 if m.cuenta == "1120-000-000" and m.orden == 1)
    assert enero.cargos == Decimal("28304459.40")
    assert enero.abonos == Decimal("28339930.18")
    assert enero.saldo == Decimal("65833.97")
    assert enero.acum_cargos == Decimal("28304459.40")
    assert enero.acum_abonos == Decimal("28339930.18")


def test_la_cuenta_resume_lo_que_el_documento_ya_declara(mayor):
    bancos = next(c for c in mayor.cuentas if c.cuenta == "1120-000-000")
    assert bancos.saldo_inicial == Decimal("101304.75")
    diciembre = next(m for m in mayor.meses
                     if m.cuenta == "1120-000-000" and m.orden == 12)
    assert bancos.saldo_final == diciembre.saldo
    assert bancos.total_cargos == diciembre.acum_cargos
    assert bancos.total_abonos == diciembre.acum_abonos


def test_es_determinista(mayor):
    doc, _ = extraer(requires_real_pdf("mayor-gume"))
    assert MayorParser().parse(doc).meses == mayor.meses


# --- Fase 8e: fallar limpio en vez de entregar sin haber leido ----------
# `mayor-proactivity` no es un libro mayor: es un reporte de movimientos por
# cuenta que no imprime meses. `_es_mes` mira si el primer token del renglon
# es un nombre de mes, y el documento los menciona dentro de descripciones,
# asi que produce 48 renglones de mes vacios, 1 cuenta y cobertura sobre 145
# casos. Un parser que entrega sin haber leido.
#
# La guarda es a nivel de DOCUMENTO y sobre el DATO, no sobre la forma:
# si ningun renglon de mes de todo el documento trajo un importe, no se
# leyo nada. Medido en la 8e: `mayor-gume` trae 303 de sus 588 meses con
# importe no nulo ni cero, y `mayor-proactivity` 0 de 48.
#
# NO es el arreglo de `_es_mes`, que sigue aceptando un nombre de mes al
# principio de cualquier renglon de descripcion.

def _mes(orden, periodo, cargos="0.00", abonos="0.00", saldo=None,
         acum=(None, None)):
    from contapdf.parsers.mayor import MesMayor
    return MesMayor(cuenta="1000-000-000", orden=orden, periodo=periodo,
                    cargos=Decimal(cargos), abonos=Decimal(abonos),
                    saldo=None if saldo is None else Decimal(saldo),
                    acum_cargos=None if acum[0] is None else Decimal(acum[0]),
                    acum_abonos=None if acum[1] is None else Decimal(acum[1]),
                    pagina=1)


def test_la_guarda_dispara_cuando_ningun_mes_trae_importes():
    from contapdf.parsers.mayor import _sin_un_solo_importe

    vacios = [_mes(1, "ENERO"), _mes(2, "FEBRERO"), _mes(3, "MARZO")]
    assert _sin_un_solo_importe(vacios)


def test_la_guarda_no_dispara_si_UNO_SOLO_trae_algo():
    """Es a nivel de DOCUMENTO: con un importe en todo el mayor, no salta."""
    from contapdf.parsers.mayor import _sin_un_solo_importe

    for campo in ({"cargos": "1.00"}, {"abonos": "1.00"}, {"saldo": "1.00"},
                  {"acum": ("1.00", None)}, {"acum": (None, "1.00")}):
        meses = [_mes(1, "ENERO"), _mes(2, "FEBRERO", **campo)]
        assert not _sin_un_solo_importe(meses), campo


def test_un_saldo_en_cero_no_cuenta_como_importe():
    """Un mes en ceros es un mes sin leer, no un mes leido que vale cero.

    `mayor-gume` tiene 285 de sus 588 meses asi y aun asi pasa la guarda,
    porque los otros 303 traen cifras.
    """
    from contapdf.parsers.mayor import _sin_un_solo_importe

    assert _sin_un_solo_importe([_mes(1, "ENERO", saldo="0.00",
                                      acum=("0.00", "0.00"))])


def test_sin_meses_la_guarda_no_opina():
    """Un documento sin un solo renglon de mes falla por otro camino."""
    from contapdf.parsers.mayor import _sin_un_solo_importe

    assert not _sin_un_solo_importe([])


@pytest.mark.lento          # 60 s: 276 paginas
def test_mayor_proactivity_falla_limpio():
    from conftest import requires_real_pdf

    from contapdf.extract.strategy import extraer
    from contapdf.parsers.balanza import LayoutDesconocido

    documento, _ = extraer(requires_real_pdf("mayor-proactivity"))
    with pytest.raises(LayoutDesconocido) as exc:
        MayorParser().parse(documento)
    mensaje = str(exc.value)
    # 48, que es lo que el parser produjo. Los 50 renglones candidatos que
    # midio la 8e incluyen 2 que se pierden antes (fuera de la zona de tabla
    # o sin cuenta abierta), y el parser no los guarda: el mensaje dice lo
    # que vio, no lo que una medicion externa conto.
    assert "48" in mensaje
    assert "cargos" in mensaje and "abonos" in mensaje and "saldo" in mensaje
    assert "libro mayor" in mensaje.lower()


@pytest.mark.lento          # el fixture bueno no se toca
def test_mayor_gume_sigue_pasando_la_guarda():
    """Margen medido en la 8e: 303 de sus 588 meses traen importe."""
    from conftest import requires_real_pdf

    from contapdf.pipeline import procesar_mayor

    resultado = procesar_mayor(requires_real_pdf("mayor-gume"))
    assert len(resultado.mayor.cuentas) == 49
    assert len(resultado.mayor.meses) == 588
    con_importe = sum(1 for m in resultado.mayor.meses
                      if m.cargos or m.abonos or (m.saldo is not None and m.saldo))
    assert con_importe == 303
    reglas = {r.regla: r for r in resultado.cobertura.reglas}
    assert (reglas["saldo_mensual"].evaluados,
            reglas["saldo_mensual"].aplicables) == (588, 588)
    assert (reglas["acumulados"].evaluados,
            reglas["acumulados"].aplicables) == (1176, 1176)
