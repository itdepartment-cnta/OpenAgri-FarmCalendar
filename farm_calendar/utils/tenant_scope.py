"""PARCHE CNTA — segmentación por empresa (tenant).

Upstream no guarda de quién es cada registro, así que cualquiera que entre ve
los datos de todos. Aquí está la pieza que lo corrige: el tenant viaja como
claim en el JWT y estas utilidades lo aplican al queryset de cada viewset.

El valor canónico es el UUID del `Tenant` de GateKeeper, que es quien posee el
concepto de empresa en todo el sistema.
"""
from django.urls import set_script_prefix  # noqa: F401  (evita import vacío)

from farm_calendar.utils.jwt_utils import decode_jwt, get_token_from_jwt_request


TENANT_CLAIM = "tenant"


def tenant_de_peticion(request):
    """Tenant del token de la petición, o None si no trae.

    No valida nada más: la firma ya la comprobó el middleware de
    autenticación antes de llegar aquí.
    """
    cacheado = getattr(request, "_cnta_tenant", "sin_calcular")
    if cacheado != "sin_calcular":
        return cacheado

    tenant = None
    token = get_token_from_jwt_request(request)
    if token:
        payload = decode_jwt(token)
        if payload:
            tenant = payload.get(TENANT_CLAIM) or None
    request._cnta_tenant = tenant
    return tenant


def modelo_tiene_tenant(modelo):
    return any(f.name == TENANT_CLAIM for f in modelo._meta.get_fields())


class TenantScopedModelViewSet:
    """Mixin que acota el queryset de un viewset al tenant de la petición.

    Se antepone a ModelViewSet, no lo sustituye, para no alterar el resto del
    comportamiento de DRF.

    Tres reglas:

    - Los modelos sin campo `tenant` no se filtran. Hoy son
      FarmCalendarActivityType, que es un catálogo compartido y debe serlo, y
      AddRawMaterialCompostQuantity, tabla de detalle de compost que SheepCare
      no usa.
    - Los superusuarios ven todo. Es la vía de soporte; por eso la cuenta de
      servicio de SheepCare NO es superusuario.
    - Sin tenant en el token no se ve nada. Falla cerrado a propósito: es
      preferible que una integración mal configurada no vea datos a que los
      vea todos.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        if not modelo_tiene_tenant(qs.model):
            return qs

        usuario = getattr(self.request, "user", None)
        if usuario is not None and getattr(usuario, "is_superuser", False):
            return qs

        tenant = tenant_de_peticion(self.request)
        if not tenant:
            return qs.none()
        return qs.filter(tenant=tenant)

    def perform_create(self, serializer):
        """El tenant lo pone el token, no el cuerpo de la petición.

        Si se aceptara del cuerpo, cualquiera con una credencial válida podría
        escribir en la empresa de otro con solo cambiar un campo.
        """
        tenant = tenant_de_peticion(self.request)
        if tenant and modelo_tiene_tenant(serializer.Meta.model):
            serializer.save(tenant=tenant)
        else:
            serializer.save()
