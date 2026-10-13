from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
	"""Staff user. Access is driven by Groups plus per-user permissions set by an admin."""

	preferred_language = models.CharField(
		_("Lian"), max_length=5, choices=settings.LANGUAGES, default=settings.LANGUAGE_CODE
	)
	operator = models.ForeignKey(
		"custom.Operator", null=True, blank=True, on_delete=models.SET_NULL,
		related_name="users", verbose_name=_("Operadór"),
		help_text=_("Uza-na'in operadór nia haree de'it dadus operadór rasik nian."),
	)
	phone = models.CharField(_("Telefone"), max_length=30, blank=True)


class AuditLog(models.Model):
	"""Append-only record of logins, cancellations/refunds and other sensitive actions."""

	user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
	username = models.CharField(max_length=150, blank=True)
	action = models.CharField(max_length=60, db_index=True)
	detail = models.TextField(blank=True)
	ip = models.GenericIPAddressField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True, db_index=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"{self.created_at:%Y-%m-%d %H:%M} {self.username} {self.action}"

	@classmethod
	def record(cls, action, user=None, detail="", request=None, username=""):
		ip = None
		if request is not None:
			ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
		return cls.objects.create(
			user=user if getattr(user, "pk", None) else None,
			username=username or getattr(user, "username", ""),
			action=action, detail=detail, ip=ip or None,
		)
