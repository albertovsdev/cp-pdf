"""La cola de trabajos: sobrevive al reinicio y aisla por despacho.

Fase 8b. SERVIDORSIST se apaga a las 21:00, asi que un trabajo a medias no
es una hipotesis. Hasta la 8a el registro vivia en memoria: al reiniciar,
el trabajo desaparecia y la pagina daba 404, que no distingue «nunca
existio» de «se murio a medias».

SQLite y no ficheros JSON: la actualizacion de estado tiene que ser
transaccional -- el worker escribe mientras las peticiones leen -- y
consultar por tenant tiene que ser una operacion, no recorrer un
directorio. Ademas viene en la stdlib, y PLAN 0 pide no sumar dependencias
que no hagan falta.

Un trabajo a la vez, como manda PLAN 6: la maquina objetivo tiene 8 GB
compartidos con Apache y MySQL, y el pico medido del pipeline es 543 MB.
"""

from __future__ import annotations

import time

import pytest

from contapdf.web.cola import (
    CON_DISCREPANCIAS,
    EN_COLA,
    ERROR,
    INTERRUMPIDO,
    LISTO,
    NO_RECONOCIDO,
    PROCESANDO,
    Cola,
)


@pytest.fixture()
def cola(tmp_path):
    return Cola(tmp_path / "trabajos.db", raiz=tmp_path)


def _encolar(cola, tenant="despacho-a", tipo="balanza", archivo="x.pdf"):
    return cola.encolar(tenant=tenant, tipo=tipo, archivo=archivo)


# --- Lo basico ----------------------------------------------------------
def test_un_trabajo_encolado_arranca_en_cola(cola):
    trabajo = _encolar(cola)
    assert trabajo.estado == EN_COLA
    assert trabajo.directorio.is_dir()
    assert cola.buscar(trabajo.identificador, tenant="despacho-a") is not None


def test_el_identificador_no_es_adivinable(cola):
    uno = _encolar(cola).identificador
    otro = _encolar(cola).identificador
    assert uno != otro
    assert len(uno) >= 24


def test_los_estados_recorren_el_ciclo(cola):
    trabajo = _encolar(cola)
    cola.marcar_procesando(trabajo.identificador)
    assert cola.buscar(trabajo.identificador, tenant="despacho-a").estado == PROCESANDO
    cola.marcar_terminado(trabajo.identificador, estado=LISTO, resumen={"a": 1})
    recuperado = cola.buscar(trabajo.identificador, tenant="despacho-a")
    assert recuperado.estado == LISTO
    assert recuperado.resumen == {"a": 1}


# --- Criterio 1: sobrevive al reinicio ----------------------------------
def test_un_trabajo_sobrevive_a_reabrir_la_cola(tmp_path):
    ruta = tmp_path / "trabajos.db"
    primera = Cola(ruta, raiz=tmp_path)
    trabajo = primera.encolar(tenant="t", tipo="balanza", archivo="x.pdf")
    primera.cerrar()

    segunda = Cola(ruta, raiz=tmp_path)
    recuperado = segunda.buscar(trabajo.identificador, tenant="t")
    assert recuperado is not None
    assert recuperado.archivo == "x.pdf"


def test_lo_que_estaba_procesando_al_reiniciar_dice_que_se_interrumpio(tmp_path):
    """Nunca un 404: «se interrumpio» y «nunca existio» no son lo mismo."""
    ruta = tmp_path / "trabajos.db"
    primera = Cola(ruta, raiz=tmp_path)
    corriendo = primera.encolar(tenant="t", tipo="balanza", archivo="a.pdf")
    esperando = primera.encolar(tenant="t", tipo="balanza", archivo="b.pdf")
    primera.marcar_procesando(corriendo.identificador)
    primera.cerrar()

    segunda = Cola(ruta, raiz=tmp_path)      # el arranque hace la limpieza
    assert segunda.buscar(corriendo.identificador, tenant="t").estado == INTERRUMPIDO
    # El que solo estaba esperando sigue esperando: no se perdio nada.
    assert segunda.buscar(esperando.identificador, tenant="t").estado == EN_COLA


def test_un_trabajo_interrumpido_dice_por_que(tmp_path):
    ruta = tmp_path / "trabajos.db"
    primera = Cola(ruta, raiz=tmp_path)
    trabajo = primera.encolar(tenant="t", tipo="balanza", archivo="a.pdf")
    primera.marcar_procesando(trabajo.identificador)
    primera.cerrar()

    segunda = Cola(ruta, raiz=tmp_path)
    recuperado = segunda.buscar(trabajo.identificador, tenant="t")
    assert recuperado.mensaje
    assert "interrump" in recuperado.mensaje.lower()


# --- Criterio 2: uno a la vez, con posicion visible ---------------------
def test_solo_se_entrega_un_trabajo_a_la_vez(cola):
    uno = _encolar(cola, archivo="1.pdf")
    dos = _encolar(cola, archivo="2.pdf")
    tomado = cola.tomar_siguiente()
    assert tomado.identificador == uno.identificador
    # Mientras uno esta en curso, no se entrega otro.
    assert cola.tomar_siguiente() is None
    cola.marcar_terminado(uno.identificador, estado=LISTO, resumen={})
    assert cola.tomar_siguiente().identificador == dos.identificador


def test_la_posicion_en_cola_es_visible(cola):
    uno = _encolar(cola, archivo="1.pdf")
    dos = _encolar(cola, archivo="2.pdf")
    tres = _encolar(cola, archivo="3.pdf")
    assert cola.posicion(uno.identificador) == 1
    assert cola.posicion(dos.identificador) == 2
    assert cola.posicion(tres.identificador) == 3
    cola.tomar_siguiente()
    assert cola.posicion(uno.identificador) == 0      # ya no espera
    assert cola.posicion(dos.identificador) == 1


def test_se_atienden_en_orden_de_llegada(cola):
    ids = [_encolar(cola, archivo=f"{i}.pdf").identificador for i in range(3)]
    salidos = []
    for _ in range(3):
        t = cola.tomar_siguiente()
        salidos.append(t.identificador)
        cola.marcar_terminado(t.identificador, estado=LISTO, resumen={})
    assert salidos == ids


# --- Criterio 3: aislamiento por tenant ---------------------------------
def test_un_tenant_no_ve_el_trabajo_de_otro_ni_con_el_id(cola):
    ajeno = _encolar(cola, tenant="despacho-a")
    assert cola.buscar(ajeno.identificador, tenant="despacho-a") is not None
    assert cola.buscar(ajeno.identificador, tenant="despacho-b") is None


def test_listar_solo_devuelve_lo_propio(cola):
    _encolar(cola, tenant="a", archivo="1.pdf")
    _encolar(cola, tenant="a", archivo="2.pdf")
    _encolar(cola, tenant="b", archivo="3.pdf")
    assert len(cola.listar("a")) == 2
    assert len(cola.listar("b")) == 1
    assert {t.archivo for t in cola.listar("b")} == {"3.pdf"}


def test_el_directorio_de_un_trabajo_cuelga_de_su_tenant(cola):
    uno = _encolar(cola, tenant="despacho-a")
    otro = _encolar(cola, tenant="despacho-b")
    assert "despacho-a" in uno.directorio.parts
    assert "despacho-b" in otro.directorio.parts
    assert not str(uno.directorio).startswith(str(otro.directorio))


@pytest.mark.parametrize("malo", ["../otro", "a/b", "", ".", "con espacio",
                                  "a" * 100])
def test_un_tenant_con_nombre_peligroso_se_rechaza(cola, malo):
    """La ruta se deriva del ID: un '..' se saldria del directorio."""
    with pytest.raises(ValueError):
        cola.encolar(tenant=malo, tipo="balanza", archivo="x.pdf")


# --- Criterio 5: los tres estados finales se distinguen ----------------
def test_los_estados_finales_no_se_confunden(cola):
    casos = ((LISTO, "listo"), (CON_DISCREPANCIAS, "con_discrepancias"),
             (NO_RECONOCIDO, "no_reconocido"), (ERROR, "error"))
    for estado, nombre in casos:
        trabajo = _encolar(cola, archivo=f"{nombre}.pdf")
        cola.marcar_procesando(trabajo.identificador)
        cola.marcar_terminado(trabajo.identificador, estado=estado, resumen={})
        assert cola.buscar(trabajo.identificador,
                           tenant="despacho-a").estado == estado
    assert len({LISTO, CON_DISCREPANCIAS, NO_RECONOCIDO, ERROR}) == 4


def test_un_trabajo_terminado_ya_no_se_toma(cola):
    trabajo = _encolar(cola)
    cola.marcar_procesando(trabajo.identificador)
    cola.marcar_terminado(trabajo.identificador, estado=NO_RECONOCIDO, resumen={})
    assert cola.tomar_siguiente() is None


# --- Criterio 4: el barrido -------------------------------------------
def test_el_barrido_borra_lo_viejo_y_su_directorio(cola):
    viejo = _encolar(cola, archivo="viejo.pdf")
    (viejo.directorio / "salida.xlsx").write_bytes(b"PK")
    cola.marcar_terminado(viejo.identificador, estado=LISTO, resumen={})
    cola.envejecer(viejo.identificador, segundos=31 * 60)   # para el test

    nuevo = _encolar(cola, archivo="nuevo.pdf")
    barridos = cola.barrer()

    assert barridos == 1
    assert not viejo.directorio.exists()
    assert cola.buscar(viejo.identificador, tenant="despacho-a") is None
    assert cola.buscar(nuevo.identificador, tenant="despacho-a") is not None


def test_el_barrido_no_toca_lo_que_esta_en_curso(cola):
    trabajo = _encolar(cola)
    cola.marcar_procesando(trabajo.identificador)
    cola.envejecer(trabajo.identificador, segundos=31 * 60)
    assert cola.barrer() == 0
    assert cola.buscar(trabajo.identificador, tenant="despacho-a") is not None


def test_el_barrido_limpia_directorios_sin_trabajo(cola, tmp_path):
    """Si el proceso murio antes de registrar, el PDF no puede quedarse."""
    huerfano = cola.raiz / "despacho-a" / "trabajo-suelto"
    huerfano.mkdir(parents=True)
    (huerfano / "entrada.pdf").write_bytes(b"%PDF-1.4 datos del cliente")
    import os
    viejo = time.time() - 31 * 60
    os.utime(huerfano, (viejo, viejo))

    cola.barrer()
    assert not huerfano.exists()


def test_la_edad_maxima_son_treinta_minutos():
    from contapdf.web.cola import EDAD_MAXIMA

    assert EDAD_MAXIMA == 30 * 60
