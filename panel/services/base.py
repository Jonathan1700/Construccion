"""Contrato de datos entre el panel y el sistema.

Cada método devuelve diccionarios simples; las plantillas solo dependen de estas claves.
Para conectar el sistema real basta con implementar estos métodos (ver ``api.py``).

Convenciones
------------
* Tiempos en segundos (``*_s``) y fechas como ``datetime`` con zona horaria.
* ``estado`` de mesa: ``"libre"``, ``"casi_libre"`` u ``"ocupada"`` (equivale a
  LIBRE, POSIBLEMENTE_LIBRE y OCUPADA de la máquina de estados del microservicio).
* ``periodo``: ``"hoy"``, ``"semana"`` o ``"mes"``.
"""

PERIODOS = ("hoy", "semana", "mes")
ESTADOS = ("libre", "casi_libre", "ocupada")
TIPOS_EVENTO = ("ocupacion", "entrega", "fusion")


class PanelBackend:
    def estado(self):
        """Estado en vivo del salón.

        {
          "camara": {"nombre", "en_vivo", "mesas", "zonas_excluidas"},
          "resumen": {"total", "libres", "casi_libres", "ocupadas", "personas", "espera_prom_s"},
          "mesas": [{"id", "codigo", "estado", "personas", "desde", "entregas", "x", "y", "w", "h"}],
          "plano": {"ancho", "alto", "caja": {x,y,w,h} | None, "fusiones": [{x,y,w,h,mesas}]},
          "en_espera": [{"mesa_id", "codigo", "personas", "entregas", "desde", "fusion"}],
        }
        """
        raise NotImplementedError

    def espera(self, periodo):
        """Métrica 1. {"promedio_s","max_s","min_s","delta_ayer_s","en_curso":[...],"por_hora":[{"hora","min"}]}"""
        raise NotImplementedError

    def personal(self, periodo):
        """Métrica 2. {"top": {...}, "ranking": [{"codigo","mesas","respuesta_s"}]}"""
        raise NotImplementedError

    def uso_mesas(self, periodo):
        """Métrica 3. {"mesas": [{"id","codigo","usos","x","y","w","h"}], "mas_usada": {...}, "menos_usada": {...}}"""
        raise NotImplementedError

    def mesa(self, mesa_id):
        """Detalle de una mesa o ``None``. {"id","codigo","estado","personas","desde","entregas","promedio_s","actividad":[...]}"""
        raise NotImplementedError

    def evidencias(self, tipo=None):
        """Clips de evidencia. [{"id","titulo","tipo","hora","detalle","duracion_s","url","mesa_id"}]"""
        raise NotImplementedError

    def ajustes(self):
        """{"periodo_gracia_min","solo_objetos_min","confianza_min"}"""
        raise NotImplementedError

    def guardar_ajustes(self, datos):
        raise NotImplementedError

    def zonas(self):
        """{"ancho","alto","frame_url","zonas":[{"id","nombre","tipo","capacidad","adyacentes","puntos":[[x,y],...]}]}"""
        raise NotImplementedError

    def guardar_zonas(self, zonas):
        raise NotImplementedError
