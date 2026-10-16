"""
Motor de estado de ocupación por mesa: zona fija + overlap geométrico. La mesa
se marca "ocupada" apenas se detecta una persona en su zona (sin período de
gracia de apertura). El período de gracia solo aplica al CIERRE: para no
confundir una ausencia temporal (cliente va al baño o a la caja) con que la
mesa quedó libre.

Es la pieza más importante del microservicio de visión y por eso está escrita
sin dependencias de OpenCV/YOLO: se testea con datos sintéticos (secuencias de
"hay_presencia": True/False por timestamp) y luego se conecta al pipeline real
en pipeline.py.

Objetos abandonados sin persona
-------------------------------
Además del período de gracia normal (ausencia temporal de la persona), el motor
maneja un timeout específico y configurable para el caso "solo hay objetos
sobre la mesa, cero personas" (`timeout_objeto_abandonado`): una mochila que
quedó olvidada, o los platos/vasos que quedan después de que el cliente se fue
y el personal todavía no retira. Sin este timeout un objeto mantendría la mesa
"ocupada" indefinidamente.

Reglas:
  * Un objeto solo NUNCA abre una ocupación: tiene que haber una persona. Así
    los platos sucios que quedan tras liberar la mesa no generan ocupaciones
    fantasma en bucle. Una vez abierta por una persona, un objeto sí "sostiene"
    la ocupación si la persona se levanta (caso normal en este negocio: se pide
    y paga en caja, dejando sus cosas en la mesa).
  * Con la mesa ocupada, si desaparecen las personas pero quedan objetos, se
    entra en gracia de liberación pero el plazo que aplica es
    `timeout_objeto_abandonado` en vez de `periodo_gracia`.
  * Si vuelve a haber una persona DE FORMA SOSTENIDA (no un parpadeo de un solo
    frame), la liberación se cancela.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

# Valor por defecto del timeout de objeto abandonado. Se eligió MÁS LARGO que
# el período de gracia por defecto (45 s) a propósito: en este negocio el
# cliente elige mesa, deja sus cosas y va a la caja a pedir/pagar, o el plato
# llega mientras está en el baño; un plazo muy corto liberaría la mesa en esos
# casos y generaría ocupaciones partidas. Dos minutos cubre esa ida y vuelta y
# aun así libera razonablemente rápido una mesa con platos sucios o una
# mochila olvidada. Se sobreescribe desde config/mesas_zonas.json
# (`parametros.timeout_objeto_abandonado_segundos`).
TIMEOUT_OBJETO_ABANDONADO_DEFAULT = timedelta(seconds=120)

MOTIVO_AUSENCIA_PERSONA = "ausencia_persona"
MOTIVO_OBJETO_ABANDONADO = "objeto_abandonado"

# Tolerancia durante EN_GRACIA_LIBERANDO: un solo frame donde vuelve a
# detectarse a alguien (parpadeo de YOLO, o el bbox de una persona sentada en
# OTRA mesa apenas rozando esta zona) no debe cancelar la liberación de
# inmediato ni reiniciar el conteo. Solo una presencia SOSTENIDA por más de
# esto confirma que el cliente realmente volvió.
TOLERANCIA_INTERRUPCION_GRACIA_DEFAULT = timedelta(seconds=6)


class EstadoMesa(str, Enum):
    LIBRE = "libre"
    OCUPADA = "ocupada"
    EN_GRACIA_LIBERANDO = "en_gracia_liberando"  # dejó de haber presencia, confirmando


@dataclass
class EventoMotor:
    tipo: str  # "abrir_ocupacion" | "cerrar_ocupacion"
    mesa_id: int
    timestamp: datetime
    num_personas_detectadas: int = 0
    confianza: float = 0.0
    # Solo para "cerrar_ocupacion": por qué se liberó la mesa
    # (MOTIVO_AUSENCIA_PERSONA | MOTIVO_OBJETO_ABANDONADO).
    motivo: str = ""


@dataclass
class _EstadoInterno:
    estado: EstadoMesa = EstadoMesa.LIBRE
    desde: datetime | None = None
    ocupacion_actual_inicio: datetime | None = None
    max_personas_en_ocupacion: int = 0
    confianza_acumulada: list[float] = field(default_factory=list)
    # Durante EN_GRACIA_LIBERANDO: True si en el último frame quedaban objetos
    # sobre la mesa (sin personas). Decide qué plazo aplica.
    solo_objetos: bool = False
    # Durante EN_GRACIA_LIBERANDO: desde cuándo hay presencia sostenida sin
    # interrupción (para confirmar que el cliente volvió de verdad, no un
    # parpadeo de detección). None mientras no haya presencia.
    regreso_desde: datetime | None = None


class OccupancyEngine:
    def __init__(
        self,
        periodo_gracia: timedelta = timedelta(seconds=45),
        timeout_objeto_abandonado: timedelta = TIMEOUT_OBJETO_ABANDONADO_DEFAULT,
        tolerancia_interrupcion_gracia: timedelta = TOLERANCIA_INTERRUPCION_GRACIA_DEFAULT,
    ):
        self.periodo_gracia = periodo_gracia
        self.timeout_objeto_abandonado = timeout_objeto_abandonado
        self.tolerancia_interrupcion_gracia = tolerancia_interrupcion_gracia
        self._estados: dict[int, _EstadoInterno] = {}

    def _estado_de(self, mesa_id: int) -> _EstadoInterno:
        return self._estados.setdefault(mesa_id, _EstadoInterno())

    def procesar(
        self,
        mesa_id: int,
        timestamp: datetime,
        hay_presencia: bool,
        num_personas: int = 0,
        confianza: float = 0.0,
        hay_persona: bool | None = None,
    ) -> EventoMotor | None:
        """
        Alimentar con un frame (o un frame agregado/sampleado) para una mesa.
        Devuelve un EventoMotor cuando el estado confirmado cambia (abrir o
        cerrar ocupación), o None si no hay cambio que reportar todavía.

        `hay_presencia`: hay algo (persona u objeto) solapando la zona.
        `hay_persona`:   hay al menos una persona solapando la zona. Si se omite
                         se asume igual a `hay_presencia` (compatibilidad con
                         el uso original, donde no se distinguía objeto de
                         persona). `hay_presencia and not hay_persona` es el
                         caso "solo objetos".
        """
        if hay_persona is None:
            hay_persona = hay_presencia
        hay_presencia = hay_presencia or hay_persona
        solo_objetos = hay_presencia and not hay_persona

        st = self._estado_de(mesa_id)

        if st.estado == EstadoMesa.LIBRE:
            # Un objeto solo no abre ocupación (platos sucios, mochila olvidada):
            # hace falta una persona. A diferencia del cierre, la apertura no
            # tiene período de gracia: se confirma "ocupada" apenas se detecta
            # a alguien (a pedido: el período de gracia queda reservado para
            # cuando la mesa ya está ocupada y la persona se levanta).
            if hay_persona:
                st.estado = EstadoMesa.OCUPADA
                st.ocupacion_actual_inicio = timestamp
                st.max_personas_en_ocupacion = num_personas
                st.confianza_acumulada = [confianza]
                return EventoMotor(
                    tipo="abrir_ocupacion",
                    mesa_id=mesa_id,
                    timestamp=timestamp,
                    num_personas_detectadas=num_personas,
                    confianza=confianza,
                )
            return None

        if st.estado == EstadoMesa.OCUPADA:
            st.max_personas_en_ocupacion = max(st.max_personas_en_ocupacion, num_personas)
            if confianza:
                st.confianza_acumulada.append(confianza)
            if not hay_persona:
                st.estado = EstadoMesa.EN_GRACIA_LIBERANDO
                st.desde = timestamp
                st.solo_objetos = solo_objetos
            return None

        if st.estado == EstadoMesa.EN_GRACIA_LIBERANDO:
            if hay_persona:
                if st.regreso_desde is None:
                    st.regreso_desde = timestamp
                elif timestamp - st.regreso_desde >= self.tolerancia_interrupcion_gracia:
                    # presencia sostenida (no un parpadeo): el cliente volvió de
                    # verdad (baño, caja) y se cancela la liberación.
                    st.estado = EstadoMesa.OCUPADA
                    st.desde = None
                    st.regreso_desde = None
                    st.solo_objetos = False
                return None
            # la ausencia de presencia (aunque sea tras un parpadeo dentro de la
            # tolerancia) descarta cualquier "regreso" que no se llegó a confirmar.
            st.regreso_desde = None
            st.solo_objetos = solo_objetos
            plazo = self.timeout_objeto_abandonado if solo_objetos else self.periodo_gracia
            if timestamp - st.desde >= plazo:
                inicio = st.ocupacion_actual_inicio
                confianza_prom = (
                    sum(st.confianza_acumulada) / len(st.confianza_acumulada)
                    if st.confianza_acumulada
                    else 0.0
                )
                num_personas = st.max_personas_en_ocupacion
                motivo = MOTIVO_OBJETO_ABANDONADO if solo_objetos else MOTIVO_AUSENCIA_PERSONA
                # se libera: reset completo para la próxima ocupación.
                self._estados[mesa_id] = _EstadoInterno(estado=EstadoMesa.LIBRE)
                return EventoMotor(
                    tipo="cerrar_ocupacion",
                    mesa_id=mesa_id,
                    timestamp=st.desde,
                    num_personas_detectadas=num_personas,
                    confianza=confianza_prom,
                    motivo=motivo,
                )
            return None

        return None

    def estado_actual(self, mesa_id: int) -> EstadoMesa:
        return self._estado_de(mesa_id).estado

    def inicio_ocupacion_actual(self, mesa_id: int) -> datetime | None:
        """Inicio de la ocupación confirmada en curso, o None si la mesa no está ocupada."""
        st = self._estado_de(mesa_id)
        if st.estado in (EstadoMesa.OCUPADA, EstadoMesa.EN_GRACIA_LIBERANDO):
            return st.ocupacion_actual_inicio
        return None
