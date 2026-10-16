from django.urls import path

from . import views

app_name = "panel"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("acceso/", views.AccesoView.as_view(), name="login"),
    path("salir/", views.salir, name="logout"),
    path("espera/", views.espera, name="espera"),
    path("mesas/<int:mesa_id>/", views.mesa_detalle, name="mesa"),
    path("evidencia/", views.evidencia, name="evidencia"),
    path("personal/", views.personal, name="personal"),
    path("uso-mesas/", views.uso_mesas, name="uso_mesas"),
    path("ajustes/", views.ajustes, name="ajustes"),
    path("zonas/", views.zonas, name="zonas"),
    path("zonas/guardar/", views.zonas_guardar, name="zonas_guardar"),
    path("zonas/frame/", views.zonas_frame, name="zonas_frame"),
    path("api/estado/", views.api_estado, name="api_estado"),
]
