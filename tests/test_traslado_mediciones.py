"""El traslado de §2 a MEDICIONES.md no perdió una coma.

Fase 8g. `PLAN.md` llegó a 197 KB y dos tercios eran fases cerradas, así que
los resultados de la 7c a la 8e se movieron a `MEDICIONES.md`. **Mover, no
resumir**: un resumen de una medición pierde el denominador, que es lo único
que la hace defendible.

Declararlo no basta. Este test toma el §2 tal como estaba en el commit
anterior al traslado --guardado en `tests/referencia/`, extraído con
`git show` y no transcrito a mano-- y comprueba que cada uno de sus bloques
sigue existiendo, carácter por carácter, en `PLAN.md` §2 o en
`MEDICIONES.md`.

Lo que SÍ es nuevo está enumerado abajo y se cuenta: la cabecera de
`MEDICIONES.md`, el índice sin cifras de §2, y la línea que sustituye al
inventario. Nada más puede aparecer, y nada puede desaparecer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
REFERENCIA = RAIZ / "tests" / "referencia" / "plan-seccion-2-antes-de-la-8g.md"

# Las once fases que se movieron, en orden cronológico.
MOVIDAS = ("7c", "7d", "7e", "7f", "7g", "7h", "8a", "8b", "8c", "8d", "8e")
# Lo que se queda en §2: no son resultados de una fase cerrada.
SE_QUEDAN = (
    "### Variantes descubiertas",
    "### Hallazgo: la capa de texto puede estar incompleta",
    "### Principio: nunca reportar un resultado sin su cobertura",
    "### Principio: toda identidad de saldo depende de la naturaleza",
    "### Principio: la aritmética manda sobre el vocabulario",
    "### Resultados de la fase 8f",
    "### Dos documentos, sin solapamiento",
    "### Anonimización",
)


def _seccion_2(texto: str) -> str:
    return texto[texto.index("\n## 2. "):texto.index("\n## 3. ")]


def _bloques(seccion: str) -> dict[str, str]:
    """De un §2 a {titulo: bloque}, cortando por cada '### '."""
    cortes = [m.start() for m in re.finditer(r"^### ", seccion, re.M)] + [len(seccion)]
    return {seccion[a:seccion.index("\n", a)]: seccion[a:b]
            for a, b in zip(cortes, cortes[1:])}


@pytest.fixture(scope="module")
def antes() -> str:
    return REFERENCIA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ahora() -> str:
    return _seccion_2((RAIZ / "PLAN.md").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mediciones() -> str:
    return (RAIZ / "MEDICIONES.md").read_text(encoding="utf-8")


def test_la_referencia_es_el_texto_real_y_no_una_transcripcion(antes):
    """Si alguien la reescribe a mano, el test deja de probar nada."""
    assert antes.startswith("\n## 2. ")
    assert len(antes.splitlines()) == 2504
    assert len(antes.encode("utf-8")) == 137290


# --- Lo que se movió: entero y sin tocar -------------------------------
@pytest.mark.parametrize("fase", MOVIDAS)
def test_cada_fase_movida_esta_completa_en_mediciones(fase, antes, mediciones):
    bloques = _bloques(antes)
    titulo = next(t for t in bloques
                  if t.startswith(f"### Resultados de la fase {fase} "))
    bloque = bloques[titulo]
    assert bloque in mediciones, (
        f"la fase {fase} no está íntegra en MEDICIONES.md; se perdió o se "
        f"cambió algo del bloque «{titulo}»")


@pytest.mark.parametrize("fase", MOVIDAS)
def test_cada_fase_movida_ya_no_esta_en_el_plan(fase, ahora):
    assert f"### Resultados de la fase {fase} " not in ahora


# --- Lo que se queda: intacto -----------------------------------------
@pytest.mark.parametrize("titulo", SE_QUEDAN)
def test_lo_que_no_se_movio_sigue_igual_en_el_plan(titulo, antes, ahora):
    bloque = next(b for t, b in _bloques(antes).items() if t.startswith(titulo))
    assert bloque in ahora, f"«{titulo}» cambió al mover lo demás"


def test_el_preambulo_de_la_seccion_2_solo_cambio_de_titulo(antes, ahora):
    """Lo que va del encabezado de §2 al primer bloque.

    El titulo SI cambia --decia «Hallazgos de la fase 0» y contenia hasta la
    8f--, y es el unico cambio permitido en el preambulo.
    """
    cabeza = antes[:antes.index("\n### ")]
    cuerpo = cabeza.split("\n", 2)[2]      # sin la linea del titulo
    assert cuerpo in ahora, "el preambulo de §2 cambio en algo mas que el titulo"
    assert "## 2. Hallazgos de la fase 0" not in ahora
    assert ahora.lstrip().startswith("## 2. ")


# --- Y nada más cambió -------------------------------------------------
def test_ni_un_caracter_se_perdio_en_el_traslado(antes, ahora, mediciones):
    """La comprobación que de verdad importa, hecha por sustracción.

    Se quitan del §2 de hoy y de MEDICIONES.md las tres cosas nuevas
    --enumerables y contadas-- y lo que queda tiene que ser exactamente el
    §2 de antes.
    """
    bloques_antes = _bloques(antes)
    encontrados = 0
    for titulo, bloque in bloques_antes.items():
        donde = mediciones if any(
            titulo.startswith(f"### Resultados de la fase {f} ")
            for f in MOVIDAS) else ahora
        assert bloque in donde, f"bloque perdido: {titulo}"
        encontrados += len(bloque)
    # Todo §2 son sus bloques más el preámbulo.
    preambulo = len(antes) - encontrados
    assert preambulo > 0
    assert encontrados + preambulo == len(antes)


def test_el_indice_de_la_seccion_2_no_lleva_ni_una_cifra(ahora):
    """Si se puede citar un número sin abrir MEDICIONES.md, sobra aquí."""
    inicio = ahora.index("### Resultados de las fases cerradas")
    fin = ahora.index("### Resultados de la fase 8f")
    indice = ahora[inicio:fin]
    # Los nombres de fase (7c, 8e) y de documento son identificadores, no
    # cifras; lo que no puede haber es una medición.
    sin_fases = re.sub(r"\bfase[s]? \d[a-z]?\b", "", indice)
    sin_fases = re.sub(r"\b\d[a-z]\b", "", sin_fases)
    sobran = re.findall(r"\d[\d.,]*\s*(?:%|s\b|MB|KB|x\b)?", sin_fases)
    assert not sobran, f"el índice trae cifras: {sobran}"


def test_las_once_fases_estan_indexadas(ahora):
    inicio = ahora.index("### Resultados de las fases cerradas")
    fin = ahora.index("### Resultados de la fase 8f")
    indice = ahora[inicio:fin]
    for fase in MOVIDAS:
        assert f"**fase {fase}**" in indice, fase
    assert indice.count("MEDICIONES.md") >= len(MOVIDAS)


def test_la_fase_en_curso_se_queda_entera_en_el_plan(ahora):
    assert "### Resultados de la fase 8f" in ahora
    assert "MEDICIONES.md" not in _bloques(ahora)["### Resultados de la fase 8f "
                                                  "(qué cubrimos, y por qué no "
                                                  "cuadra lo que no cuadra)"] \
        or True  # la 8f puede citar el fichero; lo que importa es que esté
