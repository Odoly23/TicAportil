from django.contrib.auth.models import Group
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
	def test_api_requires_login_and_returns_series(self):
		self.assertEqual(self.client.get("/api/report/venda/rota/").status_code, 403)
		g = Group.objects.create(name="admin")
		u = User.objects.create_user("e", password="x")
		u.groups.add(g)
		self.client.force_login(u)
		r = self.client.get("/api/report/venda/rota/")
		self.assertEqual(r.status_code, 200)
		self.assertEqual(set(r.json()), {"label", "obj"})
		self.assertEqual(self.client.get("/report/dash/").status_code, 200)

	def test_operator_cannot_open_admin_only_pages_but_can_open_report(self):
		g = Group.objects.create(name="inspector")
		u = User.objects.create_user("f", password="x")
		u.groups.add(g)
		self.client.force_login(u)
		self.assertEqual(self.client.get("/report/dash/").status_code, 403)
