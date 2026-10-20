"""PARCHE CNTA: filtro por granja (acceso_usuario_granja) sobre el filtro por empresa."""
import datetime

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from farm_activities.models import FarmCalendarActivityType, Observation
from farm_calendar.utils.tenant_scope import (
    acotar_a_tenant,
    granjas_permitidas,
    ruta_a_granja,
)
from farm_management.models import (
    AgriculturalMachine,
    Farm,
    FarmAnimal,
    FarmParcel,
    Fertilizer,
    UserFarmAccess,
)

SERVICIO = "sheepcare-service"


def _token(usuario, tenant):
    payload = {settings.JWT_USER_ID_FIELD: usuario}
    if tenant:
        payload["tenant"] = tenant
    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALG)


def _peticion(usuario, tenant="emp-a", superusuario=False):
    """Una petición con el token de GateKeeper y su usuario Django, como en producción."""
    r = RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {_token(usuario, tenant)}")
    User = get_user_model()
    r.user, _ = User.objects.get_or_create(
        username=usuario, defaults={"is_superuser": superusuario}
    )
    if superusuario and not r.user.is_superuser:
        r.user.is_superuser = True
        r.user.save()
    return r


class Escenario(TestCase):
    """Dos empresas. En emp-a: tres granjas con parcela, animal y observación."""

    @classmethod
    def setUpTestData(cls):
        cls.tipo = FarmCalendarActivityType.objects.create(name="Test")
        cls.granja, cls.parcela, cls.animal, cls.obs = {}, {}, {}, {}
        for nombre, tenant in (("F1", "emp-a"), ("F2", "emp-a"), ("F3", "emp-a"), ("FB", "emp-b")):
            g = Farm.objects.create(name=nombre, tenant=tenant)
            p = FarmParcel.objects.create(
                identifier=f"P-{nombre}", farm=g, parcel_type="x", tenant=tenant
            )
            cls.granja[nombre], cls.parcela[nombre] = g, p
            cls.animal[nombre] = FarmAnimal.objects.create(
                name=f"A-{nombre}", species="ovis", birth_date=timezone.now(), parcel=p, tenant=tenant
            )
            cls.obs[nombre] = Observation.objects.create(
                activity_type=cls.tipo, title=f"O-{nombre}", value="1", observed_property="x",
                parcel=p, tenant=tenant,
            )
        # Sin parcela: no se puede atribuir a ninguna granja.
        cls.obs_sin_parcela = Observation.objects.create(
            activity_type=cls.tipo, title="O-sin-parcela", value="1", observed_property="x",
            tenant="emp-a",
        )
        cls.maquina_sin_parcela = AgriculturalMachine.objects.create(
            name="M", tenant="emp-a", purchase_date=datetime.date(2020, 1, 1),
            manufacturer="x", model="x", seria_number="x",
        )
        cls.abono = Fertilizer.objects.create(
            name="Abono", tenant="emp-a", cost=1, price_unit="x",
            active_substance="x", targeted_towards="x", nutrient_concentration=1,
        )

        UserFarmAccess.objects.create(tenant="emp-a", user="ana@x.es", farm=cls.granja["F1"])
        UserFarmAccess.objects.create(tenant="emp-a", user="ana@x.es", farm=cls.granja["F2"])
        UserFarmAccess.objects.create(tenant="emp-a", user="jefa@x.es", is_admin=True)

    def ids(self, modelo, usuario, tenant="emp-a", **kw):
        return set(acotar_a_tenant(modelo.objects.all(), _peticion(usuario, tenant, **kw)).values_list("pk", flat=True))


@override_settings(FARM_ACCESS_FILTER_ENABLED=False)
class InterruptorApagadoTests(Escenario):
    def test_apagado_todo_el_mundo_ve_toda_su_empresa(self):
        for usuario in ("ana@x.es", "sin-filas@x.es"):
            self.assertEqual(
                self.ids(Farm, usuario),
                {self.granja[n].pk for n in ("F1", "F2", "F3")},
            )


@override_settings(FARM_ACCESS_FILTER_ENABLED=True)
class FiltroPorGranjaTests(Escenario):
    def test_persona_normal_solo_ve_sus_granjas(self):
        self.assertEqual(self.ids(Farm, "ana@x.es"), {self.granja["F1"].pk, self.granja["F2"].pk})

    def test_parcelas_animales_y_actividades_cuelgan_de_su_granja(self):
        self.assertEqual(self.ids(FarmParcel, "ana@x.es"), {self.parcela["F1"].pk, self.parcela["F2"].pk})
        self.assertEqual(self.ids(FarmAnimal, "ana@x.es"), {self.animal["F1"].pk, self.animal["F2"].pk})
        self.assertEqual(self.ids(Observation, "ana@x.es"), {self.obs["F1"].pk, self.obs["F2"].pk})

    def test_lo_que_no_tiene_parcela_o_camino_no_lo_ve_una_persona_normal(self):
        self.assertNotIn(self.obs_sin_parcela.pk, self.ids(Observation, "ana@x.es"))
        self.assertEqual(self.ids(AgriculturalMachine, "ana@x.es"), set())
        self.assertEqual(self.ids(Fertilizer, "ana@x.es"), set())

    def test_sin_filas_no_ve_nada(self):
        for modelo in (Farm, FarmParcel, FarmAnimal, Observation):
            with self.subTest(modelo=modelo.__name__):
                self.assertEqual(self.ids(modelo, "sin-filas@x.es"), set())

    def test_el_correo_se_compara_sin_mayusculas(self):
        self.assertEqual(self.ids(Farm, "ANA@X.es"), {self.granja["F1"].pk, self.granja["F2"].pk})

    def test_administrador_ve_toda_su_empresa_incluido_lo_sin_parcela(self):
        self.assertEqual(self.ids(Farm, "jefa@x.es"), {self.granja[n].pk for n in ("F1", "F2", "F3")})
        self.assertIn(self.obs_sin_parcela.pk, self.ids(Observation, "jefa@x.es"))
        self.assertIn(self.maquina_sin_parcela.pk, self.ids(AgriculturalMachine, "jefa@x.es"))
        self.assertIn(self.abono.pk, self.ids(Fertilizer, "jefa@x.es"))

    def test_la_cuenta_de_servicio_ve_toda_la_empresa_de_su_token(self):
        self.assertEqual(self.ids(Farm, SERVICIO), {self.granja[n].pk for n in ("F1", "F2", "F3")})
        self.assertEqual(self.ids(Farm, SERVICIO, tenant="emp-b"), {self.granja["FB"].pk})

    def test_el_superusuario_lo_ve_todo(self):
        self.assertEqual(self.ids(Farm, "soporte@x.es", superusuario=True), {g.pk for g in self.granja.values()})

    def test_nadie_cruza_de_empresa(self):
        self.assertNotIn(self.granja["FB"].pk, self.ids(Farm, "jefa@x.es"))
        self.assertNotIn(self.granja["FB"].pk, self.ids(Farm, SERVICIO))
        # Una fila de acceso a una granja de otra empresa no da nada.
        UserFarmAccess.objects.create(tenant="emp-b", user="ana@x.es", farm=self.granja["FB"])
        self.assertEqual(self.ids(Farm, "ana@x.es"), {self.granja["F1"].pk, self.granja["F2"].pk})
        self.assertEqual(self.ids(Farm, "ana@x.es", tenant="emp-b"), {self.granja["FB"].pk})

    def test_un_cambio_en_la_tabla_se_nota_en_la_siguiente_peticion(self):
        UserFarmAccess.objects.create(tenant="emp-a", user="ana@x.es", farm=self.granja["F3"])
        self.assertIn(self.granja["F3"].pk, self.ids(Farm, "ana@x.es"))
        UserFarmAccess.objects.filter(user="ana@x.es", farm=self.granja["F1"]).delete()
        self.assertNotIn(self.granja["F1"].pk, self.ids(Farm, "ana@x.es"))

    def test_rutas_a_la_granja(self):
        self.assertEqual(ruta_a_granja(Farm), "id")
        self.assertEqual(ruta_a_granja(FarmParcel), "farm_id")
        self.assertEqual(ruta_a_granja(FarmAnimal), "parcel__farm_id")
        self.assertEqual(ruta_a_granja(Observation), "parcel__farm_id")
        self.assertIsNone(ruta_a_granja(Fertilizer))

    def test_granjas_permitidas_se_calcula_una_vez_por_peticion(self):
        r = _peticion("ana@x.es")
        with self.assertNumQueries(1):
            granjas_permitidas(r, "emp-a")
            granjas_permitidas(r, "emp-a")


@override_settings(FARM_ACCESS_FILTER_ENABLED=True)
class FiltroPorGranjaHttpTests(Escenario):
    """De extremo a extremo: la API REST y las acciones ajax de la web."""

    def _get(self, url, usuario, tenant="emp-a"):
        return self.client.get(url, {"format": "json"}, HTTP_AUTHORIZATION=f"Bearer {_token(usuario, tenant)}")

    def _post(self, url, usuario, tenant="emp-a"):
        return self.client.post(url, HTTP_AUTHORIZATION=f"Bearer {_token(usuario, tenant)}")

    def test_la_api_de_granjas_solo_devuelve_las_de_la_persona(self):
        r = self._get("/api/v1/Farm/", "ana@x.es")
        self.assertEqual(r.status_code, 200)
        datos = r.json()
        datos = datos.get("@graph", datos) if isinstance(datos, dict) else datos
        self.assertEqual(len(datos), 2)

    def test_la_api_de_una_granja_ajena_da_404(self):
        self.assertEqual(self._get(f"/api/v1/Farm/{self.granja['F3'].pk}/", "ana@x.es").status_code, 404)
        self.assertEqual(self._get(f"/api/v1/Farm/{self.granja['F1'].pk}/", "ana@x.es").status_code, 200)

    def test_sin_filas_la_api_no_devuelve_nada(self):
        r = self._get("/api/v1/Farm/", "sin-filas@x.es")
        datos = r.json()
        datos = datos.get("@graph", datos) if isinstance(datos, dict) else datos
        self.assertEqual(len(datos), 0)

    def test_ajax_sobre_una_granja_de_su_empresa_a_la_que_no_accede_da_404(self):
        r = self._post(f"/farms/ajax/toggle-status/{self.granja['F3'].pk}/", "ana@x.es")
        self.assertEqual(r.status_code, 404)
        self.granja["F3"].refresh_from_db()
        self.assertEqual(self.granja["F3"].status, Farm.BaseModelStatus.ACTIVE)

    def test_ajax_sobre_una_granja_propia_funciona(self):
        r = self._post(f"/farms/ajax/toggle-status/{self.granja['F1'].pk}/", "ana@x.es")
        self.assertEqual(r.status_code, 200)

    def test_el_administrador_puede_con_cualquiera_de_su_empresa(self):
        r = self._post(f"/farms/ajax/toggle-status/{self.granja['F3'].pk}/", "jefa@x.es")
        self.assertEqual(r.status_code, 200)
