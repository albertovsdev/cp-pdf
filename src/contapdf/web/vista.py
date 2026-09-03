"""Del `ResultadoDocumento` a algo que se pueda guardar y volver a mostrar.

La cola persiste en SQLite, asi que un trabajo terminado tiene que poder
ense~narse despues de un reinicio. Eso obliga a serializar la cobertura, y
serializarla obliga a fijar QUE se ense~na.

Se conserva todo lo que la fase 7f y la 7h hicieron visible, porque perderlo
en la traduccion seria deshacerlas en silencio:

- las dos cifras por regla (`evaluados` de `aplicables`),
- las exactas partidas en impresas y recalculadas,
- el motivo de lo que no se pudo evaluar,
- el resumen completo de la cobertura, con su aviso de circularidad.

Los importes se guardan como TEXTO, no como float: `Decimal('0.1')` y
`float(0.1)` no son el mismo numero y este proyecto no mete dinero en un
float ni de paso por una plantilla.
"""

from __future__ import annotations


def como_diccionario(resultado) -> dict:
    """Todo lo que la pagina necesita, en tipos que JSON entiende."""
    cobertura = resultado.cobertura
    return {
        "tipo": resultado.tipo,
        "paginas": resultado.paginas,
        "estrategia": resultado.estrategia,
        "motivo_estrategia": resultado.motivo_estrategia,
        "resumen_cobertura": cobertura.resumen(),
        "fallan": cobertura.fallan,
        "cuadran": cobertura.cuadran,
        "no_verificables": cobertura.no_verificables,
        "resumen": [list(par) for par in resultado.resumen],
        "reglas": [_regla(r) for r in cobertura.reglas],
        "discrepancias": [_discrepancia(d) for d in cobertura.discrepancias[:50]],
        "total_discrepancias": len(cobertura.discrepancias),
        "plantilla": _plantilla(resultado.plantilla, resultado.reutilizada),
    }


def _regla(regla) -> dict:
    return {
        "regla": regla.regla,
        "estado": regla.estado,
        "aplicables": regla.aplicables,
        "evaluados": regla.evaluados,
        "exactas": regla.exactas,
        "exactas_impresas": regla.exactas_impresas,
        "exactas_recalculadas": regla.exactas_recalculadas,
        "con_tolerancia": len(regla.con_tolerancia),
        "discrepancias": len(regla.discrepancias),
        "motivo": regla.motivo,
        # La linea que el CLI imprime, tal cual: si la pagina la recompusiera
        # por su cuenta, las dos versiones se separarian.
        "linea": regla.resumen(),
    }


def _discrepancia(d) -> dict:
    # Hay reglas que cruzan identidades y no importes; ahi las dos cifras
    # vienen en cero y ense~nar «0.00 contra 0.00» haria pensar que el
    # documento dice cero.
    numerica = d.esperado != d.obtenido
    return {
        "fila": d.fila,
        "regla": d.regla,
        "numerica": numerica,
        "esperado": f"{d.esperado:,.2f}" if numerica else "",
        "obtenido": f"{d.obtenido:,.2f}" if numerica else "",
    }


def _plantilla(plantilla, reutilizada: bool) -> dict | None:
    if plantilla is None:
        return None
    return {
        "huella": plantilla.huella,
        "reutilizada": reutilizada,
        "pendiente": plantilla.pendiente_de_confirmacion,
        "pendientes": [
            {"campo": p["campo"],
             "consecuencia": p["consecuencia"],
             "se_apoya_en": p["se_apoya_en"],
             "sin_propuesta": p["se_propone"] is None}
            for p in plantilla.pendientes()
        ],
    }
