import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import permissions, status
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from farm_calendar.utils.auth_backends import CustomJWTAuthentication
from farm_calendar.utils.tenant_scope import tenant_de_peticion
from farm_management.models import Farm, UserFarmAccess  # PARCHE CNTA


class IsFarmAccessService(permissions.BasePermission):
    """Solo la cuenta de servicio de SheepCare puede leer y escribir los accesos.

    Quien manda sobre dueños, comparticiones y roles es la base privada de
    SheepCare, no Farm Calendar: una persona normal que pudiera tocar esta tabla
    se daría acceso a cualquier granja de su empresa. Se compara con una lista
    de nombres (FARM_ACCESS_SERVICE_USERS); vacía, nadie pasa. La firma del token
    ya la comprobó la autenticación, así que el nombre no se puede falsificar sin
    la clave compartida.
    """

    def has_permission(self, request, view):
        usuario = request.user
        if not usuario or not usuario.is_authenticated:
            return False
        return usuario.get_username().strip().lower() in settings.FARM_ACCESS_SERVICE_USERS


class FarmAccessView(APIView):
    """PARCHE CNTA: accesos por granja de la empresa del token.

    GET  /api/v1/farm-access/[?user=<correo>]   lista los accesos de la empresa.
    POST /api/v1/farm-access/                   deja el acceso de UNA persona
        exactamente como se indica, y es idempotente:

        {"user": "ana@cnta.es", "is_admin": false, "farms": ["<uuid>", ...]}

        - `is_admin: true` da acceso a toda la empresa y exige `farms` vacío.
        - `is_admin: false` da acceso solo a esas granjas; con `farms` vacío la
          persona queda sin acceso (también sirve para quitarlo todo).
        - Todas las granjas deben ser de la empresa del token; si alguna no lo
          es no se cambia nada (400).

    La empresa sale del token, no del cuerpo, como en el resto de Farm Calendar.
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsFarmAccessService]
    parser_classes = [JSONParser]
    # El renderizador por defecto es JSON-LD y aquí no aplica.
    renderer_classes = [JSONRenderer]

    @staticmethod
    def _tenant_o_400(request):
        tenant = tenant_de_peticion(request)
        if not tenant:
            return None, Response(
                {"error": "El token no trae tenant."}, status=status.HTTP_400_BAD_REQUEST
            )
        return tenant, None

    def get(self, request, version=None):
        tenant, error = self._tenant_o_400(request)
        if error:
            return error
        filas = UserFarmAccess.objects.filter(tenant=tenant)
        usuario = request.query_params.get("user")
        if usuario:
            filas = filas.filter(user=usuario.strip().lower())
        return Response([
            {"user": f.user, "is_admin": f.is_admin, "farm": str(f.farm_id) if f.farm_id else None}
            for f in filas.order_by("user", "farm_id")
        ])

    def post(self, request, version=None):
        tenant, error = self._tenant_o_400(request)
        if error:
            return error

        datos = request.data if isinstance(request.data, dict) else {}
        usuario = datos.get("user")
        if not isinstance(usuario, str) or not usuario.strip():
            return Response({"error": "Falta `user`."}, status=status.HTTP_400_BAD_REQUEST)
        usuario = usuario.strip().lower()

        es_admin = datos.get("is_admin", False)
        if not isinstance(es_admin, bool):
            return Response({"error": "`is_admin` debe ser booleano."}, status=status.HTTP_400_BAD_REQUEST)

        crudas = datos.get("farms", [])
        if not isinstance(crudas, list):
            return Response({"error": "`farms` debe ser una lista."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            granjas = {uuid.UUID(str(g)) for g in crudas}
        except ValueError:
            return Response({"error": "`farms` contiene un UUID no válido."}, status=status.HTTP_400_BAD_REQUEST)

        if es_admin and granjas:
            return Response(
                {"error": "Un administrador ve toda la empresa: `farms` debe ir vacío."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Antes de tocar nada: todas las granjas existen y son de esta empresa.
        # Uno ajeno responde igual que uno inexistente.
        propias = set(Farm.objects.filter(tenant=tenant, id__in=granjas).values_list("id", flat=True))
        desconocidas = granjas - propias
        if desconocidas:
            return Response(
                {"error": "Granjas desconocidas para esta empresa.",
                 "farms": sorted(str(g) for g in desconocidas)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                existentes = UserFarmAccess.objects.filter(tenant=tenant, user=usuario)
                if es_admin:
                    quitar = existentes.filter(farm__isnull=False)
                    ya_admin = existentes.filter(farm__isnull=True).exists()
                    crear = [] if ya_admin else [UserFarmAccess(tenant=tenant, user=usuario, is_admin=True)]
                else:
                    # `exclude` incluye también la fila de administrador (farm NULL).
                    quitar = existentes.exclude(farm__in=granjas)
                    tenia = set(existentes.filter(farm__in=granjas).values_list("farm_id", flat=True))
                    crear = [
                        UserFarmAccess(tenant=tenant, user=usuario, farm_id=g)
                        for g in granjas - tenia
                    ]
                # Se cuenta antes de borrar: en .delete() el recuento incluye cascadas.
                quitadas = quitar.count()
                quitar.delete()
                # `save()` normaliza el usuario; bulk_create no lo llama, y ya va en minúsculas.
                UserFarmAccess.objects.bulk_create(crear)
        except IntegrityError:
            # Dos llamadas a la vez para la misma persona. Reintentar es seguro.
            return Response(
                {"error": "Conflicto al guardar, vuelve a intentarlo."}, status=status.HTTP_409_CONFLICT
            )

        return Response({
            "tenant": tenant,
            "user": usuario,
            "is_admin": es_admin,
            "farms": sorted(str(g) for g in granjas),
            "created": len(crear),
            "removed": quitadas,
        })
