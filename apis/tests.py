import jwt
from django.conf import settings
from django.test import TestCase

from farm_management.models import Farm, UserFarmAccess

URL = "/api/v1/farm-access/"
SERVICIO = "sheepcare-service"


def _token(usuario, tenant):
    """JWT como el que firma el backend público, con el claim `tenant`."""
    payload = {settings.JWT_USER_ID_FIELD: usuario}
    if tenant:
        payload["tenant"] = tenant
    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALG)


class FarmAccessEndpointTests(TestCase):
    """PARCHE CNTA: el endpoint que rellena acceso_usuario_granja."""

    def setUp(self):
        self.f1 = Farm.objects.create(name="F1", tenant="emp-a")
        self.f2 = Farm.objects.create(name="F2", tenant="emp-a")
        self.ajena = Farm.objects.create(name="Ajena", tenant="emp-b")

    def _post(self, cuerpo, usuario=SERVICIO, tenant="emp-a"):
        return self.client.post(
            URL, cuerpo, content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token(usuario, tenant)}",
        )

    def _get(self, usuario=SERVICIO, tenant="emp-a", query=""):
        return self.client.get(
            URL + query, HTTP_AUTHORIZATION=f"Bearer {_token(usuario, tenant)}"
        )

    def _granjas_de(self, usuario, tenant="emp-a"):
        return set(
            UserFarmAccess.objects.filter(tenant=tenant, user=usuario, farm__isnull=False)
            .values_list("farm_id", flat=True)
        )

    # ── quién puede ──────────────────────────────────────────────────
    def test_sin_token_no_entra(self):
        r = self.client.post(URL, {"user": "a@cnta.es"}, content_type="application/json")
        self.assertIn(r.status_code, (401, 403))

    def test_una_persona_normal_no_puede_escribir_ni_leer(self):
        cuerpo = {"user": "a@cnta.es", "farms": [str(self.f1.pk)]}
        self.assertEqual(self._post(cuerpo, usuario="a@cnta.es").status_code, 403)
        self.assertEqual(self._get(usuario="a@cnta.es").status_code, 403)
        self.assertEqual(UserFarmAccess.objects.count(), 0)

    def test_el_servicio_sin_tenant_en_el_token_recibe_400(self):
        r = self._post({"user": "a@cnta.es"}, tenant=None)
        self.assertEqual(r.status_code, 400)

    # ── escribir ─────────────────────────────────────────────────────
    def test_da_acceso_a_dos_granjas_y_normaliza_el_usuario(self):
        r = self._post({"user": " Ana@CNTA.es ", "farms": [str(self.f1.pk), str(self.f2.pk)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["created"], 2)
        self.assertEqual(self._granjas_de("ana@cnta.es"), {self.f1.pk, self.f2.pk})

    def test_es_idempotente(self):
        cuerpo = {"user": "a@cnta.es", "farms": [str(self.f1.pk)]}
        self._post(cuerpo)
        r = self._post(cuerpo)
        self.assertEqual((r.json()["created"], r.json()["removed"]), (0, 0))
        self.assertEqual(UserFarmAccess.objects.count(), 1)

    def test_deja_el_acceso_exactamente_como_se_pide(self):
        self._post({"user": "a@cnta.es", "farms": [str(self.f1.pk), str(self.f2.pk)]})
        r = self._post({"user": "a@cnta.es", "farms": [str(self.f2.pk)]})
        self.assertEqual((r.json()["created"], r.json()["removed"]), (0, 1))
        self.assertEqual(self._granjas_de("a@cnta.es"), {self.f2.pk})

    def test_lista_vacia_quita_todo(self):
        self._post({"user": "a@cnta.es", "farms": [str(self.f1.pk)]})
        r = self._post({"user": "a@cnta.es", "farms": []})
        self.assertEqual(r.json()["removed"], 1)
        self.assertFalse(UserFarmAccess.objects.filter(user="a@cnta.es").exists())

    def test_una_granja_de_otra_empresa_rechaza_todo_sin_cambiar_nada(self):
        self._post({"user": "a@cnta.es", "farms": [str(self.f1.pk)]})
        r = self._post({"user": "a@cnta.es", "farms": [str(self.f2.pk), str(self.ajena.pk)]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["farms"], [str(self.ajena.pk)])
        self.assertEqual(self._granjas_de("a@cnta.es"), {self.f1.pk})

    def test_una_granja_inexistente_recibe_400(self):
        r = self._post({"user": "a@cnta.es", "farms": ["00000000-0000-0000-0000-000000000000"]})
        self.assertEqual(r.status_code, 400)

    def test_cuerpo_mal_formado(self):
        self.assertEqual(self._post({}).status_code, 400)
        self.assertEqual(self._post({"user": "a@cnta.es", "farms": "x"}).status_code, 400)
        self.assertEqual(self._post({"user": "a@cnta.es", "farms": ["no-es-uuid"]}).status_code, 400)
        self.assertEqual(self._post({"user": "a@cnta.es", "is_admin": "si"}).status_code, 400)

    # ── administrador ────────────────────────────────────────────────
    def test_administrador_ve_toda_la_empresa_y_pierde_las_filas_por_granja(self):
        self._post({"user": "a@cnta.es", "farms": [str(self.f1.pk)]})
        r = self._post({"user": "a@cnta.es", "is_admin": True})
        self.assertEqual((r.json()["created"], r.json()["removed"]), (1, 1))
        filas = UserFarmAccess.objects.filter(user="a@cnta.es")
        self.assertEqual([(f.is_admin, f.farm_id) for f in filas], [(True, None)])
        # Repetir no duplica la fila de administrador.
        self._post({"user": "a@cnta.es", "is_admin": True})
        self.assertEqual(UserFarmAccess.objects.filter(user="a@cnta.es").count(), 1)

    def test_administrador_con_granjas_recibe_400(self):
        r = self._post({"user": "a@cnta.es", "is_admin": True, "farms": [str(self.f1.pk)]})
        self.assertEqual(r.status_code, 400)

    def test_quitar_el_rol_de_administrador(self):
        self._post({"user": "a@cnta.es", "is_admin": True})
        r = self._post({"user": "a@cnta.es", "is_admin": False, "farms": [str(self.f1.pk)]})
        self.assertEqual((r.json()["created"], r.json()["removed"]), (1, 1))
        self.assertFalse(UserFarmAccess.objects.filter(user="a@cnta.es", is_admin=True).exists())
        self.assertEqual(self._granjas_de("a@cnta.es"), {self.f1.pk})

    # ── empresas ─────────────────────────────────────────────────────
    def test_no_toca_a_la_misma_persona_en_otra_empresa(self):
        otra = UserFarmAccess.objects.create(tenant="emp-b", user="a@cnta.es", farm=self.ajena)
        self._post({"user": "a@cnta.es", "farms": []})
        self.assertTrue(UserFarmAccess.objects.filter(pk=otra.pk).exists())

    def test_get_solo_lista_la_empresa_del_token(self):
        UserFarmAccess.objects.create(tenant="emp-b", user="b@cnta.es", farm=self.ajena)
        self._post({"user": "a@cnta.es", "farms": [str(self.f1.pk)]})
        usuarios = {f["user"] for f in self._get().json()}
        self.assertEqual(usuarios, {"a@cnta.es"})
        filtrado = self._get(query="?user=A@CNTA.es").json()
        self.assertEqual([f["farm"] for f in filtrado], [str(self.f1.pk)])
