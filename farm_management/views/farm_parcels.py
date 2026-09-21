import json
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import F
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from farm_management.models import FarmParcel, Farm
from farm_management.forms.farm_parcels import FarmParcelsForm

# PARCHE CNTA: la interfaz web no filtraba por empresa. Ver tenant_scope.
from farm_calendar.utils.tenant_scope import (
    acotar_a_tenant, acotar_formulario, sellar_con_tenant,
)


@method_decorator(never_cache, name='dispatch')
class FarmParcelView(LoginRequiredMixin, TemplateView):
    template_name = "farm_parcels/farm_parcels.html"
    success_url = reverse_lazy('farm_parcels')

    def decimal_to_float(self, data):
        """Convert all Decimal values to float in a nested dictionary."""
        for key, value in data.items():
            if isinstance(value, Decimal):
                data[key] = float(value)
        return data

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get all field names from FarmParcel dynamically
        farm_parcel_fields = [field.name for field in FarmParcel._meta.get_fields() if
                              not field.is_relation or field.one_to_one or (field.many_to_one and field.related_model)]

        # Add related fields using F expressions
        # PARCHE CNTA: solo las de la empresa de quien mira.
        farm_parcels = acotar_a_tenant(FarmParcel.active_objects.all(), self.request).values(
            'pk',
            *farm_parcel_fields,
            farm_name=F('farm__name'),  # Related field from FarmMaster
                )
        farm_parcels_with_coordinates = [
            {**parcel, "coordinates": f"{parcel_obj.latitude}, {parcel_obj.longitude}"}
            for parcel, parcel_obj in zip(farm_parcels, acotar_a_tenant(FarmParcel.objects.all(), self.request).filter(pk__in=[p['pk'] for p in farm_parcels]))
        ]

        context["farm_parcels"] = json.dumps(list(farm_parcels_with_coordinates), cls=DjangoJSONEncoder)


        return context

    def get(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')

        if pk:
            farm_parcel = get_object_or_404(acotar_a_tenant(FarmParcel.objects.all(), request), pk=pk)
            form = acotar_formulario(FarmParcelsForm(instance=farm_parcel), request)
        else:
            form = acotar_formulario(FarmParcelsForm(), request)

        context = self.get_context_data(**kwargs)
        context.update({
            'form': form,
            'is_edit': bool(pk)
        })
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')

        if pk:
            farm_parcel = get_object_or_404(acotar_a_tenant(FarmParcel.objects.all(), request), pk=pk)
            form = acotar_formulario(FarmParcelsForm(request.POST, instance=farm_parcel), request)
        else:
            farm_parcel = None
            form = acotar_formulario(FarmParcelsForm(request.POST), request)

        context = self.get_context_data(**kwargs)
        # Validate form and handle redirection or re-rendering with errors
        if form.is_valid():
            # PARCHE CNTA: lo que se crea desde la interfaz nace con dueno.
            instancia = form.save(commit=False)
            sellar_con_tenant(instancia, request)
            instancia.save()
            form.save_m2m()
            return redirect(self.success_url)

        context.update({
            'form': form,
            'is_edit': bool(pk)
        })
        return render(request, self.template_name, context)

    # Handle DELETE requests for deleting
    def delete(self, request, *args, **kwargs):
        pk = kwargs.get('pk')
        farm_parcel = get_object_or_404(acotar_a_tenant(FarmParcel.objects.all(), request), pk=pk)
        farm_parcel.delete()
        return redirect(self.success_url)