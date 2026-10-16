from django.conf import settings


def panel(request):
    return {
        "nombre_local": getattr(settings, "PANEL_NOMBRE_LOCAL", "Encebollados X"),
        "nombre_sistema": "ScanEats",
    }
