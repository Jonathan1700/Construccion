"""Backend con los datos reales de ScanEats.

Lee directamente los modelos de ``monitoreo`` (los mismos que alimentan la API DRF y
sus 3 métricas) y la config de zonas/parámetros del microservicio de visión
(``settings.PANEL_CONFIG_VISION``, la misma que recibe ``vision_service.pipeline --config``):

    PANEL_BACKEND = "panel.services.api.ApiBackend"

Correspondencia con el sistema:
    estado(), mesa()   -> EventoOcupacion abiertos (fin=None) + EventoEntrega
    espera()           -> métrica 1 (tiempo_espera_segundos de EventoEntrega)
    personal()         -> métrica 2 (EventoEntrega por Personal)
    uso_mesas()        -> métrica 3 (EventoOcupacion por Mesa, sin contar las fusionadas)
    evidencias()       -> EventoOcupacion con clip_s3_key (clip en S3)
    ajustes(), zonas() -> config JSON del pipeline (+ Mesa.zona_poligono al guardar zonas)

El pipeline solo reporta ocupaciones "ocupada" / "liberada" / "fusionada", así que el
estado "casi libre" (gracia de liberación) no llega a la API y aquí no se muestra.
"""
import json
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, Max, Min, Q
from django.urls import reverse
from django.utils import timezone

from monitoreo.models import EventoEntrega, EventoOcupacion, Mesa, Personal

from .base import PanelBackend

PARAMETROS_DEFAULT = {
    "periodo_gracia_segundos": 45,
    "timeout_objeto_abandonado_segundos": 120,
    "umbral_overlap_ocupacion": 0.45,
    "umbral_overlap_liberacion": 0.1,
    "umbral_overlap_visita_staff": 0.3,
    "exceso_personas_para_fusion": 1,
}
try:  # mismos defaults que la herramienta de calibración, si el paquete está disponible
    from vision_service.calibracion import PARAMETROS_DEFAULT as _PARAMS_CALIBRACION

    PARAMETROS_DEFAULT.update(_PARAMS_CALIBRACION)
except Exception:  # pragma: no cover - el panel no debe depender del microservicio
    pass

CONFIANZA_DEFAULT = 0.4  # umbral por defecto de vision_service.detector.DetectorYOLO
ABIERTA = Q(fin__isnull=True) & ~Q(estado=EventoOcupacion.Estado.LIBERADA)
SIN_DATO = {"id": 0, "codigo": "—", "usos": 0}


# ------------------------------------------------------------------ utilidades
def _codigo(mesa):
    return f"M{mesa.numero}"


def _inicio_periodo(periodo):
    hoy = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return hoy - timedelta(days={"semana": 6, "mes": 29}.get(periodo, 0))


def _hora(dt):
    return timezone.localtime(dt).strftime("%H:%M")


def _bbox(puntos):
    xs, ys = [p[0] for p in puntos], [p[1] for p in puntos]
    return {"x": min(xs), "y": min(ys), "w": max(max(xs) - min(xs), 1), "h": max(max(ys) - min(ys), 1)}


def _union(cajas):
    x0, y0 = min(c["x"] for c in cajas), min(c["y"] for c in cajas)
    x1, y1 = max(c["x"] + c["w"] for c in cajas), max(c["y"] + c["h"] for c in cajas)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _numero_de(nombre):
    """'Mesa 12' / 'M12' -> 12 (None si el nombre no trae número)."""
    m = re.search(r"\d+", str(nombre))
    return int(m.group()) if m else None


def _promedio(valor):
    return round(valor) if valor is not None else None


# ------------------------------------------------------------------ config del pipeline
def _ruta_config():
    return Path(getattr(settings, "PANEL_CONFIG_VISION", "vision_service/config/mesas_zonas.json"))


def leer_config():
    try:
        data = json.loads(_ruta_config().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("camara_id", "cam-1")
    data.setdefault("mesas", [])
    data["parametros"] = {**PARAMETROS_DEFAULT, **data.get("parametros", {})}
    return data


def escribir_config(data):
    ruta = _ruta_config()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tamano_frame(cfg):
    """Resolución del frame calibrado. La config no siempre la trae: se infiere de los polígonos."""
    frame = cfg.get("frame") or {}
    if frame.get("ancho") and frame.get("alto"):
        return int(frame["ancho"]), int(frame["alto"])
    imagen = ruta_frame()
    if imagen and imagen.suffix == ".png":
        with imagen.open("rb") as fh:
            cabecera = fh.read(24)  # PNG: ancho y alto en el chunk IHDR (bytes 16-24)
        if cabecera[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(cabecera[16:20], "big"), int.from_bytes(cabecera[20:24], "big")
    puntos = [p for m in cfg.get("mesas", []) for p in m.get("poligono", [])]
    puntos += [p for z in cfg.get("zonas_excluidas", []) for p in z.get("poligono", [])]
    max_x = max((p[0] for p in puntos), default=0)
    max_y = max((p[1] for p in puntos), default=0)
    for ancho, alto in ((640, 480), (1280, 720), (1920, 1080), (2560, 1440)):
        if max_x <= ancho and max_y <= alto:
            return ancho, alto
    return int(max_x) + 1, int(max_y) + 1


def ruta_frame():
    """Imagen de referencia para el editor de zonas: `<config>.frame.png` o el preview de calibración."""
    base = _ruta_config()
    for sufijo in (".frame.png", ".frame.jpg", ".preview.png"):
        candidato = base.with_suffix(sufijo)
        if candidato.is_file():
            return candidato
    return None


# ------------------------------------------------------------------ backend
class ApiBackend(PanelBackend):
    # ---- geometría del plano ------------------------------------------
    def _plano(self, mesas, cfg):
        """Ubica cada mesa según el bounding box de su zona en el frame de la cámara."""
        ancho, alto = tamano_frame(cfg)
        poligonos_cfg = {m["mesa_id"]: m.get("poligono") for m in cfg["mesas"]}
        cajas, sin_zona = {}, []
        for m in mesas:
            puntos = m.zona_poligono or poligonos_cfg.get(m.id)
            if puntos and len(puntos) >= 3:
                cajas[m.id] = _bbox(puntos)
            else:
                sin_zona.append(m)
        # Mesas sin zona calibrada: una fila al pie del plano, para que igual se vean.
        lado = ancho / 12
        for i, m in enumerate(sin_zona):
            cajas[m.id] = {"x": lado * 0.2 + i * lado * 1.2, "y": alto - lado * 1.2, "w": lado, "h": lado}
        excluidas = [z["poligono"] for z in cfg.get("zonas_excluidas", []) if len(z.get("poligono", [])) >= 3]
        caja = _bbox(excluidas[0]) if excluidas else None
        return cajas, {"ancho": ancho, "alto": alto, "caja": caja, "fusiones": []}

    def _ultima_actividad(self):
        fechas = [
            EventoOcupacion.objects.aggregate(v=Max("inicio"))["v"],
            EventoOcupacion.objects.aggregate(v=Max("fin"))["v"],
            EventoEntrega.objects.aggregate(v=Max("timestamp"))["v"],
        ]
        fechas = [f for f in fechas if f]
        return max(fechas) if fechas else None

    def _abiertas(self):
        """Ocupación en curso por mesa (la más reciente si hubiera más de una)."""
        qs = (EventoOcupacion.objects.filter(ABIERTA, mesa__activa=True)
              .select_related("mesa").annotate(n_entregas=Count("entregas")).order_by("inicio"))
        return {o.mesa_id: o for o in qs}

    # ---- estado en vivo -------------------------------------------------
    def estado(self):
        cfg = leer_config()
        mesas = list(Mesa.objects.filter(activa=True))
        abiertas = self._abiertas()
        cajas, plano = self._plano(mesas, cfg)

        filas = []
        for m in mesas:
            o = abiertas.get(m.id)
            filas.append({
                "id": m.id, "codigo": _codigo(m), "estado": "ocupada" if o else "libre",
                "personas": o.num_personas_detectadas if o else 0,
                "desde": o.inicio if o else None, "entregas": o.n_entregas if o else 0,
                **cajas[m.id],
            })

        # Fusiones: la ocupación "hija" (estado fusionada) se muestra junto a la de su mesa vecina.
        por_id = {o.id: o for o in abiertas.values()}
        hijas = {}
        for o in abiertas.values():
            if o.fusionada_con_id in por_id and o.fusionada_con_id != o.id:
                hijas.setdefault(o.fusionada_con_id, []).append(o)
        ids_hijas = {h.id for hs in hijas.values() for h in hs}

        en_espera = []
        for o in sorted(abiertas.values(), key=lambda o: o.inicio):
            if o.id in ids_hijas:
                continue
            grupo = [o] + hijas.get(o.id, [])
            en_espera.append({
                "mesa_id": o.mesa_id, "codigo": "+".join(_codigo(g.mesa) for g in grupo),
                "personas": sum(g.num_personas_detectadas for g in grupo),
                "entregas": sum(g.n_entregas for g in grupo),
                "desde": min(g.inicio for g in grupo), "fusion": len(grupo) > 1,
            })
            if len(grupo) > 1:
                plano["fusiones"].append({**_union([cajas[g.mesa_id] for g in grupo]),
                                          "mesas": [_codigo(g.mesa) for g in grupo]})

        ocupadas = sum(1 for f in filas if f["estado"] == "ocupada")
        ultima = self._ultima_actividad()
        sin_senal = timedelta(minutes=getattr(settings, "PANEL_MINUTOS_SIN_SENAL", 30))
        camara_id = cfg.get("camara_id") or (mesas[0].camara_id if mesas else "")
        return {
            "camara": {
                "nombre": f"Cámara · {camara_id}" if camara_id else "Cámara",
                "en_vivo": bool(abiertas) or bool(ultima and timezone.now() - ultima <= sin_senal),
                "mesas": len(mesas), "zonas_excluidas": len(cfg.get("zonas_excluidas", [])),
            },
            "resumen": {
                "total": len(filas), "libres": len(filas) - ocupadas, "casi_libres": 0, "ocupadas": ocupadas,
                "personas": sum(f["personas"] for f in filas),
                "espera_prom_s": self._promedio_espera(_inicio_periodo("hoy")),
            },
            "mesas": filas,
            "plano": plano,
            "en_espera": en_espera,
        }

    # ---- métrica 1 ------------------------------------------------------
    def _promedio_espera(self, desde, hasta=None):
        qs = EventoEntrega.objects.filter(timestamp__gte=desde)
        if hasta:
            qs = qs.filter(timestamp__lt=hasta)
        return _promedio(qs.aggregate(v=Avg("tiempo_espera_segundos"))["v"])

    def espera(self, periodo):
        desde = _inicio_periodo(periodo)
        entregas = EventoEntrega.objects.filter(timestamp__gte=desde)
        agg = entregas.aggregate(prom=Avg("tiempo_espera_segundos"), max=Max("tiempo_espera_segundos"),
                                 min=Min("tiempo_espera_segundos"))

        # Comparación contra el período anterior de igual duración (para "hoy": ayer).
        dias = (timezone.localtime() - desde).days + 1
        anterior = self._promedio_espera(desde - timedelta(days=dias), desde)
        delta = agg["prom"] - anterior if agg["prom"] is not None and anterior is not None else None

        por_hora = {}
        for ts, seg in entregas.values_list("timestamp", "tiempo_espera_segundos"):
            por_hora.setdefault(timezone.localtime(ts).hour, []).append(seg)
        return {
            "promedio_s": _promedio(agg["prom"]), "max_s": agg["max"], "min_s": agg["min"],
            "delta_ayer_s": _promedio(delta),
            "en_curso": self.estado()["en_espera"],
            "por_hora": [{"hora": h, "min": round(sum(v) / len(v) / 60, 1)} for h, v in sorted(por_hora.items())],
        }

    # ---- métrica 2 ------------------------------------------------------
    def personal(self, periodo):
        f = Q(entregas__timestamp__gte=_inicio_periodo(periodo))
        qs = (Personal.objects
              .annotate(mesas=Count("entregas__evento_ocupacion", filter=f, distinct=True),
                        n_entregas=Count("entregas", filter=f),
                        respuesta=Avg("entregas__tiempo_espera_segundos", filter=f),
                        primera=Min("entregas__timestamp", filter=f))
              .filter(n_entregas__gt=0).order_by("-mesas", "-n_entregas"))
        filas = list(qs)
        ranking = [{"codigo": p.alias or f"P-{p.id:02d}", "mesas": p.mesas, "respuesta_s": _promedio(p.respuesta)}
                   for p in filas]
        if not filas:
            top = {"codigo": "—", "mesas": 0, "respuesta_s": None, "pct_entregas": 0, "activo_desde": "—", "total": 0}
            return {"top": top, "ranking": []}
        total_entregas = sum(p.n_entregas for p in filas)
        top = dict(ranking[0], pct_entregas=round(100 * filas[0].n_entregas / total_entregas),
                   activo_desde=_hora(filas[0].primera), total=sum(r["mesas"] for r in ranking))
        return {"top": top, "ranking": ranking}

    # ---- métrica 3 ------------------------------------------------------
    def uso_mesas(self, periodo):
        cfg = leer_config()
        # Igual que /api/metricas/uso-mesas/: las ocupaciones fusionadas no suman uso a su mesa.
        f = Q(eventos_ocupacion__inicio__gte=_inicio_periodo(periodo)) & Q(
            eventos_ocupacion__estado__in=[e for e in EventoOcupacion.Estado if e != EventoOcupacion.Estado.FUSIONADA])
        mesas = list(Mesa.objects.filter(activa=True).annotate(usos=Count("eventos_ocupacion", filter=f)))
        cajas, plano = self._plano(mesas, cfg)
        filas = [{"id": m.id, "codigo": _codigo(m), "usos": m.usos, **cajas[m.id]} for m in mesas]
        orden = sorted(filas, key=lambda m: -m["usos"])
        return {"mesas": filas, "orden": orden, "plano": plano,
                "mas_usada": orden[0] if orden else SIN_DATO, "menos_usada": orden[-1] if orden else SIN_DATO}

    # ---- detalle de mesa ------------------------------------------------
    def mesa(self, mesa_id):
        m = Mesa.objects.filter(pk=mesa_id).first()
        if m is None:
            return None
        o = (EventoOcupacion.objects.filter(ABIERTA, mesa=m).select_related("fusionada_con__mesa")
             .order_by("-inicio").first())
        promedio = self._promedio_espera(_inicio_periodo("hoy")) or self._promedio_espera(_inicio_periodo("mes"))
        actividad, entregas = [], []
        if o:
            entregas = list(o.entregas.select_related("personal"))
            actividad.append({"hora": _hora(o.inicio), "titulo": "Mesa ocupada", "tono": "ocupada",
                              "detalle": f"{o.num_personas_detectadas} persona{'s' if o.num_personas_detectadas != 1 else ''} detectada{'s' if o.num_personas_detectadas != 1 else ''}"})
            if o.fusionada_con_id and o.fusionada_con:
                actividad.append({"hora": _hora(o.inicio), "titulo": "Mesas unidas", "tono": "casi_libre",
                                  "detalle": f"Se unió con {_codigo(o.fusionada_con.mesa)}"})
            for i, e in enumerate(entregas, start=1):
                quien = (e.personal.alias or f"P-{e.personal.id:02d}") if e.personal else "personal sin identificar"
                actividad.append({"hora": _hora(e.timestamp), "titulo": f"{i}.ª entrega", "tono": "libre",
                                  "detalle": f"{e.get_tipo_display()} · {quien} · a los {e.tiempo_espera_segundos // 60} min"})
            actividad.append({"hora": "Ahora", "tono": "casi_libre", "detalle": "El temporizador sigue corriendo",
                              "titulo": "Esperando siguiente entrega" if entregas else "Esperando la primera entrega"})
        return {"id": m.id, "codigo": _codigo(m), "estado": "ocupada" if o else "libre",
                "personas": o.num_personas_detectadas if o else 0, "desde": o.inicio if o else None,
                "entregas": len(entregas), "promedio_s": promedio, "actividad": actividad}

    # ---- evidencia ------------------------------------------------------
    def evidencias(self, tipo=None):
        if tipo == "entrega":  # el pipeline graba un clip por ocupación, no por entrega
            return []
        qs = EventoOcupacion.objects.exclude(clip_s3_key="").select_related("mesa", "fusionada_con__mesa")
        fusion = Q(fusionada_con__isnull=False) | Q(estado=EventoOcupacion.Estado.FUSIONADA)
        if tipo == "fusion":
            qs = qs.filter(fusion)
        elif tipo == "ocupacion":
            qs = qs.exclude(fusion)
        hoy = timezone.localdate()
        clips = []
        for o in qs.order_by("-inicio")[:60]:
            es_fusion = bool(o.fusionada_con_id) or o.estado == EventoOcupacion.Estado.FUSIONADA
            local = timezone.localtime(o.inicio)
            titulo = (f"Mesas {o.mesa.numero} + {o.fusionada_con.mesa.numero} · Fusión" if es_fusion and o.fusionada_con
                      else f"Mesa {o.mesa.numero} · {'Fusión' if es_fusion else 'Ocupación'}")
            clips.append({
                "id": o.id, "titulo": titulo, "tipo": "fusion" if es_fusion else "ocupacion",
                "hora": local.strftime("%H:%M") if local.date() == hoy else local.strftime("%d/%m %H:%M"),
                "detalle": f"{o.num_personas_detectadas} persona{'s' if o.num_personas_detectadas != 1 else ''}",
                "duracion_s": int(o.duracion_segundos), "url": o.clip_s3_url or "", "mesa_id": o.mesa_id,
            })
        return clips

    # ---- ajustes (parámetros del pipeline) --------------------------------
    def ajustes(self):
        p = leer_config()["parametros"]
        objetos = p.get("timeout_objeto_abandonado_segundos")
        return {
            "periodo_gracia_min": max(1, round(p["periodo_gracia_segundos"] / 60)),
            "solo_objetos_min": max(1, round(objetos / 60)) if objetos else None,
            "confianza_min": p.get("confianza_minima", CONFIANZA_DEFAULT),
        }

    def guardar_ajustes(self, datos):
        cfg = leer_config()
        p = cfg["parametros"]
        actuales = self.ajustes()
        # El formulario trabaja en minutos y la config en segundos: si el valor en minutos no
        # cambió se conservan los segundos originales (ej. 45 s no se convierte en 60 s).
        if datos["periodo_gracia_min"] != actuales["periodo_gracia_min"]:
            p["periodo_gracia_segundos"] = datos["periodo_gracia_min"] * 60
        if datos.get("solo_objetos_min") is None:
            p.pop("timeout_objeto_abandonado_segundos", None)  # el pipeline usa su default
        elif datos["solo_objetos_min"] != actuales["solo_objetos_min"]:
            p["timeout_objeto_abandonado_segundos"] = datos["solo_objetos_min"] * 60
        p["confianza_minima"] = round(float(datos["confianza_min"]), 2)
        escribir_config(cfg)

    # ---- zonas ------------------------------------------------------------
    def zonas(self):
        cfg = leer_config()
        ancho, alto = tamano_frame(cfg)
        numeros = dict(Mesa.objects.values_list("id", "numero"))
        codigo = lambda mesa_id: f"M{numeros.get(mesa_id, mesa_id)}"  # noqa: E731
        zonas = [{
            "id": m["mesa_id"], "nombre": f"Mesa {numeros.get(m['mesa_id'], m['mesa_id'])}", "tipo": "mesa",
            "capacidad": m.get("capacidad"), "adyacentes": [codigo(a) for a in m.get("adyacentes", [])],
            "puntos": m["poligono"],
        } for m in cfg["mesas"]]
        siguiente = max([z["id"] for z in zonas] + [0]) + 1
        for i, z in enumerate(cfg.get("zonas_excluidas", [])):
            zonas.append({"id": siguiente + i, "nombre": z.get("nombre", "Caja"), "tipo": "caja",
                          "capacidad": None, "adyacentes": [], "puntos": z["poligono"]})
        frame_url = reverse("panel:zonas_frame") if ruta_frame() else ""
        return {"ancho": ancho, "alto": alto, "frame_url": frame_url, "zonas": zonas}

    def guardar_zonas(self, zonas):
        """Escribe la config del pipeline y sincroniza las Mesa de la API (zona, capacidad, adyacentes).

        Cada zona de mesa se asocia a la Mesa por el número de su nombre ("Mesa 3" -> numero=3);
        si no existe se crea. Las mesas de esta cámara que ya no tienen zona quedan inactivas
        (no se borran, para conservar su historial de ocupaciones).
        """
        cfg = leer_config()
        camara_id = cfg["camara_id"]
        mesas_z = [z for z in zonas if z["tipo"] == "mesa"]
        numeros = []
        for z in mesas_z:
            n = _numero_de(z["nombre"])
            if n is None:
                raise ValueError(f"«{z['nombre']}»: el nombre de la mesa debe llevar su número (ej. Mesa 3)")
            numeros.append(n)
        if len(set(numeros)) != len(numeros):
            raise ValueError("Hay dos zonas con el mismo número de mesa")

        with transaction.atomic():
            por_numero = {}
            for z, n in zip(mesas_z, numeros):
                puntos = [[round(x), round(y)] for x, y in z["puntos"]]
                mesa, _ = Mesa.objects.update_or_create(numero=n, defaults={
                    "camara_id": camara_id, "zona_poligono": puntos, "capacidad": z.get("capacidad") or 4,
                    "activa": True})
                por_numero[n] = (mesa, z, puntos)
            for mesa, z, _ in por_numero.values():
                vecinas = [por_numero[a][0] for a in map(_numero_de, z.get("adyacentes", []))
                           if a in por_numero and a != mesa.numero]
                mesa.mesas_adyacentes.set(vecinas)
            ids = [m.id for m, _, _ in por_numero.values()]
            Mesa.objects.filter(camara_id=camara_id).exclude(id__in=ids).update(activa=False)

            cfg["mesas"] = [{
                "mesa_id": mesa.id, "poligono": puntos, "capacidad": mesa.capacidad,
                "adyacentes": sorted(v.id for v in mesa.mesas_adyacentes.all()),
            } for mesa, _, puntos in por_numero.values()]
            cfg["zonas_excluidas"] = [{"nombre": z["nombre"], "poligono": [[round(x), round(y)] for x, y in z["puntos"]]}
                                      for z in zonas if z["tipo"] == "caja"]
            escribir_config(cfg)
