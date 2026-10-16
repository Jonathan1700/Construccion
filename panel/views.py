import json

from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .forms import AjustesForm, LoginForm
from .services import get_backend
from .services.base import PERIODOS, TIPOS_EVENTO

ETIQUETA_PERIODO = {"hoy": "Hoy", "semana": "Semana", "mes": "Mes"}
ETIQUETA_TIPO = {"": "Todos", "ocupacion": "Ocupación", "entrega": "Entrega", "fusion": "Fusión"}


def _periodo(request):
    p = request.GET.get("periodo", "hoy")
    return p if p in PERIODOS else "hoy"


def _con_segundos(filas, ahora=None):
    """Agrega ``segundos`` (tiempo transcurrido) a cada fila que tenga ``desde``."""
    ahora = ahora or timezone.now()
    for f in filas:
        f["segundos"] = max(0, int((ahora - f["desde"]).total_seconds())) if f.get("desde") else 0
        f["desde_iso"] = f["desde"].isoformat() if f.get("desde") else ""
    return filas


def _periodos(request, actual):
    """Opciones del selector Hoy · Semana · Mes (enlaces, funcionan sin JavaScript)."""
    q = request.GET.copy()
    opciones = []
    for clave in PERIODOS:
        q["periodo"] = clave
        opciones.append({"clave": clave, "etiqueta": ETIQUETA_PERIODO[clave], "url": "?" + q.urlencode(), "activo": clave == actual})
    return opciones


def _mesas_estado(est):
    """Mesas del plano coloreadas por estado (libre · casi libre · ocupada)."""
    etiquetas = {"libre": "Libre", "casi_libre": "Casi libre", "ocupada": "Ocupada"}
    return [dict(m, clase=f"mesa--{m['estado']}", sub=etiquetas.get(m["estado"], "")) for m in est["mesas"]]


def _mesas_calor(uso):
    """Mesas del plano coloreadas por uso relativo (mapa de calor)."""
    tope = max(uso["mas_usada"]["usos"], 1)
    salida = []
    for m in uso["mesas"]:
        f = m["usos"] / tope
        nivel = 4 if f >= 0.8 else 3 if f >= 0.55 else 2 if f >= 0.3 else 1
        salida.append(dict(m, clase=f"mesa--h{nivel}", sub=f"{m['usos']} usos"))
    return salida


def _ctx(request, activo, **extra):
    base = {"activo": activo, "hoy": timezone.localtime()}
    base.update(extra)
    return base


# ------------------------------------------------------------------ acceso
class AccesoView(View):
    template = "panel/login.html"

    def _siguiente(self, request):
        destino = request.POST.get("next") or request.GET.get("next") or ""
        if destino and url_has_allowed_host_and_scheme(destino, {request.get_host()}, request.is_secure()):
            return destino
        return reverse("panel:inicio")

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(self._siguiente(request))
        return render(request, self.template, {"form": LoginForm(request), "next": request.GET.get("next", "")})

    def post(self, request):
        form = LoginForm(request, request.POST)
        if form.is_valid():
            login(request, form.usuario)
            request.session.set_expiry(60 * 60 * 24 * 14 if form.cleaned_data.get("recordarme") else 0)
            return redirect(self._siguiente(request))
        return render(request, self.template, {"form": form, "next": request.POST.get("next", "")}, status=200)


@require_POST
def salir(request):
    logout(request)
    return redirect("panel:login")


# ------------------------------------------------------------------ pantallas
@login_required
def inicio(request):
    est = get_backend().estado()
    _con_segundos(est["en_espera"])
    _con_segundos(est["mesas"])
    resumen = est["resumen"]
    esp = get_backend().espera("hoy")
    per = get_backend().personal("hoy")
    uso = get_backend().uso_mesas("hoy")
    return render(request, "panel/inicio.html", _ctx(
        request, "inicio", est=est, resumen=resumen, esp=esp, per=per, uso=uso, mesas_plano=_mesas_estado(est),
        mesas_orden=uso["orden"], max_uso=uso["mas_usada"]["usos"],
        max_hora=max((h["min"] for h in esp["por_hora"]), default=1),
        max_mesas=per["ranking"][0]["mesas"] if per["ranking"] else 1))


@login_required
def espera(request):
    periodo = _periodo(request)
    esp = get_backend().espera(periodo)
    _con_segundos(esp["en_curso"])
    return render(request, "panel/espera.html", _ctx(
        request, "espera", esp=esp, periodo=periodo, periodos=_periodos(request, periodo),
        max_hora=max((h["min"] for h in esp["por_hora"]), default=1)))


@login_required
def mesa_detalle(request, mesa_id):
    m = get_backend().mesa(mesa_id)
    if m is None:
        raise Http404("La mesa no existe")
    _con_segundos([m])
    return render(request, "panel/mesa_detalle.html", _ctx(request, "espera", m=m))


@login_required
def evidencia(request):
    tipo = request.GET.get("tipo", "")
    tipo = tipo if tipo in TIPOS_EVENTO else ""
    clips = get_backend().evidencias(tipo or None)
    sel_id = request.GET.get("clip")
    seleccionado = next((c for c in clips if str(c["id"]) == str(sel_id)), clips[0] if clips else None)
    filtros = [{"clave": k, "etiqueta": v, "activo": k == tipo} for k, v in ETIQUETA_TIPO.items()]
    return render(request, "panel/evidencia.html", _ctx(
        request, "evidencia", clips=clips, sel=seleccionado, filtros=filtros, tipo=tipo))


@login_required
def personal(request):
    periodo = _periodo(request)
    per = get_backend().personal(periodo)
    return render(request, "panel/personal.html", _ctx(
        request, "personal", per=per, periodo=periodo, periodos=_periodos(request, periodo),
        max_mesas=per["ranking"][0]["mesas"] if per["ranking"] else 1))


@login_required
def uso_mesas(request):
    periodo = _periodo(request)
    uso = get_backend().uso_mesas(periodo)
    return render(request, "panel/uso_mesas.html", _ctx(
        request, "uso_mesas", uso=uso, periodo=periodo, periodos=_periodos(request, periodo), mesas_calor=_mesas_calor(uso),
        max_uso=uso["mas_usada"]["usos"]))


@login_required
def ajustes(request):
    be = get_backend()
    guardado = False
    if request.method == "POST":
        form = AjustesForm(request.POST)
        if form.is_valid():
            be.guardar_ajustes(form.cleaned_data)
            return redirect(reverse("panel:ajustes") + "?guardado=1")
    else:
        inicial = be.ajustes()
        form = AjustesForm(initial=inicial)
        guardado = request.GET.get("guardado") == "1"
    est = be.estado()
    return render(request, "panel/ajustes.html", _ctx(
        request, "ajustes", form=form, guardado=guardado, camara=est["camara"], ajustes=be.ajustes()))


@login_required
@ensure_csrf_cookie
def zonas(request):
    z = get_backend().zonas()
    return render(request, "panel/zonas.html", _ctx(request, "zonas", z=z))


@login_required
@require_POST
def zonas_guardar(request):
    try:
        datos = json.loads(request.body.decode("utf-8"))
        zonas_lista = datos["zonas"]
        limpias = []
        for i, z in enumerate(zonas_lista, start=1):
            puntos = [[round(float(x), 1), round(float(y), 1)] for x, y in z["puntos"]]
            tipo = z.get("tipo", "mesa")
            if tipo not in ("mesa", "caja") or len(puntos) < 3:
                raise ValueError("Cada zona necesita al menos 3 vértices")
            nombre = str(z.get("nombre", "")).strip()[:40]
            if not nombre:
                raise ValueError("Cada zona necesita un nombre")
            cap = z.get("capacidad")
            limpias.append({"id": z.get("id") or i, "nombre": nombre, "tipo": tipo,
                            "capacidad": int(cap) if cap not in (None, "") else None,
                            "adyacentes": [str(a)[:8] for a in z.get("adyacentes", [])][:12], "puntos": puntos})
        get_backend().guardar_zonas(limpias)
    except (ValueError, KeyError, TypeError) as e:
        return JsonResponse({"ok": False, "error": str(e) or "Datos no válidos"}, status=400)
    mesas = sum(1 for z in limpias if z["tipo"] == "mesa")
    cajas = sum(1 for z in limpias if z["tipo"] == "caja")
    return JsonResponse({"ok": True, "mesas": mesas, "cajas": cajas})


@login_required
def zonas_frame(request):
    """Fotograma de referencia de la cámara para el editor de zonas (solo con ApiBackend)."""
    from .services.api import ruta_frame

    ruta = ruta_frame()
    if ruta is None:
        raise Http404("No hay fotograma de referencia")
    return FileResponse(ruta.open("rb"))


@login_required
def api_estado(request):
    """JSON liviano para refrescar contadores en vivo sin recargar la página."""
    est = get_backend().estado()
    _con_segundos(est["en_espera"])
    return JsonResponse({
        "resumen": est["resumen"], "camara": est["camara"],
        "mesas": [{"id": m["id"], "estado": m["estado"]} for m in est["mesas"]],
        "en_espera": [{"mesa_id": f["mesa_id"], "segundos": f["segundos"]} for f in est["en_espera"]],
    })
