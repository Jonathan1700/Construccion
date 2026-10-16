"""Datos de ejemplo iguales a los del prototipo de Figma (sirven para probar la interfaz)."""
import copy
from datetime import timedelta

from django.utils import timezone

from .base import PanelBackend

_W, _H = 64, 64
_POS = {1: (16, 20), 2: (98, 20), 3: (180, 20), 4: (262, 20), 5: (16, 108), 6: (98, 108),
        7: (180, 108), 8: (262, 108), 9: (16, 208), 10: (98, 208)}
_ESTADO = {1: "libre", 2: "ocupada", 3: "libre", 4: "ocupada", 5: "casi_libre",
           6: "ocupada", 7: "ocupada", 8: "ocupada", 9: "libre", 10: "libre"}
_PERSONAS = {2: 2, 4: 4, 6: 3, 7: 4, 8: 3}
_ESPERA_S = {6: 768, 2: 435, 4: 272, 7: 130, 8: 130}      # segundos desde que se ocupó
_ENTREGAS = {6: 1}
_USOS = {1: 18, 2: 22, 3: 12, 4: 27, 5: 15, 6: 20, 7: 9, 8: 8, 9: 5, 10: 3}
_FACTOR = {"hoy": 1, "semana": 6, "mes": 24}
_PROMEDIO_S = 680

_ZONAS = [
    {"id": 1, "nombre": "Mesa 1", "tipo": "mesa", "capacidad": 4, "adyacentes": ["M2", "M5"], "puntos": [[120, 130], [210, 130], [215, 172], [115, 172]]},
    {"id": 2, "nombre": "Mesa 2", "tipo": "mesa", "capacidad": 4, "adyacentes": ["M1", "M3", "M6"], "puntos": [[262, 130], [352, 130], [358, 172], [256, 172]]},
    {"id": 3, "nombre": "Mesa 3", "tipo": "mesa", "capacidad": 4, "adyacentes": ["M2", "M4", "M7"], "puntos": [[404, 130], [494, 130], [501, 172], [398, 172]]},
    {"id": 4, "nombre": "Mesa 4", "tipo": "mesa", "capacidad": 4, "adyacentes": ["M3", "M8"], "puntos": [[546, 130], [636, 130], [644, 172], [540, 172]]},
    {"id": 5, "nombre": "Mesa 5", "tipo": "mesa", "capacidad": 4, "adyacentes": ["M1", "M6"], "puntos": [[80, 240], [210, 240], [222, 314], [64, 314]]},
    {"id": 6, "nombre": "Mesa 6", "tipo": "mesa", "capacidad": 4, "adyacentes": ["M2", "M5", "M7"], "puntos": [[270, 240], [400, 240], [412, 314], [260, 314]]},
    {"id": 7, "nombre": "Mesa 7", "tipo": "mesa", "capacidad": 4, "adyacentes": ["M3", "M6", "M8"], "puntos": [[460, 240], [590, 240], [602, 314], [452, 314]]},
    {"id": 8, "nombre": "Mesa 8", "tipo": "mesa", "capacidad": 4, "adyacentes": ["M4", "M7"], "puntos": [[640, 240], [762, 240], [778, 314], [632, 314]]},
    {"id": 9, "nombre": "Caja", "tipo": "caja", "capacidad": None, "adyacentes": [], "puntos": [[590, 360], [770, 360], [782, 438], [580, 438]]},
]
_AJUSTES = {"periodo_gracia_min": 5, "solo_objetos_min": None, "confianza_min": 0.5}


class DemoBackend(PanelBackend):
    """Datos en memoria: se reinician al reiniciar el servidor."""

    def __init__(self):
        self._ajustes = dict(_AJUSTES)
        self._zonas = copy.deepcopy(_ZONAS)

    # ---- estado en vivo -------------------------------------------------
    def estado(self):
        ahora = timezone.now()
        mesas = []
        for i in range(1, 11):
            x, y = _POS[i]
            seg = _ESPERA_S.get(i)
            mesas.append({
                "id": i, "codigo": f"M{i}", "estado": _ESTADO[i],
                "personas": _PERSONAS.get(i, 0),
                "desde": ahora - timedelta(seconds=seg) if seg else None,
                "entregas": _ENTREGAS.get(i, 0),
                "x": x, "y": y, "w": _W, "h": _H,
            })
        en_espera = [
            {"mesa_id": 6, "codigo": "M6", "personas": 3, "entregas": 1, "desde": ahora - timedelta(seconds=768), "fusion": False},
            {"mesa_id": 2, "codigo": "M2", "personas": 2, "entregas": 0, "desde": ahora - timedelta(seconds=435), "fusion": False},
            {"mesa_id": 4, "codigo": "M4", "personas": 4, "entregas": 0, "desde": ahora - timedelta(seconds=272), "fusion": False},
            {"mesa_id": 7, "codigo": "M7+M8", "personas": 7, "entregas": 0, "desde": ahora - timedelta(seconds=130), "fusion": True},
        ]
        return {
            "camara": {"nombre": "Cámara 1 · Salón", "en_vivo": True, "mesas": 10, "zonas_excluidas": 1},
            "resumen": {"total": 10, "libres": 4, "casi_libres": 1, "ocupadas": 5, "personas": 23, "espera_prom_s": _PROMEDIO_S},
            "mesas": mesas,
            "plano": {"ancho": 342, "alto": 292,
                      "caja": {"x": 212, "y": 208, "w": 114, "h": 64},
                      "fusiones": [{"x": 172, "y": 100, "w": 162, "h": 80, "mesas": ["M7", "M8"]}]},
            "en_espera": en_espera,
        }

    # ---- métrica 1 ------------------------------------------------------
    def espera(self, periodo):
        est = self.estado()
        horas = [(7, 6), (8, 9), (9, 12), (10, 10), (11, 14), (12, 16), (13, 13), (14, 8)]
        return {
            "promedio_s": _PROMEDIO_S, "max_s": 1445, "min_s": 250, "delta_ayer_s": 65,
            "en_curso": est["en_espera"],
            "por_hora": [{"hora": h, "min": m} for h, m in horas],
        }

    # ---- métrica 2 ------------------------------------------------------
    def personal(self, periodo):
        f = _FACTOR.get(periodo, 1)
        filas = [("P-02", 38, 400), ("P-01", 29, 475), ("P-04", 17, 550), ("P-03", 6, 500)]
        ranking = [{"codigo": c, "mesas": n * f, "respuesta_s": r} for c, n, r in filas]
        total = sum(r["mesas"] for r in ranking)
        top = dict(ranking[0], pct_entregas=42, activo_desde="07:12")
        top["total"] = total
        return {"top": top, "ranking": ranking}

    # ---- métrica 3 ------------------------------------------------------
    def uso_mesas(self, periodo):
        f = _FACTOR.get(periodo, 1)
        mesas = []
        for i in range(1, 11):
            x, y = _POS[i]
            mesas.append({"id": i, "codigo": f"M{i}", "usos": _USOS[i] * f, "x": x, "y": y, "w": _W, "h": _H})
        orden = sorted(mesas, key=lambda m: -m["usos"])
        return {"mesas": mesas, "orden": orden, "mas_usada": orden[0], "menos_usada": orden[-1],
                "plano": {"ancho": 342, "alto": 292, "caja": {"x": 212, "y": 208, "w": 114, "h": 64}, "fusiones": []}}

    # ---- detalle de mesa ------------------------------------------------
    def mesa(self, mesa_id):
        if mesa_id not in _POS:
            return None
        ahora = timezone.now()
        seg = _ESPERA_S.get(mesa_id)
        est = _ESTADO[mesa_id]
        desde = ahora - timedelta(seconds=seg) if seg else None
        actividad = []
        if desde:
            actividad.append({"hora": timezone.localtime(desde).strftime("%H:%M"), "titulo": "Mesa ocupada",
                              "detalle": f"{_PERSONAS.get(mesa_id, 0)} personas detectadas", "tono": "ocupada"})
            if _ENTREGAS.get(mesa_id):
                actividad.append({"hora": timezone.localtime(desde + timedelta(seconds=420)).strftime("%H:%M"),
                                  "titulo": "1.ª entrega", "detalle": "Llegó parte del pedido", "tono": "libre"})
            actividad.append({"hora": "Ahora", "titulo": "Esperando siguiente entrega" if _ENTREGAS.get(mesa_id) else "Esperando la primera entrega",
                              "detalle": "El temporizador sigue corriendo", "tono": "casi_libre"})
        return {"id": mesa_id, "codigo": f"M{mesa_id}", "estado": est, "personas": _PERSONAS.get(mesa_id, 0),
                "desde": desde, "entregas": _ENTREGAS.get(mesa_id, 0), "promedio_s": _PROMEDIO_S,
                "actividad": actividad}

    # ---- evidencia ------------------------------------------------------
    def evidencias(self, tipo=None):
        todos = [
            {"id": 1, "titulo": "Mesa 6 · Entrega", "tipo": "entrega", "hora": "13:09", "detalle": "P-02", "duracion_s": 12, "url": "", "mesa_id": 6},
            {"id": 2, "titulo": "Mesa 6 · Ocupación", "tipo": "ocupacion", "hora": "13:02", "detalle": "3 personas", "duracion_s": 15, "url": "", "mesa_id": 6},
            {"id": 3, "titulo": "Mesas 7 + 8 · Fusión", "tipo": "fusion", "hora": "12:58", "detalle": "7 personas", "duracion_s": 20, "url": "", "mesa_id": 7},
            {"id": 4, "titulo": "Mesa 2 · Ocupación", "tipo": "ocupacion", "hora": "12:55", "detalle": "2 personas", "duracion_s": 15, "url": "", "mesa_id": 2},
        ]
        return [c for c in todos if not tipo or c["tipo"] == tipo]

    # ---- ajustes --------------------------------------------------------
    def ajustes(self):
        return dict(self._ajustes)

    def guardar_ajustes(self, datos):
        self._ajustes.update(datos)

    # ---- zonas ----------------------------------------------------------
    def zonas(self):
        return {"ancho": 800, "alto": 450, "frame_url": "", "zonas": copy.deepcopy(self._zonas)}

    def guardar_zonas(self, zonas):
        self._zonas = copy.deepcopy(zonas)
