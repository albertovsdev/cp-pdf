"""Orquestacion: de un PDF a filas validadas, aprendiendo el formato.

Un formato desconocido se resuelve una vez y queda guardado; la carga
siguiente del mismo formato se procesa sin volver a proponer mapeos ni
preguntarle nada a nadie.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from contapdf.cuentas import inferir_esquema
from contapdf.extract.strategy import extraer
from contapdf.ir import Page
from contapdf.parsers.auxiliar import Auxiliar, AuxiliarParser
from contapdf.parsers.balanza import Balanza, BalanzaParser, Mapeo
from contapdf.parsers.estado_cuenta import (
    EstadoCuenta,
    EstadoCuentaParser,
    detectar_cabecera,
)
from contapdf.parsers.mayor import Mayor, MayorParser
from contapdf.parsers.polizas import LibroDiario, PolizasParser
from contapdf.parsers.base import Layout, detectar_layout, lineas_de_tabla
from contapdf.templates.fingerprint import Huella, huella_de
from contapdf.templates.store import AlmacenPlantillas, Plantilla
from contapdf.validate.rules import (
    Cobertura,
    ReglasBalanza,
    evaluar_auxiliar,
    evaluar_balanza,
    evaluar_estado_cuenta,
    evaluar_mayor,
    evaluar_polizas,
)

_LOG = logging.getLogger(__name__)
_X_CUENTA = 100.0


@dataclass(frozen=True)
class ResultadoAuxiliar:
    auxiliar: Auxiliar
    cobertura: Cobertura
    estrategia: str
    huella: Huella | None
    plantilla: Plantilla | None
    reutilizada: bool


@dataclass(frozen=True)
class Resultado:
    balanza: Balanza
    cobertura: Cobertura
    estrategia: str
    huella: Huella | None
    plantilla: Plantilla | None
    reutilizada: bool


def _muestra(documento, cuantas: int) -> list[Page]:
    """Las primeras paginas con tabla, para deducir layout y huella."""
    paginas = documento.open_pages()
    try:
        recogidas: list[Page] = []
        for page in paginas:
            recogidas.append(page)
            if len(recogidas) >= cuantas:
                break
        return recogidas
    finally:
        paginas.close()


def _cuentas_de(paginas: Sequence[Page]) -> list[str]:
    return [w.text for p in paginas for ln in lineas_de_tabla(p)
            for w in ln.words if w.x0 < _X_CUENTA]


def _reglas_de(plantilla: Plantilla) -> ReglasBalanza:
    datos = plantilla.reglas
    return ReglasBalanza(
        tolerancia=Decimal(datos["tolerancia"]),
        subconjunto_totales=datos["subconjunto_totales"],
        exige_partida_doble=datos["exige_partida_doble"],
    )


def _mapeo_de(plantilla: Plantilla) -> Mapeo:
    return Mapeo(campos=dict(plantilla.mapeo), forma=plantilla.forma,
                 verificado_por=plantilla.verificado_por,
                 orientacion_verificada=plantilla.orientacion_verificada,
                 filas_afectadas=plantilla.filas_afectadas)


def construir_plantilla(tenant_id: str, huella: Huella, estrategia: str,
                        balanza: Balanza, cobertura: Cobertura,
                        reglas: ReglasBalanza) -> Plantilla:
    """Todo lo que la fase 3 y la 4a demostraron que varia por formato."""
    mapeo = balanza.mapeo
    esquema = inferir_esquema([f.cuenta for f in balanza.filas])
    return Plantilla(
        tenant_id=tenant_id,
        huella=huella.valor,
        tipo="balanza",
        estrategia=estrategia,
        mapeo=dict(mapeo.campos),
        forma=mapeo.forma,
        verificado_por=mapeo.verificado_por,
        orientacion_verificada=mapeo.orientacion_verificada,
        filas_afectadas=mapeo.filas_afectadas,
        esquema={"separador": esquema.separador, "anchos": list(esquema.anchos),
                 "marcador": list(esquema.marcador) if esquema.marcador else None,
                 "largo": esquema.largo},
        reglas={"tolerancia": str(reglas.tolerancia),
                "subconjunto_totales": reglas.subconjunto_totales,
                "exige_partida_doble": reglas.exige_partida_doble},
        cobertura={"cuadran": cobertura.cuadran, "fallan": cobertura.fallan,
                   "no_verificables": cobertura.no_verificables,
                   "sin_comprobar": [r.regla for r in cobertura.reglas
                                     if r.motivo]},
        # Un mapeo que solo sostiene el vocabulario es el que un humano
        # confirma una vez; despues la plantilla ya no pregunta.
        pendiente_de_confirmacion=not mapeo.orientacion_verificada,
    )


def procesar_balanza(pdf: str | Path, *, tenant_id: str | None = None,
                     almacen: AlmacenPlantillas | None = None,
                     paginas_muestra: int = 3,
                     estrategia: str | None = None) -> Resultado:
    """Procesa una balanza, reutilizando la plantilla del tenant si la hay."""
    documento, estrategia = extraer(pdf, estrategia=estrategia)
    muestra = _muestra(documento, paginas_muestra)
    layout: Layout | None = detectar_layout(muestra)
    huella = huella_de(layout, _cuentas_de(muestra))

    plantilla = None
    if almacen is not None and tenant_id and huella is not None:
        plantilla = almacen.buscar(tenant_id, huella.valor)

    parser = BalanzaParser(paginas_muestra=paginas_muestra)
    if plantilla is not None:
        if plantilla.estrategia != estrategia:
            documento, estrategia = extraer(pdf, estrategia=plantilla.estrategia)
        balanza = parser.parse(documento, layout=layout,
                               mapeo=_mapeo_de(plantilla))
        reglas = _reglas_de(plantilla)
        _LOG.info("plantilla reutilizada: %s", plantilla.huella)
    else:
        balanza = parser.parse(documento, layout=layout)
        reglas = ReglasBalanza.para(balanza)

    cobertura = evaluar_balanza(balanza, reglas=reglas)

    aprendida = plantilla
    if (plantilla is None and almacen is not None and tenant_id
            and huella is not None and not cobertura.fallan):
        aprendida = construir_plantilla(tenant_id, huella, estrategia, balanza,
                                        cobertura, reglas)
        almacen.guardar(aprendida)

    return Resultado(balanza=balanza, cobertura=cobertura, estrategia=estrategia,
                     huella=huella, plantilla=aprendida,
                     reutilizada=plantilla is not None)


def procesar_auxiliar(pdf: str | Path, *, tenant_id: str | None = None,
                      almacen: AlmacenPlantillas | None = None,
                      page_numbers: Sequence[int] | None = None,
                      paginas_muestra: int = 3,
                      estrategia: str | None = None) -> ResultadoAuxiliar:
    """Procesa un auxiliar reutilizando la plantilla del tenant si la hay."""
    documento, estrategia = extraer(pdf, estrategia=estrategia,
                                    page_numbers=page_numbers)
    parser = AuxiliarParser(paginas_muestra=paginas_muestra)
    muestra = _muestra(documento, paginas_muestra)
    layout = parser._layout(muestra)
    huella = huella_de(layout, _cuentas_de(muestra))

    plantilla = None
    if almacen is not None and tenant_id and huella is not None:
        plantilla = almacen.buscar(tenant_id, huella.valor)

    auxiliar = parser.parse(
        documento, layout=layout,
        mapeo=_mapeo_de(plantilla) if plantilla is not None else None)
    cobertura = evaluar_auxiliar(auxiliar)

    aprendida = plantilla
    if (plantilla is None and almacen is not None and tenant_id
            and huella is not None and not cobertura.fallan):
        aprendida = _plantilla_de_auxiliar(tenant_id, huella, estrategia,
                                           auxiliar, cobertura)
        almacen.guardar(aprendida)

    return ResultadoAuxiliar(auxiliar=auxiliar, cobertura=cobertura,
                             estrategia=estrategia, huella=huella,
                             plantilla=aprendida,
                             reutilizada=plantilla is not None)


def _plantilla_de_auxiliar(tenant_id: str, huella: Huella, estrategia: str,
                           auxiliar: Auxiliar, cobertura: Cobertura) -> Plantilla:
    mapeo = auxiliar.mapeo
    esquema = inferir_esquema([f.cuenta for f in auxiliar.filas])
    return Plantilla(
        tenant_id=tenant_id, huella=huella.valor, tipo="auxiliar",
        estrategia=estrategia, mapeo=dict(mapeo.campos), forma=mapeo.forma,
        verificado_por=mapeo.verificado_por,
        orientacion_verificada=mapeo.orientacion_verificada,
        filas_afectadas=mapeo.filas_afectadas,
        esquema={"separador": esquema.separador, "anchos": list(esquema.anchos),
                 "marcador": list(esquema.marcador) if esquema.marcador else None,
                 "largo": esquema.largo},
        reglas={"tolerancia": "0.01", "subconjunto_totales": "nivel_1",
                "exige_partida_doble": False},
        cobertura={"cuadran": cobertura.cuadran, "fallan": cobertura.fallan,
                   "no_verificables": cobertura.no_verificables,
                   "sin_comprobar": [r.regla for r in cobertura.reglas if r.motivo]},
        pendiente_de_confirmacion=not mapeo.orientacion_verificada,
    )


@dataclass(frozen=True)
class ResultadoPolizas:
    libro: LibroDiario
    cobertura: Cobertura
    estrategia: str
    huella: Huella | None
    plantilla: Plantilla | None
    reutilizada: bool


def procesar_polizas(pdf: str | Path, *, tenant_id: str | None = None,
                     almacen: AlmacenPlantillas | None = None,
                     page_numbers: Sequence[int] | None = None,
                     paginas_muestra: int = 3,
                     estrategia: str | None = None) -> ResultadoPolizas:
    """Procesa un libro diario reutilizando la plantilla del tenant si la hay."""
    documento, estrategia = extraer(pdf, estrategia=estrategia,
                                    page_numbers=page_numbers)
    muestra = _muestra(documento, paginas_muestra)
    layout = detectar_layout(muestra)
    huella = huella_de(layout, _cuentas_de(muestra))

    plantilla = None
    if almacen is not None and tenant_id and huella is not None:
        plantilla = almacen.buscar(tenant_id, huella.valor)

    libro = PolizasParser(paginas_muestra=paginas_muestra).parse(
        documento, layout=layout,
        mapeo=_mapeo_de(plantilla) if plantilla is not None else None)
    cobertura = evaluar_polizas(libro)

    aprendida = plantilla
    if (plantilla is None and almacen is not None and tenant_id
            and huella is not None and not cobertura.fallan):
        aprendida = _plantilla_simple(tenant_id, huella, estrategia, "polizas",
                                      libro.mapeo, cobertura,
                                      [m.cuenta for m in libro.movimientos])
        almacen.guardar(aprendida)

    return ResultadoPolizas(libro=libro, cobertura=cobertura,
                            estrategia=estrategia, huella=huella,
                            plantilla=aprendida,
                            reutilizada=plantilla is not None)


def _plantilla_simple(tenant_id: str, huella: Huella, estrategia: str, tipo: str,
                      mapeo: Mapeo, cobertura: Cobertura,
                      cuentas: Sequence[str]) -> Plantilla:
    esquema = inferir_esquema(list(cuentas))
    return Plantilla(
        tenant_id=tenant_id, huella=huella.valor, tipo=tipo,
        estrategia=estrategia, mapeo=dict(mapeo.campos), forma=mapeo.forma,
        verificado_por=mapeo.verificado_por,
        orientacion_verificada=mapeo.orientacion_verificada,
        filas_afectadas=mapeo.filas_afectadas,
        esquema={"separador": esquema.separador, "anchos": list(esquema.anchos),
                 "marcador": list(esquema.marcador) if esquema.marcador else None,
                 "largo": esquema.largo},
        reglas={"tolerancia": "0.01", "subconjunto_totales": "nivel_1",
                "exige_partida_doble": True},
        cobertura={"cuadran": cobertura.cuadran, "fallan": cobertura.fallan,
                   "no_verificables": cobertura.no_verificables,
                   "sin_comprobar": [r.regla for r in cobertura.reglas if r.motivo]},
        pendiente_de_confirmacion=not mapeo.orientacion_verificada,
    )


# Lo que este tipo de documento NO cubre. Se declara en la plantilla en vez
# de suponerse general. Fase 7d: ya son seis formatos medidos, asi que lo
# que queda fuera esta acotado y es concreto.
_SIN_CUBRIR_EDOCTA = (
    "seis formatos medidos: el vocabulario del encabezado y las etiquetas de "
    "saldo son tablas de sinonimos, y un banco que nombre distinto sus "
    "columnas necesita agregarlos antes de leerse",
    "la union de continuaciones usa el separador del formato: la geometria no "
    "distingue un documento que parte palabras al envolver de uno que envuelve "
    "por palabra entera, y elegir mal pega o separa dentro de la descripcion",
    "cuando el documento solo imprime el dia, la fecha se deriva del periodo y "
    "solo si el periodo no cruza de mes",
    "con dos o mas cuentas los depositos y retiros por cuenta se leen solo si "
    "el documento los desglosa; el total del documento no se reparte",
)


@dataclass(frozen=True)
class ResultadoEstadoCuenta:
    estado: EstadoCuenta
    cobertura: Cobertura
    estrategia: str
    huella: Huella | None
    plantilla: Plantilla | None
    reutilizada: bool


def procesar_estado_cuenta(pdf: str | Path, *, tenant_id: str | None = None,
                           almacen: AlmacenPlantillas | None = None,
                           page_numbers: Sequence[int] | None = None,
                           paginas_muestra: int = 2,
                           estrategia: str | None = None) -> ResultadoEstadoCuenta:
    """Procesa un estado de cuenta reutilizando la plantilla del tenant."""
    documento, estrategia = extraer(pdf, estrategia=estrategia,
                                    page_numbers=page_numbers)
    # La huella sale de la fila de encabezado de la tabla de movimientos, no
    # del clustering de columnas: es lo que distingue (banco, tipo de
    # reporte), que es el eje real de la plantilla. Dos reportes del mismo
    # banco con estructuras distintas no pueden compartir plantilla.
    layout = detectar_cabecera(_muestra(documento, paginas_muestra + 1))
    huella = huella_de(layout)

    plantilla = None
    if almacen is not None and tenant_id and huella is not None:
        plantilla = almacen.buscar(tenant_id, huella.valor)

    estado = EstadoCuentaParser(paginas_muestra=paginas_muestra).parse(
        documento, layout=layout,
        mapeo=_mapeo_de(plantilla) if plantilla is not None else None)
    cobertura = evaluar_estado_cuenta(estado)

    aprendida = plantilla
    if (plantilla is None and almacen is not None and tenant_id
            and huella is not None and not cobertura.fallan):
        aprendida = _plantilla_simple(tenant_id, huella, estrategia,
                                      "estado_cuenta", estado.mapeo, cobertura, [])
        aprendida = replace(
            aprendida,
            cobertura={**aprendida.cobertura,
                       "sin_cubrir": list(_SIN_CUBRIR_EDOCTA)})
        almacen.guardar(aprendida)

    return ResultadoEstadoCuenta(estado=estado, cobertura=cobertura,
                                 estrategia=estrategia, huella=huella,
                                 plantilla=aprendida,
                                 reutilizada=plantilla is not None)


@dataclass(frozen=True)
class ResultadoMayor:
    mayor: Mayor
    cobertura: Cobertura
    estrategia: str
    huella: Huella | None
    plantilla: Plantilla | None
    reutilizada: bool


def procesar_mayor(pdf: str | Path, *, tenant_id: str | None = None,
                   almacen: AlmacenPlantillas | None = None,
                   page_numbers: Sequence[int] | None = None,
                   paginas_muestra: int = 2, estrategia: str | None = None,
                   balanza: Balanza | None = None) -> ResultadoMayor:
    """Procesa un libro mayor. 'balanza' habilita el cruce entre documentos.

    Quien orquesta decide que balanza corresponde: el parser nunca va a
    buscar archivos por su cuenta.
    """
    documento, estrategia = extraer(pdf, estrategia=estrategia,
                                    page_numbers=page_numbers)
    muestra = _muestra(documento, paginas_muestra)
    layout = detectar_layout(muestra)
    huella = huella_de(layout, _cuentas_de(muestra))

    plantilla = None
    if almacen is not None and tenant_id and huella is not None:
        plantilla = almacen.buscar(tenant_id, huella.valor)

    mayor = MayorParser(paginas_muestra=paginas_muestra).parse(
        documento, layout=layout,
        mapeo=_mapeo_de(plantilla) if plantilla is not None else None)
    cobertura = evaluar_mayor(mayor, balanza=balanza)

    aprendida = plantilla
    if (plantilla is None and almacen is not None and tenant_id
            and huella is not None and not cobertura.fallan):
        aprendida = _plantilla_simple(tenant_id, huella, estrategia, "mayor",
                                      mayor.mapeo, cobertura,
                                      [c.cuenta for c in mayor.cuentas])
        almacen.guardar(aprendida)

    return ResultadoMayor(mayor=mayor, cobertura=cobertura,
                          estrategia=estrategia, huella=huella,
                          plantilla=aprendida,
                          reutilizada=plantilla is not None)
