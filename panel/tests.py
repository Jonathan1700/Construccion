import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .services import get_backend
from .templatetags.panel_extras import barra_espera, con_signo, mmss, minseg, nivel


# Estas pruebas cubren la interfaz con los datos fijos del prototipo; el backend real
# (ApiBackend, el que usa el proyecto) se prueba en test_api_backend.py.
@override_settings(PANEL_BACKEND="panel.services.demo.DemoBackend")
class PanelBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            "admin", email="admin@correo.com", password="clave-segura-123", first_name="Admin")

    def setUp(self):
        get_backend.cache_clear()

    def entrar(self):
        self.client.force_login(self.usuario)


class AccesoTests(PanelBase):
    def test_login_se_muestra(self):
        r = self.client.get(reverse("panel:login"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Panel del local")

    def test_campos_vacios_muestran_error_con_salida(self):
        r = self.client.post(reverse("panel:login"), {"username": "", "password": ""})
        self.assertContains(r, "Completa tu correo y contraseña")
        self.assertContains(r, "Campo obligatorio", count=2)
        self.assertContains(r, 'role="alert"')

    def test_credenciales_incorrectas(self):
        r = self.client.post(reverse("panel:login"), {"username": "admin@correo.com", "password": "mala"})
        self.assertContains(r, "Correo o contraseña incorrectos")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ingreso_con_correo(self):
        r = self.client.post(reverse("panel:login"), {"username": "ADMIN@correo.com", "password": "clave-segura-123"})
        self.assertRedirects(r, reverse("panel:inicio"))

    def test_ingreso_con_usuario(self):
        r = self.client.post(reverse("panel:login"), {"username": "admin", "password": "clave-segura-123"})
        self.assertRedirects(r, reverse("panel:inicio"))

    def test_next_externo_se_ignora(self):
        r = self.client.post(reverse("panel:login"), {"username": "admin", "password": "clave-segura-123", "next": "https://malo.example/"})
        self.assertRedirects(r, reverse("panel:inicio"))

    def test_pantallas_exigen_sesion(self):
        for nombre in ("inicio", "espera", "personal", "uso_mesas", "evidencia", "ajustes", "zonas"):
            r = self.client.get(reverse(f"panel:{nombre}"))
            self.assertEqual(r.status_code, 302, nombre)
            self.assertIn(reverse("panel:login"), r["Location"])

    def test_salir_solo_por_post(self):
        self.entrar()
        self.assertEqual(self.client.get(reverse("panel:logout")).status_code, 405)
        r = self.client.post(reverse("panel:logout"))
        self.assertRedirects(r, reverse("panel:login"))


class PantallasTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.entrar()

    def test_todas_las_pantallas_responden(self):
        for nombre in ("inicio", "espera", "personal", "uso_mesas", "evidencia", "ajustes", "zonas"):
            r = self.client.get(reverse(f"panel:{nombre}"))
            self.assertEqual(r.status_code, 200, nombre)

    def test_inicio_muestra_las_tres_metricas(self):
        r = self.client.get(reverse("panel:inicio"))
        self.assertContains(r, "Tiempo de espera")
        self.assertContains(r, "Quién atiende más")
        self.assertContains(r, "Uso de mesas")
        self.assertContains(r, "P-02")

    def test_periodo_valido_e_invalido(self):
        r = self.client.get(reverse("panel:personal") + "?periodo=semana")
        self.assertContains(r, "esta semana")
        r = self.client.get(reverse("panel:personal") + "?periodo=%3Cscript%3E")
        self.assertContains(r, "Quien más atiende hoy")

    def test_detalle_de_mesa_con_temporizador(self):
        r = self.client.get(reverse("panel:mesa", args=[6]))
        self.assertContains(r, "Actividad de la mesa")
        self.assertContains(r, "Ver evidencia de video")
        self.assertContains(r, "sobre el promedio")

    def test_detalle_de_mesa_libre_y_mesa_inexistente(self):
        r = self.client.get(reverse("panel:mesa", args=[1]))
        self.assertContains(r, "no tiene una ocupación en curso")
        self.assertEqual(self.client.get(reverse("panel:mesa", args=[99])).status_code, 404)

    def test_evidencia_filtra_por_tipo(self):
        r = self.client.get(reverse("panel:evidencia") + "?tipo=entrega")
        self.assertContains(r, "1 clip")
        r = self.client.get(reverse("panel:evidencia") + "?tipo=fusion")
        self.assertContains(r, "Fusión")

    def test_api_estado(self):
        r = self.client.get(reverse("panel:api_estado"))
        d = r.json()
        self.assertEqual(d["resumen"]["total"], 10)
        self.assertEqual(len(d["en_espera"]), 4)


class AjustesTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.entrar()

    def test_guardar_muestra_confirmacion_con_dos_salidas(self):
        r = self.client.post(reverse("panel:ajustes"), {"periodo_gracia_min": 8, "solo_objetos_min": 3, "confianza_min": "0.6"})
        self.assertRedirects(r, reverse("panel:ajustes") + "?guardado=1", fetch_redirect_response=False)
        r = self.client.get(reverse("panel:ajustes") + "?guardado=1")
        self.assertContains(r, "Cambios guardados")
        self.assertContains(r, "Volver al inicio")
        self.assertContains(r, "Seguir editando")
        self.assertEqual(get_backend().ajustes()["periodo_gracia_min"], 8)

    def test_valores_invalidos_no_se_guardan(self):
        r = self.client.post(reverse("panel:ajustes"), {"periodo_gracia_min": 99, "confianza_min": "0.6"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Máximo 30 minutos")
        self.assertContains(r, "Revisa los campos marcados")
        self.assertEqual(get_backend().ajustes()["periodo_gracia_min"], 5)

    def test_campo_vacio_pide_dato(self):
        r = self.client.post(reverse("panel:ajustes"), {"periodo_gracia_min": "", "confianza_min": "0.6"})
        self.assertContains(r, "Ingresa un número de minutos")


class ZonasTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.entrar()

    def _post(self, cuerpo):
        return self.client.post(reverse("panel:zonas_guardar"), json.dumps(cuerpo), content_type="application/json")

    def test_guardar_zonas_validas(self):
        r = self._post({"zonas": [
            {"nombre": "Mesa 1", "tipo": "mesa", "capacidad": 4, "adyacentes": ["M2"], "puntos": [[0, 0], [10, 0], [10, 10]]},
            {"nombre": "Caja", "tipo": "caja", "capacidad": None, "puntos": [[0, 0], [5, 0], [5, 5]]}]})
        self.assertEqual(r.json(), {"ok": True, "mesas": 1, "cajas": 1})
        self.assertEqual(len(get_backend().zonas()["zonas"]), 2)

    def test_zona_con_menos_de_tres_vertices(self):
        r = self._post({"zonas": [{"nombre": "Mesa 1", "tipo": "mesa", "puntos": [[0, 0], [1, 1]]}]})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])

    def test_json_roto(self):
        r = self.client.post(reverse("panel:zonas_guardar"), "no es json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_solo_post(self):
        self.assertEqual(self.client.get(reverse("panel:zonas_guardar")).status_code, 405)


class EtiquetasTests(TestCase):
    def test_formato_de_tiempos(self):
        self.assertEqual(mmss(768), "12:48")
        self.assertEqual(mmss(3725), "1:02:05")
        self.assertEqual(mmss(None), "--:--")
        self.assertEqual(minseg(400), "6:40")
        self.assertEqual(con_signo(65), "+1:05")
        self.assertEqual(con_signo(-65), "−1:05")
        self.assertEqual(con_signo(None), "—")

    def test_nivel_frente_al_promedio(self):
        self.assertEqual(nivel(300, 680), "ok")
        self.assertEqual(nivel(600, 680), "cerca")
        self.assertEqual(nivel(768, 680), "tarde")

    def test_barra_de_espera_acotada(self):
        self.assertEqual(barra_espera(99999, 680), 100)
        self.assertGreaterEqual(barra_espera(0, 680), 2)
