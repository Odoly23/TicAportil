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
