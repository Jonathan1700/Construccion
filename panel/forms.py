from django import forms
from django.contrib.auth import authenticate


class LoginForm(forms.Form):
    """Formulario de acceso con los mensajes del diseño (estado de error del prototipo)."""

    username = forms.CharField(label="Correo", required=False, widget=forms.TextInput(attrs={
        "autocomplete": "username", "inputmode": "email", "placeholder": "admin@correo.com", "autofocus": True}))
    password = forms.CharField(label="Contraseña", required=False, widget=forms.PasswordInput(attrs={
        "autocomplete": "current-password", "placeholder": "••••••••"}))
    recordarme = forms.BooleanField(label="Recordarme", required=False, initial=True)

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.usuario = None
        super().__init__(*args, **kwargs)

    def clean(self):
        datos = super().clean()
        usuario, clave = (datos.get("username") or "").strip(), datos.get("password") or ""
        if not usuario:
            self.add_error("username", "Campo obligatorio")
        if not clave:
            self.add_error("password", "Campo obligatorio")
        if not usuario or not clave:
            raise forms.ValidationError(
                "Completa tu correo y contraseña|Necesitamos ambos datos para ingresar.", code="vacio")
        self.usuario = authenticate(self.request, username=usuario, password=clave)
        if self.usuario is None:
            raise forms.ValidationError(
                "Correo o contraseña incorrectos|Revisa tus datos e inténtalo de nuevo.", code="invalido")
        return datos

    def alerta(self):
        """Devuelve (título, detalle) de la alerta general o None."""
        errores = self.non_field_errors()
        if not errores:
            return None
        titulo, _, detalle = str(errores[0]).partition("|")
        return titulo, detalle


class AjustesForm(forms.Form):
    periodo_gracia_min = forms.IntegerField(
        label="Período de gracia", min_value=1, max_value=30,
        error_messages={"required": "Ingresa un número de minutos", "invalid": "Ingresa un número entero",
                        "min_value": "Debe ser de 1 minuto o más", "max_value": "Máximo 30 minutos"})
    solo_objetos_min = forms.IntegerField(
        label="Solo objetos, sin personas", min_value=1, max_value=30, required=False,
        error_messages={"invalid": "Ingresa un número entero", "min_value": "Debe ser de 1 minuto o más",
                        "max_value": "Máximo 30 minutos"})
    confianza_min = forms.FloatField(
        label="Confianza mínima", min_value=0.1, max_value=0.95,
        error_messages={"required": "Elige un valor", "invalid": "Valor no válido",
                        "min_value": "Mínimo 0,10", "max_value": "Máximo 0,95"})
