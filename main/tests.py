from django.contrib.auth.models import Group
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from config.decorators import allowed_users
from users.models import User


class LandingTests(TestCase):
	def test_public_and_default_tetun(self):
		self.assertContains(self.client.get(reverse("landing")), "Horáriu Ró-Laran")

	def test_language_switch(self):
		r = self.client.post("/i18n/setlang/", {"language": "en", "next": "/"}, follow=True)
		self.assertContains(r, "Ferry Schedule")

	def test_login_page_renders_in_all_languages(self):
		for lang in ("tet", "pt", "en", "id"):
			self.client.post("/i18n/setlang/", {"language": lang, "next": "/"})
			self.assertEqual(self.client.get(reverse("login")).status_code, 200)


class DecoratorTests(TestCase):
	def _call(self, user, roles):
		req = RequestFactory().get("/")
		req.user = user
		return allowed_users(roles)(lambda r: HttpResponse("ok"))(req)

	def test_group_membership_any_group(self):
		u = User.objects.create_user("a", password="x")
		u.groups.add(Group.objects.create(name="staff2"), Group.objects.create(name="admin"))
		self.assertEqual(self._call(u, ["admin"]).status_code, 200)

	def test_denied_without_group(self):
		u = User.objects.create_user("b", password="x")
		self.assertEqual(self._call(u, ["admin"]).status_code, 403)

	def test_superuser_passes(self):
		u = User.objects.create_superuser("c", password="x")
		self.assertEqual(self._call(u, ["admin"]).status_code, 200)

	def test_navbar_by_role(self):
		g = Group.objects.create(name="inspector")
		u = User.objects.create_user("d", password="x")
		u.groups.add(g)
		self.client.force_login(u)
		self.assertContains(self.client.get(reverse("home")), "inspector")


class ReportApiTests(TestCase):
	def setUp(self):
		call_command("setup_roles", verbosity=0)

	def test_api_requires_login_and_returns_series(self):
		self.assertEqual(self.client.get("/api/report/venda/rota/").status_code, 403)
		g = Group.objects.get(name="admin")
		u = User.objects.create_user("e", password="x")
		u.groups.add(g)
		self.client.force_login(u)
		r = self.client.get("/api/report/venda/rota/")
		self.assertEqual(r.status_code, 200)
		self.assertEqual(set(r.json()), {"label", "obj", "obj2"})
		self.assertEqual(self.client.get("/report/dash/").status_code, 200)

	def test_operator_cannot_open_admin_only_pages_but_can_open_report(self):
		g = Group.objects.get(name="inspector")
		u = User.objects.create_user("f", password="x")
		u.groups.add(g)
		self.client.force_login(u)
		self.assertEqual(self.client.get("/report/dash/").status_code, 403)


class MenuTests(TestCase):
	def setUp(self):
		call_command("setup_roles", verbosity=0)

	def _menu_for(self, group):
		u = User.objects.create_user(group, password="x")
		u.groups.add(Group.objects.get(name=group))
		self.client.force_login(u)
		return [m["url"] for m in self.client.get(reverse("home")).context["menu_flat"]]

	def test_menu_per_role(self):
		self.assertEqual(self._menu_for("inspector"), ["home", "scan"])
		self.assertEqual(self._menu_for("resepsionista"), ["home", "sell-sailings", "ticket-list", "report-cashier"])

	def test_admin_and_operator_see_reports(self):
		self.assertIn("report-dash", self._menu_for("operator"))

	def test_sidebar_and_navbar_render(self):
		u = User.objects.create_superuser("root", password="x")
		self.client.force_login(u)
		html = self.client.get(reverse("home")).content.decode()
		self.assertIn('id="sidebar"', html)
		self.assertIn('class="main-navbar"', html)


class LogoTests(TestCase):
	def test_page_renders_without_logo_file(self):
		self.assertEqual(self.client.get(reverse("landing")).status_code, 200)

	def test_logo_used_when_present(self):
		from unittest import mock
		with mock.patch("main.context_processors.finders.find", return_value="/x/logo.png"):
			self.assertContains(self.client.get(reverse("login")), "main/images/logo.png")
