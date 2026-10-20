"""PARCHE CNTA — segmentación por empresa (tenant).

Upstream no guarda de quién es cada registro, así que cualquiera que entre ve
los datos de todos. Aquí está la pieza que lo corrige: el tenant viaja como
claim en el JWT y estas utilidades lo aplican al queryset de cada viewset.

El valor canónico es el UUID del `Tenant` de GateKeeper, que es quien posee el
concepto de empresa en todo el sistema.
"""
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
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


# ── Filtro por granja ────────────────────────────────────────────────
#
# Encima del filtro por empresa. Con FARM_ACCESS_FILTER_ENABLED apagado no hace
# nada. Encendido, una persona normal solo ve lo que cuelga de las granjas de
# sus filas en acceso_usuario_granja. Ver DISENO_ROLES_Y_GRANJAS_COMPARTIDAS.md §6.


def granjas_permitidas(request, tenant):
    """Granjas que la persona de la petición puede ver dentro de su empresa.

    None significa TODAS las de la empresa; un conjunto, solo esas (vacío = ninguna,
    falla cerrado). Ven toda la empresa:

    - la cuenta de servicio de SheepCare (FARM_ACCESS_SERVICE_USERS): busca y crea
      granjas y parcelas por nombre para cualquier persona de la empresa, y sin
      verlas todas duplicaría o fallaría;
    - quien tenga una fila de administrador.

    Los superusuarios se tratan antes, en quien llama.
    """
    cacheado = getattr(request, "_cnta_granjas", "sin_calcular")
    if cacheado != "sin_calcular":
        return cacheado

    # Import tardio: el modelo no existe aun cuando se carga este modulo.
    from farm_management.models import UserFarmAccess

    usuario = getattr(request, "user", None)
    nombre = ""
    if usuario is not None and getattr(usuario, "is_authenticated", False):
        nombre = (usuario.get_username() or "").strip().lower()

    if nombre in settings.FARM_ACCESS_SERVICE_USERS:
        resultado = None
    else:
        filas = list(
            UserFarmAccess.objects.filter(tenant=tenant, user=nombre).values_list("is_admin", "farm_id")
        )
        resultado = None if any(es_admin for es_admin, _ in filas) else {f for _, f in filas}

    request._cnta_granjas = resultado
    return resultado


def ruta_a_granja(modelo):
    """Camino ORM desde el modelo hasta el id de su granja, o None si no lo hay.

    Farm: su propio id. FarmParcel: `farm_id`. Activos (cultivos, animales, maquinas,
    sensores) y actividades: por su parcela, `parcel__farm_id`. Lo demas (materiales,
    catalogos con tenant) no se puede atribuir a una granja.
    """
    from farm_management.models import Farm, FarmParcel

    if issubclass(modelo, Farm):
        return "id"
    if issubclass(modelo, FarmParcel):
        return "farm_id"
    try:
        campo = modelo._meta.get_field("parcel")
    except FieldDoesNotExist:
        return None
    if campo.is_relation and campo.related_model is FarmParcel:
        return "parcel__farm_id"
    return None


def _acotar_por_granja(qs, request, tenant):
    if not getattr(settings, "FARM_ACCESS_FILTER_ENABLED", False):
        return qs
    permitidas = granjas_permitidas(request, tenant)
    if permitidas is None:
        return qs
    ruta = ruta_a_granja(qs.model)
    if ruta is None:
        # Sin camino a una granja solo lo ve quien ve toda la empresa.
        return qs.none()
    # Una parcela nula (activo o actividad sin parcela) tampoco entra: no se
    # puede atribuir.
    return qs.filter(**{f"{ruta}__in": permitidas})


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
        return _acotar_por_granja(qs.filter(tenant=tenant), self.request, tenant)

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


# ── Vistas web ───────────────────────────────────────────────────────
#
# El mixin de arriba solo cubre la API REST. La interfaz web de Farm Calendar
# consultaba con `.all()` sin filtrar, así que un cliente veía los datos de
# todos: listados completos y, conociendo un UUID, el detalle de un recurso
# ajeno. Lo de aquí abajo cierra ese camino con las mismas tres reglas.


def acotar_a_tenant(qs, request):
    """Acota un queryset al tenant de la petición. Mismas reglas que el mixin.

    Pensada para las vistas web, donde no hay DRF y cada vista arma su propio
    queryset.
    """
    if not modelo_tiene_tenant(qs.model):
        return qs

    usuario = getattr(request, "user", None)
    if usuario is not None and getattr(usuario, "is_superuser", False):
        return qs

    tenant = tenant_de_peticion(request)
    if not tenant:
        return qs.none()
    return _acotar_por_granja(qs.filter(tenant=tenant), request, tenant)


class TenantScopedWebViewMixin:
    """Acota el queryset de una vista web (ListView, UpdateView, DetailView).

    Al actuar sobre `get_queryset`, cubre a la vez el listado y la búsqueda
    del objeto por pk: `get_object` de Django parte de ese mismo queryset, así
    que un recurso de otra empresa deja de existir para la vista y devuelve
    404 en vez de 200.
    """

    def get_queryset(self):
        return acotar_a_tenant(super().get_queryset(), self.request)


def sellar_con_tenant(instancia, request):
    """Pone el tenant de la petición en un objeto antes de guardarlo.

    El equivalente de `perform_create` para las vistas web. Sin esto, lo que
    se crea desde la interfaz nace sin dueño y no lo ve nadie.
    """
    if not instancia.pk and hasattr(instancia, TENANT_CLAIM):
        if not getattr(instancia, TENANT_CLAIM, None):
            tenant = tenant_de_peticion(request)
            if tenant:
                setattr(instancia, TENANT_CLAIM, tenant)
    return instancia


def acotar_formulario(form, request):
    """Acota los desplegables de un formulario al tenant de la petición.

    Filtrar solo el listado no basta: los formularios de alta y edición traen
    campos de elección —la parcela de un animal, por ejemplo— cuyo queryset
    era el global. Los nombres de las granjas de otras empresas aparecían en
    los `<option>`, y además se podía asignar un recurso propio a una parcela
    ajena enviando su UUID.

    Recorre los campos con queryset y acota los que apunten a un modelo con
    `tenant`. Los demás los deja como están.
    """
    if form is None:
        return form
    for campo in getattr(form, "fields", {}).values():
        qs = getattr(campo, "queryset", None)
        if qs is None:
            continue
        try:
            campo.queryset = acotar_a_tenant(qs, request)
        except Exception:
            # Un campo raro no debe tumbar el formulario entero.
            continue
    return form


class TenantScopedFormMixin:
    """Acota los desplegables del formulario de una vista basada en clase."""

    def get_form(self, *args, **kwargs):
        return acotar_formulario(super().get_form(*args, **kwargs), self.request)
