from farm_calendar.utils.tenant_scope import TenantScopedModelViewSet  # PARCHE CNTA
from rest_framework import permissions, viewsets

from farm_management.models import (
    Fertilizer,
    Pesticide,
)
from ..serializers import (
    FertilizerSerializer,
    PesticideSerializer
)


class FertilizerViewSet(TenantScopedModelViewSet, viewsets.ModelViewSet):
    """
    API endpoint that allows Fertilizer to be viewed or edited.
    """
    queryset = Fertilizer.objects.all().order_by('-created_at')
    serializer_class = FertilizerSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['name', 'status']



class PesticideViewSet(TenantScopedModelViewSet, viewsets.ModelViewSet):
    """
    API endpoint that allows Pesticide to be viewed or edited.
    """
    queryset = Pesticide.objects.all().order_by('-created_at')
    serializer_class = PesticideSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['name', 'status']

