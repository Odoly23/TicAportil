from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import AuditLog, User


class LoginTests(TestCase):
	def setUp(self):
		cache.clear()
		User.objects.create_user("rita", password="S3gredu!pass")

	def test_login_ok_and_audited(self):
		r = self.client.post(reverse("login"), {"username": "rita", "password": "S3gredu!pass"})
		self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)
		self.assertTrue(AuditLog.objects.filter(action="login", username="rita").exists())

	def test_locks_after_five_failures(self):
		for _ in range(5):
			self.client.post(reverse("login"), {"username": "rita", "password": "bad"})
		r = self.client.post(reverse("login"), {"username": "rita", "password": "S3gredu!pass"})
		self.assertEqual(r.status_code, 200)
		self.assertNotIn("_auth_user_id", self.client.session)
		self.assertTrue(AuditLog.objects.filter(action="login_locked").exists())

	def test_dashboard_requires_login(self):
		r = self.client.get(reverse("home"))
		self.assertEqual(r.status_code, 302)
		self.assertIn(reverse("login"), r["Location"])


# --------------------------------------------------------------------------- phase 6: user administration
import re  # noqa: E402

from django.contrib.auth.models import Group, Permission  # noqa: E402
from django.core import mail  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.test import Client, override_settings  # noqa: E402

from custom.models import Operator  # noqa: E402

STRONG = 'Tr0pic-Reef!77'


class AdminBase(TestCase):
	def setUp(self):
		cache.clear()
		call_command('setup_roles', verbosity=0)
		self.op = Operator.objects.create(name='Op1')
		self.admin = self.make('admin1', 'admin', email='admin1@example.com')
		self.client.force_login(self.admin)

	def make(self, name, role, **kw):
		u = User.objects.create_user(name, password=STRONG, **kw)
		u.groups.add(Group.objects.get(name=role))
		return u

	def new_user_data(self, **kw):
		d = {'username': 'maria', 'first_name': 'Maria', 'last_name': 'Silva', 'email': 'maria@example.com', 'phone': '',
			'preferred_language': 'tet', 'role': 'resepsionista', 'is_active': 'on', 'password1': STRONG, 'password2': STRONG}
		d.update(kw)
		return d


class UserCrudTests(AdminBase):
	def test_only_admin_manages_users(self):
		for name in ('resepsionista', 'inspector', 'operator'):
			self.client.force_login(self.make('x_' + name, name))
			for u in (reverse('user-list'), reverse('user-add'), reverse('user-edit', args=[self.admin.pk]), reverse('audit-list')):
				self.assertEqual(self.client.get(u).status_code, 403, (name, u))
		self.client.logout()
		self.assertEqual(self.client.get(reverse('user-list')).status_code, 302)

	def test_create_with_password_sets_exactly_one_group_and_can_login(self):
		r = self.client.post(reverse('user-add'), self.new_user_data())
		self.assertRedirects(r, reverse('user-list'))
		u = User.objects.get(username='maria')
		self.assertEqual(list(u.groups.values_list('name', flat=True)), ['resepsionista'])
		self.assertTrue(u.check_password(STRONG)); self.assertFalse(u.is_staff or u.is_superuser)
		self.assertTrue(AuditLog.objects.filter(action='user_added', detail__contains='maria').exists())
		self.assertNotIn(STRONG, ''.join(AuditLog.objects.values_list('detail', flat=True)))
		c = Client()
		self.assertTrue(c.login(username='maria', password=STRONG))

	def test_cannot_create_a_superuser_or_staff_by_posting_extra_fields(self):
		self.client.post(reverse('user-add'), self.new_user_data(is_superuser='on', is_staff='on', groups='1'))
		u = User.objects.get(username='maria')
		self.assertFalse(u.is_superuser or u.is_staff)

	def test_password_rules(self):
		for bad in ({'password1': '12345678', 'password2': '12345678'}, {'password1': 'short', 'password2': 'short'},
				{'password1': STRONG, 'password2': STRONG + 'x'}, {'password1': '', 'password2': ''}):
			r = self.client.post(reverse('user-add'), self.new_user_data(**bad))
			self.assertEqual(r.status_code, 200, bad)
		self.assertFalse(User.objects.filter(username='maria').exists())

	def test_username_unique_and_role_required(self):
		self.client.post(reverse('user-add'), self.new_user_data())
		self.assertEqual(self.client.post(reverse('user-add'), self.new_user_data()).status_code, 200)
		self.assertEqual(User.objects.filter(username='maria').count(), 1)
		r = self.client.post(reverse('user-add'), self.new_user_data(username='zz', role='nonsense'))
		self.assertEqual(r.status_code, 200); self.assertFalse(User.objects.filter(username='zz').exists())

	def test_operator_role_needs_operator_and_others_get_none(self):
		r = self.client.post(reverse('user-add'), self.new_user_data(username='opx', role='operator'))
		self.assertIn('operator', r.context['form'].errors)
		self.client.post(reverse('user-add'), self.new_user_data(username='opx', role='operator', operator=self.op.pk))
		self.assertEqual(User.objects.get(username='opx').operator, self.op)
		self.client.post(reverse('user-add'), self.new_user_data(username='clk', role='resepsionista', operator=self.op.pk))
		self.assertIsNone(User.objects.get(username='clk').operator)  # only operator users are tied to an operator
		# changing an operator user to another role drops the tie
		opx = User.objects.get(username='opx')
		self.client.post(reverse('user-edit', args=[opx.pk]), {'username': 'opx', 'first_name': '', 'last_name': '', 'email': '', 'phone': '',
			'preferred_language': 'tet', 'role': 'inspector', 'operator': self.op.pk, 'is_active': 'on'})
		opx.refresh_from_db(); self.assertIsNone(opx.operator); self.assertEqual(opx.groups.get().name, 'inspector')

	def test_extra_permissions_are_granted_and_revoked(self):
		clerk = self.make('clerk', 'resepsionista')
		self.client.force_login(clerk)
		self.assertEqual(self.client.get(reverse('report-sales')).status_code, 403)
		self.client.force_login(self.admin)
		form = {'username': 'clerk', 'first_name': '', 'last_name': '', 'email': '', 'phone': '', 'preferred_language': 'tet',
			'role': 'resepsionista', 'is_active': 'on', 'extra_perms': ['view_reports', 'view_documents']}
		self.assertEqual(self.client.post(reverse('user-edit', args=[clerk.pk]), form).status_code, 302)
		self.client.force_login(User.objects.get(pk=clerk.pk))
		self.assertEqual(self.client.get(reverse('report-sales')).status_code, 200)
		self.client.force_login(self.admin)
		self.client.post(reverse('user-edit', args=[clerk.pk]), {**form, 'extra_perms': []})
		self.client.force_login(User.objects.get(pk=clerk.pk))
		self.assertEqual(self.client.get(reverse('report-sales')).status_code, 403)

	def test_edit_page_shows_current_extras_and_role_permissions(self):
		clerk = self.make('clerk', 'resepsionista')
		clerk.user_permissions.add(Permission.objects.get(codename='view_reports'))
		r = self.client.get(reverse('user-edit', args=[clerk.pk]))
		self.assertEqual(r.context['form'].fields['extra_perms'].initial, ['view_reports'])
		self.assertIn('issue_ticket', r.context['inherited'])
		self.assertEqual(r.context['form'].fields['role'].initial, 'resepsionista')


class GuardRailTests(AdminBase):
	def edit_data(self, u, **kw):
		d = {'username': u.username, 'first_name': '', 'last_name': '', 'email': '', 'phone': '', 'preferred_language': 'tet',
			'role': 'admin', 'is_active': 'on'}
		d.update(kw)
		return d

	def test_cannot_lock_yourself_out(self):
		second = self.make('admin2', 'admin')  # so "last admin" is not the reason
		r = self.client.post(reverse('user-edit', args=[self.admin.pk]), self.edit_data(self.admin, is_active=''))
		self.assertEqual(r.status_code, 200)
		r = self.client.post(reverse('user-edit', args=[self.admin.pk]), self.edit_data(self.admin, role='inspector'))
		self.assertEqual(r.status_code, 200)
		self.assertTrue(User.objects.get(pk=self.admin.pk).groups.filter(name='admin').exists())

	def test_last_admin_cannot_be_demoted_or_deactivated(self):
		clerk = self.make('c', 'resepsionista', is_staff=False)
		su = User.objects.create_superuser('root', password=STRONG)   # a superuser counts as an admin
		self.client.force_login(su)
		r = self.client.post(reverse('user-edit', args=[self.admin.pk]), self.edit_data(self.admin, role='inspector'))
		self.assertEqual(r.status_code, 302)  # superuser remains, so this is allowed
		User.objects.filter(pk=su.pk).update(is_superuser=False)
		a2 = self.make('adm2', 'admin'); self.client.force_login(a2)
		r = self.client.post(reverse('user-edit', args=[a2.pk]), self.edit_data(a2, is_active=''))
		self.assertEqual(r.status_code, 200)
		self.assertTrue(User.objects.get(pk=a2.pk).is_active)

	def test_other_admin_can_be_demoted_when_one_remains(self):
		second = self.make('admin2', 'admin')
		r = self.client.post(reverse('user-edit', args=[second.pk]), self.edit_data(second, role='inspector'))
		self.assertEqual(r.status_code, 302)
		self.assertEqual(User.objects.get(pk=second.pk).groups.get().name, 'inspector')

	def test_deactivated_user_cannot_login(self):
		u = self.make('ana', 'resepsionista')
		self.client.post(reverse('user-edit', args=[u.pk]), self.edit_data(u, role='resepsionista', is_active=''))
		self.assertFalse(User.objects.get(pk=u.pk).is_active)
		self.assertFalse(Client().login(username='ana', password=STRONG))

	def test_admin_group_is_not_django_staff_so_no_admin_link(self):
		menu = [m['url'] for m in self.client.get(reverse('home')).context['menu_flat']]
		self.assertNotIn('admin:index', menu)
		self.admin.is_staff = True; self.admin.save()
		self.client.force_login(User.objects.get(pk=self.admin.pk))
		self.assertIn('admin:index', [m['url'] for m in self.client.get(reverse('home')).context['menu_flat']])


class InviteAndPasswordTests(AdminBase):
	def link(self, body):
		return re.search(r'https?://[^\s]+/password-reset/confirm/[^\s]+', body).group(0)

	def test_invite_creates_unusable_password_and_the_link_works_once(self):
		r = self.client.post(reverse('user-add'), self.new_user_data(invite='on', password1='', password2=''))
		self.assertRedirects(r, reverse('user-list'))
		u = User.objects.get(username='maria')
		self.assertFalse(u.has_usable_password())
		m = mail.outbox[0]
		self.assertEqual(m.to, ['maria@example.com']); self.assertIn('[TET]', m.body); self.assertIn('[ID]', m.body)
		url = self.link(m.body)
		c = Client()
		r = c.get(url.split('testserver')[-1], follow=True)   # Django swaps the token for a session URL
		self.assertTrue(r.context['validlink'])
		post_url = r.redirect_chain[-1][0]
		self.assertEqual(c.post(post_url, {'new_password1': STRONG, 'new_password2': STRONG}).status_code, 302)
		self.assertTrue(Client().login(username='maria', password=STRONG))
		self.assertTrue(AuditLog.objects.filter(action='password_reset_done', username='maria').exists())
		# the same link cannot be used again
		again = Client().get(url.split('testserver')[-1], follow=True)
		self.assertFalse(again.context['validlink'])

	def test_invite_requires_email(self):
		r = self.client.post(reverse('user-add'), self.new_user_data(invite='on', email='', password1='', password2=''))
		self.assertIn('email', r.context['form'].errors); self.assertFalse(User.objects.filter(username='maria').exists())

	def test_invite_survives_smtp_failure(self):
		from unittest import mock
		with mock.patch('users.views.send_mail', side_effect=OSError('down')):
			r = self.client.post(reverse('user-add'), self.new_user_data(invite='on', password1='', password2=''), follow=True)
		self.assertTrue(User.objects.filter(username='maria').exists())
		self.assertContains(r, 'email la haruka')
		self.assertTrue(AuditLog.objects.filter(action='email_failed').exists())

	def test_resend_link_from_list(self):
		u = self.make('ana', 'resepsionista', email='ana@example.com')
		self.client.post(reverse('user-send-link', args=[u.pk]))
		self.assertEqual(mail.outbox[0].to, ['ana@example.com'])
		noemail = self.make('bob', 'inspector')
		r = self.client.post(reverse('user-send-link', args=[noemail.pk]), follow=True)
		self.assertContains(r, 'la iha email'); self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(self.client.get(reverse('user-send-link', args=[u.pk])).status_code, 302)  # GET does nothing
		self.assertEqual(len(mail.outbox), 1)

	def test_admin_sets_password_and_old_sessions_end(self):
		u = self.make('ana', 'resepsionista')
		victim = Client(); victim.force_login(u)
		self.assertEqual(victim.get(reverse('home')).status_code, 200)
		r = self.client.post(reverse('user-password', args=[u.pk]), {'new_password1': STRONG + '2', 'new_password2': STRONG + '2'})
		self.assertRedirects(r, reverse('user-list'))
		self.assertEqual(victim.get(reverse('home')).status_code, 302)   # logged out by the password change
		self.assertTrue(Client().login(username='ana', password=STRONG + '2'))
		self.assertNotIn(STRONG, ''.join(AuditLog.objects.values_list('detail', flat=True)))
		weak = self.client.post(reverse('user-password', args=[u.pk]), {'new_password1': '12345678', 'new_password2': '12345678'})
		self.assertEqual(weak.status_code, 200)


class AccountTests(AdminBase):
	def test_profile_update_and_language_cookie(self):
		me = self.make('ana', 'resepsionista')
		self.client.force_login(me)
		r = self.client.post(reverse('account'), {'first_name': 'Ana', 'last_name': 'Costa', 'email': 'ana@example.com', 'phone': '77', 'preferred_language': 'pt'})
		self.assertRedirects(r, reverse('account'))
		me.refresh_from_db(); self.assertEqual((me.first_name, me.preferred_language), ('Ana', 'pt'))
		self.assertEqual(r.cookies['django_language'].value, 'pt')
		self.assertEqual(me.username, 'ana')   # username and role cannot be self-edited
		self.client.post(reverse('account'), {'first_name': 'A', 'last_name': '', 'email': '', 'phone': '', 'preferred_language': 'tet', 'is_superuser': 'on', 'groups': '1'})
		me.refresh_from_db(); self.assertFalse(me.is_superuser); self.assertEqual(me.groups.get().name, 'resepsionista')

	def test_password_change_needs_current_password_and_keeps_session(self):
		me = self.make('ana', 'resepsionista'); self.client.force_login(me)
		bad = self.client.post(reverse('password_change'), {'old_password': 'wrong', 'new_password1': STRONG + '9', 'new_password2': STRONG + '9'})
		self.assertEqual(bad.status_code, 200); self.assertTrue(User.objects.get(pk=me.pk).check_password(STRONG))
		ok = self.client.post(reverse('password_change'), {'old_password': STRONG, 'new_password1': STRONG + '9', 'new_password2': STRONG + '9'})
		self.assertRedirects(ok, reverse('account'))
		self.assertEqual(self.client.get(reverse('home')).status_code, 200)   # still logged in
		self.assertTrue(AuditLog.objects.filter(action='password_changed', username='ana').exists())

	def test_account_pages_need_login(self):
		self.client.logout()
		for n in ('account', 'password_change'):
			self.assertEqual(self.client.get(reverse(n)).status_code, 302)


class ForgotPasswordTests(AdminBase):
	def test_reset_email_only_for_active_users_with_email_and_never_reveals_which(self):
		self.make('ana', 'resepsionista', email='ana@example.com')
		self.make('gone', 'resepsionista', email='gone@example.com', is_active=False)
		for addr in ('ana@example.com', 'gone@example.com', 'nobody@example.com'):
			r = Client().post(reverse('password_reset'), {'email': addr})
			self.assertRedirects(r, reverse('password_reset_done'))   # identical answer every time
		self.assertEqual([m.to for m in mail.outbox], [['ana@example.com']])
		self.assertIn('[PT]', mail.outbox[0].body)

	def test_reset_is_throttled_per_ip(self):
		self.make('ana', 'resepsionista', email='ana@example.com')
		c = Client()
		for _ in range(8):
			c.post(reverse('password_reset'), {'email': 'ana@example.com'})
		self.assertEqual(len(mail.outbox), 5)

	def test_full_reset_flow(self):
		self.make('ana', 'resepsionista', email='ana@example.com')
		c = Client(); c.post(reverse('password_reset'), {'email': 'ana@example.com'})
		url = re.search(r'/password-reset/confirm/[^\s]+', mail.outbox[0].body).group(0)
		r = c.get(url, follow=True); self.assertTrue(r.context['validlink'])
		self.assertEqual(c.post(r.redirect_chain[-1][0], {'new_password1': STRONG + '!', 'new_password2': STRONG + '!'}).status_code, 302)
		self.assertTrue(Client().login(username='ana', password=STRONG + '!'))
		self.assertFalse(Client().login(username='ana', password=STRONG))

	def test_login_page_links_to_reset(self):
		self.client.logout()
		self.assertContains(self.client.get(reverse('login')), reverse('password_reset'))


class AuditViewTests(AdminBase):
	def test_audit_list_filters_by_action(self):
		AuditLog.record('ticket_sold', user=self.admin, detail='AP-1'); AuditLog.record('login', user=self.admin)
		r = self.client.get(reverse('audit-list'), {'action': 'ticket_sold'})
		self.assertEqual({a.action for a in r.context['objects']}, {'ticket_sold'})
		self.assertIn('login', set(r.context['actions']))
		self.assertEqual(self.client.get(reverse('audit-list')).status_code, 200)
