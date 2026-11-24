from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from custom.models import Fare, FareItem, Operator, Port, Route, Vessel
from users.models import AuditLog, User

from .models import Announcement, Notification, Sailing, SailingQuota, Ticket


def dtl(dt):
	return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')


class SchedBase(TestCase):
	def setUp(self):
		call_command('setup_roles', verbosity=0)
		self.op1 = Operator.objects.create(name='Op1', email='op1@example.com')
		self.op2 = Operator.objects.create(name='Op2')
		self.v1 = Vessel.objects.create(operator=self.op1, name='V1')
		self.v1b = Vessel.objects.create(operator=self.op1, name='V1b')
		self.v2 = Vessel.objects.create(operator=self.op2, name='V2')
		self.route = Route.objects.create(origin=Port.objects.create(code='DIL', name='Dili'),
			destination=Port.objects.create(code='BEL', name='Beloi'))
		self.item = FareItem.objects.create(name_tet='Adultu', quota_group='passenger')
		Fare.objects.create(route=self.route, item=self.item, price=Decimal('4'))
		self.admin = self.user('admin1', 'admin')
		self.opuser = self.user('op1user', 'operator', operator=self.op1)
		self.op2user = self.user('op2user', 'operator', operator=self.op2)
		self.clerk = self.user('clerk', 'resepsionista')
		self.s1 = self.sailing(self.v1, hours=48)
		self.s2 = self.sailing(self.v1b, hours=72)
		self.sv2 = self.sailing(self.v2, hours=48)

	def user(self, name, group, **kw):
		u = User.objects.create_user(name, password='x', **kw)
		u.groups.add(Group.objects.get(name=group))
		return u

	def sailing(self, vessel, hours, caps=(100, 5, 20), **kw):
		s = Sailing.objects.create(vessel=vessel, route=self.route, departure=timezone.now() + timedelta(hours=hours), **kw)
		for g, c in zip(('passenger', 'vehicle', 'goods'), caps):
			SailingQuota.objects.create(sailing=s, quota_group=g, capacity=c)
		return s

	def ticket(self, s, email='', status='issued', qty=1, **kw):
		return Ticket.objects.create(sailing=s, item=self.item, quantity=qty, unit_price=Decimal('4'), status=status,
			full_name='Ana', contact_email=email, **kw)

	def login(self, u):
		self.client.force_login(u)


class ScopeAndCrudTests(SchedBase):
	def test_operator_sees_only_own_sailings(self):
		self.login(self.opuser)
		r = self.client.get(reverse('sailing-list'))
		ids = {row['obj'].pk for row in r.context['rows']}
		self.assertEqual(ids, {self.s1.pk, self.s2.pk})
		self.assertEqual(self.client.get(reverse('sailing-detail', args=[self.sv2.pk])).status_code, 404)
		self.assertEqual(self.client.post(reverse('sailing-cancel', args=[self.sv2.pk]), {'reason': 'x'}).status_code, 404)
		self.login(self.admin)
		self.assertEqual(len(self.client.get(reverse('sailing-list')).context['rows']), 3)

	def test_clerk_and_anonymous_denied(self):
		self.assertEqual(self.client.get(reverse('sailing-list')).status_code, 302)
		self.login(self.clerk)
		self.assertEqual(self.client.get(reverse('sailing-list')).status_code, 403)
		self.assertEqual(self.client.get(reverse('sailing-add')).status_code, 403)

	def post_new(self, vessel, dep, **kw):
		d = {'vessel': vessel.pk, 'route': self.route.pk, 'departure': dtl(dep), 'sales_close_minutes': 60, 'note': '',
			'cap_passenger': 150, 'cap_vehicle': 4, 'cap_goods': 30, 'cap_charter': 1}
		d.update(kw)
		return self.client.post(reverse('sailing-add'), d)

	def test_create_makes_quotas(self):
		self.login(self.admin)
		r = self.post_new(self.v1, timezone.now() + timedelta(days=10))
		s = Sailing.objects.latest('id')
		self.assertRedirects(r, reverse('sailing-detail', args=[s.pk]))
		self.assertEqual({q.quota_group: q.capacity for q in s.quotas.all()}, {'passenger': 150, 'vehicle': 4, 'goods': 30, 'charter': 1})
		self.assertEqual(s.created_by, self.admin)

	def test_create_rejects_past_overlap_and_foreign_vessel(self):
		self.login(self.admin)
		self.assertEqual(Sailing.objects.count(), 3)
		self.post_new(self.v1, timezone.now() - timedelta(hours=1))
		self.post_new(self.v1, self.s1.departure + timedelta(hours=1))  # same vessel within 3h
		self.assertEqual(Sailing.objects.count(), 3)
		self.login(self.opuser)
		self.post_new(self.v2, timezone.now() + timedelta(days=9))  # not own vessel
		self.assertEqual(Sailing.objects.count(), 3)

	def test_cannot_lower_capacity_below_sold(self):
		self.ticket(self.s1, qty=1); self.ticket(self.s1)
		self.login(self.admin)
		d = {'vessel': self.v1.pk, 'route': self.route.pk, 'departure': dtl(self.s1.departure), 'sales_close_minutes': 60,
			'note': '', 'cap_passenger': 1, 'cap_vehicle': 5, 'cap_goods': 20, 'cap_charter': 1}
		r = self.client.post(reverse('sailing-edit', args=[self.s1.pk]), d)
		self.assertIn('cap_passenger', r.context['form'].errors)
		d['cap_passenger'] = 2
		self.assertEqual(self.client.post(reverse('sailing-edit', args=[self.s1.pk]), d).status_code, 302)
		self.assertEqual(self.s1.quotas.get(quota_group='passenger').capacity, 2)

	def test_vessel_and_route_locked_once_tickets_exist(self):
		self.ticket(self.s1)
		self.login(self.admin)
		f = self.client.get(reverse('sailing-edit', args=[self.s1.pk])).context['form']
		self.assertTrue(f.fields['vessel'].disabled and f.fields['route'].disabled)

	def test_depart_and_complete(self):
		self.login(self.admin)
		self.client.post(reverse('sailing-status', args=[self.s1.pk, 'complete']))  # not departed yet -> refused
		self.s1.refresh_from_db(); self.assertEqual(self.s1.status, 'scheduled')
		self.client.post(reverse('sailing-status', args=[self.s1.pk, 'depart']))
		self.client.post(reverse('sailing-status', args=[self.s1.pk, 'complete']))
		self.s1.refresh_from_db(); self.assertEqual(self.s1.status, 'completed')
		self.assertEqual(self.client.get(reverse('sailing-status', args=[self.s1.pk, 'depart'])).status_code, 302)


class DelayCancelTests(SchedBase):
	def test_delay_updates_notifies_everyone_in_four_languages(self):
		self.ticket(self.s1, email='pax@example.com'); self.ticket(self.s1, email='PAX@example.com'); self.ticket(self.s1)
		self.login(self.admin)
		new = self.s1.departure + timedelta(hours=5)
		r = self.client.post(reverse('sailing-delay', args=[self.s1.pk]), {'new_departure': dtl(new), 'reason': 'Tempu aat'})
		self.assertRedirects(r, reverse('sailing-detail', args=[self.s1.pk]))
		old = self.s1.departure
		self.s1.refresh_from_db()
		self.assertEqual((self.s1.status, self.s1.note), ('delayed', 'Tempu aat'))
		self.assertEqual(self.s1.original_departure, old)
		self.assertEqual(Announcement.objects.get().kind, 'delayed')
		self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['op1@example.com', 'pax@example.com'])  # deduped, no blanks
		body = mail.outbox[0].body
		for tag in ('[TET]', '[PT]', '[EN]', '[ID]'):
			self.assertIn(tag, body)
		self.assertIn('Pelayaran', body)  # Indonesian text
		# staff notified: operator user yes, other operator no, the actor not
		users = set(Notification.objects.values_list('user__username', flat=True))
		self.assertEqual(users, {'op1user'})
		# still sellable after a delay, ticket still valid
		self.assertTrue(self.s1.sales_open)
		self.assertEqual(Ticket.objects.filter(sailing=self.s1, status='issued').count(), 3)

	def test_delay_validation(self):
		self.login(self.admin)
		bad = self.client.post(reverse('sailing-delay', args=[self.s1.pk]), {'new_departure': dtl(timezone.now() - timedelta(hours=2)), 'reason': 'x'})
		self.assertIn('new_departure', bad.context['form'].errors)
		self.assertEqual(Announcement.objects.count(), 0)

	def test_email_failure_does_not_block_change(self):
		self.ticket(self.s1, email='pax@example.com')
		self.login(self.admin)
		with mock.patch('django.core.mail.backends.locmem.EmailBackend.send_messages', side_effect=OSError('smtp down')):
			r = self.client.post(reverse('sailing-delay', args=[self.s1.pk]),
				{'new_departure': dtl(self.s1.departure + timedelta(hours=2)), 'reason': 'x'})
		self.assertEqual(r.status_code, 302)
		self.s1.refresh_from_db(); self.assertEqual(self.s1.status, 'delayed')
		self.assertTrue(AuditLog.objects.filter(action='email_failed').exists())

	def test_cancel_and_move_tickets(self):
		t1 = self.ticket(self.s1, email='a@example.com'); t2 = self.ticket(self.s1, qty=1)
		boarded = self.ticket(self.s1, status='boarded')
		self.login(self.admin)
		r = self.client.post(reverse('sailing-cancel', args=[self.s1.pk]), {'reason': 'Angin kuat', 'move_to': self.s2.pk})
		self.assertEqual(r.status_code, 302)
		self.s1.refresh_from_db()
		self.assertEqual((self.s1.status, self.s1.replaced_by), ('cancelled', self.s2))
		t1.refresh_from_db(); t2.refresh_from_db(); boarded.refresh_from_db()
		self.assertEqual((t1.sailing, t2.sailing, boarded.sailing), (self.s2, self.s2, self.s1))  # only issued tickets move
		self.assertEqual(Announcement.objects.get().kind, 'cancelled_moved')
		self.assertIn('a@example.com', [m.to[0] for m in mail.outbox])
		self.assertFalse(self.s1.sales_open)
		self.assertTrue(AuditLog.objects.filter(action='tickets_moved').exists())

	def test_move_rolls_back_when_target_too_small(self):
		small = self.sailing(self.v1b, hours=100, caps=(1, 0, 0))
		self.ticket(self.s1); self.ticket(self.s1)
		self.login(self.admin)
		r = self.client.post(reverse('sailing-cancel', args=[self.s1.pk]), {'reason': 'x', 'move_to': small.pk})
		self.assertEqual(r.status_code, 200)
		self.assertIn('move_to', r.context['form'].errors)
		self.s1.refresh_from_db()
		self.assertEqual(self.s1.status, 'scheduled')  # whole action rolled back
		self.assertEqual(Ticket.objects.filter(sailing=self.s1).count(), 2)
		self.assertEqual((Announcement.objects.count(), len(mail.outbox)), (0, 0))

	def test_cancel_without_move_then_move_later(self):
		self.ticket(self.s1, email='a@example.com')
		self.login(self.admin)
		self.client.post(reverse('sailing-cancel', args=[self.s1.pk]), {'reason': 'Cuaca', 'move_to': ''})
		self.assertEqual(Announcement.objects.get().kind, 'cancelled')
		self.assertTrue(self.client.get(reverse('sailing-detail', args=[self.s1.pk])).context['can_move'])
		mail.outbox.clear()
		r = self.client.post(reverse('sailing-move', args=[self.s1.pk]), {'move_to': self.s2.pk})
		self.assertEqual(r.status_code, 302)
		self.assertEqual(Ticket.objects.get().sailing, self.s2)
		self.assertTrue(any('a@example.com' in m.to for m in mail.outbox))

	def test_cannot_move_across_routes_and_targets_exclude_other_operators(self):
		other_route = Route.objects.create(origin=self.route.destination, destination=self.route.origin)
		wrong = Sailing.objects.create(vessel=self.v1b, route=other_route, departure=timezone.now() + timedelta(days=5))
		self.login(self.opuser)
		qs = self.client.get(reverse('sailing-cancel', args=[self.s1.pk])).context['form'].fields['move_to'].queryset
		self.assertEqual(set(qs), {self.s2})  # not other route, not another operator's sailing
		self.assertNotIn(wrong, qs)


class NotificationAnnouncementTests(SchedBase):
	def test_badge_and_mark_read(self):
		Notification.objects.create(user=self.opuser, kind='delayed', sailing=self.s1,
			data={'route': 'Dili ➔ Beloi', 'vessel': 'V1', 'old': self.s1.departure.isoformat(), 'new': self.s1.departure.isoformat(), 'note': 'x'})
		self.login(self.opuser)
		menu = self.client.get(reverse('home')).context['menu_flat']
		self.assertEqual([m['badge'] for m in menu if m['url'] == 'notifications'], [1])
		r = self.client.get(reverse('notifications'))
		self.assertContains(r, 'Dili')
		self.assertEqual(self.client.get(reverse('home')).context['menu_flat'][-2]['badge'] if False else
			[m['badge'] for m in self.client.get(reverse('home')).context['menu_flat'] if m['url'] == 'notifications'], [0])

	def test_auto_announcement_renders_in_visitor_language_and_expires(self):
		data = {'route': 'Dili ➔ Beloi', 'vessel': 'V1', 'old': self.s1.departure.isoformat(), 'new': self.s1.departure.isoformat(), 'note': 'Cuaca'}
		a = Announcement.objects.create(kind='delayed', data=data, sailing=self.s1)
		self.client.post('/i18n/setlang/', {'language': 'id', 'next': '/'})
		self.assertContains(self.client.get('/'), 'Pelayaran Dili')
		self.client.post('/i18n/setlang/', {'language': 'en', 'next': '/'})
		self.assertContains(self.client.get('/'), 'sailing delayed')
		Announcement.objects.filter(pk=a.pk).update(created_at=timezone.now() - timedelta(days=8))
		self.assertNotContains(self.client.get('/'), 'sailing delayed')

	def test_manual_announcement_with_email_and_operator_scope(self):
		self.ticket(self.s1, email='pax@example.com')
		self.login(self.opuser)
		r = self.client.post(reverse('announcement-add'), {'title': 'Naik jam 7', 'body': 'Mohon hadir', 'sailing': self.s1.pk,
			'is_public': 'on', 'send_email': 'on'})
		self.assertRedirects(r, reverse('announcement-list'))
		self.assertEqual([m.to[0] for m in mail.outbox], ['pax@example.com'])
		# operator must pick a sailing, and only their own
		bad = self.client.post(reverse('announcement-add'), {'title': 'x', 'body': 'y', 'is_public': 'on'})
		self.assertIn('sailing', bad.context['form'].errors)
		bad = self.client.post(reverse('announcement-add'), {'title': 'x', 'body': 'y', 'sailing': self.sv2.pk})
		self.assertIn('sailing', bad.context['form'].errors)
		a = Announcement.objects.get(title='Naik jam 7')
		self.login(self.op2user)
		self.assertEqual(self.client.post(reverse('announcement-delete', args=[a.pk])).status_code, 403)
		self.login(self.admin)
		self.client.post(reverse('announcement-delete', args=[a.pk]))
		self.assertFalse(Announcement.objects.filter(pk=a.pk).exists())


class TicketCancelTests(SchedBase):
	def test_admin_refund_frees_quota_and_audits(self):
		t = self.ticket(self.s1, email='')
		q = self.s1.quotas.get(quota_group='passenger')
		before = q.remaining
		self.login(self.admin)
		r = self.client.post(reverse('ticket-cancel', args=[t.pk]), {'kind': 'refund', 'reason': 'Ibu hamil, sakit'})
		self.assertEqual(r.status_code, 302)
		t.refresh_from_db()
		self.assertEqual((t.status, t.cancelled_by), ('refunded', self.admin))
		self.assertEqual(q.remaining, before + 1)
		self.assertTrue(AuditLog.objects.filter(action='ticket_refund', detail__contains=t.serial).exists())

	def test_void_without_refund_and_requires_reason(self):
		t = self.ticket(self.s1)
		self.login(self.admin)
		bad = self.client.post(reverse('ticket-cancel', args=[t.pk]), {'kind': 'void', 'reason': 'ab'})
		self.assertIn('reason', bad.context['form'].errors)
		self.client.post(reverse('ticket-cancel', args=[t.pk]), {'kind': 'void', 'reason': 'Salah input'})
		t.refresh_from_db(); self.assertEqual(t.status, 'cancelled')

	def test_clerk_cannot_cancel_unless_granted(self):
		from django.contrib.auth.models import Permission
		t = self.ticket(self.s1, sold_by=self.clerk)
		self.login(self.clerk)
		self.assertEqual(self.client.get(reverse('ticket-cancel', args=[t.pk])).status_code, 403)
		self.clerk.user_permissions.add(Permission.objects.get(codename='cancel_ticket'))
		self.login(User.objects.get(pk=self.clerk.pk))
		form = self.client.get(reverse('ticket-cancel', args=[t.pk])).context['form']
		self.assertEqual([k for k, _ in form.fields['kind'].choices], ['void'])  # no refund right
		bad = self.client.post(reverse('ticket-cancel', args=[t.pk]), {'kind': 'refund', 'reason': 'sakit parah'})
		self.assertIn('kind', bad.context['form'].errors)
		t.refresh_from_db(); self.assertEqual(t.status, 'issued')

	def test_cannot_cancel_boarded_or_after_departure(self):
		boarded = self.ticket(self.s1, status='boarded')
		gone = self.sailing(self.v1b, hours=200, status='departed')
		late = self.ticket(gone)
		self.login(self.admin)
		for t in (boarded, late):
			self.assertRedirects(self.client.post(reverse('ticket-cancel', args=[t.pk]), {'kind': 'refund', 'reason': 'sakit parah'}),
				reverse('ticket-detail', args=[t.pk]), fetch_redirect_response=False)
			t.refresh_from_db(); self.assertNotIn(t.status, ('cancelled', 'refunded'))
