import jwt
from django.conf import settings
from django.test import TestCase

from farm_management.models.farm_parcels import Farm


def _token(usuario, tenant):
    """JWT como el que emite GateKeeper, con el claim `tenant`."""
    payload = {settings.JWT_USER_ID_FIELD: usuario}
    if tenant:
        payload["tenant"] = tenant
    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALG)


class AjaxHandlerAisladoPorEmpresaTests(TestCase):
    """PARCHE CNTA: desactivar o borrar una granja de otra empresa da 404."""

    def setUp(self):
        self.mia = Farm.objects.create(name="Mia", tenant="empresa-a")
        self.ajena = Farm.objects.create(name="Ajena", tenant="empresa-b")

    def _post(self, accion, granja, usuario="a@cnta.es", tenant="empresa-a"):
        return self.client.post(
            f"/farms/ajax/{accion}/{granja.pk}/",
            HTTP_AUTHORIZATION=f"Bearer {_token(usuario, tenant)}",
        )

    def test_desactivar_granja_propia(self):
        r = self._post("toggle-status", self.mia)
        self.assertEqual(r.status_code, 200)
        self.mia.refresh_from_db()
        self.assertEqual(self.mia.status, Farm.BaseModelStatus.INACTIVE)

    def test_desactivar_granja_ajena_da_404_y_no_la_toca(self):
        r = self._post("toggle-status", self.ajena)
        self.assertEqual(r.status_code, 404)
        self.ajena.refresh_from_db()
        self.assertEqual(self.ajena.status, Farm.BaseModelStatus.ACTIVE)

    def test_borrar_granja_ajena_da_404_y_no_la_toca(self):
        r = self._post("delete", self.ajena)
        self.assertEqual(r.status_code, 404)
        self.ajena.refresh_from_db()
        self.assertEqual(self.ajena.status, Farm.BaseModelStatus.ACTIVE)

    def test_sin_tenant_en_el_token_no_toca_nada(self):
        r = self._post("toggle-status", self.mia, tenant=None)
        self.assertEqual(r.status_code, 404)
