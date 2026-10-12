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
