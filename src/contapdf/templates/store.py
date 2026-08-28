"""Persistencia de plantillas, ligada al tenant.

La clave es (tenant_id, huella): el mapeo que configuro un despacho no se
le aplica a otro aunque el formato sea el mismo. La ruta se deriva del ID
del tenant, nunca del nombre del archivo que subieron (PLAN 0).

JSON en disco por ahora; la base de datos llega en la fase 8. Por eso todo
lo que se guarda es serializable y plano.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

_RE_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_RE_HUELLA = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class TenantInvalido(ValueError):
    """El identificador de tenant no sirve como nombre de directorio."""


class PlantillaRechazada(ValueError):
    """Una plantilla cuya aritmetica no cuadro no se guarda (PLAN 2)."""


@dataclass(frozen=True)
class Plantilla:
    """Todo lo que varia por formato, hecho explicito y persistente."""

    tenant_id: str
    huella: str
    tipo: str
    estrategia: str
    mapeo: dict[str, int]
    forma: str
    verificado_por: str
    orientacion_verificada: bool
    filas_afectadas: int
    esquema: dict
    reglas: dict
    cobertura: dict
    pendiente_de_confirmacion: bool
    confirmada_por: str = ""
    confirmada_en: str = ""
    version: int = 1

    def que_confirmar(self) -> dict | None:
        """Lo que un humano tiene que confirmar una vez, como datos.

        La interfaz llega en la fase 8: aqui solo se expone que se propone,
        sobre que se apoya y que cambiaria si estuviera mal.
        """
        if not self.pendiente_de_confirmacion:
            return None
        return {
            "campo": "orientacion debe/haber",
            "se_propone": {"debe": self.mapeo.get("debe"),
                           "haber": self.mapeo.get("haber")},
            "se_apoya_en": self.verificado_por,
            "consecuencia": (f"invertirla cambia la naturaleza de "
                             f"{self.filas_afectadas} filas"),
        }

    def a_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def desde_dict(cls, datos: dict) -> "Plantilla":
        return cls(**datos)


def _validar_tenant(tenant_id: str) -> str:
    if not _RE_TENANT.match(tenant_id or ""):
        raise TenantInvalido(
            f"identificador de tenant invalido: {tenant_id!r}; solo letras, "
            "digitos, guion y guion bajo")
    return tenant_id


class AlmacenPlantillas:
    """Plantillas en disco, un directorio por tenant."""

    def __init__(self, raiz: Path | str) -> None:
        self._raiz = Path(raiz)

    def _ruta(self, tenant_id: str, huella: str) -> Path:
        _validar_tenant(tenant_id)
        if not _RE_HUELLA.match(huella or ""):
            raise ValueError(f"huella invalida: {huella!r}")
        return self._raiz / tenant_id / f"{huella}.json"

    def guardar(self, plantilla: Plantilla) -> Path:
        """Escribe la plantilla. Rechaza las que no cuadraron."""
        if plantilla.cobertura.get("fallan", 0):
            raise PlantillaRechazada(
                f"la validacion de {plantilla.huella} reporto "
                f"{plantilla.cobertura['fallan']} reglas fallidas: no se aprende "
                "un formato cuya aritmetica no cuadro")
        ruta = self._ruta(plantilla.tenant_id, plantilla.huella)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(plantilla.a_dict(), ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return ruta

    def buscar(self, tenant_id: str, huella: str) -> Plantilla | None:
        ruta = self._ruta(tenant_id, huella)
        if not ruta.exists():
            return None
        return Plantilla.desde_dict(json.loads(ruta.read_text(encoding="utf-8")))

    def listar(self, tenant_id: str) -> list[Plantilla]:
        _validar_tenant(tenant_id)
        directorio = self._raiz / tenant_id
        if not directorio.is_dir():
            return []
        return sorted(
            (Plantilla.desde_dict(json.loads(r.read_text(encoding="utf-8")))
             for r in directorio.glob("*.json")),
            key=lambda p: p.huella)

    def confirmar(self, tenant_id: str, huella: str, *, por: str,
                  cuando: str | None = None) -> Plantilla:
        """Deja constancia de que un humano reviso lo que no se pudo verificar."""
        plantilla = self.buscar(tenant_id, huella)
        if plantilla is None:
            raise KeyError(f"no hay plantilla {huella} para el tenant {tenant_id}")
        confirmada = replace(
            plantilla,
            pendiente_de_confirmacion=False,
            confirmada_por=por,
            confirmada_en=cuando or datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
        )
        self.guardar(confirmada)
        return confirmada
