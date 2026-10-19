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
		self.child = mk(name_tet="Labarik", quota_group="passenger", age_min=2, age_max=11)
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
		self.assertTrue(labels[0].startswith(("Adultu", "Labarik", "Estranjeiru")))

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


# --------------------------------------------- categories: adult / senior / child, charter, government bonus
from django.contrib.auth.models import Permission  # noqa: E402


class ThreeClassTests(SaleBase):
	"""Passenger classes are only child / adult / senior. Foreigners buy those same classes unless the admin
	defines a separate foreigner tariff."""

	def setUp(self):
		super().setUp()
		for it in (self.adult, self.child, self.foreign):
			it.name_tet = it.name_tet  # keep fixture names; the rules below are what matter
		FareItem.objects.filter(pk=self.foreign.pk).update(is_active=False)  # no foreigner tariff defined
		Fare.objects.filter(item=self.foreign).delete()
		self.senior = FareItem.objects.create(name_tet='Idozu', quota_group='passenger', age_min=60)
		FareItem.objects.filter(pk=self.adult.pk).update(age_min=12, age_max=59)
		Fare.objects.create(route=self.route, item=self.senior, price=Decimal('2'))

	def test_foreigner_with_passport_buys_normal_adult_when_no_foreign_tariff(self):
		r = self.client.post(self.url, self.pax(document_type='passport', document_number='P123'))
		self.assertEqual(r.status_code, 302)
		self.assertEqual(Ticket.objects.get().item, self.adult)

	def test_foreign_tariff_is_enforced_only_once_the_admin_defines_it(self):
		FareItem.objects.filter(pk=self.foreign.pk).update(is_active=True)
		Fare.objects.create(route=self.route, item=self.foreign, price=Decimal('10'))
		r = self.client.post(self.url, self.pax(document_type='passport'))
		self.assertIn('item', r.context['form'].errors)
		# a senior passport holder: the foreign tariff starts at 12 so it fits, still enforced
		born = date.today().replace(year=date.today().year - 70)
		r = self.client.post(self.url, self.pax(document_type='passport', item=self.senior.pk, birth_date=born.isoformat()))
		self.assertIn('item', r.context['form'].errors)
		# a 5-year-old foreigner is below the foreign tariff's minimum age, so the child class is fine
		kid = date.today().replace(year=date.today().year - 5)
		ok = self.client.post(self.url, self.pax(document_type='passport', item=self.child.pk, birth_date=kid.isoformat(), document_number='P9'))
		self.assertEqual(ok.status_code, 302)

	def test_senior_class_by_age(self):
		born = date.today().replace(year=date.today().year - 70)
		self.assertEqual(self.client.post(self.url, self.pax(item=self.senior.pk, birth_date=born.isoformat())).status_code, 302)
		r = self.client.post(self.url, self.pax(item=self.senior.pk))  # born 1990: not a senior
		self.assertIn('item', r.context['form'].errors)
		r = self.client.post(self.url, self.pax(item=self.adult.pk, birth_date=born.isoformat(), document_number='2', document_photo=photo()))
		self.assertIn('item', r.context['form'].errors)   # a 70-year-old cannot take the adult (12-59) price


class SeedClassesTests(TestCase):
	def test_demo_seed_has_exactly_the_three_passenger_classes(self):
		call_command('seed_demo', force=True, stdout=StringIO())
		self.assertEqual(set(FareItem.objects.filter(quota_group='passenger', is_block=False).values_list('name_tet', flat=True)), {'Labarik', 'Adultu', 'Idozu'})
		self.assertFalse(FareItem.objects.filter(name_tet__in=['Kiak', 'Riku']).exists())
		self.assertFalse(FareItem.objects.filter(foreigner_only=True).exists())
		self.assertEqual(set(FareItem.objects.filter(quota_group='charter').values_list('name_tet', flat=True)), {'Aluga ró'})
		from custom.views import age_coverage_warnings
		self.assertEqual(age_coverage_warnings(), [])   # 0-11 / 12-59 / 60+ leaves no gap and no overlap


class CharterTests(SaleBase):
	def setUp(self):
		super().setUp()
		self.charter = FareItem.objects.create(name_tet='Aluga ró', quota_group='charter')
		Fare.objects.create(route=self.route, item=self.charter, price=Decimal('500'))
		SailingQuota.objects.create(sailing=self.sailing, quota_group='charter', capacity=1)
		self.clerk.user_permissions.add(Permission.objects.get(codename='issue_charter'))
		self.client.force_login(User.objects.get(pk=self.clerk.pk))

	def hire(self, **kw):
		d = {'item': self.charter.pk, 'full_name': 'Ministériu Saúde', 'contact_whatsapp': '+67077000000', 'payment_method': 'transfer',
			'transfer_reference': 'TRX9', 'transfer_proof': photo('p.jpg', (800, 600))}
		d.update(kw)
		return self.client.post(self.url, d)

	def test_charter_needs_its_own_permission(self):
		plain = User.objects.create_user('plain', password='x'); plain.groups.add(Group.objects.get(name='resepsionista'))
		self.client.force_login(plain)
		items = self.client.get(self.url).context['form'].fields['item'].queryset
		self.assertNotIn(self.charter, items)
		r = self.client.post(self.url, {'item': self.charter.pk, 'full_name': 'X', 'contact_whatsapp': '1', 'payment_method': 'cash'})
		self.assertIn('item', r.context['form'].errors)   # forged request: the item is not a valid choice for this user
		self.assertEqual(Ticket.objects.count(), 0)

	def test_charter_sale_uses_tariff_or_negotiated_price_and_closes_the_sailing(self):
		r = self.hire(custom_price='450.50')
		t = Ticket.objects.get()
		self.assertRedirects(r, reverse('ticket-print', args=[t.pk]), fetch_redirect_response=False)
		self.assertEqual((t.unit_price, t.list_price, t.quantity), (Decimal('450.50'), Decimal('500.00'), 1))
		self.assertTrue(self.sailing.is_chartered)
		self.assertTrue(AuditLog.objects.filter(action='charter_sold', detail__contains='tariff $500').exists())
		# nobody else can buy seats on a chartered sailing
		other = self.client.post(self.url, self.pax(), follow=True)
		self.assertRedirects(other, reverse('sell-sailings')); self.assertEqual(Ticket.objects.count(), 1)
		self.assertContains(other, 'charter')
		# and the rule also holds inside the form itself (a sale that raced the charter)
		from .forms import TicketForm
		form = TicketForm(self.pax(), {'document_photo': photo()}, sailing=self.sailing, user=self.clerk)
		self.assertFalse(form.is_valid()); self.assertIn('charter', ' '.join(form.non_field_errors()).lower())

	def test_quantity_is_never_zero_and_blank_means_one(self):
		r = self.client.post(self.url, {'item': self.buffalo_item().pk, 'quantity': 0, 'payment_method': 'cash'})
		self.assertIn('quantity', r.context['form'].errors)
		self.assertEqual(Ticket.objects.count(), 0)
		self.client.post(self.url, {'item': self.buffalo_item().pk, 'payment_method': 'cash'})
		self.assertEqual(Ticket.objects.get().quantity, 1)

	def buffalo_item(self):
		it, _ = FareItem.objects.get_or_create(name_tet='Karau', defaults={'quota_group': 'goods'})
		Fare.objects.get_or_create(route=self.route, item=it, defaults={'price': Decimal('10')})
		return it

	def test_default_price_is_the_tariff(self):
		self.hire()
		self.assertEqual(Ticket.objects.get().unit_price, Decimal('500'))

	def test_cannot_charter_a_sailing_that_already_has_passengers(self):
		self.ticket_for_sailing()
		r = self.hire()
		self.assertEqual(r.status_code, 200); self.assertEqual(Ticket.objects.filter(item=self.charter).count(), 0)

	def ticket_for_sailing(self):
		return Ticket.objects.create(sailing=self.sailing, item=self.adult, unit_price=Decimal('4'), full_name='Seat')

	def test_charter_validation(self):
		r = self.hire(full_name='')
		self.assertIn('full_name', r.context['form'].errors)
		r = self.hire(contact_whatsapp='')
		self.assertIn('contact_whatsapp', r.context['form'].errors)
		r = self.hire(custom_price='-5')
		self.assertIn('custom_price', r.context['form'].errors)
		self.assertEqual(Ticket.objects.count(), 0)
		bonus = self.hire(payment_method='complimentary', bonus_reference='Nota 12')
		self.assertEqual(Ticket.objects.count(), 0)   # a charter is never a free bonus

	def test_chartered_sailing_shows_as_locked_and_charter_is_sold_once(self):
		self.hire()
		page = self.client.get(reverse('sell-sailings'))
		self.assertContains(page, 'charter')
		again = self.hire(transfer_proof=photo('p2.jpg', (800, 600)))
		self.assertEqual(Ticket.objects.filter(item=self.charter).count(), 1)

	def test_opening_the_sell_page_of_a_chartered_sailing_explains_and_redirects(self):
		self.hire()
		r = self.client.get(self.url, follow=True)
		self.assertRedirects(r, reverse('sell-sailings'))
		self.assertContains(r, 'aluga ona')

	def test_cancelling_the_charter_reopens_the_sailing(self):
		self.hire()
		t = Ticket.objects.get(); Ticket.objects.filter(pk=t.pk).update(status='cancelled')
		self.assertFalse(self.sailing.is_chartered)
		self.assertEqual(self.client.post(self.url, self.pax()).status_code, 302)

	def test_move_keeps_charter_and_seats_apart(self):
		from .services import ShortQuota, move_tickets
		self.hire()
		dest = Sailing.objects.create(vessel=self.sailing.vessel, route=self.sailing.route, departure=timezone.now() + timedelta(days=3))
		for g in ('passenger', 'charter'):
			SailingQuota.objects.create(sailing=dest, quota_group=g, capacity=5 if g == 'passenger' else 1)
		Ticket.objects.create(sailing=dest, item=self.adult, unit_price=Decimal('4'), full_name='Seat')
		with self.assertRaises(ShortQuota):
			move_tickets(self.sailing, dest)         # the charter cannot join a sailing that has passengers
		self.assertTrue(self.sailing.is_chartered)

	def test_boarding_scan_works_for_the_charter_ticket(self):
		from .scanning import process_scan
		self.hire()
		t = Ticket.objects.get()
		self.assertEqual(process_scan(self.clerk, self.sailing, t.qr_payload)['result'], 'ok')


class BonusTests(SaleBase):
	def setUp(self):
		super().setUp()
		self.officer = User.objects.create_user('officer', password='x')
		self.officer.groups.add(Group.objects.get(name='resepsionista'))
		self.officer.user_permissions.add(Permission.objects.get(codename='issue_complimentary'))
		self.client.force_login(User.objects.get(pk=self.officer.pk))

	def bonus(self, **kw):
		return self.client.post(self.url, self.pax(payment_method='complimentary', bonus_reference='Nota Gabinete PM nu. 12/2026', **kw))

	def test_bonus_ticket_is_free_but_keeps_the_normal_price_and_takes_a_seat(self):
		r = self.bonus()
		t = Ticket.objects.get()
		self.assertRedirects(r, reverse('ticket-print', args=[t.pk]), fetch_redirect_response=False)
		self.assertEqual((t.unit_price, t.list_price, t.total, t.payment_method), (Decimal('0.00'), Decimal('4.00'), Decimal('0.00'), 'complimentary'))
		self.assertEqual(self.sailing.quotas.get(quota_group='passenger').remaining, 1)   # still occupies a seat
		self.assertTrue(AuditLog.objects.filter(action='ticket_bonus', detail__contains='Nota Gabinete').exists())
		self.assertContains(self.client.get(reverse('ticket-print', args=[t.pk])), 'BONUS')

	def test_only_people_with_the_permission_can_issue_bonus(self):
		plain = User.objects.create_user('plain', password='x'); plain.groups.add(Group.objects.get(name='resepsionista'))
		self.client.force_login(plain)
		choices = [c[0] for c in self.client.get(self.url).context['form'].fields['payment_method'].choices]
		self.assertNotIn('complimentary', choices)
		r = self.bonus()
		self.assertIn('payment_method', r.context['form'].errors); self.assertEqual(Ticket.objects.count(), 0)

	def test_bonus_needs_a_reference_and_only_for_passengers(self):
		r = self.client.post(self.url, self.pax(payment_method='complimentary', bonus_reference='ab'))
		self.assertIn('bonus_reference', r.context['form'].errors)
		r = self.client.post(self.url, self.pax(payment_method='complimentary'))
		self.assertIn('bonus_reference', r.context['form'].errors)
		goat = FareItem.objects.create(name_tet='Bibi', quota_group='goods'); Fare.objects.create(route=self.route, item=goat, price=Decimal('5'))
		r = self.client.post(self.url, {'item': goat.pk, 'quantity': 1, 'payment_method': 'complimentary', 'bonus_reference': 'Nota 12345'})
		self.assertIn('payment_method', r.context['form'].errors)
		self.assertEqual(Ticket.objects.count(), 0)

	def test_age_rules_still_apply_to_bonus(self):
		r = self.client.post(self.url, self.pax(item=self.child.pk, payment_method='complimentary', bonus_reference='Nota 12345'))
		self.assertIn('item', r.context['form'].errors)

	def test_bonus_is_never_refundable_only_voidable(self):
		self.bonus()
		t = Ticket.objects.get()
		admin = User.objects.create_user('adm', password='x'); admin.groups.add(Group.objects.get(name='admin'))
		self.client.force_login(admin)
		kinds = [k for k, _ in self.client.get(reverse('ticket-cancel', args=[t.pk])).context['form'].fields['kind'].choices]
		self.assertEqual(kinds, ['void'])
		self.client.post(reverse('ticket-cancel', args=[t.pk]), {'kind': 'refund', 'reason': 'sakit parah'})
		t.refresh_from_db(); self.assertEqual(t.status, 'issued')


class ReportBonusTests(SaleBase):
	def test_reports_show_bonus_separately_and_money_is_untouched(self):
		from report import services as RS
		paying = Ticket.objects.create(sailing=self.sailing, item=self.adult, unit_price=Decimal('4'), full_name='A', sold_by=self.clerk)
		free = Ticket.objects.create(sailing=self.sailing, item=self.adult, unit_price=Decimal('0'), list_price=Decimal('4'), full_name='B',
			payment_method='complimentary', bonus_reference='Nota 12345', sold_by=self.clerk)
		day = timezone.localdate()
		s = RS.summary(RS.Filters(None, day, day))
		self.assertEqual((s['gross'], s['net'], s['tickets'], s['pax']), (Decimal('4'), Decimal('4'), 2, 2))
		self.assertEqual((s['bonus_tickets'], s['bonus_pax'], s['bonus_value']), (1, 1, Decimal('4')))
		rows = {r['label']: r for r in RS.by_payment(RS.Filters(None, day, day))}
		self.assertEqual((rows['Bonus (gratis)']['tickets'], rows['Bonus (gratis)']['net']), (1, Decimal('0')))
		drawer = RS.cashier_day(None, day)[0]
		self.assertEqual((drawer['cash'], drawer['transfer'], drawer['drawer']), (Decimal('4'), Decimal('0'), Decimal('4')))


# ------------------------------------------------------------------ partial charter (blocks) and bonus limits
from datetime import timedelta as _td  # noqa: E402

from .models import BonusPolicy  # noqa: E402
from .services import bonus_violation  # noqa: E402


class BlockCharterTests(SaleBase):
	def setUp(self):
		super().setUp()
		self.block = FareItem.objects.create(name_tet='Aluga kursi (blok)', quota_group='passenger', is_block=True)
		self.cargo_block = FareItem.objects.create(name_tet='Aluga sasán (blok)', quota_group='goods', is_block=True)
		self.full = FareItem.objects.create(name_tet='Aluga ró', quota_group='charter')
		for it, price in ((self.block, '3'), (self.cargo_block, '1'), (self.full, '500')):
			Fare.objects.create(route=self.route, item=it, price=Decimal(price))
		SailingQuota.objects.create(sailing=self.sailing, quota_group='charter', capacity=1)
		self.clerk.user_permissions.add(Permission.objects.get(codename='issue_charter'))
		self.client.force_login(User.objects.get(pk=self.clerk.pk))

	def rent(self, item=None, **kw):
		d = {'item': (item or self.block).pk, 'quantity': 2, 'full_name': 'Igreja Dili', 'contact_email': 'igreja@example.com', 'payment_method': 'cash'}
		d.update(kw)
		return self.client.post(self.url, d)

	def test_block_takes_seats_without_passenger_data_and_leaves_the_rest_sellable(self):
		r = self.rent(quantity=2, custom_price='2.50')
		t = Ticket.objects.get()
		self.assertRedirects(r, reverse('ticket-print', args=[t.pk]), fetch_redirect_response=False)
		self.assertEqual((t.quantity, t.unit_price, t.list_price, t.total, t.document_photo.name), (2, Decimal('2.50'), Decimal('3.00'), Decimal('5.00'), ''))
		self.assertEqual(self.sailing.quotas.get(quota_group='passenger').remaining, 0)   # 2 of 2 seats
		self.assertFalse(self.sailing.is_chartered)                                       # a block does not lock the vessel
		self.assertTrue(AuditLog.objects.filter(action='block_sold').exists())
		self.assertContains(self.client.get(reverse('ticket-print', args=[t.pk])), 'BLOK')

	def test_block_defaults_to_the_tariff_and_respects_the_quota(self):
		SailingQuota.objects.filter(sailing=self.sailing, quota_group='passenger').update(capacity=10)
		self.rent(quantity=4)
		self.assertEqual(Ticket.objects.get().unit_price, Decimal('3.00'))
		over = self.rent(quantity=7)   # only 6 seats left
		self.assertEqual(over.status_code, 200); self.assertEqual(Ticket.objects.count(), 1)
		self.assertContains(over, 'Kuota')
		self.assertEqual(self.client.post(self.url, self.pax()).status_code, 302)   # ordinary passengers can still buy

	def test_block_needs_hirer_and_contact_and_the_charter_permission(self):
		self.assertIn('full_name', self.rent(full_name='').context['form'].errors)
		self.assertIn('contact_whatsapp', self.rent(contact_email='').context['form'].errors)
		plain = User.objects.create_user('plain', password='x'); plain.groups.add(Group.objects.get(name='resepsionista'))
		self.client.force_login(plain)
		self.assertIn('item', self.rent().context['form'].errors)   # not even a valid choice for them
		self.assertEqual(Ticket.objects.count(), 0)

	def test_a_block_can_cover_cargo_space_too(self):
		self.rent(item=self.cargo_block, quantity=4)   # the goods quota in this fixture is 5
		t = Ticket.objects.get()
		self.assertEqual((t.item, t.quantity, t.total), (self.cargo_block, 4, Decimal('4.00')))

	def test_block_is_never_a_bonus(self):
		r = self.rent(payment_method='complimentary', bonus_reference='Nota 12345')
		self.assertIn('payment_method', r.context['form'].errors)

	def test_full_charter_and_blocks_exclude_each_other(self):
		self.rent()
		full = self.client.post(self.url, {'item': self.full.pk, 'full_name': 'X', 'contact_whatsapp': '1', 'payment_method': 'cash'})
		self.assertEqual(full.status_code, 200); self.assertEqual(Ticket.objects.filter(item=self.full).count(), 0)
		Ticket.objects.all().delete()
		self.client.post(self.url, {'item': self.full.pk, 'full_name': 'X', 'contact_whatsapp': '1', 'payment_method': 'cash'})
		self.assertTrue(self.sailing.is_chartered)
		self.assertEqual(self.rent().status_code, 302)   # redirected away from the sale page of a chartered sailing
		self.assertEqual(Ticket.objects.count(), 1)

	def test_boarding_scan_works_for_a_block_ticket(self):
		from .scanning import process_scan
		self.rent()
		self.assertEqual(process_scan(self.clerk, self.sailing, Ticket.objects.get().qr_payload)['result'], 'ok')

	def test_block_category_rules_in_the_admin_form(self):
		from custom.forms import FareItemForm
		ok = {'name_tet': 'B', 'quota_group': 'goods', 'sort_order': 1, 'is_active': True, 'is_block': True}
		self.assertTrue(FareItemForm(ok).is_valid())
		for bad in ({**ok, 'quota_group': 'charter'}, {**ok, 'quota_group': 'passenger', 'age_min': 3}, {**ok, 'quota_group': 'vehicle', 'requires_plate': True}):
			self.assertFalse(FareItemForm(bad).is_valid(), bad)

	def test_block_appears_as_its_own_row_in_reports_and_pax_counts_its_seats(self):
		from report import services as RS
		self.rent(quantity=2)
		day = timezone.localdate()
		rows = {r['label']: r for r in RS.by_item(RS.Filters(None, day, day))}
		self.assertEqual((rows['Aluga kursi (blok)']['tickets'], rows['Aluga kursi (blok)']['gross']), (1, Decimal('6.00')))
		self.assertEqual(RS.summary(RS.Filters(None, day, day))['pax'], 2)


class BonusLimitTests(SaleBase):
	def setUp(self):
		super().setUp()
		SailingQuota.objects.filter(sailing=self.sailing, quota_group='passenger').update(capacity=50)
		self.officer = User.objects.create_user('officer', password='x'); self.officer.groups.add(Group.objects.get(name='resepsionista'))
		self.officer.user_permissions.add(Permission.objects.get(codename='issue_complimentary'))
		self.client.force_login(User.objects.get(pk=self.officer.pk))

	def bonus(self, n, **kw):
		return self.client.post(self.url, self.pax(payment_method='complimentary', bonus_reference='Nota Gabinete 12/2026',
			document_number=kw.pop('doc', f'D{n}'), document_photo=photo(), **kw))

	def test_per_sailing_limit_counts_only_valid_bonus_tickets(self):
		Sailing.objects.filter(pk=self.sailing.pk).update(bonus_limit=2)
		self.assertEqual((self.bonus(1).status_code, self.bonus(2).status_code), (302, 302))
		r = self.bonus(3)
		self.assertEqual(r.status_code, 200); self.assertIn('payment_method', r.context['form'].errors)
		self.assertContains(r, 'Batas bonus')
		Ticket.objects.filter(pk=Ticket.objects.filter(payment_method='complimentary').first().pk).update(status='cancelled')
		self.assertEqual(self.bonus(4).status_code, 302)           # a voided bonus frees its slot
		self.client.post(self.url, self.pax(document_number='PAID'))  # paying tickets are never limited
		self.assertEqual(Ticket.objects.filter(payment_method='cash').count(), 1)

	def test_no_limit_by_default(self):
		for n in range(5):
			self.assertEqual(self.bonus(n).status_code, 302)

	def test_per_person_monthly_limit(self):
		BonusPolicy.objects.update_or_create(pk=1, defaults={'max_per_person_per_month': 2})
		self.assertEqual((self.bonus(1, doc='E-77').status_code, self.bonus(2, doc='e-77').status_code), (302, 302))   # case-insensitive
		r = self.bonus(3, doc='E-77')
		self.assertIn('payment_method', r.context['form'].errors)
		self.assertEqual(self.bonus(4, doc='E-88').status_code, 302)    # another official is unaffected
		# the same person in a different month is a different allowance
		later = self.sailing.__class__.objects.create(vessel=self.sailing.vessel, route=self.route,
			departure=self.sailing.departure + _td(days=40))
		SailingQuota.objects.create(sailing=later, quota_group='passenger', capacity=5)
		later_url = reverse('ticket-sell', args=[later.pk])
		ok = self.client.post(later_url, self.pax(payment_method='complimentary', bonus_reference='Nota 12345', document_number='E-77', document_photo=photo()))
		self.assertEqual(ok.status_code, 302)

	def test_the_limit_is_rechecked_under_the_lock(self):
		Sailing.objects.filter(pk=self.sailing.pk).update(bonus_limit=1)
		self.bonus(1)
		self.sailing.refresh_from_db()
		self.assertEqual(bonus_violation(self.sailing, 'eleitoral', 'D9')[0], 'sailing')   # what the view asks inside the transaction

	def test_policy_screen_is_admin_only_audited_and_seeds_new_sailings(self):
		self.assertEqual(self.client.get(reverse('bonus-policy')).status_code, 403)
		admin = User.objects.create_user('adm', password='x'); admin.groups.add(Group.objects.get(name='admin'))
		self.client.force_login(admin)
		r = self.client.post(reverse('bonus-policy'), {'max_per_person_per_month': '3', 'default_sailing_limit': '5'})
		self.assertRedirects(r, reverse('bonus-policy'))
		p = BonusPolicy.get(); self.assertEqual((p.max_per_person_per_month, p.default_sailing_limit), (3, 5))
		self.assertTrue(AuditLog.objects.filter(action='bonus_policy_changed').exists())
		from .forms_sched import SailingForm
		self.assertEqual(SailingForm(user=admin).fields['bonus_limit'].initial, 5)
		self.client.post(reverse('bonus-policy'), {'max_per_person_per_month': '', 'default_sailing_limit': ''})
		self.assertIsNone(BonusPolicy.get().max_per_person_per_month)    # blank = no limit

	def test_sailing_limit_cannot_go_below_bonuses_already_issued(self):
		self.bonus(1); self.bonus(2)
		admin = User.objects.create_user('adm', password='x'); admin.groups.add(Group.objects.get(name='admin'))
		self.client.force_login(admin)
		d = {'vessel': self.sailing.vessel_id, 'route': self.route.pk, 'departure': timezone.localtime(self.sailing.departure).strftime('%Y-%m-%dT%H:%M'),
			'sales_close_minutes': 60, 'note': '', 'cap_passenger': 50, 'cap_vehicle': 1, 'cap_goods': 1, 'cap_charter': 1, 'bonus_limit': 1}
		r = self.client.post(reverse('sailing-edit', args=[self.sailing.pk]), d)
		self.assertIn('bonus_limit', r.context['form'].errors)
		d['bonus_limit'] = 2
		self.assertEqual(self.client.post(reverse('sailing-edit', args=[self.sailing.pk]), d).status_code, 302)
		self.sailing.refresh_from_db(); self.assertEqual(self.sailing.bonus_limit, 2)
