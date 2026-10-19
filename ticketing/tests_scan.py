import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from custom.models import Fare, FareItem, Operator, Port, Route, Vessel
from users.models import AuditLog, User

from .models import ScanEvent, Sailing, SailingQuota, Ticket


class ScanBase(TestCase):
	def setUp(self):
		call_command('setup_roles', verbosity=0)
		op = Operator.objects.create(name='Op')
		v = Vessel.objects.create(operator=op, name='Berlin')
		self.route = Route.objects.create(origin=Port.objects.create(code='DIL', name='Dili'),
			destination=Port.objects.create(code='BEL', name='Beloi'))
		self.item = FareItem.objects.create(name_tet='Adultu', quota_group='passenger')
		self.s = Sailing.objects.create(vessel=v, route=self.route, departure=timezone.now() + timedelta(hours=3))
		self.other = Sailing.objects.create(vessel=v, route=self.route, departure=timezone.now() + timedelta(hours=9))
		self.insp = self.user('insp', 'inspector')
		self.client.force_login(self.insp)

	def user(self, name, group):
		u = User.objects.create_user(name, password='x')
		u.groups.add(Group.objects.get(name=group))
		return u

	def ticket(self, sailing=None, **kw):
		d = dict(sailing=sailing or self.s, item=self.item, unit_price=Decimal('4'), full_name='Ana Lopes')
		d.update(kw)
		return Ticket.objects.create(**d)

	def validate(self, token, sailing=None):
		r = self.client.post(reverse('scan-validate'), json.dumps({'sailing': (sailing or self.s).pk, 'token': token}),
			content_type='application/json')
		return r.status_code, r.json()


class ValidateTests(ScanBase):
	def test_ok_then_duplicate(self):
		t = self.ticket()
		code, d = self.validate(t.qr_payload)
		self.assertEqual((code, d['result'], d['name'], d['stats']), (200, 'ok', 'Ana Lopes', {'boarded': 1, 'total': 1}))
		t.refresh_from_db()
		self.assertEqual((t.status, t.boarded_by), ('boarded', self.insp))
		self.assertIsNotNone(t.boarded_at)
		code, d = self.validate(t.qr_payload)
		self.assertEqual(d['result'], 'duplicate')
		self.assertEqual(d['boarded_by'], str(self.insp))
		self.assertEqual(ScanEvent.objects.filter(ticket=t).count(), 2)

	def test_forged_and_garbage_are_invalid(self):
		t = self.ticket()
		for bad in (t.serial + '.deadbeefdeadbeef', 'garbage.token', '.', '', 'AP-ZZZZZZZZ.0000000000000000'):
			self.assertEqual(self.validate(bad)[1]['result'], 'invalid' if bad else 'invalid', bad)
		t.refresh_from_db(); self.assertEqual(t.status, 'issued')
		ev = ScanEvent.objects.filter(result='invalid').first()
		self.assertNotIn('deadbeef', ev.serial)  # signature is never stored

	def test_valid_signature_but_no_ticket(self):
		self.assertEqual(self.validate('AP-NOPE2345.' + Ticket.sign('AP-NOPE2345'))[1]['result'], 'not_found')

	def test_wrong_sailing_names_the_right_one(self):
		t = self.ticket(sailing=self.other)
		d = self.validate(t.qr_payload)[1]
		self.assertEqual((d['result'], d['route']), ('wrong_sailing', str(self.route)))
		t.refresh_from_db(); self.assertEqual(t.status, 'issued')

	def test_cancelled_refunded_and_cancelled_sailing(self):
		c = self.ticket(status='cancelled'); r = self.ticket(status='refunded')
		self.assertEqual([self.validate(x.qr_payload)[1]['result'] for x in (c, r)], ['cancelled', 'cancelled'])
		dead = Sailing.objects.create(vessel=self.s.vessel, route=self.route, departure=timezone.now() + timedelta(hours=5), status='cancelled')
		t = self.ticket(sailing=dead)
		self.assertEqual(self.validate(t.qr_payload, dead)[1]['result'], 'sailing_cancelled')

	def test_moved_ticket_boards_on_new_sailing_only(self):
		t = self.ticket(sailing=self.other)  # e.g. moved here after a cancellation
		self.assertEqual(self.validate(t.qr_payload, self.s)[1]['result'], 'wrong_sailing')
		self.assertEqual(self.validate(t.qr_payload, self.other)[1]['result'], 'ok')

	def test_manual_serial_is_flagged_and_case_insensitive(self):
		t = self.ticket()
		d = self.validate(t.serial.lower())[1]
		self.assertEqual(d['result'], 'ok')
		self.assertTrue(ScanEvent.objects.get(ticket=t).manual)

	def test_only_one_of_two_scans_boards(self):
		t = self.ticket()
		from . import scanning
		first = scanning._decide(Ticket.objects.get(pk=t.pk), self.s, self.insp, timezone.now())
		stale = Ticket.objects.get(pk=t.pk); stale.status = 'issued'  # a second request that read the row before the first committed
		second = scanning._decide(stale, self.s, self.insp, timezone.now())
		self.assertEqual((first, second), ('ok', 'duplicate'))

	def test_bad_requests(self):
		for body in ('not json', '{}', json.dumps({'sailing': 'x', 'token': 'a'}), json.dumps({'sailing': self.s.pk, 'token': 5})):
			r = self.client.post(reverse('scan-validate'), body, content_type='application/json')
			self.assertEqual(r.status_code, 400, body)
		self.assertEqual(self.client.get(reverse('scan-validate')).status_code, 405)


class AccessTests(ScanBase):
	def test_api_returns_json_401_403_not_redirects(self):
		self.client.logout()
		r = self.client.post(reverse('scan-validate'), '{}', content_type='application/json')
		self.assertEqual((r.status_code, r.json()['error']), (401, 'auth'))
		self.client.force_login(self.user('clerk', 'resepsionista'))
		for name, kw in (('scan-validate', {}), ('scan-sync', {}), ('scan-sailing-manifest', {'sailing_id': self.s.pk})):
			r = self.client.post(reverse(name, kwargs=kw), '{}', content_type='application/json')
			self.assertEqual(r.status_code, 403, name)
		self.assertEqual(self.client.get(reverse('scan')).status_code, 403)

	def test_scan_page_lists_boardable_sailings_only(self):
		far = Sailing.objects.create(vessel=self.s.vessel, route=self.route, departure=timezone.now() + timedelta(days=3))
		gone = Sailing.objects.create(vessel=self.s.vessel, route=self.route, departure=timezone.now() - timedelta(hours=1), status='cancelled')
		r = self.client.get(reverse('scan'))
		ids = {x['id'] for x in r.context['sailings_json']}
		self.assertEqual(ids, {self.s.pk, self.other.pk})
		self.assertContains(r, 'main/js/scan.js'); self.assertContains(r, 'manifest.webmanifest')

	def test_every_shell_file_exists(self):
		from django.contrib.staticfiles import finders
		from .views_scan import STATIC_SHELL
		from django.template.loader import render_to_string
		page = render_to_string('main/layout.html', {'user': self.insp})
		for path in STATIC_SHELL:
			self.assertTrue(finders.find(path), path)
		import re
		for src in re.findall(r'/static/(main/[^"\']+)', page):
			self.assertIn(src, STATIC_SHELL, 'layout asset missing from offline shell')

	def test_pwa_assets(self):
		sw = self.client.get(reverse('scan-sw'))
		self.assertEqual((sw.status_code, sw['Content-Type'].split(';')[0], sw['Cache-Control']), (200, 'application/javascript', 'no-cache'))
		self.assertContains(sw, 'main/js/scan.js')
		m = self.client.get(reverse('scan-manifest'))
		self.assertEqual(m['Content-Type'], 'application/manifest+json')
		j = m.json()
		self.assertEqual((j['display'], j['start_url']), ('standalone', '/ticketing/scan/'))
		self.assertEqual(len(j['icons']), 2)


class ManifestTests(ScanBase):
	def test_manifest_lists_valid_tickets_with_signed_payloads(self):
		a = self.ticket(); b = self.ticket(status='boarded'); self.ticket(status='cancelled'); self.ticket(sailing=self.other)
		d = self.client.get(reverse('scan-sailing-manifest', args=[self.s.pk])).json()
		self.assertEqual({t['s'] for t in d['tickets']}, {a.serial, b.serial})
		self.assertEqual({t['s']: t['b'] for t in d['tickets']}, {a.serial: False, b.serial: True})
		t = next(t for t in d['tickets'] if t['s'] == a.serial)
		self.assertEqual(Ticket.verify_payload(t['p']), a.serial)
		self.assertNotIn('document', json.dumps(d))
		self.assertTrue(AuditLog.objects.filter(action='scan_manifest').exists())

	def test_manifest_refused_outside_boarding_window(self):
		far = Sailing.objects.create(vessel=self.s.vessel, route=self.route, departure=timezone.now() + timedelta(days=5))
		self.assertEqual(self.client.get(reverse('scan-sailing-manifest', args=[far.pk])).status_code, 404)


class SyncTests(ScanBase):
	def sync(self, items):
		r = self.client.post(reverse('scan-sync'), json.dumps({'items': items}), content_type='application/json')
		return r.status_code, (r.json() if r.status_code == 200 else None)

	def test_replays_offline_scans_with_original_time(self):
		t = self.ticket()
		when = (timezone.now() - timedelta(minutes=40)).replace(microsecond=0)
		code, d = self.sync([{'token': t.qr_payload, 'sailing': self.s.pk, 'scanned_at': when.isoformat()}])
		self.assertEqual((code, d['results'][0]['result'], d['results'][0]['index']), (200, 'ok', 0))
		t.refresh_from_db(); self.assertEqual(t.boarded_at, when)
		ev = ScanEvent.objects.get(ticket=t); self.assertTrue(ev.offline)

	def test_future_clock_is_clamped_and_replay_is_idempotent(self):
		t = self.ticket()
		future = (timezone.now() + timedelta(days=2)).isoformat()
		item = {'token': t.qr_payload, 'sailing': self.s.pk, 'scanned_at': future}
		self.sync([item])
		t.refresh_from_db(); self.assertLessEqual(t.boarded_at, timezone.now())
		self.assertEqual(self.sync([item])[1]['results'][0]['result'], 'duplicate')  # a retried upload never double boards

	def test_two_phones_same_ticket_earliest_wins_results_keep_order(self):
		t = self.ticket(); other = self.ticket(full_name='Beto')
		early = (timezone.now() - timedelta(minutes=30)).isoformat(); late = (timezone.now() - timedelta(minutes=5)).isoformat()
		items = [{'token': t.qr_payload, 'sailing': self.s.pk, 'scanned_at': late},
			{'token': other.qr_payload, 'sailing': self.s.pk, 'scanned_at': late},
			{'token': t.qr_payload, 'sailing': self.s.pk, 'scanned_at': early}]
		res = self.sync(items)[1]['results']
		self.assertEqual([r['index'] for r in res], [0, 1, 2])
		self.assertEqual([r['result'] for r in res], ['duplicate', 'ok', 'ok'])  # item 2 (earliest) boarded the ticket

	def test_bad_items_do_not_abort_the_batch(self):
		t = self.ticket()
		code, d = self.sync([{'token': 5, 'sailing': self.s.pk}, 'junk', {'token': t.qr_payload, 'sailing': 99999},
			{'token': t.qr_payload, 'sailing': self.s.pk}])
		self.assertEqual([r['result'] for r in d['results']], ['error', 'error', 'error', 'ok'])
		self.assertEqual(self.sync('x')[0], 400)
		self.assertEqual(self.sync([{}] * 501)[0], 400)
