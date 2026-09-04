"""Un CFDI sin folio fiscal no trae numero de documento que cruzar.

Fase 7h, objetivo 3. El parser rellenaba `documento` con la primera palabra
que quedara en el renglon, y en las polizas manuales esa palabra era el
texto 'Diario'. Resultado: 101 CFDI inventados con `documento='Diario'`,
que la regla marcaba como cruce fallido.

Marcador inequivoco, medido: los CFDI inventados son EXACTAMENTE los que no
traen UUID ni RFC — su renglon es `fecha | Diario | (Manual)`. Un CFDI de
verdad siempre trae folio fiscal. El criterio no mira el resultado del
cruce, asi que no vuelve tautologica a la regla.

Los CFDI sin folio del fixture son **112**, no 101: los 101 eran solo los
que ademas eran comparables y fallaban. De los 12 restantes, su documento
inventado coincidia por casualidad con la descripcion de su poliza y
producia un cruce FALSO POSITIVO, que este arreglo tambien elimina.
"""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.pipeline import procesar_polizas
from contapdf.validate.rules import evaluar_polizas

# Fase 8c: el fichero entero cuesta 153 s porque vuelve a parsear
# poliza.pdf (968 paginas) cinco veces. La suite rapida no puede pagarlo
# en cada ciclo; `pytest -m lento` lo corre antes de cada entrega.
pytestmark = pytest.mark.lento


def _regla(cobertura, nombre="cfdi_cruzado"):
    return next(r for r in cobertura.reglas if r.regla == nombre)


def test_un_cfdi_sin_uuid_no_inventa_numero_de_documento():
    libro = procesar_polizas(requires_real_pdf("poliza")).libro
    inventados = [c for c in libro.cfdi if c.documento and not c.uuid]
    assert inventados == [], (
        f"{len(inventados)} CFDI con documento pero sin folio fiscal")


def test_los_manuales_siguen_existiendo_como_filas():
    """No se borran: el documento los imprime y son parte de la tabla."""
    libro = procesar_polizas(requires_real_pdf("poliza")).libro
    manuales = [c for c in libro.cfdi if not c.uuid]
    assert len(manuales) == 112
    assert all(c.documento == "" for c in manuales)
    assert all(c.fecha for c in manuales)


def test_salen_del_numerador_pero_no_del_denominador():
    """Aplicables, no evaluadas, con motivo: la decision de universo de 7f."""
    r = procesar_polizas(requires_real_pdf("poliza"))
    regla = _regla(r.cobertura)
    assert regla.aplicables == 1942          # el universo no encoge
    assert regla.evaluados == 1821
    assert regla.motivo
    assert "112" in regla.motivo
    assert "folio fiscal" in regla.motivo


def test_las_fallas_bajan_de_162_a_53():
    """109 de las 162 eran CFDI inventados por el parser."""
    r = procesar_polizas(requires_real_pdf("poliza"))
    regla = _regla(r.cobertura)
    assert len(regla.discrepancias) == 53


def test_las_exactas_pierden_los_12_falsos_positivos():
    """De las 1,780 exactas de la 7g, 12 cruzaban por casualidad contra un
    documento que el parser habia inventado."""
    r = procesar_polizas(requires_real_pdf("poliza"))
    regla = _regla(r.cobertura)
    assert regla.exactas == 1768
    assert all(c.uuid for c in r.libro.cfdi if c.documento)
