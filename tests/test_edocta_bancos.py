"""Los estados de cuenta de nueve bancos, con UN solo parser.

Fase 7d. Lo que se prueba aqui no es "cada banco funciona": es que la
misma maquina --vocabulario del encabezado, anclas del encabezado,
secciones por cuenta-- cubre seis formatos sin una sola rama por banco.

Los numeros son MEDICIONES tomadas del propio documento: los saldos salen
del resumen que el banco imprime, y los conteos de BBVA salen del contador
que el propio resumen declara ('Depositos / Abonos (+) 53').

Ningun test afirma sobre nombres de personas: los PDFs reales estan
gitignored porque traen datos del cliente.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.balanza import LayoutDesconocido
from contapdf.parsers.estado_cuenta import (
    EstadoCuentaParser,
    ReporteNoEsperado,
)
from contapdf.validate.rules import CUADRA, NO_VERIFICABLE, evaluar_estado_cuenta

_D = Decimal


def _parse(nombre: str):
    doc, _ = extraer(requires_real_pdf(nombre))
    return EstadoCuentaParser().parse(doc)


@pytest.fixture(scope="module")
def bancos():
    """Los seis con tabla de movimientos, leidos una sola vez."""
    return {n: _parse(n) for n in (
        "edocta", "edocta-abril-santander", "edocta-julio-banorte",
        "edocta-bajio", "edocta-inbursa", "edocta-bbva")}


def _regla(cobertura, nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


# --- Criterio 1: los seis, el MISMO parser -------------------------------
# El resumen que cada banco imprime, con su vocabulario propio:
#   AFIRME     Depositos / Retiros
#   Santander  +Depsitos / - Retiros      (el PDF no trae los acentos)
#   Bajio      (+) DEPOSITOS / (-) CARGOS  en tabla horizontal
#   Inbursa    ABONOS / CARGOS             (invertidas respecto a AFIRME)
#   BBVA       Depositos / Abonos (+) 53   (con contador de movimientos)
_RESUMENES = {
    "edocta": (_D("32411.67"), _D("118420.39"), _D("118958.74"), _D("31873.32")),
    "edocta-abril-santander": (_D("181609.21"), _D("2789056.92"),
                               _D("2924939.71"), _D("45726.42")),
    "edocta-bajio": (_D("6598.82"), _D("1828459.92"), _D("1715473.47"),
                     _D("119585.27")),
    "edocta-inbursa": (_D("916.71"), _D("37037357.05"), _D("37037584.97"),
                       _D("688.79")),
    "edocta-bbva": (_D("4905508.33"), _D("8135310.01"), _D("13012595.49"),
                    _D("28222.85")),
}


@pytest.mark.parametrize("nombre", sorted(_RESUMENES))
def test_lee_el_resumen_de_cada_banco(bancos, nombre):
    cuenta = bancos[nombre].cuentas[0]
    esperado = _RESUMENES[nombre]
    assert (cuenta.saldo_inicial, cuenta.depositos,
            cuenta.retiros, cuenta.saldo_corte) == esperado


@pytest.mark.parametrize("nombre", sorted(_RESUMENES))
def test_el_resumen_de_cada_banco_cuadra_solo(bancos, nombre):
    inicial, depositos, retiros, corte = _RESUMENES[nombre]
    assert inicial + depositos - retiros == corte


@pytest.mark.parametrize("nombre", sorted(_RESUMENES) + ["edocta-julio-banorte"])
def test_cada_banco_entrega_movimientos_con_cuenta(bancos, nombre):
    estado = bancos[nombre]
    assert estado.movimientos
    cuentas = {c.num_cuenta for c in estado.cuentas}
    assert cuentas
    assert {m.num_cuenta for m in estado.movimientos} <= cuentas


@pytest.mark.parametrize("nombre", sorted(_RESUMENES) + ["edocta-julio-banorte"])
def test_ningun_movimiento_trae_deposito_y_retiro_a_la_vez(bancos, nombre):
    for m in bancos[nombre].movimientos:
        assert not (m.deposito > 0 and m.retiro > 0), m


def test_el_parser_no_tiene_ramas_por_banco():
    """La generalizacion es por vocabulario y anclas, no por 'if banco ==='."""
    from pathlib import Path

    import contapdf.parsers.estado_cuenta as modulo
    fuente = Path(modulo.__file__).read_text(encoding="utf-8").lower()
    for banco in ("afirme", "santander", "banorte", "bajio", "inbursa",
                  "bbva", "hsbc", "scotiabank", "monex", "multiva"):
        assert banco not in fuente, (
            f"el parser nombra a {banco}: eso es una rama por banco")


# Conteos MEDIDOS, no metas. Cada uno esta respaldado por un checksum del
# propio documento: los cinco con resumen completo suman exactamente lo
# declarado, y en Banorte el saldo corrido encadena los 283 sin un solo
# hueco.
_MOVIMIENTOS = {
    "edocta": 45,
    "edocta-abril-santander": 110,
    "edocta-julio-banorte": 283,
    "edocta-bajio": 67,
    "edocta-inbursa": 44,
    "edocta-bbva": 116,
}


@pytest.mark.parametrize("nombre", sorted(_MOVIMIENTOS))
def test_cuantos_movimientos_trae_cada_uno(bancos, nombre):
    assert len(bancos[nombre].movimientos) == _MOVIMIENTOS[nombre]


def test_la_fila_de_saldo_anterior_no_cuenta_como_movimiento(bancos):
    """Varios formatos abren la tabla con su saldo de arranque.

    Lleva fecha y saldo, asi que pasa la regla de fila nueva, pero no es un
    movimiento: no mueve dinero y contarlo inflaria el total.
    """
    for nombre, estado in bancos.items():
        for m in estado.movimientos:
            plano = m.descripcion.lower().replace(" ", "")
            if m.deposito or m.retiro:
                continue
            assert not plano.startswith(("saldoanterior", "saldoinicial",
                                         "balanceinicial")), (nombre, m)


# --- Criterio 1 (bis): la forma que comparten ---------------------------
def test_los_seis_dan_saldo_corrido_que_cuadra(bancos):
    """Prueba que la fila se armo bien: el saldo impreso encadena.

    BBVA imprime el saldo solo en la ultima fila del dia, asi que ahi la
    regla comprueba menos renglones; lo que no puede pasar es que falle.
    """
    for nombre, estado in bancos.items():
        regla = _regla(evaluar_estado_cuenta(estado), "saldo_corrido")
        assert regla.estado in (CUADRA, NO_VERIFICABLE), (nombre, regla)


@pytest.mark.parametrize("nombre", sorted(_RESUMENES))
def test_los_movimientos_suman_lo_que_declara_el_resumen(bancos, nombre):
    """La regla que prueba que no se perdio media tabla."""
    regla = _regla(evaluar_estado_cuenta(bancos[nombre]), "resumen_movimientos")
    assert regla.estado == CUADRA, regla


def test_bbva_trae_los_dos_contadores_que_el_resumen_declara(bancos):
    # 'Depositos / Abonos (+) 53' y 'Retiros / Cargos (-) 63': el propio
    # documento dice cuantos movimientos hay de cada lado.
    movimientos = bancos["edocta-bbva"].movimientos
    assert sum(1 for m in movimientos if m.deposito > 0) == 53
    assert sum(1 for m in movimientos if m.retiro > 0) == 63


def test_cada_banco_trae_su_formato_de_fecha(bancos):
    """Seis formatos distintos, todos normalizados a dd/mm/aaaa."""
    esperado = {
        "edocta": "04/2025",                   # solo el dia: '03'
        "edocta-abril-santander": "04/2025",   # '01-ABR-2025'
        "edocta-julio-banorte": "07/2023",     # '01-JUL-23'
        "edocta-bajio": "09/2022",             # '1 SEP'
        "edocta-inbursa": "07/2025",           # 'JUL. 03'
        "edocta-bbva": "12/2022",              # '01/DIC'
    }
    for nombre, cola in esperado.items():
        fechas = {m.fecha for m in bancos[nombre].movimientos}
        assert fechas, nombre
        assert all(f.endswith(cola) for f in fechas), (nombre, sorted(fechas)[:3])


# --- Criterio 2: Banorte julio, dos cuentas ------------------------------
def test_banorte_trae_dos_cuentas(bancos):
    cuentas = bancos["edocta-julio-banorte"].cuentas
    assert len(cuentas) == 2
    assert [c.num_cuenta for c in cuentas] == ["1228999123", "1228999730"]
    assert all(c.clabe and len(c.clabe) == 18 for c in cuentas)


def test_banorte_reparte_los_saldos_por_cuenta(bancos):
    principal, inversion = bancos["edocta-julio-banorte"].cuentas
    assert principal.saldo_inicial == _D("4859.71")
    assert principal.saldo_corte == _D("406720.80")
    assert inversion.saldo_inicial == _D("0.00")
    assert inversion.saldo_corte == _D("0.00")


def test_banorte_atribuye_cada_movimiento_a_su_cuenta(bancos):
    estado = bancos["edocta-julio-banorte"]
    principal, inversion = estado.cuentas
    # La cuenta de inversion imprime 'SIN MOVIMIENTOS': su seccion existe
    # pero no aporta ninguno.
    assert estado.movimientos_de(inversion.num_cuenta) == ()
    propios = estado.movimientos_de(principal.num_cuenta)
    assert len(propios) == len(estado.movimientos) > 100


def test_banorte_cierra_el_saldo_corrido_de_la_cuenta_principal(bancos):
    estado = bancos["edocta-julio-banorte"]
    principal = estado.cuentas[0]
    propios = estado.movimientos_de(principal.num_cuenta)
    corrido = principal.saldo_inicial + sum(
        (m.deposito - m.retiro for m in propios), Decimal("0.00"))
    assert corrido == principal.saldo_corte


def test_banorte_no_reparte_totales_que_no_estan_desglosados(bancos):
    """Con dos cuentas y sin desglose legible, van a None. No se reparte."""
    for cuenta in bancos["edocta-julio-banorte"].cuentas:
        assert cuenta.depositos is None
        assert cuenta.retiros is None


def test_la_regla_del_total_corre_en_banorte(bancos):
    # El documento imprime 'TOTAL $4,859.71 $406,720.80': la suma por
    # cuenta tiene con que cruzarse.
    estado = bancos["edocta-julio-banorte"]
    assert estado.meta.total_saldo_inicial == _D("4859.71")
    assert estado.meta.total_saldo_corte == _D("406720.80")
    regla = _regla(evaluar_estado_cuenta(estado), "total_declarado")
    assert regla.estado == CUADRA
    assert regla.comprobaciones == 2


def test_sin_fila_total_la_regla_lo_declara(bancos):
    regla = _regla(evaluar_estado_cuenta(bancos["edocta-bajio"]),
                   "total_declarado")
    assert regla.estado == NO_VERIFICABLE
    assert regla.motivo


# --- Criterio 3: los que NO traen tabla dicen QUE son --------------------
_SIN_TABLA = {
    "edocta-scotiabank": "sin_movimientos",
    "edocta-monex": "sin_movimientos",
    "edocta-multiva": "sin_movimientos",
}


@pytest.mark.parametrize("nombre,clave", sorted(_SIN_TABLA.items()))
def test_el_que_no_trae_tabla_se_identifica(nombre, clave):
    with pytest.raises(ReporteNoEsperado) as exc:
        _parse(nombre)
    assert exc.value.tipo.clave == clave
    # El motivo tiene que servirle a la capa web para decir QUE paso, no
    # 'layout desconocido'.
    assert "movimiento" in exc.value.tipo.etiqueta.lower()
    assert exc.value.tipo.evidencia


def test_sigue_siendo_un_layout_desconocido():
    """Quien ya atrapaba LayoutDesconocido no se entera del cambio."""
    with pytest.raises(LayoutDesconocido):
        _parse("edocta-monex")


def test_el_sin_movimientos_se_apoya_en_el_resumen_del_documento():
    # No es 'no encontre la tabla': es 'el banco declara cero movimientos'.
    with pytest.raises(ReporteNoEsperado) as exc:
        _parse("edocta-multiva")
    assert exc.value.tipo.cuentas
    cuenta = exc.value.tipo.cuentas[0]
    assert cuenta.depositos == _D("0.00")
    assert cuenta.retiros == _D("0.00")
    assert cuenta.saldo_inicial == cuenta.saldo_corte == _D("10652.00")


# --- Santander integral: medicion corregida de la fase 7d ---------------
def test_santander_integral_si_trae_tabla():
    """PLAN lo listaba como 'sin tabla'; se midio sobre 3 paginas de 10.

    Trae tres secciones de detalle (cheques, dinero creciente, inversiones
    a plazo) y una de credito. Las que traen encabezado de movimientos se
    leen; la de inversiones a plazo tiene otro encabezado y no se lee.
    """
    estado = _parse("edocta-santander")
    assert len(estado.cuentas) >= 2
    assert estado.movimientos


# --- Criterio 4: HSBC, recuperacion por OCR ------------------------------
@pytest.mark.lento
def test_hsbc_se_recupera_por_ocr():
    """97% de sus palabras vienen en CID. La pregunta es cuanto recupera.

    Medido: 565 de 590 tokens (95.8%), muy por encima de Inbursa (35%) y
    Multiva (20%), porque aqui la pagina entera esta dibujada a tamano
    normal en vez de ser un sello digital diminuto.
    """
    from contapdf.reintento import reintentar_cid
    r = reintentar_cid(requires_real_pdf("edocta-hsbc"))
    if not r.disponible:
        pytest.skip("tesseract no esta instalado")
    assert r.ilegibles == 590
    assert r.recuperados / r.ilegibles > 0.90


@pytest.mark.lento
def test_hsbc_leido_por_ocr_si_lo_procesa_el_mismo_parser():
    """El parser no sabe de que extractor vino el Document (ARQUITECTURA 1)."""
    from contapdf.extract import ocr
    if not ocr.hay_tesseract():
        pytest.skip("tesseract no esta instalado")
    estado = EstadoCuentaParser().parse(ocr.extract(requires_real_pdf("edocta-hsbc")))
    cuenta = estado.cuentas[0]
    assert cuenta.saldo_inicial == _D("7945.22")
    assert cuenta.depositos == _D("0.00")
    assert cuenta.retiros == _D("2749.62")
    assert cuenta.saldo_corte == _D("5195.60")
    assert sum(m.retiro for m in estado.movimientos) == _D("2749.62")
