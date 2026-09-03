"""Capa web: subir un PDF, procesarlo, descargar el Excel.

Fase 8a. Una interfaz minima sobre el nucleo que YA existe. No agrega
capacidades de extraccion ni de validacion: todo lo que hace es llamar a
`cli.procesar_documento()`, la misma puerta que usa la linea de comandos, y
presentar lo que devuelve.

NO importa parsers, reglas ni exportadores. Si la web pudiera alcanzarlos
directo acabaria repitiendo la orquestacion, y las dos versiones se
separarian en la primera correccion; un test lee los imports y lo impide.

Alcance de 8a, a proposito: un documento a la vez, sincrono, un usuario, en
la maquina de desarrollo. Sin cola, sin worker, sin autenticacion y sin
aislamiento por tenant -- eso es 8b.
"""

from contapdf.web.app import crear_app

# Tupla y no lista: un test de arquitectura prohibe estado mutable a
# nivel de modulo bajo src/contapdf/.
__all__ = ("crear_app",)
