from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _

from config.decorators import perm_required

from .forms import LockoutAuthenticationForm, ProfileForm, UserCreateForm, UserEditForm, client_ip
from .models import AuditLog, User


class StaffLoginView(auth_views.LoginView):
	template_name = "home/login.html"
	authentication_form = LockoutAuthenticationForm
	redirect_authenticated_user = True

	def form_valid(self, form):
		response = super().form_valid(form)
		AuditLog.record("login", user=form.get_user(), request=self.request)
		lang = form.get_user().preferred_language
		if lang:
			response.set_cookie("django_language", lang)
		return response


class StaffLogoutView(auth_views.LogoutView):
	def post(self, request, *args, **kwargs):
		if request.user.is_authenticated:
			AuditLog.record("logout", user=request.user, request=request)
		return super().post(request, *args, **kwargs)


def _group(request):
	return request.user.groups.all()[0].name if request.user.groups.exists() else 'admin'


# ------------------------------------------------------------------------------- user administration
@login_required
@perm_required('users.change_user')
def UserList(request):
	objects = User.objects.select_related('operator').prefetch_related('groups').order_by('username')
	context = {'group': _group(request), 'objects': objects, 'title': 'Uza-na\'in', 'legend': "Uza-na'in"}
	return render(request, 'users/list.html', context)


def _user_page(request, form, legend, target=None):
	inherited = []
	if target is not None:
		from django.contrib.auth.models import Permission
		inherited = sorted(Permission.objects.filter(group__user=target, content_type__app_label='ticketing').values_list('codename', flat=True))
	return render(request, 'users/form.html', {'group': _group(request), 'form': form, 'legend': legend, 'title': "Uza-na'in",
		'target': target, 'inherited': inherited})


@login_required
@perm_required('users.add_user')
def UserAdd(request):
	form = UserCreateForm(request.POST or None, acting=request.user)
	if request.method == 'POST' and form.is_valid():
		user = form.save()
		AuditLog.record('user_added', user=request.user, request=request, detail=f'{user.username} role={form.cleaned_data["role"]}')
		if form.cleaned_data.get('invite'):
			sent = send_set_password_email(request, user, invited=True)
			messages.success(request, _("Uza-na'in kria ona. Konvite haruka ona.") if sent else _("Uza-na'in kria ona, maibé email la haruka. Haruka link husi lista."))
		else:
			messages.success(request, _("Uza-na'in kria ona."))
		return redirect('user-list')
	return _user_page(request, form, _("Aumenta uza-na'in"))


@login_required
@perm_required('users.change_user')
def UserEdit(request, pk):
	target = get_object_or_404(User, pk=pk)
	form = UserEditForm(request.POST or None, instance=target, acting=request.user)
	if request.method == 'POST' and form.is_valid():
		changed = sorted(form.changed_data)
		user = form.save()
		AuditLog.record('user_changed', user=request.user, request=request, detail=f'{user.username} {changed}')
		messages.success(request, _("Atualiza ona."))
		return redirect('user-list')
	return _user_page(request, form, f'{_("Edita")} · {target.username}', target)


@login_required
@perm_required('users.change_user')
def UserPassword(request, pk):
	target = get_object_or_404(User, pk=pk)
	form = SetPasswordForm(target, request.POST or None)
	if request.method == 'POST' and form.is_valid():
		form.save()
		AuditLog.record('user_password_set', user=request.user, request=request, detail=target.username)
		messages.success(request, _("Liafuan-pase muda ona. Sesaun antigu taka ona."))
		return redirect('user-list')
	from crispy_forms.helper import FormHelper
	form.helper = FormHelper(); form.helper.form_tag = False
	return render(request, 'users/password_form.html', {'group': _group(request), 'form': form, 'target': target,
		'legend': f'{_("Liafuan-pase")} · {target.username}', 'title': "Uza-na'in"})


@login_required
@perm_required('users.change_user')
def UserSendLink(request, pk):
	target = get_object_or_404(User, pk=pk)
	if request.method == 'POST':
		if not target.email:
			messages.error(request, _("Uza-na'in ne'e la iha email."))
		elif send_set_password_email(request, target, invited=not target.has_usable_password()):
			AuditLog.record('user_link_sent', user=request.user, request=request, detail=target.username)
			messages.success(request, _("Link haruka ona ba %(e)s.") % {'e': target.email})
		else:
			messages.error(request, _("Email la haruka."))
	return redirect('user-list')


@login_required
@perm_required('users.view_auditlog')
def AuditList(request):
	qs = AuditLog.objects.all()
	action = request.GET.get('action', '').strip()
	if action:
		qs = qs.filter(action=action)
	context = {'group': _group(request), 'objects': qs[:1500], 'action': action, 'actions': AuditLog.objects.order_by().values_list('action', flat=True).distinct(),
		'title': 'Audit', 'legend': 'Audit Log'}
	return render(request, 'users/audit.html', context)


# --------------------------------------------------------------------------------------- own account
@login_required
def Account(request):
	form = ProfileForm(request.POST or None, instance=request.user)
	if request.method == 'POST' and form.is_valid():
		form.save()
		AuditLog.record('profile_changed', user=request.user, request=request, detail=str(sorted(form.changed_data)))
		messages.success(request, _("Atualiza ona."))
		response = redirect('account')
		response.set_cookie('django_language', request.user.preferred_language)
		return response
	return render(request, 'auth/account.html', {'group': _group(request), 'form': form, 'title': 'Konta', 'legend': 'Ha\'u-nia konta'})


class PasswordChange(auth_views.PasswordChangeView):
	template_name = 'auth/change_password.html'
	success_url = reverse_lazy('account')

	def form_valid(self, form):
		AuditLog.record('password_changed', user=self.request.user, request=self.request)
		messages.success(self.request, _("Liafuan-pase muda ona."))
		return super().form_valid(form)

	def get_context_data(self, **kw):
		return {**super().get_context_data(**kw), 'title': 'Konta', 'legend': _("Muda liafuan-pase")}


# -------------------------------------------------------------------------- "forgot my password" by e-mail
RESET_PER_HOUR = 5


class PasswordReset(auth_views.PasswordResetView):
	template_name = 'auth/password_reset.html'
	email_template_name = 'auth/password_reset_email.txt'
	subject_template_name = 'auth/password_reset_subject.txt'
	success_url = reverse_lazy('password_reset_done')

	def form_valid(self, form):
		key = f'pwreset:{client_ip(self.request)}'
		n = cache.get(key, 0)
		cache.set(key, n + 1, 3600)
		if n >= RESET_PER_HOUR:  # throttled: look identical to the user, send nothing
			return redirect(self.success_url)
		AuditLog.record('password_reset_requested', request=self.request, username=form.cleaned_data.get('email', '')[:150])
		return super().form_valid(form)


class PasswordResetConfirm(auth_views.PasswordResetConfirmView):
	template_name = 'auth/password_reset_confirm.html'
	success_url = reverse_lazy('password_reset_complete')

	def form_valid(self, form):
		AuditLog.record('password_reset_done', user=form.user, request=self.request)
		return super().form_valid(form)


def send_set_password_email(request, user, invited=False):
	"""Mail a one-time set/reset password link (works for users that have no usable password yet)."""
	if not user.email:
		return False
	ctx = {'email': user.email, 'domain': request.get_host(), 'site_name': 'APORTIL Bilheteira', 'uid': urlsafe_base64_encode(force_bytes(user.pk)),
		'user': user, 'token': default_token_generator.make_token(user), 'protocol': 'https' if request.is_secure() else 'http', 'invited': invited}
	subject = ''.join(render_to_string('auth/password_reset_subject.txt', ctx).splitlines())
	try:
		return bool(send_mail(subject, render_to_string('auth/password_reset_email.txt', ctx), settings.DEFAULT_FROM_EMAIL, [user.email]))
	except Exception as e:
		AuditLog.record('email_failed', user=request.user, request=request, detail=f'set-password link for {user.username}: {type(e).__name__}'[:300])
		return False
