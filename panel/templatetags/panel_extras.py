import math

from django import template
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

register = template.Library()

ETIQUETAS = {"libre": "Libre", "casi_libre": "Casi libre", "ocupada": "Ocupada"}


@register.filter
def mmss(segundos):
    """768 -> '12:48' (o '1:02:05' si pasa de una hora)."""
    try:
        s = max(0, int(segundos))
    except (TypeError, ValueError):
        return "--:--"
    h, resto = divmod(s, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@register.filter
def minseg(segundos):
    """400 -> '6:40' (minutos sin cero a la izquierda)."""
    try:
        s = max(0, int(segundos))
    except (TypeError, ValueError):
        return "-"
    return f"{s // 60}:{s % 60:02d}"


@register.filter
def con_signo(segundos):
    """65 -> '+1:05', -65 -> '−1:05', None -> '—' (sin datos para comparar)."""
    try:
        s = int(segundos)
    except (TypeError, ValueError):
        return "—"
    return ("+" if s >= 0 else "−") + minseg(abs(s))


@register.filter
def etiqueta_estado(estado):
    return ETIQUETAS.get(estado, estado)


@register.filter
def coma(valor, decimales=2):
    """0.5 -> '0,50' (formato es-EC)."""
    try:
        return f"{float(valor):.{int(decimales)}f}".replace(".", ",")
    except (TypeError, ValueError):
        return ""


@register.simple_tag
def nivel(segundos, promedio):
    """'ok' (a tiempo), 'cerca' (>=80 % del promedio) o 'tarde' (sobre el promedio)."""
    try:
        f = float(segundos) / float(promedio)
    except (TypeError, ValueError, ZeroDivisionError):
        return "ok"
    return "tarde" if f > 1 else ("cerca" if f >= 0.8 else "ok")


@register.simple_tag
def porcentaje(valor, maximo):
    try:
        return max(0, min(100, round(float(valor) * 100 / float(maximo))))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.simple_tag
def pos(valor, total):
    """Convierte una coordenada en % del plano (para posicionar mesas de forma fluida)."""
    return f"{float(valor) * 100 / float(total):.3f}".rstrip("0").rstrip(".")


@register.simple_tag
def anillo(segundos, promedio, total=None):
    """Temporizador circular (SVG). Verde: a tiempo · limón: cerca del promedio · coral: demorado."""
    r = 96
    circ = 2 * math.pi * r
    promedio = max(1, int(promedio or 0))  # sin entregas registradas aún no hay promedio
    total = int(total or max(1200, promedio * 1.75))
    seg = max(0, int(segundos))
    frac_prom = promedio / total
    frac_act = min(seg, total) / total

    def arco(a, b, color, ancho=14, cap="butt"):
        return (f'<circle class="ring-seg" cx="120" cy="120" r="{r}" fill="none" stroke="{color}" '
                f'stroke-width="{ancho}" stroke-linecap="{cap}" stroke-dasharray="{(b - a) * circ:.1f} {circ:.1f}" '
                f'stroke-dashoffset="{-a * circ:.1f}" transform="rotate(-90 120 120)"/>')

    ang = math.radians(-90 + frac_prom * 360)
    mx, my = 120 + r * math.cos(ang), 120 + r * math.sin(ang)
    nv = "ok" if seg / promedio < 0.8 else ("cerca" if seg / promedio <= 1 else "tarde")
    svg = (
        f'<svg class="ring" data-nivel="{nv}" data-prom="{promedio}" data-total="{total}" viewBox="0 0 240 240" '
        f'role="img" aria-label="Tiempo de espera {seg // 60} minutos {seg % 60} segundos; el promedio es {promedio // 60} minutos">'
        + arco(0, frac_prom * 0.8, "var(--libre-bg)")
        + arco(frac_prom * 0.8, frac_prom, "var(--casi-bg)")
        + arco(frac_prom, 1, "var(--ocu-bg)")
        + f'<circle class="ring-prog" cx="120" cy="120" r="{r}" fill="none" stroke-width="14" stroke-linecap="round" '
          f'stroke-dasharray="{frac_act * circ:.1f} {circ:.1f}" transform="rotate(-90 120 120)"/>'
        + f'<circle class="ring-marca" cx="{mx:.1f}" cy="{my:.1f}" r="7"/>'
        + "</svg>"
    )
    return mark_safe(svg)


# ---------------------------------------------------------------- íconos
ICONOS = {
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "users": '<path d="M16 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1"/><circle cx="9" cy="8" r="3.5"/><path d="M22 20v-1a4 4 0 0 0-3-3.8"/><path d="M16 4.2a3.5 3.5 0 0 1 0 6.6"/>',
    "chart": '<path d="M5 20V11"/><path d="M12 20V5"/><path d="M19 20v-6"/><path d="M3 20h18"/>',
    "video": '<rect x="2" y="6" width="14" height="12" rx="2"/><path d="M16 10l6-3v10l-6-3z"/>',
    "settings": '<path d="M4 6h9"/><path d="M19 6h1"/><circle cx="16" cy="6" r="2.5"/><path d="M4 12h2"/><path d="M12 12h8"/><circle cx="9" cy="12" r="2.5"/><path d="M4 18h11"/><circle cx="18" cy="18" r="2.5"/>',
    "left": '<path d="M15 18l-6-6 6-6"/>',
    "right": '<path d="M9 18l6-6-6-6"/>',
    "camera": '<path d="M4 7h3l2-3h6l2 3h3a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="4"/>',
    "play": '<path d="M8 5l11 7-11 7z"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16 9.5"/>',
    "star": '<path d="M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.2L12 17.4l-5.5 2.9 1-6.2L3 9.7l6.2-.9z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><path d="M12 16.5h.01"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
    "scan": '<path d="M4 8V5a1 1 0 0 1 1-1h3"/><path d="M16 4h3a1 1 0 0 1 1 1v3"/><path d="M20 16v3a1 1 0 0 1-1 1h-3"/><path d="M8 20H5a1 1 0 0 1-1-1v-3"/><rect x="8.5" y="8.5" width="7" height="7" rx="1.5"/>',
    "poly": '<path d="M12 3l8.5 6.5-3.3 10.5H6.8L3.5 9.5z"/>',
    "cursor": '<path d="M5 3l14 7-6 2-2 6z"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    "cash": '<rect x="3" y="7" width="18" height="12" rx="2"/><circle cx="12" cy="13" r="2.5"/><path d="M6 4h12"/>',
    "download": '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M4 20h16"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
}


@register.simple_tag
def icon(nombre, tam=20, trazo="1.8"):
    """Ícono de línea en SVG (hereda el color del texto)."""
    cuerpo = ICONOS.get(nombre, "")
    return mark_safe(
        f'<svg class="icon" width="{tam}" height="{tam}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="{trazo}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{cuerpo}</svg>'
    )


# ---------------------------------------------------------------- textos
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


@register.filter
def fecha_larga(fecha):
    """'Martes 29 de septiembre' (independiente del idioma configurado)."""
    if not fecha:
        return ""
    f = timezone.localtime(fecha) if timezone.is_aware(fecha) else fecha
    return f"{DIAS[f.weekday()]} {f.day} de {MESES[f.month - 1]}"


@register.simple_tag
def delta_texto(segundos, promedio):
    """'+1:28 sobre el promedio' o '1:10 bajo el promedio'."""
    try:
        d = int(segundos) - int(promedio)
    except (TypeError, ValueError):
        return ""
    signo = "+" if d > 0 else ""
    cuerpo = minseg(abs(d))
    return f"{signo}{cuerpo} sobre el promedio" if d > 0 else f"{cuerpo} bajo el promedio"


@register.simple_tag
def nav_items():
    """Secciones del panel (móvil: barra inferior · escritorio: menú lateral)."""
    filas = [
        ("inicio", "panel:inicio", "Inicio", "Inicio", "grid", True),
        ("espera", "panel:espera", "Espera", "Tiempo de espera", "clock", True),
        ("personal", "panel:personal", "Personal", "Personal", "users", True),
        ("uso_mesas", "panel:uso_mesas", "Mesas", "Uso de mesas", "chart", True),
        ("evidencia", "panel:evidencia", "Videos", "Evidencia", "video", True),
        ("zonas", "panel:zonas", "Zonas", "Zonas y cámaras", "poly", False),
        ("ajustes", "panel:ajustes", "Ajustes", "Ajustes", "settings", False),
    ]
    return [{"clave": c, "url": reverse(u), "corto": corto, "largo": largo, "icono": ic, "movil": mv}
            for c, u, corto, largo, ic, mv in filas]


@register.simple_tag
def barra_espera(segundos, promedio):
    """Ancho (%) de la barra de una fila de espera: llena al 120 % del promedio."""
    try:
        return max(2, min(100, round(float(segundos) * 100 / (float(promedio) * 1.2))))
    except (TypeError, ValueError, ZeroDivisionError):
        return 2
