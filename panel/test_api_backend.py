"""Pruebas del backend real del panel (modelos de `monitoreo` + config del pipeline)."""
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from monitoreo.models import EventoEntrega, EventoOcupacion, Mesa, Personal

from .services import get_backend

CONFIG = {
    "camara_id": "cam-1",
    "mesas": [
        {"mesa_id": 1, "poligono": [[0, 0], [100, 0], [100, 100], [0, 100]], "capacidad": 4, "adyacentes": [2]},
        {"mesa_id": 2, "poligono": [[200, 0], [300, 0], [300, 100], [200, 100]], "capacidad": 4, "adyacentes": [1]},
    ],
    "parametros": {"periodo_gracia_segundos": 45, "timeout_objeto_abandonado_segundos": 120,
                   "umbral_overlap_ocupacion": 0.45},
}


class ApiBackendBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user("admin", email="admin@correo.com", password="x")
        cls.m1 = Mesa.objects.create(id=1, numero=1, camara_id="cam-1", zona_poligono=CONFIG["mesas"][0]["poligono"])
        cls.m2 = Mesa.objects.create(id=2, numero=2, camara_id="cam-1", zona_poligono=CONFIG["mesas"][1]["poligono"])
        cls.m3 = Mesa.objects.create(id=3, numero=3, camara_id="cam-1", zona_poligono=[])
        cls.p1 = Personal.objects.create(codigo_tracking="track-7")
        cls.p2 = Personal.objects.create(codigo_tracking="track-9", alias="Ana")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ruta = Path(tmp.name) / "mesas_zonas.json"
        self.ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
        ajustes = override_settings(PANEL_BACKEND="panel.services.api.ApiBackend", PANEL_CONFIG_VISION=self.ruta)
        ajustes.enable()
        self.addCleanup(ajustes.disable)
        get_backend.cache_clear()
        self.addCleanup(get_backend.cache_clear)
        self.be = get_backend()
        self.ahora = timezone.now()

    def ocupar(self, mesa, minutos_atras, personas=2, estado="ocupada", **extra):
        return EventoOcupacion.objects.create(mesa=mesa, inicio=self.ahora - timedelta(minutes=minutos_atras),
                                              estado=estado, num_personas_detectadas=personas, **extra)

    def entregar(self, ocupacion, segundos, personal=None):
        return EventoEntrega.objects.create(evento_ocupacion=ocupacion, personal=personal, tipo="plato_principal",
                                            timestamp=ocupacion.inicio + timedelta(seconds=segundos),
                                            tiempo_espera_segundos=segundos)

    def config(self):
        return json.loads(self.ruta.read_text(encoding="utf-8"))


class EstadoYMetricasTests(ApiBackendBase):
    def test_sin_datos_no_rompe_ninguna_pantalla(self):
        self.client.force_login(self.usuario)
        for nombre in ("inicio", "espera", "personal", "uso_mesas", "evidencia", "ajustes", "zonas"):
            self.assertEqual(self.client.get(reverse(f"panel:{nombre}")).status_code, 200, nombre)
        self.assertEqual(self.client.get(reverse("panel:mesa", args=[1])).status_code, 200)
        self.assertEqual(self.client.get(reverse("panel:mesa", args=[99])).status_code, 404)

    def test_estado_en_vivo(self):
        o = self.ocupar(self.m1, 10, personas=3)
        self.entregar(o, 300, self.p1)
        self.ocupar(self.m2, 60, estado="liberada", fin=self.ahora)
        est = self.be.estado()
        self.assertEqual(est["resumen"], {"total": 3, "libres": 2, "casi_libres": 0, "ocupadas": 1,
                                          "personas": 3, "espera_prom_s": 300})
        self.assertEqual([f["codigo"] for f in est["en_espera"]], ["M1"])
        self.assertEqual(est["en_espera"][0]["entregas"], 1)
        self.assertTrue(est["camara"]["en_vivo"])
        m1 = next(m for m in est["mesas"] if m["id"] == 1)
        self.assertEqual((m1["x"], m1["y"], m1["w"], m1["h"]), (0, 0, 100, 100))
        self.assertEqual(est["plano"]["ancho"], 640)  # inferido de los polígonos

    def test_fusion_se_muestra_como_una_fila(self):
        padre = self.ocupar(self.m1, 5, personas=4)
        self.ocupar(self.m2, 4, personas=3, estado="fusionada", fusionada_con=padre)
        est = self.be.estado()
        self.assertEqual(len(est["en_espera"]), 1)
        fila = est["en_espera"][0]
        self.assertEqual((fila["codigo"], fila["personas"], fila["fusion"]), ("M1+M2", 7, True))
        self.assertEqual(est["plano"]["fusiones"][0]["mesas"], ["M1", "M2"])

    def test_metrica_espera(self):
        o = self.ocupar(self.m1, 30)
        self.entregar(o, 200)
        self.entregar(o, 600)
        ayer = EventoOcupacion.objects.create(mesa=self.m2, inicio=self.ahora - timedelta(days=1),
                                              fin=self.ahora - timedelta(days=1) + timedelta(minutes=30))
        self.entregar(ayer, 300)
        esp = self.be.espera("hoy")
        self.assertEqual((esp["promedio_s"], esp["max_s"], esp["min_s"]), (400, 600, 200))
        self.assertEqual(esp["delta_ayer_s"], 100)
        self.assertTrue(esp["por_hora"])
        self.assertEqual(self.be.espera("semana")["promedio_s"], 367)

    def test_metrica_personal(self):
        for mesa in (self.m1, self.m2):
            self.entregar(self.ocupar(mesa, 20), 120, self.p2)
        self.entregar(self.ocupar(self.m3, 10), 240, self.p1)
        self.entregar(self.ocupar(self.m3, 10), 60)  # entrega sin personal asociado: no cuenta
        per = self.be.personal("hoy")
        self.assertEqual([(r["codigo"], r["mesas"]) for r in per["ranking"]], [("Ana", 2), (f"P-{self.p1.id:02d}", 1)])
        self.assertEqual(per["top"]["pct_entregas"], 67)
        self.assertEqual(per["top"]["respuesta_s"], 120)

    def test_metrica_uso_no_cuenta_fusionadas(self):
        for _ in range(3):
            self.ocupar(self.m1, 50)
        padre = self.ocupar(self.m2, 40)
        EventoOcupacion.objects.create(mesa=self.m3, inicio=self.ahora, estado="fusionada", fusionada_con=padre)
        uso = self.be.uso_mesas("hoy")
        self.assertEqual({m["codigo"]: m["usos"] for m in uso["mesas"]}, {"M1": 3, "M2": 1, "M3": 0})
        self.assertEqual((uso["mas_usada"]["codigo"], uso["menos_usada"]["codigo"]), ("M1", "M3"))

    def test_detalle_de_mesa(self):
        o = self.ocupar(self.m1, 15, personas=2)
        self.entregar(o, 420, self.p2)
        m = self.be.mesa(1)
        self.assertEqual((m["estado"], m["entregas"], m["promedio_s"]), ("ocupada", 1, 420))
        self.assertEqual([a["titulo"] for a in m["actividad"]],
                         ["Mesa ocupada", "1.ª entrega", "Esperando siguiente entrega"])
        self.client.force_login(self.usuario)
        self.assertContains(self.client.get(reverse("panel:mesa", args=[1])), "Actividad de la mesa")

    def test_evidencias_desde_clips_s3(self):
        self.ocupar(self.m1, 90, clip_s3_key="evidencia/cam-1/mesa-1/a.mp4")
        self.ocupar(self.m2, 80)  # sin clip
        with self.settings(AWS_STORAGE_BUCKET_NAME="bucket", AWS_S3_REGION_NAME="us-east-1"):
            clips = self.be.evidencias()
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["url"], "https://bucket.s3.us-east-1.amazonaws.com/evidencia/cam-1/mesa-1/a.mp4")
        self.assertEqual(clips[0]["duracion_s"], 90 * 60)
        self.assertEqual(self.be.evidencias("entrega"), [])


class AjustesYZonasTests(ApiBackendBase):
    def test_ajustes_se_leen_y_escriben_en_la_config_del_pipeline(self):
        self.assertEqual(self.be.ajustes(), {"periodo_gracia_min": 1, "solo_objetos_min": 2, "confianza_min": 0.4})
        # La gracia no cambió (sigue en "1 min"): se conservan los 45 s originales.
        self.be.guardar_ajustes({"periodo_gracia_min": 1, "solo_objetos_min": 5, "confianza_min": 0.55})
        p = self.config()["parametros"]
        self.assertEqual((p["periodo_gracia_segundos"], p["timeout_objeto_abandonado_segundos"], p["confianza_minima"]),
                         (45, 300, 0.55))
        self.assertEqual(p["umbral_overlap_ocupacion"], 0.45)
        self.be.guardar_ajustes({"periodo_gracia_min": 3, "solo_objetos_min": None, "confianza_min": 0.5})
        p = self.config()["parametros"]
        self.assertEqual(p["periodo_gracia_segundos"], 180)
        self.assertNotIn("timeout_objeto_abandonado_segundos", p)

    def test_zonas_desde_la_config(self):
        z = self.be.zonas()
        self.assertEqual([(x["nombre"], x["adyacentes"]) for x in z["zonas"]], [("Mesa 1", ["M2"]), ("Mesa 2", ["M1"])])

    def test_guardar_zonas_sincroniza_mesas_y_config(self):
        self.client.force_login(self.usuario)
        cuerpo = {"zonas": [
            {"nombre": "Mesa 1", "tipo": "mesa", "capacidad": 6, "adyacentes": ["M5"], "puntos": [[0, 0], [50.4, 0], [50, 50]]},
            {"nombre": "Mesa 5", "tipo": "mesa", "capacidad": 2, "adyacentes": ["M1"], "puntos": [[60, 0], [90, 0], [90, 50]]},
            {"nombre": "Caja", "tipo": "caja", "puntos": [[0, 60], [40, 60], [40, 90]]},
        ]}
        r = self.client.post(reverse("panel:zonas_guardar"), json.dumps(cuerpo), content_type="application/json")
        self.assertEqual(r.json(), {"ok": True, "mesas": 2, "cajas": 1})

        m5 = Mesa.objects.get(numero=5)
        self.m1.refresh_from_db()
        self.assertEqual((self.m1.capacidad, self.m1.zona_poligono), (6, [[0, 0], [50, 0], [50, 50]]))
        self.assertEqual(list(self.m1.mesas_adyacentes.all()), [m5])
        self.assertFalse(Mesa.objects.get(numero=2).activa)  # sin zona: inactiva, no borrada

        cfg = self.config()
        self.assertEqual([m["mesa_id"] for m in cfg["mesas"]], [self.m1.id, m5.id])
        self.assertEqual(cfg["mesas"][0]["adyacentes"], [m5.id])
        self.assertEqual(cfg["zonas_excluidas"][0]["nombre"], "Caja")
        self.assertEqual(cfg["parametros"]["periodo_gracia_segundos"], 45)
        self.assertEqual(self.be.estado()["camara"]["zonas_excluidas"], 1)

    def test_zona_de_mesa_sin_numero_o_repetida(self):
        self.client.force_login(self.usuario)
        url = reverse("panel:zonas_guardar")
        tri = [[0, 0], [1, 0], [1, 1]]
        for zonas in ([{"nombre": "Terraza", "tipo": "mesa", "puntos": tri}],
                      [{"nombre": "Mesa 1", "tipo": "mesa", "puntos": tri}, {"nombre": "M1", "tipo": "mesa", "puntos": tri}]):
            r = self.client.post(url, json.dumps({"zonas": zonas}), content_type="application/json")
            self.assertEqual(r.status_code, 400)
        self.assertEqual(self.config()["mesas"], CONFIG["mesas"])
