from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from custom.models import FareItem, Operator, Port, Route, Vessel

from .models import Sailing, SailingQuota, Ticket


def make_sailing(**kw):
    op = Operator.objects.create(name="Op")
    v = Vessel.objects.create(operator=op, name="Berlin Nakroma")
    r = Route.objects.create(origin=Port.objects.create(code="DIL", name="Dili"), destination=Port.objects.create(code="BEL", name="Beloi"))
    return Sailing.objects.create(vessel=v, route=r, departure=timezone.now() + timedelta(hours=5), **kw)


class QRTests(TestCase):
    def test_signature_roundtrip_and_tamper(self):
        self.assertEqual(Ticket.verify_payload("AP-ABCD2345." + Ticket.sign("AP-ABCD2345")), "AP-ABCD2345")
        self.assertIsNone(Ticket.verify_payload("AP-ABCD2346." + Ticket.sign("AP-ABCD2345")))
        self.assertIsNone(Ticket.verify_payload("garbage"))


class QuotaTests(TestCase):
    def test_remaining_ignores_cancelled(self):
        s = make_sailing()
        q = SailingQuota.objects.create(sailing=s, quota_group="passenger", capacity=3)
        item = FareItem.objects.create(name_tet="Adultu", quota_group="passenger")
        for st in ("issued", "boarded", "cancelled"):
            Ticket.objects.create(sailing=s, item=item, unit_price=Decimal("4"), status=st)
        self.assertEqual(q.remaining, 1)

    def test_sales_close(self):
        s = make_sailing(sales_close_minutes=60)
        self.assertTrue(s.sales_open)
        s.departure = timezone.now() + timedelta(minutes=30)
        self.assertFalse(s.sales_open)


class PurgeTests(TestCase):
    def test_old_photos_removed_new_kept(self):
        import tempfile

        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            s = make_sailing()
            item = FareItem.objects.create(name_tet="Adultu", quota_group="passenger")
            img = lambda: SimpleUploadedFile("a.jpg", b"x", "image/jpeg")
            old = Ticket.objects.create(sailing=s, item=item, unit_price=1, document_photo=img())
            new = Ticket.objects.create(sailing=s, item=item, unit_price=1, document_photo=img())
            Ticket.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=31))
            call_command("purge_documents", stdout=StringIO())
            old.refresh_from_db(); new.refresh_from_db()
            self.assertFalse(old.document_photo)
            self.assertIsNotNone(old.document_deleted_at)
            self.assertTrue(new.document_photo)


# ---------------------------------------------------------------- phase 2: counter sales
import tempfile
from datetime import date
from io import BytesIO

from django.contrib.auth.models import Group
from django.urls import reverse
from PIL import Image

from custom.models import Fare
from users.models import AuditLog, User


def photo(name="doc.jpg", size=(2400, 1800)):
	buf = BytesIO()
	Image.new("RGB", size, (200, 30, 30)).save(buf, "JPEG")
	return SimpleUploadedFile(name, buf.getvalue(), "image/jpeg")


class SaleBase(TestCase):
	def setUp(self):
		self._media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
		self._media.enable()
		self.addCleanup(self._media.disable)
		call_command("setup_roles", verbosity=0)
		self.sailing = make_sailing()
		self.route = self.sailing.route
		for g, cap in (("passenger", 2), ("vehicle", 1), ("goods", 5)):
			SailingQuota.objects.create(sailing=self.sailing, quota_group=g, capacity=cap)
		mk = lambda **kw: FareItem.objects.create(**kw)
		self.adult = mk(name_tet="Adultu", quota_group="passenger", age_min=12)
		self.child = mk(name_tet="Kiak", quota_group="passenger", age_min=2, age_max=11)
		self.foreign = mk(name_tet="Estranjeiru", quota_group="passenger", age_min=12, foreigner_only=True)
		self.moto = mk(name_tet="Motór", quota_group="vehicle", requires_plate=True)
		self.buffalo = mk(name_tet="Karau", quota_group="goods")
		self.unpriced = mk(name_tet="Sen presu", quota_group="goods")
		for it, p in ((self.adult, "4"), (self.child, "2"), (self.foreign, "10"), (self.moto, "8"), (self.buffalo, "10")):
			Fare.objects.create(route=self.route, item=it, price=Decimal(p))
		self.clerk = User.objects.create_user("clerk", password="x")
		self.clerk.groups.add(Group.objects.get(name="resepsionista"))
		self.client.force_login(self.clerk)
		self.url = reverse("ticket-sell", args=[self.sailing.pk])

	def pax(self, **kw):
		d = {"item": self.adult.pk, "quantity": 1, "full_name": "Maria da Silva", "birth_date": "1990-05-01",
			"sex": "F", "nationality": "Timor-Leste", "document_type": "eleitoral", "document_number": "E-123",
			"document_photo": photo(), "payment_method": "cash"}
		d.update(kw)
		return d


class SellTests(SaleBase):
	def test_passenger_sale_creates_ticket_shrinks_photo_and_audits(self):
		r = self.client.post(self.url, self.pax())
		t = Ticket.objects.get()
		self.assertRedirects(r, reverse("ticket-print", args=[t.pk]), fetch_redirect_response=False)
		self.assertEqual((t.unit_price, t.sold_by, t.status), (Decimal("4"), self.clerk, "issued"))
		self.assertTrue(t.document_photo.name.endswith(".jpg"))
		self.assertLessEqual(max(Image.open(t.document_photo).size), 1600)
		self.assertTrue(AuditLog.objects.filter(action="ticket_sold", detail__contains=t.serial).exists())

	def test_passenger_items_listed_first(self):
		labels = [c[1] for c in self.client.get(self.url).context["form"].fields["item"].choices if c[0]]
		self.assertTrue(labels[0].startswith(("Adultu", "Kiak", "Estranjeiru")))

	def test_unpriced_item_not_offered(self):
		r = self.client.get(self.url)
		self.assertNotIn(self.unpriced, r.context["form"].fields["item"].queryset)

	def test_passenger_requires_document_photo_and_fields(self):
		d = self.pax(); d.pop("document_photo"); d["full_name"] = ""
		r = self.client.post(self.url, d)
		self.assertEqual(r.status_code, 200)
		self.assertEqual(Ticket.objects.count(), 0)
		self.assertIn("document_photo", r.context["form"].errors)
		self.assertIn("full_name", r.context["form"].errors)

	def test_child_price_rejected_for_adult_age(self):
		r = self.client.post(self.url, self.pax(item=self.child.pk))
		self.assertIn("item", r.context["form"].errors)
		self.assertEqual(Ticket.objects.count(), 0)

	def test_child_ok_and_adult_rejected_for_child_age(self):
		born = date.today().replace(year=date.today().year - 5)
		self.assertEqual(self.client.post(self.url, self.pax(item=self.child.pk, birth_date=born.isoformat())).status_code, 302)
		r = self.client.post(self.url, self.pax(birth_date=born.isoformat()))
		self.assertIn("item", r.context["form"].errors)

	def test_foreigner_rules_follow_passport(self):
		r = self.client.post(self.url, self.pax(item=self.foreign.pk))  # local ID, foreign price
		self.assertIn("item", r.context["form"].errors)
		r = self.client.post(self.url, self.pax(document_type="passport"))  # passport, local price
		self.assertIn("item", r.context["form"].errors)
		self.assertEqual(self.client.post(self.url, self.pax(item=self.foreign.pk, document_type="passport")).status_code, 302)

	def test_transfer_requires_reference_and_proof(self):
		r = self.client.post(self.url, self.pax(payment_method="transfer"))
		self.assertIn("transfer_reference", r.context["form"].errors)
		self.assertIn("transfer_proof", r.context["form"].errors)
		ok = self.pax(payment_method="transfer", transfer_reference="TRX1", transfer_proof=photo("p.jpg", (800, 600)))
		self.assertEqual(self.client.post(self.url, ok).status_code, 302)
		self.assertTrue(Ticket.objects.get().transfer_proof)

	def test_vehicle_needs_plate_and_goods_use_quantity(self):
		r = self.client.post(self.url, {"item": self.moto.pk, "quantity": 1, "payment_method": "cash"})
		self.assertIn("plate_number", r.context["form"].errors)
		self.assertEqual(self.client.post(self.url, {"item": self.moto.pk, "quantity": 1, "plate_number": "DL 1234", "payment_method": "cash"}).status_code, 302)
		self.assertEqual(self.client.post(self.url, {"item": self.buffalo.pk, "quantity": 3, "payment_method": "cash"}).status_code, 302)
		self.assertEqual(Ticket.objects.get(item=self.buffalo).total, Decimal("30.00"))

	def test_quota_enforced_and_cancelled_frees_seat(self):
		self.assertEqual(self.client.post(self.url, self.pax(document_number="1", document_photo=photo())).status_code, 302)
		self.assertEqual(self.client.post(self.url, self.pax(document_number="2", document_photo=photo())).status_code, 302)
		r = self.client.post(self.url, self.pax(document_number="3", document_photo=photo()))
		self.assertEqual(r.status_code, 200)
		self.assertEqual(Ticket.objects.count(), 2)
		self.assertContains(r, "Kuota")
		Ticket.objects.first().__class__.objects.filter(pk=Ticket.objects.first().pk).update(status="cancelled")
		self.assertEqual(self.client.post(self.url, self.pax(document_number="4", document_photo=photo())).status_code, 302)

	def test_goods_quota(self):
		r = self.client.post(self.url, {"item": self.buffalo.pk, "quantity": 6, "payment_method": "cash"})
		self.assertEqual(Ticket.objects.count(), 0)
		self.assertContains(r, "Kuota")

	def test_sales_closed_blocks_sale(self):
		self.sailing.departure = timezone.now() + timedelta(minutes=10)
		self.sailing.save()
		self.assertRedirects(self.client.get(self.url), reverse("sell-sailings"))
		self.assertEqual(self.client.post(self.url, self.pax()).status_code, 302)
		self.assertEqual(Ticket.objects.count(), 0)


class AccessTests(SaleBase):
	def test_inspector_and_anonymous_denied(self):
		self.client.logout()
		self.assertEqual(self.client.get(self.url).status_code, 302)
		u = User.objects.create_user("insp", password="x")
		u.groups.add(Group.objects.get(name="inspector"))
		self.client.force_login(u)
		self.assertEqual(self.client.get(self.url).status_code, 403)
		self.assertEqual(self.client.get(reverse("sell-sailings")).status_code, 403)

	def test_admin_can_grant_individual_permission(self):
		u = User.objects.create_user("plain", password="x")
		self.client.force_login(u)
		self.assertEqual(self.client.get(reverse("sell-sailings")).status_code, 403)
		from django.contrib.auth.models import Permission
		u.user_permissions.add(Permission.objects.get(codename="issue_ticket"))
		u = User.objects.get(pk=u.pk)
		self.client.force_login(u)
		self.assertEqual(self.client.get(reverse("sell-sailings")).status_code, 200)

	def test_clerk_sees_only_own_tickets_and_documents_are_admin_only(self):
		self.client.post(self.url, self.pax())
		t = Ticket.objects.get()
		other = User.objects.create_user("clerk2", password="x")
		other.groups.add(Group.objects.get(name="resepsionista"))
		self.client.force_login(other)
		self.assertEqual(self.client.get(reverse("ticket-detail", args=[t.pk])).status_code, 404)
		self.assertNotContains(self.client.get(reverse("ticket-list")), t.serial)
		self.client.force_login(self.clerk)
		self.assertContains(self.client.get(reverse("ticket-list")), t.serial)
		self.assertEqual(self.client.get(reverse("ticket-document", args=[t.pk])).status_code, 403)
		admin = User.objects.create_user("adm", password="x")
		admin.groups.add(Group.objects.get(name="admin"))
		self.client.force_login(admin)
		r = self.client.get(reverse("ticket-document", args=[t.pk]))
		self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/jpeg"))
		self.assertTrue(AuditLog.objects.filter(action="document_view").exists())

	def test_print_page_has_signed_qr(self):
		self.client.post(self.url, self.pax())
		t = Ticket.objects.get()
		r = self.client.get(reverse("ticket-print", args=[t.pk]))
		self.assertContains(r, t.serial)
		self.assertContains(r, "<svg")
		self.assertEqual(Ticket.verify_payload(t.qr_payload), t.serial)
		self.assertTrue(AuditLog.objects.filter(action="ticket_print").exists())


class SeedDemoTests(TestCase):
	def test_seed_is_idempotent_and_sellable(self):
		with self.assertRaises(Exception):
			call_command("seed_demo", stdout=StringIO())  # refuses with DEBUG off
		call_command("seed_demo", force=True, stdout=StringIO()); call_command("seed_demo", force=True, stdout=StringIO())
		self.assertEqual(Sailing.objects.count(), 2)
		self.assertEqual(SailingQuota.objects.filter(quota_group="passenger", capacity=200).count(), 2)
