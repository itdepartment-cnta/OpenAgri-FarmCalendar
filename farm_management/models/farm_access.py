from django.db import models
from django.db.models import Q

from .farm_parcels import Farm


class UserFarmAccess(models.Model):
    """PARCHE CNTA: a qué granjas puede acceder cada persona dentro de su empresa.

    Farm Calendar filtra por `tenant` (empresa) pero no por granja: quien entra
    veía todas las de su empresa. Esta tabla es lo que permite que una persona
    normal vea solo las suyas. La rellena el backend público de SheepCare, que
    es quien conoce dueños, comparticiones y roles (la fuente de verdad es la
    base privada); aquí solo se consulta.

    Dos clases de fila, que la restricción `farm_access_admin_xor_farm` obliga a
    distinguir:

    - `is_admin=True`, `farm=NULL`: la persona ve toda su empresa.
    - `is_admin=False`, `farm=<granja>`: la persona ve esa granja.

    Una persona sin ninguna fila no ve nada: se falla cerrado.
    """

    tenant = models.CharField(max_length=64)
    # Claim `user_id` del token (el username de GateKeeper, que es el correo).
    # Siempre en minúsculas: `empresaTest@cnta.es` y `empresatest@cnta.es` son la
    # misma persona.
    user = models.CharField(max_length=254)
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='user_access')
    is_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'acceso_usuario_granja'
        verbose_name = 'Farm access'
        verbose_name_plural = 'Farm access'
        constraints = [
            # Con NULL, un UNIQUE(tenant, user, farm) normal permitiría repetir la
            # fila de administrador: en Postgres los NULL no son iguales entre sí.
            # Por eso son dos restricciones parciales.
            models.UniqueConstraint(
                fields=['tenant', 'user', 'farm'],
                condition=Q(farm__isnull=False),
                name='farm_access_unique_farm',
            ),
            models.UniqueConstraint(
                fields=['tenant', 'user'],
                condition=Q(farm__isnull=True),
                name='farm_access_unique_admin',
            ),
            models.CheckConstraint(
                condition=(Q(is_admin=True, farm__isnull=True)
                       | Q(is_admin=False, farm__isnull=False)),
                name='farm_access_admin_xor_farm',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'user'], name='farm_access_tenant_user_idx'),
        ]

    def save(self, *args, **kwargs):
        if self.user:
            self.user = self.user.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} -> {'ALL' if self.is_admin else self.farm_id}"
