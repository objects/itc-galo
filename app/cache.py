"""Cache en memoria LRU + TTL para resultados costosos (Fase 5, Parte B).

Alcance minimo viable: la resolucion de lote por CHIP (`ServidorLotes.
_resolver_lote_por_chip`: Mapas Bogota + capa ArcGIS Lote). NO se cachea el
informe completo ni nada que dependa de Ollama: la cache es transparente
(mismo input -> mismo resultado) y solo guarda datos de fuentes geoespaciales.

Configuracion por entorno:
- `CACHE_TTL_SEGUNDOS` (default 3600): vida de cada entrada. `0` DESACTIVA la
  cache (cada consulta va a la fuente; comportamiento pre-Fase 5).
- Tamano maximo acotado (`TAMANO_MAXIMO_DEFAULT` entradas, politica LRU): la
  memoria no crece sin limite aunque el numero de CHIPs consultados crezca.

Determinismo (SC-003): la cache nunca altera resultados, solo evita repetir
consultas. Los tests inyectan un reloj propio o usan TTL=0.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from typing import Any, Callable

# Default razonable: una sesion de analisis reutiliza los lotes ya resueltos
# durante ~1 hora sin volver a golpear Mapas Bogota/ArcGIS.
CACHE_TTL_SEGUNDOS_DEFAULT = 3600
TAMANO_MAXIMO_DEFAULT = 128


def ttl_segundos_de_entorno() -> float:
    """Lee `CACHE_TTL_SEGUNDOS` del entorno (default 3600; 0 = desactivada).

    Misma convencion del proyecto para env vars: valor vacio o con espacios se
    trata como no definida y cae al default. Un valor no numerico tambien cae
    al default (fail-soft en configuracion, fail-loud en datos).
    """
    bruto = os.getenv("CACHE_TTL_SEGUNDOS", "").strip()
    if not bruto:
        return float(CACHE_TTL_SEGUNDOS_DEFAULT)
    try:
        return float(bruto)
    except ValueError:
        return float(CACHE_TTL_SEGUNDOS_DEFAULT)


class CacheLRUConTTL:
    """Cache generica en memoria: LRU con tamano acotado y TTL por entrada.

    - `obtener` devuelve None en miss O entrada expirada (la expirada ademas se
      purga: no ocupa cupo LRU).
    - `guardar` inserta/actualiza y desaloja la entrada menos recientemente
      usada cuando se supera `tamano_maximo`.
    - Con `ttl_segundos <= 0` la cache queda DESACTIVADA: obtener siempre da
      miss y guardar es no-op (comportamiento transparente).
    - `reloj` inyectable (monotonico) para tests de expiracion sin esperas.
    """

    def __init__(
        self,
        tamano_maximo: int = TAMANO_MAXIMO_DEFAULT,
        ttl_segundos: float = CACHE_TTL_SEGUNDOS_DEFAULT,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tamano_maximo = tamano_maximo
        self._ttl_segundos = ttl_segundos
        self._reloj = reloj
        self._entradas: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    @property
    def activa(self) -> bool:
        """False si la cache esta desactivada (ttl <= 0)."""
        return self._ttl_segundos > 0

    def obtener(self, clave: str) -> Any | None:
        """Valor asociado a `clave`, o None si miss/expirado/desactivada."""
        if not self.activa:
            return None
        entrada = self._entradas.get(clave)
        if entrada is None:
            return None
        guardada_en, valor = entrada
        if self._reloj() - guardada_en >= self._ttl_segundos:
            del self._entradas[clave]
            return None
        self._entradas.move_to_end(clave)
        return valor

    def guardar(self, clave: str, valor: Any) -> None:
        """Inserta/actualiza `clave` con el reloj actual (no-op si desactivada)."""
        if not self.activa:
            return
        self._entradas[clave] = (self._reloj(), valor)
        self._entradas.move_to_end(clave)
        while len(self._entradas) > self._tamano_maximo:
            self._entradas.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entradas)


def construir_cache_por_defecto() -> CacheLRUConTTL:
    """Cache del servidor real: TTL desde `CACHE_TTL_SEGUNDOS`, LRU acotada."""
    return CacheLRUConTTL(ttl_segundos=ttl_segundos_de_entorno())
