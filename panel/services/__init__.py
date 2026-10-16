"""Capa de datos del panel.

Las vistas nunca tocan modelos ni la API directamente: piden todo a un *backend*
(ver ``services/base.py`` para el contrato). Así la interfaz se puede probar con datos
de ejemplo (``DemoBackend``) y conectar al sistema real cambiando un solo ajuste:

    PANEL_BACKEND = "panel.services.demo.DemoBackend"      # por defecto
    PANEL_BACKEND = "panel.services.api.ApiBackend"        # datos reales de ScanEats
"""
from functools import lru_cache

from django.conf import settings
from django.utils.module_loading import import_string


@lru_cache(maxsize=1)
def get_backend():
    ruta = getattr(settings, "PANEL_BACKEND", "panel.services.demo.DemoBackend")
    return import_string(ruta)()
