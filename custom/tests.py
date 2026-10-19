from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ticketing.models import Sailing, SailingQuota, Ticket
from users.models import AuditLog, User

from .models import Fare, FareItem, Operator, Port, Route, Vessel


class MasterBase(TestCase):
	def setUp(self):
		call_command('setup_roles', verbosity=0)
		self.admin = self.user('admin1', 'admin')
		self.client.force_login(self.admin)
		self.dili = Port.objects.create(code='DIL', name='Dili'); self.beloi = Port.objects.create(code='BEL', name='Beloi')
		self.route = Route.objects.create(origin=self.dili, destination=self.beloi)
		self.op = Operator.objects.create(name='Op1')
		self.vessel = Vessel.objects.create(operator=self.op, name='V1')
		self.adult = FareItem.objects.create(name_tet='Adultu', quota_group='passenger', sort_order=1)
		self.goat = FareItem.objects.create(name_tet='Bibi', quota_group='goods', sort_order=2)

	def user(self, name, group, **kw):
		u = User.objects.create_user(name, password='x', **kw); u.groups.add(Group.objects.get(name=group)); return u


ALL = ['port', 'route', 'operator', 'vessel', 'fareitem']


class AccessTests(MasterBase):
	def test_only_admin_reaches_management(self):
		urls = [reverse(f'{k}-list') for k in ALL] + [reverse(f'{k}-add') for k in ALL] + [reverse('fare-matrix')]
		for name in ('resepsionista', 'inspector', 'operator'):
			self.client.force_login(self.user('u_' + name, name))
			for u in urls:
				self.assertEqual(self.client.get(u).status_code, 403, (name, u))
			self.assertEqual(self.client.post(reverse('route-delete', args=[self.route.pk])).status_code, 403)
		self.client.logout()
		for u in urls:
			self.assertEqual(self.client.get(u).status_code, 302, u)
		self.client.force_login(self.admin)
		for u in urls:
			self.assertEqual(self.client.get(u).status_code, 200, u)

	def test_a_single_granted_permission_opens_only_that_screen(self):
		u = User.objects.create_user('partial', password='x')
		u.user_permissions.add(Permission.objects.get(codename='change_route'))
		self.client.force_login(User.objects.get(pk=u.pk))
		self.assertEqual(self.client.get(reverse('route-list')).status_code, 200)
		self.assertEqual(self.client.get(reverse('vessel-list')).status_code, 403)
		self.assertEqual(self.client.get(reverse('route-add')).status_code, 403)  # add and delete are separate rights
		self.assertEqual(self.client.post(reverse('route-delete', args=[self.route.pk])).status_code, 403)
		self.assertTrue(Route.objects.filter(pk=self.route.pk).exists())

	def test_menu_has_management_group_for_admin_only(self):
		menu = self.client.get(reverse('home')).context['menu_flat']
		self.assertTrue({'fare-matrix', 'route-list', 'user-list', 'audit-list'} <= {m['url'] for m in menu})
		self.client.force_login(self.user('c', 'resepsionista'))
		self.assertFalse({'fare-matrix', 'route-list', 'user-list'} & {m['url'] for m in self.client.get(reverse('home')).context['menu_flat']})


class CrudTests(MasterBase):
	def test_add_edit_delete_each_model(self):
		made = {
			'port': {'code': 'mah', 'name': 'Mahata'},
			'operator': {'name': 'Op2', 'email': 'op2@example.com', 'phone': '', 'is_active': 'on'},
			'vessel': {'operator': self.op.pk, 'name': 'V2', 'is_active': 'on'},
			'route': {'origin': self.dili.pk, 'destination': self.dili.pk + 100},  # replaced below
			'fareitem': {'name_tet': 'Kiak', 'quota_group': 'passenger', 'sort_order': 3, 'is_active': 'on', 'age_min': 2, 'age_max': 11},
		}
		mahata_resp = self.client.post(reverse('port-add'), made['port'])
		self.assertRedirects(mahata_resp, reverse('port-list'))
		mahata = Port.objects.get(name='Mahata'); self.assertEqual(mahata.code, 'MAH')  # normalised
		made['route'] = {'origin': self.dili.pk, 'destination': mahata.pk, 'is_active': 'on'}
		for key in ('operator', 'vessel', 'route', 'fareitem'):
			self.assertEqual(self.client.post(reverse(f'{key}-add'), made[key]).status_code, 302, key)
		self.assertTrue(Operator.objects.filter(name='Op2').exists() and Vessel.objects.filter(name='V2').exists())
		# edit
		self.client.post(reverse('operator-edit', args=[self.op.pk]), {'name': 'Op1 renamed', 'email': '', 'phone': '', 'is_active': 'on'})
		self.op.refresh_from_db(); self.assertEqual(self.op.name, 'Op1 renamed')
		self.assertTrue(AuditLog.objects.filter(action='operator_changed', detail__contains='Op1 renamed').exists())
		# delete something unused
		kiak = FareItem.objects.get(name_tet='Kiak')
		self.client.post(reverse('fareitem-delete', args=[kiak.pk]))
		self.assertFalse(FareItem.objects.filter(pk=kiak.pk).exists())
		self.assertTrue(AuditLog.objects.filter(action='fareitem_deleted').exists())
		for key in ALL:
			self.assertEqual(self.client.get(reverse(f'{key}-list')).status_code, 200)

	def test_delete_requires_post_and_survives_get(self):
		self.client.get(reverse('route-delete', args=[self.route.pk]))
		self.assertTrue(Route.objects.filter(pk=self.route.pk).exists())

	def test_protected_delete_explains_instead_of_crashing(self):
		r = self.client.post(reverse('operator-delete', args=[self.op.pk]), follow=True)  # has a vessel
		self.assertTrue(Operator.objects.filter(pk=self.op.pk).exists())
		self.assertContains(r, 'La bele hamoos')
		Vessel.objects.filter(pk=self.vessel.pk).delete()
		self.client.post(reverse('operator-delete', args=[self.op.pk]))
		self.assertFalse(Operator.objects.filter(pk=self.op.pk).exists())

	def test_route_validation(self):
		r = self.client.post(reverse('route-add'), {'origin': self.dili.pk, 'destination': self.dili.pk, 'is_active': 'on'})
		self.assertEqual(r.status_code, 200); self.assertEqual(Route.objects.count(), 1)
		r = self.client.post(reverse('route-add'), {'origin': self.dili.pk, 'destination': self.beloi.pk, 'is_active': 'on'})  # duplicate
		self.assertEqual((r.status_code, Route.objects.count()), (200, 1))

	def test_port_code_and_vessel_uniqueness(self):
		self.assertEqual(self.client.post(reverse('port-add'), {'code': 'dil', 'name': 'Other'}).status_code, 200)
		self.assertEqual(Port.objects.count(), 2)
		self.assertEqual(self.client.post(reverse('vessel-add'), {'operator': self.op.pk, 'name': 'V1'}).status_code, 200)
		self.assertEqual(Vessel.objects.count(), 1)

	def test_fareitem_rules(self):
		base = {'name_tet': 'X', 'quota_group': 'passenger', 'sort_order': 0, 'is_active': 'on'}
		bad = [{**base, 'age_min': 12, 'age_max': 5}, {**base, 'quota_group': 'goods', 'age_min': 3}, {**base, 'quota_group': 'goods', 'foreigner_only': 'on'},
			{**base, 'requires_plate': 'on'}, {**base, 'quota_group': 'vehicle', 'age_max': 4}]
		for d in bad:
			self.assertEqual(self.client.post(reverse('fareitem-add'), d).status_code, 200, d)
		self.assertEqual(FareItem.objects.filter(name_tet='X').count(), 0)
		good = {**base, 'quota_group': 'vehicle', 'requires_plate': 'on'}
		self.assertEqual(self.client.post(reverse('fareitem-add'), good).status_code, 302)


class FareMatrixTests(MasterBase):
	def setUp(self):
		super().setUp()
		self.mahata = Port.objects.create(code='MAH', name='Mahata')
		self.r2 = Route.objects.create(origin=self.dili, destination=self.mahata)
		Fare.objects.create(route=self.route, item=self.adult, price=Decimal('4.00'))
		self.url = reverse('fare-matrix')

	def cell(self, item, route):
		return f'p_{item.pk}_{route.pk}'

	def test_shows_only_active_items_and_routes_with_current_prices(self):
		FareItem.objects.create(name_tet='Hidden', quota_group='goods', is_active=False)
		Route.objects.create(origin=self.beloi, destination=self.mahata, is_active=False)
		r = self.client.get(self.url)
		self.assertEqual([row['item'].name_tet for row in r.context['rows']], ['Adultu', 'Bibi'])
		self.assertEqual(len(r.context['routes']), 2)
		self.assertEqual(r.context['rows'][0]['cells'][0]['value'], '4.00')

	def post(self, **cells):
		data = {self.cell(i, r): '' for i in (self.adult, self.goat) for r in (self.route, self.r2)}
		data.update({k: v for k, v in cells.items()})
		return self.client.post(self.url, data)

	def test_set_change_and_clear_prices_with_audit(self):
		r = self.post(**{self.cell(self.adult, self.route): '5,50', self.cell(self.goat, self.r2): '10', self.cell(self.adult, self.r2): '4'})
		self.assertRedirects(r, self.url)
		self.assertEqual(Fare.objects.get(item=self.adult, route=self.route).price, Decimal('5.50'))   # comma accepted
		self.assertEqual(Fare.objects.get(item=self.goat, route=self.r2).price, Decimal('10'))
		self.post(**{self.cell(self.adult, self.route): '', self.cell(self.goat, self.r2): '10', self.cell(self.adult, self.r2): '4'})
		self.assertFalse(Fare.objects.filter(item=self.adult, route=self.route).exists())  # blank = not sold here any more
		log = AuditLog.objects.filter(action='fare_changed')
		self.assertTrue(log.filter(detail__contains='4.00 -> 5.50').exists())
		self.assertEqual(Fare.objects.count(), 2)

	def test_invalid_price_saves_nothing_and_flags_the_cell(self):
		for bad in ('abc', '-1', '1.234', '10000', '1e3'):
			r = self.post(**{self.cell(self.adult, self.route): '9', self.cell(self.goat, self.r2): bad})
			self.assertEqual(r.status_code, 200, bad)
			self.assertEqual(Fare.objects.get(item=self.adult, route=self.route).price, Decimal('4.00'), bad)  # the valid cell was not applied either
			bad_cells = [c for row in r.context['rows'] for c in row['cells'] if c['error']]
			self.assertEqual([c['name'] for c in bad_cells], [self.cell(self.goat, self.r2)])
			self.assertContains(r, 'is-invalid')

	def test_unchanged_post_changes_nothing(self):
		self.post(**{self.cell(self.adult, self.route): '4.00'})
		self.assertEqual(AuditLog.objects.filter(action='fare_changed').count(), 0)

	def test_free_price_zero_is_allowed(self):
		self.post(**{self.cell(self.goat, self.route): '0'})
		self.assertEqual(Fare.objects.get(item=self.goat, route=self.route).price, Decimal('0'))

	def test_price_change_never_rewrites_sold_tickets_and_blank_stops_selling(self):
		s = Sailing.objects.create(vessel=self.vessel, route=self.route, departure=timezone.now() + timedelta(days=2))
		for g in ('passenger', 'vehicle', 'goods'):
			SailingQuota.objects.create(sailing=s, quota_group=g, capacity=10)
		t = Ticket.objects.create(sailing=s, item=self.adult, unit_price=Decimal('4.00'), full_name='A')
		self.post(**{self.cell(self.adult, self.route): '9.99'})
		t.refresh_from_db(); self.assertEqual(t.unit_price, Decimal('4.00'))
		self.assertEqual(Ticket.objects.get(pk=t.pk).total, Decimal('4.00'))
		from ticketing.forms import TicketForm
		offered = lambda: set(TicketForm(sailing=s).fields['item'].queryset)
		self.assertIn(self.adult, offered())
		self.post(**{self.cell(self.adult, self.route): ''})
		self.assertNotIn(self.adult, offered())
