from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import AuditLog


def client_ip(request):
	return request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


class LockoutAuthenticationForm(AuthenticationForm):
	"""Login form that locks a username/IP pair after LOGIN_MAX_ATTEMPTS failures."""

	error_messages = {
		**AuthenticationForm.error_messages,
		"invalid_login": _("Naran uza-na'in ka liafuan-pase la los. Tenta fali."),
	}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields["username"].label = _("Naran uza-na'in")
		self.fields["password"].label = _("Liafuan-pase")

	def clean(self):
		username = self.cleaned_data.get("username", "")
		key = f"loginfail:{username.lower()}:{client_ip(self.request)}"
		if cache.get(key, 0) >= settings.LOGIN_MAX_ATTEMPTS:
			AuditLog.record("login_locked", request=self.request, username=username)
			raise ValidationError(
				_("Tentativa barak liu. Hein minutu %(m)d ho tenta fali.") % {"m": settings.LOGIN_LOCKOUT_SECONDS // 60},
				code="locked",
			)
		try:
			result = super().clean()
		except ValidationError:
			cache.set(key, cache.get(key, 0) + 1, settings.LOGIN_LOCKOUT_SECONDS)
			AuditLog.record("login_failed", request=self.request, username=username)
			raise
		cache.delete(key)
		return result


# ------------------------------------------------------------------------------- user administration
from django import forms as dj_forms  # noqa: E402
from django.db.models import Q  # noqa: E402
from django.contrib.auth import password_validation  # noqa: E402
from django.contrib.auth.models import Group, Permission  # noqa: E402
from crispy_forms.helper import FormHelper  # noqa: E402
from crispy_forms.layout import Layout, Row, Column  # noqa: E402

from custom.models import Operator  # noqa: E402
from .models import User  # noqa: E402

ROLES = [('admin', _("Admin APORTIL")), ('resepsionista', _("Resepsionista (loket)")), ('inspector', _("Inspector (boarding)")),
	('operator', _("Operadór ró"))]
# Extra permissions an admin can grant one person on top of their role.
EXTRA_PERMS = [
	('issue_ticket', _("Faan bilhete")), ('cancel_ticket', _("Kansela bilhete (sala emisaun)")),
	('refund_ticket', _("Fila osan (razaun saúde)")), ('scan_ticket', _("Scan QR boarding")),
	('view_documents', _("Haree foto dokumentu")), ('view_reports', _("Haree relatóriu")),
	('manage_schedule', _("Jere jadwal no anúnsiu")),
]


class UserBaseForm(dj_forms.ModelForm):
	role = dj_forms.ChoiceField(label=_("Papél"), choices=ROLES)
	extra_perms = dj_forms.MultipleChoiceField(label=_("Izin adisionál"), choices=EXTRA_PERMS, required=False,
		widget=dj_forms.CheckboxSelectMultiple, help_text=_("Soma ba izin husi papél. La hasai izin husi papél."))

	class Meta:
		model = User
		fields = ['username', 'first_name', 'last_name', 'email', 'phone', 'preferred_language', 'operator', 'is_active']
		labels = {'username': _("Naran uza-na'in"), 'first_name': _("Naran"), 'last_name': _("Apelidu"), 'email': _("Email"),
			'phone': _("Telefone"), 'preferred_language': _("Lian"), 'operator': _("Operadór"), 'is_active': _("Ativu")}
		help_texts = {'username': _("Maximu karakter 150. Letra, númeru no @/./+/-/_ de'it."),
			'is_active': _("La ativu = la bele login. Uza ne'e, la hamoos konta."), 'operator': None}
		error_messages = {'username': {'unique': _("Naran uza-na'in ne'e iha ona.")}}

	def __init__(self, *args, acting=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.acting = acting
		self.fields['operator'].queryset = Operator.objects.filter(is_active=True)
		self.fields['operator'].required = False
		self.fields['operator'].empty_label = '—'
		self.fields['operator'].help_text = _("Uza-na'in operadór nia haree de'it dadus operadór rasik nian.")
		if self.instance.pk:
			g = self.instance.groups.first()
			self.fields['role'].initial = g.name if g else None
			self.fields['extra_perms'].initial = list(self.instance.user_permissions.filter(
				content_type__app_label='ticketing').values_list('codename', flat=True))
		self.helper = FormHelper()
		self.helper.form_tag = False

	def clean(self):
		cd = super().clean()
		role, op = cd.get('role'), cd.get('operator')
		if role == 'operator' and not op:
			self.add_error('operator', _("Operadór obrigatóriu ba papél operadór."))
		if role and role != 'operator':
			cd['operator'] = None  # only operator users are tied to an operator
		if role and role != 'admin':
			cd['extra_perms'] = list(cd.get('extra_perms') or [])
		return cd

	def save_roles(self, user):
		user.groups.set(Group.objects.filter(name=self.cleaned_data['role']))
		perms = Permission.objects.filter(content_type__app_label='ticketing', codename__in=self.cleaned_data.get('extra_perms') or [])
		user.user_permissions.set(perms)


class UserCreateForm(UserBaseForm):
	invite = dj_forms.BooleanField(label=_("Haruka email atu define liafuan-pase (la presiza hakerek agora)"), required=False)
	password1 = dj_forms.CharField(label=_("Liafuan-pase"), widget=dj_forms.PasswordInput, required=False)
	password2 = dj_forms.CharField(label=_("Konfirma liafuan-pase"), widget=dj_forms.PasswordInput, required=False)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.helper.layout = Layout(
			Row(Column('username', css_class='col-md-4'), Column('first_name', css_class='col-md-4'), Column('last_name', css_class='col-md-4')),
			Row(Column('email', css_class='col-md-4'), Column('phone', css_class='col-md-4'), Column('preferred_language', css_class='col-md-4')),
			Row(Column('role', css_class='col-md-6'), Column('operator', css_class='col-md-6')),
			'extra_perms', 'is_active', 'invite',
			Row(Column('password1', css_class='col-md-6'), Column('password2', css_class='col-md-6')))

	def clean(self):
		cd = super().clean()
		if cd.get('invite'):
			if not cd.get('email'):
				self.add_error('email', _("Email obrigatóriu atu haruka konvite."))
		else:
			p1, p2 = cd.get('password1'), cd.get('password2')
			if not p1:
				self.add_error('password1', _("Obrigatóriu."))
			elif p1 != p2:
				self.add_error('password2', _("Liafuan-pase la hanesan."))
			else:
				try:
					password_validation.validate_password(p1, User(username=cd.get('username', ''), email=cd.get('email', '')))
				except dj_forms.ValidationError as e:
					self.add_error('password1', e)
		return cd

	def save(self, commit=True):
		user = super().save(commit=False)
		if self.cleaned_data.get('invite'):
			user.set_unusable_password()
		else:
			user.set_password(self.cleaned_data['password1'])
		user.save()
		self.save_roles(user)
		return user


class UserEditForm(UserBaseForm):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.helper.layout = Layout(
			Row(Column('username', css_class='col-md-4'), Column('first_name', css_class='col-md-4'), Column('last_name', css_class='col-md-4')),
			Row(Column('email', css_class='col-md-4'), Column('phone', css_class='col-md-4'), Column('preferred_language', css_class='col-md-4')),
			Row(Column('role', css_class='col-md-6'), Column('operator', css_class='col-md-6')),
			'extra_perms', 'is_active')

	def clean(self):
		cd = super().clean()
		me, target = self.acting, self.instance
		leaving_admin = target.groups.filter(name='admin').exists() and (cd.get('role') != 'admin' or not cd.get('is_active'))
		if leaving_admin and not active_admins().exclude(pk=target.pk).exists():
			raise dj_forms.ValidationError(_("Admin ikus la bele hasai ka halo la ativu."))
		if me and target.pk == me.pk and (not cd.get('is_active') or (cd.get('role') != 'admin' and me.groups.filter(name='admin').exists())):
			raise dj_forms.ValidationError(_("Ita la bele hasai ita-nia aksesu rasik."))
		return cd

	def save(self, commit=True):
		user = super().save()
		self.save_roles(user)
		return user


def active_admins():
	return User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(groups__name='admin')).distinct()


class ProfileForm(dj_forms.ModelForm):
	class Meta:
		model = User
		fields = ['first_name', 'last_name', 'email', 'phone', 'preferred_language']
		labels = {'first_name': _("Naran"), 'last_name': _("Apelidu"), 'email': _("Email"), 'phone': _("Telefone"), 'preferred_language': _("Lian")}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.helper = FormHelper()
		self.helper.form_tag = False
