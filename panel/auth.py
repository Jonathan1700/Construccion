"""Acceso con correo o usuario (HU-05)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CorreoOUsuarioBackend(ModelBackend):
    """Permite iniciar sesión con el correo electrónico además del nombre de usuario."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        Usuario = get_user_model()
        if not username or not password:
            return None
        try:
            usuario = Usuario.objects.get(email__iexact=username.strip())
        except (Usuario.DoesNotExist, Usuario.MultipleObjectsReturned):
            return None
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None
