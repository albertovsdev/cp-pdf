"""Cola de trabajos persistente, con aislamiento por despacho.

SQLite y no ficheros JSON, por tres razones medidas contra el problema:

1. **Transaccional.** El worker escribe el estado mientras las peticiones
   lo leen. Con ficheros habria que inventar bloqueo y una escritura a
   medias dejaria un JSON roto.
2. **Consultar por tenant es una operacion**, no recorrer un directorio.
3. **Viene en la stdlib.** PLAN 0 pide no sumar dependencias que no hagan
   falta, y aqui no hace falta ninguna.

Un trabajo a la vez (PLAN 6): la maquina objetivo tiene 8 GB compartidos
con Apache y MySQL y el pico medido del pipeline es 543 MB. `tomar_siguiente`
no entrega nada mientras haya algo en curso.

**El estado 'interrumpido' existe porque SERVIDORSIST se apaga a las 21:00.**
Un trabajo que estaba corriendo cuando el proceso murio no desaparece: al
arrancar se marca, y la pagina puede decir la verdad en vez de dar un 404
que confunde «nunca existio» con «se murio a medias».
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)

EN_COLA = "en_cola"
PROCESANDO = "procesando"
LISTO = "listo"
CON_DISCREPANCIAS = "con_discrepancias"
NO_RECONOCIDO = "no_reconocido"
ERROR = "error"
INTERRUMPIDO = "interrumpido"

#: Estados de los que ya no se sale. Un trabajo asi no vuelve a la cola.
TERMINALES = (LISTO, CON_DISCREPANCIAS, NO_RECONOCIDO, ERROR, INTERRUMPIDO)
#: Los que produjeron un Excel descargable.
CON_ENTREGA = (LISTO, CON_DISCREPANCIAS)

# Media hora y fuera, lo descargue alguien o no: son documentos contables de
# clientes y esto corre en un servidor que nadie reinicia en semanas.
EDAD_MAXIMA = 30 * 60

# El ID del tenant se convierte en nombre de directorio, asi que se valida
# igual que en templates/store.py: sin '..', sin barras, sin espacios.
_RE_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS trabajos (
    id           TEXT PRIMARY KEY,
    tenant       TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    archivo      TEXT NOT NULL,
    estado       TEXT NOT NULL,
    creado       REAL NOT NULL,
    directorio   TEXT NOT NULL,
    xlsx         TEXT,
    nombre_xlsx  TEXT,
    mensaje      TEXT NOT NULL DEFAULT '',
    resumen      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS trabajos_por_tenant ON trabajos (tenant, creado);
CREATE INDEX IF NOT EXISTS trabajos_por_estado ON trabajos (estado, creado);
"""


class TenantInvalido(ValueError):
    """El identificador de despacho no sirve como nombre de directorio."""


@dataclass(frozen=True)
class Trabajo:
    identificador: str
    tenant: str
    tipo: str
    archivo: str
    estado: str
    creado: float
    directorio: Path
    xlsx: Path | None = None
    nombre_xlsx: str = ""
    mensaje: str = ""
    resumen: dict = None  # type: ignore[assignment]

    @property
    def transcurrido(self) -> float:
        return time.time() - self.creado

    @property
    def reloj(self) -> str:
        segundos = int(self.transcurrido)
        return f"{segundos // 60}:{segundos % 60:02d}"

    @property
    def terminado(self) -> bool:
        return self.estado in TERMINALES

    @property
    def entrega(self) -> bool:
        return self.estado in CON_ENTREGA


def validar_tenant(tenant: str) -> str:
    if not _RE_TENANT.match(tenant or ""):
        raise TenantInvalido(
            f"identificador de despacho invalido: {tenant!r}; solo letras, "
            "digitos, guion y guion bajo")
    return tenant


class Cola:
    """Los trabajos, en SQLite. Segura entre hilos."""

    def __init__(self, base: Path | str, *, raiz: Path | str | None = None) -> None:
        self.base = Path(base)
        self.raiz = Path(raiz) if raiz is not None else self.base.parent
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self.raiz.mkdir(parents=True, exist_ok=True)
        self._candado = threading.Lock()
        self._cx = sqlite3.connect(self.base, check_same_thread=False)
        self._cx.row_factory = sqlite3.Row
        with self._cx:
            self._cx.executescript(_ESQUEMA)
        self._recuperar()

    # --- arranque -------------------------------------------------------
    def _recuperar(self) -> None:
        """Lo que quedo 'procesando' no sobrevivio al reinicio."""
        with self._candado, self._cx:
            filas = self._cx.execute(
                "SELECT id FROM trabajos WHERE estado = ?", (PROCESANDO,)
            ).fetchall()
            if filas:
                self._cx.execute(
                    "UPDATE trabajos SET estado = ?, mensaje = ? "
                    "WHERE estado = ?",
                    (INTERRUMPIDO,
                     "El servidor se detuvo y el documento quedo "
                     "interrumpido a medias. No se perdio nada del original: "
                     "vuelve a subirlo y se procesa de nuevo.",
                     PROCESANDO))
        if filas:
            _LOG.warning("%s trabajo(s) quedaron interrumpidos por un "
                         "reinicio", len(filas))

    def cerrar(self) -> None:
        self._cx.close()

    # --- escritura ------------------------------------------------------
    def encolar(self, *, tenant: str, tipo: str, archivo: str) -> Trabajo:
        validar_tenant(tenant)
        identificador = uuid.uuid4().hex
        directorio = self.raiz / tenant / f"trabajo-{identificador}"
        directorio.mkdir(parents=True)
        creado = time.time()
        with self._candado, self._cx:
            self._cx.execute(
                "INSERT INTO trabajos (id, tenant, tipo, archivo, estado, "
                "creado, directorio) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (identificador, tenant, tipo, archivo, EN_COLA, creado,
                 str(directorio)))
        return Trabajo(identificador=identificador, tenant=tenant, tipo=tipo,
                       archivo=archivo, estado=EN_COLA, creado=creado,
                       directorio=directorio, resumen={})

    def marcar_procesando(self, identificador: str) -> None:
        with self._candado, self._cx:
            self._cx.execute("UPDATE trabajos SET estado = ? WHERE id = ?",
                             (PROCESANDO, identificador))

    def marcar_terminado(self, identificador: str, *, estado: str,
                         resumen: dict, mensaje: str = "",
                         xlsx: Path | None = None,
                         nombre_xlsx: str = "") -> None:
        if estado not in TERMINALES:
            raise ValueError(f"estado final desconocido: {estado!r}")
        with self._candado, self._cx:
            self._cx.execute(
                "UPDATE trabajos SET estado = ?, resumen = ?, mensaje = ?, "
                "xlsx = ?, nombre_xlsx = ? WHERE id = ?",
                (estado, json.dumps(resumen, ensure_ascii=False), mensaje,
                 str(xlsx) if xlsx else None, nombre_xlsx, identificador))

    def tomar_siguiente(self) -> Trabajo | None:
        """El proximo trabajo, o None si hay uno en curso o la cola esta vacia.

        Uno a la vez: dos pipelines a 543 MB en una maquina de 8 GB que
        comparte con Apache y MySQL dejan el servidor inutilizable.
        """
        with self._candado, self._cx:
            en_curso = self._cx.execute(
                "SELECT 1 FROM trabajos WHERE estado = ? LIMIT 1",
                (PROCESANDO,)).fetchone()
            if en_curso:
                return None
            fila = self._cx.execute(
                "SELECT * FROM trabajos WHERE estado = ? "
                "ORDER BY creado, id LIMIT 1", (EN_COLA,)).fetchone()
            if fila is None:
                return None
            self._cx.execute("UPDATE trabajos SET estado = ? WHERE id = ?",
                             (PROCESANDO, fila["id"]))
        return _desde_fila(fila)

    # --- lectura --------------------------------------------------------
    def buscar(self, identificador: str, *, tenant: str) -> Trabajo | None:
        """El trabajo, SOLO si es de ese despacho.

        El tenant va en el WHERE, no en un `if` posterior: adivinar el id de
        otro despacho no sirve de nada.
        """
        with self._candado:
            fila = self._cx.execute(
                "SELECT * FROM trabajos WHERE id = ? AND tenant = ?",
                (identificador, tenant)).fetchone()
        return _desde_fila(fila) if fila else None

    def listar(self, tenant: str, *, limite: int = 50) -> list[Trabajo]:
        with self._candado:
            filas = self._cx.execute(
                "SELECT * FROM trabajos WHERE tenant = ? "
                "ORDER BY creado DESC LIMIT ?", (tenant, limite)).fetchall()
        return [_desde_fila(f) for f in filas]

    def hay_pendientes(self) -> bool:
        """Queda algo por atender (en cola o a medio procesar)."""
        with self._candado:
            fila = self._cx.execute(
                "SELECT 1 FROM trabajos WHERE estado IN (?, ?) LIMIT 1",
                (EN_COLA, PROCESANDO)).fetchone()
        return fila is not None

    def posicion(self, identificador: str) -> int:
        """Cuantos hay por delante, contandose. 0 si ya no espera."""
        with self._candado:
            fila = self._cx.execute(
                "SELECT estado, creado FROM trabajos WHERE id = ?",
                (identificador,)).fetchone()
            if fila is None or fila["estado"] != EN_COLA:
                return 0
            delante = self._cx.execute(
                "SELECT COUNT(*) FROM trabajos WHERE estado = ? AND creado < ?",
                (EN_COLA, fila["creado"])).fetchone()[0]
        return delante + 1

    # --- mantenimiento --------------------------------------------------
    def barrer(self, *, edad: float = EDAD_MAXIMA) -> int:
        """Borra los trabajos terminados que pasen de la edad, y su disco.

        Lo que esta en curso no se toca: un documento de cuatro minutos no
        puede desaparecerle al usuario a mitad de camino.
        """
        limite = time.time() - edad
        with self._candado, self._cx:
            filas = self._cx.execute(
                "SELECT id, directorio FROM trabajos "
                "WHERE creado < ? AND estado != ?", (limite, PROCESANDO)
            ).fetchall()
            for fila in filas:
                _borrar(Path(fila["directorio"]))
                self._cx.execute("DELETE FROM trabajos WHERE id = ?",
                                 (fila["id"],))
            vivos = {Path(f["directorio"]) for f in self._cx.execute(
                "SELECT directorio FROM trabajos").fetchall()}
        # Directorios sin trabajo: si el proceso murio antes de registrar, el
        # PDF del cliente no puede quedarse ahi para siempre.
        for tenant in self.raiz.iterdir() if self.raiz.is_dir() else ():
            if not tenant.is_dir():
                continue
            for directorio in tenant.glob("trabajo-*"):
                if directorio in vivos:
                    continue
                try:
                    if directorio.stat().st_mtime < limite:
                        _borrar(directorio)
                except OSError:
                    continue
        if filas:
            _LOG.info("barridos %s trabajo(s) de mas de %s min",
                      len(filas), int(edad // 60))
        return len(filas)

    def olvidar(self, identificador: str, *, tenant: str) -> bool:
        """Borra un trabajo y su disco antes de tiempo, si es de ese despacho.

        La descarga es de un solo uso (decision de la 8a): en cuanto el Excel
        sale hacia el navegador, el documento del cliente deja de existir en
        el servidor. El `tenant` va en el WHERE por lo mismo que en `buscar`.
        """
        with self._candado, self._cx:
            fila = self._cx.execute(
                "SELECT directorio FROM trabajos WHERE id = ? AND tenant = ?",
                (identificador, tenant)).fetchone()
            if fila is None:
                return False
            self._cx.execute("DELETE FROM trabajos WHERE id = ?",
                             (identificador,))
        _borrar(Path(fila["directorio"]))
        return True

    def envejecer(self, identificador: str, *, segundos: float) -> None:
        """Solo para pruebas: retrasa la fecha de creacion."""
        with self._candado, self._cx:
            self._cx.execute(
                "UPDATE trabajos SET creado = creado - ? WHERE id = ?",
                (segundos, identificador))


def _desde_fila(fila: sqlite3.Row) -> Trabajo:
    return Trabajo(
        identificador=fila["id"], tenant=fila["tenant"], tipo=fila["tipo"],
        archivo=fila["archivo"], estado=fila["estado"], creado=fila["creado"],
        directorio=Path(fila["directorio"]),
        xlsx=Path(fila["xlsx"]) if fila["xlsx"] else None,
        nombre_xlsx=fila["nombre_xlsx"] or "",
        mensaje=fila["mensaje"] or "",
        resumen=json.loads(fila["resumen"] or "{}"))


def _borrar(ruta: Path) -> None:
    if ruta.is_dir():
        shutil.rmtree(ruta, ignore_errors=True)
    else:
        ruta.unlink(missing_ok=True)
