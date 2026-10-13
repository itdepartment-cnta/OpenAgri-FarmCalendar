from django.db import models, transaction, DatabaseError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from django.contrib.auth.mixins import LoginRequiredMixin

from farm_calendar.utils.tenant_scope import acotar_a_tenant

from ..models.farm_parcels import Farm, FarmParcel


MODEL_MAP = {
    "farms": Farm,
    "farm-parcel": FarmParcel
}

@method_decorator(never_cache, name='dispatch')
class AjaxHandlerView(LoginRequiredMixin, View):
    def post(self, request, prefix=None, action=None, pk=None):
        # Handle missing prefix by providing a default response or error
        if prefix and prefix in MODEL_MAP:
            model = MODEL_MAP[prefix]
        elif not prefix:
            # Handle cases with no prefix - general actions
            model = None  # No specific model required for general actions
        else:
            return JsonResponse({"error": "Invalid type"}, status=400)

        # Map action names to methods
        action_methods = {
            "toggle-status": self.toggle_status,
            "delete": self.delete_object
        }

        # Check if action is in the method mapping
        if action in action_methods:
            return action_methods[action](request, model, pk)
        elif not action:
            return JsonResponse({"error": "No action specified"}, status=400)
        else:
            return JsonResponse({"error": "Invalid action"}, status=400)

    @staticmethod
    def _objeto_de_mi_empresa(request, model, pk):
        """PARCHE CNTA: busca el objeto solo entre los de la empresa de la petición.

        Con `get_object_or_404(model, pk=pk)` cualquier persona con sesión podía
        desactivar o borrar una granja o parcela de otra empresa conociendo su
        UUID. Un objeto ajeno responde 404, igual que uno que no existe.
        """
        return get_object_or_404(acotar_a_tenant(model._default_manager.all(), request), pk=pk)

    def toggle_status(self, request, model, pk):
        if not model or not pk:
            return JsonResponse({"error": "Missing subject or primary key for toggling status."}, status=400)

        # Get the object and toggle its status
        obj = self._objeto_de_mi_empresa(request, model, pk)
        if obj.status == obj.BaseModelStatus.ACTIVE:
            obj.status = obj.BaseModelStatus.INACTIVE
            message = f"{model._meta.verbose_name} has been deactivated."
        else:
            obj.status = obj.BaseModelStatus.ACTIVE
            message = f"{model._meta.verbose_name} has been activated."

        obj.save()  # Save the updated status

        # Return the updated status and message
        return JsonResponse({"farm_status": obj.status, "message": message})

    @transaction.atomic
    def delete_object(self, request, model, pk):
        if not model or not pk:
            return JsonResponse({"error": "Missing subject or primary key for deletion."}, status=400)

        # Get the object and perform a soft delete
        obj = self._objeto_de_mi_empresa(request, model, pk)

        try:
            # Only call soft_delete on the main object
            if hasattr(obj, 'soft_delete') and hasattr(obj, 'status'):
                obj.soft_delete()  # This triggers cascading soft deletes if conditions are met

            message = f"{model._meta.verbose_name} and related records have been deleted."
            return JsonResponse({"message": message})
        except DatabaseError as e:
            return JsonResponse({"error": f"Failed to delete {model._meta.verbose_name}. Error: {str(e)}"},
                                status=400)
