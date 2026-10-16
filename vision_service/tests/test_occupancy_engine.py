import unittest
from datetime import datetime, timedelta

from vision_service.occupancy_engine import (
    MOTIVO_AUSENCIA_PERSONA,
    MOTIVO_OBJETO_ABANDONADO,
    TIMEOUT_OBJETO_ABANDONADO_DEFAULT,
    EstadoMesa,
    OccupancyEngine,
)


class OccupancyEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 1, 1, 12, 0, 0)
        self.engine = OccupancyEngine(periodo_gracia=timedelta(seconds=30))

    def test_presencia_abre_ocupacion_de_inmediato(self):
        """No hay período de gracia de apertura: se confirma "ocupada" apenas se detecta a alguien."""
        evento = self.engine.procesar(1, self.t0, hay_presencia=True, num_personas=2, confianza=0.9)
        self.assertIsNotNone(evento)
        self.assertEqual(evento.tipo, "abrir_ocupacion")
        self.assertEqual(evento.mesa_id, 1)
        self.assertEqual(evento.timestamp, self.t0)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.OCUPADA)

    def test_ausencia_temporal_no_libera_mesa(self):
        """Cliente va al baño/caja (< período de gracia) y la ocupación sigue activa."""
        self.engine.procesar(1, self.t0, hay_presencia=True, num_personas=1)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.OCUPADA)

        # se ausenta 10s (menos que el período de gracia de liberación)
        evento = self.engine.procesar(1, self.t0 + timedelta(seconds=10), hay_presencia=False)
        self.assertIsNone(evento)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.EN_GRACIA_LIBERANDO)

        # vuelve de forma SOSTENIDA (más de la tolerancia de parpadeo, 6s):
        # recién ahí se cancela la liberación.
        evento = self.engine.procesar(1, self.t0 + timedelta(seconds=15), hay_presencia=True)
        self.assertIsNone(evento)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.EN_GRACIA_LIBERANDO)
        evento = self.engine.procesar(1, self.t0 + timedelta(seconds=22), hay_presencia=True)
        self.assertIsNone(evento)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.OCUPADA)

    def test_parpadeo_de_presencia_no_cancela_ni_reinicia_la_liberacion(self):
        """Un solo frame de falso positivo durante la gracia de cierre no debe
        cancelar la liberación ni reiniciar su conteo (bug: quedaba pegada en
        "en_gracia_liberando" mucho más del período de gracia configurado)."""
        self.engine.procesar(1, self.t0, hay_presencia=True, num_personas=1)
        self.engine.procesar(1, self.t0 + timedelta(seconds=10), hay_presencia=False)
        # un solo frame de "regreso" (ruido, no sostenido)
        evento = self.engine.procesar(1, self.t0 + timedelta(seconds=12), hay_presencia=True)
        self.assertIsNone(evento)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.EN_GRACIA_LIBERANDO)
        # el parpadeo no reinició el conteo: sigue contando desde el t0+10 original
        evento = self.engine.procesar(1, self.t0 + timedelta(seconds=41), hay_presencia=False)
        self.assertIsNotNone(evento)
        self.assertEqual(evento.tipo, "cerrar_ocupacion")

    def test_ausencia_sostenida_libera_mesa(self):
        self.engine.procesar(1, self.t0, hay_presencia=True, num_personas=1)
        self.engine.procesar(1, self.t0 + timedelta(seconds=10), hay_presencia=False)

        evento = self.engine.procesar(1, self.t0 + timedelta(seconds=41), hay_presencia=False)
        self.assertIsNotNone(evento)
        self.assertEqual(evento.tipo, "cerrar_ocupacion")
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.LIBRE)

    def test_mesas_independientes_entre_si(self):
        self.engine.procesar(1, self.t0, hay_presencia=True, num_personas=1)
        self.engine.procesar(2, self.t0, hay_presencia=False)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.OCUPADA)
        self.assertEqual(self.engine.estado_actual(2), EstadoMesa.LIBRE)


class ObjetoAbandonadoTestCase(unittest.TestCase):
    """
    Timeout específico para "solo objetos sobre la mesa, cero personas",
    distinto del período de gracia normal por ausencia temporal de persona.
    """

    def setUp(self):
        self.t0 = datetime(2026, 1, 1, 12, 0, 0)
        self.engine = OccupancyEngine(
            periodo_gracia=timedelta(seconds=30),
            timeout_objeto_abandonado=timedelta(seconds=60),
        )

    def _ocupar(self, mesa_id=1):
        evento = self.engine.procesar(mesa_id, self.t0, hay_presencia=True, hay_persona=True, num_personas=1)
        self.assertEqual(evento.tipo, "abrir_ocupacion")
        self.assertEqual(self.engine.estado_actual(mesa_id), EstadoMesa.OCUPADA)

    def test_default_configurable_y_razonable(self):
        engine = OccupancyEngine()
        self.assertEqual(engine.timeout_objeto_abandonado, TIMEOUT_OBJETO_ABANDONADO_DEFAULT)
        self.assertGreater(TIMEOUT_OBJETO_ABANDONADO_DEFAULT, timedelta(0))
        self.assertEqual(self.engine.timeout_objeto_abandonado, timedelta(seconds=60))

    def test_objeto_solo_no_abre_ocupacion(self):
        """Platos sucios o una mochila sin persona no deben generar una ocupación."""
        for s in (0, 10, 40, 90, 200):
            evento = self.engine.procesar(
                1, self.t0 + timedelta(seconds=s), hay_presencia=True, hay_persona=False
            )
            self.assertIsNone(evento)
            self.assertEqual(self.engine.estado_actual(1), EstadoMesa.LIBRE)

    def test_objeto_abandonado_libera_con_su_timeout_no_con_gracia(self):
        """Solo objeto (sin persona): la gracia normal (30s) no libera, el timeout de objeto (60s) sí."""
        self._ocupar()
        t_salida = self.t0 + timedelta(seconds=40)
        evento = self.engine.procesar(1, t_salida, hay_presencia=True, hay_persona=False)
        self.assertIsNone(evento)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.EN_GRACIA_LIBERANDO)

        # pasó la gracia normal (35s > 30s) pero sigue el objeto: todavía NO se libera
        evento = self.engine.procesar(
            1, t_salida + timedelta(seconds=35), hay_presencia=True, hay_persona=False
        )
        self.assertIsNone(evento)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.EN_GRACIA_LIBERANDO)

        # se cumple el timeout de objeto abandonado
        evento = self.engine.procesar(
            1, t_salida + timedelta(seconds=60), hay_presencia=True, hay_persona=False
        )
        self.assertIsNotNone(evento)
        self.assertEqual(evento.tipo, "cerrar_ocupacion")
        self.assertEqual(evento.motivo, MOTIVO_OBJETO_ABANDONADO)
        self.assertEqual(evento.timestamp, t_salida)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.LIBRE)

    def test_ausencia_sin_objetos_sigue_usando_gracia_normal(self):
        self._ocupar()
        t_salida = self.t0 + timedelta(seconds=40)
        self.engine.procesar(1, t_salida, hay_presencia=False, hay_persona=False)
        evento = self.engine.procesar(
            1, t_salida + timedelta(seconds=30), hay_presencia=False, hay_persona=False
        )
        self.assertIsNotNone(evento)
        self.assertEqual(evento.tipo, "cerrar_ocupacion")
        self.assertEqual(evento.motivo, MOTIVO_AUSENCIA_PERSONA)

    def test_persona_vuelve_cancela_timeout_de_objeto(self):
        """El cliente vuelve de la caja/baño antes del timeout: la ocupación sigue."""
        self._ocupar()
        t_salida = self.t0 + timedelta(seconds=40)
        self.engine.procesar(1, t_salida, hay_presencia=True, hay_persona=False)
        self.engine.procesar(
            1, t_salida + timedelta(seconds=50), hay_presencia=True, hay_persona=True, num_personas=1
        )
        # presencia sostenida (más de la tolerancia de parpadeo, 6s): recién
        # ahí se confirma que volvió de verdad y se cancela la liberación.
        evento = self.engine.procesar(
            1, t_salida + timedelta(seconds=58), hay_presencia=True, hay_persona=True, num_personas=1
        )
        self.assertIsNone(evento)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.OCUPADA)
        # y mucho después sigue ocupada sin haberse liberado
        evento = self.engine.procesar(
            1, t_salida + timedelta(seconds=300), hay_presencia=True, hay_persona=True, num_personas=1
        )
        self.assertIsNone(evento)
        self.assertEqual(self.engine.estado_actual(1), EstadoMesa.OCUPADA)

    def test_retiran_objetos_durante_timeout_aplica_gracia_normal(self):
        """El personal retira los platos: desde ahí manda la gracia normal (más corta)."""
        self._ocupar()
        t_salida = self.t0 + timedelta(seconds=40)
        self.engine.procesar(1, t_salida, hay_presencia=True, hay_persona=False)
        self.engine.procesar(1, t_salida + timedelta(seconds=20), hay_presencia=True, hay_persona=False)
        # a los 35s ya no hay objetos ni persona: 35s >= gracia normal (30s) -> libre
        evento = self.engine.procesar(
            1, t_salida + timedelta(seconds=35), hay_presencia=False, hay_persona=False
        )
        self.assertIsNotNone(evento)
        self.assertEqual(evento.tipo, "cerrar_ocupacion")
        self.assertEqual(evento.motivo, MOTIVO_AUSENCIA_PERSONA)

    def test_compatibilidad_sin_hay_persona(self):
        """Si no se pasa hay_persona, se comporta como antes (presencia == persona)."""
        evento = self.engine.procesar(1, self.t0, hay_presencia=True, num_personas=1)
        self.assertEqual(evento.tipo, "abrir_ocupacion")
        self.assertEqual(self.engine.inicio_ocupacion_actual(1), self.t0)
        self.engine.procesar(1, self.t0 + timedelta(seconds=40), hay_presencia=False)
        evento = self.engine.procesar(1, self.t0 + timedelta(seconds=70), hay_presencia=False)
        self.assertEqual(evento.tipo, "cerrar_ocupacion")
        self.assertEqual(evento.motivo, MOTIVO_AUSENCIA_PERSONA)
        self.assertIsNone(self.engine.inicio_ocupacion_actual(1))


if __name__ == "__main__":
    unittest.main()
