from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea el usuario de demostración del panel (admin@correo.com / scaneats2026)."

    def handle(self, *args, **opciones):
        Usuario = get_user_model()
        u, creado = Usuario.objects.get_or_create(username="admin", defaults={"email": "admin@correo.com", "first_name": "Admin"})
        u.set_password("scaneats2026")
        u.save()
        self.stdout.write(self.style.SUCCESS(
            ("Usuario creado" if creado else "Usuario actualizado") + ": admin@correo.com / scaneats2026"))
