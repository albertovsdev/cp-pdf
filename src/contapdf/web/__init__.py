"""Capa web: subir un PDF, procesarlo, descargar el Excel.

Fase 8a. Una interfaz minima sobre el nucleo que YA existe. No agrega
capacidades de extraccion ni de validacion: todo lo que hace es llamar a
`cli.procesar_documento()`, la misma puerta que usa la linea de comandos, y
presentar lo que devuelve.

NO importa parsers, reglas ni exportadores. Si la web pudiera alcanzarlos
directo acabaria repitiendo la orquestacion, y las dos versiones se
separarian en la primera correccion; un test lee los imports y lo impide.

En la 8b se agrego lo que 8a dejo fuera a proposito: cola persistente en
SQLite (`cola.py`), un worker secuencial y separacion por despacho. Sigue
SIN autenticacion: el despacho llega por la ruta, asi que separa lo de cada
quien pero no impide que alguien escriba el nombre de otro despacho.
"""

from contapdf.web.app import crear_app

# Tupla y no lista: un test de arquitectura prohibe estado mutable a
# nivel de modulo bajo src/contapdf/.
__all__ = ("crear_app",)
