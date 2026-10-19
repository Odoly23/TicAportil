from datetime import timedelta

from django import forms
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column

from custom.models import QuotaGroup, Route, Vessel
from .models import Announcement, Sailing, SailingQuota, Ticket
from .services import scoped_sailings, is_global

DT_FMT = '%Y-%m-%dT%H:%M'
OVERLAP = timedelta(hours=3)


def dt_field(label):
	return forms.DateTimeField(label=label, input_formats=[DT_FMT, '%Y-%m-%d %H:%M'],
		widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DT_FMT))


class SailingForm(forms.ModelForm):
	departure = dt_field(_("Data no oras partida"))
	cap_passenger = forms.IntegerField(label=_("Kuota pasajeiru"), min_value=0, initial=0)
	cap_vehicle = forms.IntegerField(label=_("Kuota veíkulu"), min_value=0, initial=0)
	cap_goods = forms.IntegerField(label=_("Kuota sasán / animál"), min_value=0, initial=0)
	cap_charter = forms.IntegerField(label=_("Kuota aluga ró (0 = la bele aluga)"), min_value=0, max_value=1, initial=1)

	class Meta:
		model = Sailing
		fields = ['vessel', 'route', 'departure', 'sales_close_minutes', 'note']
		labels = {'vessel': _("Ró"), 'route': _("Rota"), 'sales_close_minutes': _("Taka faan antes (minutu)"),
			'note': _("Nota")}

	def __init__(self, *args, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		vessels = Vessel.objects.filter(is_active=True, operator__is_active=True).select_related('operator')
		if not is_global(user):
			vessels = vessels.filter(operator_id=user.operator_id) if user.operator_id else vessels.none()
		self.fields['vessel'].queryset = vessels
		self.fields['route'].queryset = Route.objects.filter(is_active=True)
		self.has_tickets = bool(self.instance.pk and self.instance.tickets.exists())
		if self.instance.pk:
			for q in self.instance.quotas.all():
				self.fields[f'cap_{q.quota_group}'].initial = q.capacity
			if self.has_tickets:  # keep vessel/route stable once tickets exist
				for f in ('vessel', 'route'):
					self.fields[f].disabled = True
		self.helper = FormHelper()
		self.helper.form_tag = False
		self.helper.layout = Layout(
			Row(Column('vessel', css_class='col-md-6'), Column('route', css_class='col-md-6')),
			Row(Column('departure', css_class='col-md-6'), Column('sales_close_minutes', css_class='col-md-6')),
			Row(Column('cap_passenger', css_class='col-md-3'), Column('cap_vehicle', css_class='col-md-3'),
				Column('cap_goods', css_class='col-md-3'), Column('cap_charter', css_class='col-md-3')),
			'note',
		)

	def clean(self):
		cd = super().clean()
		dep, vessel = cd.get('departure'), cd.get('vessel')
		if not dep or not vessel:
			return cd
		if not self.instance.pk and dep <= timezone.now():
			self.add_error('departure', _("Partida tenke iha futuru."))
		clash = Sailing.objects.filter(vessel=vessel, departure__gt=dep - OVERLAP, departure__lt=dep + OVERLAP).exclude(
			status=Sailing.Status.CANCELLED).exclude(pk=self.instance.pk)
		if clash.exists():
			self.add_error('departure', _("Ró ne'e iha viajen seluk besik oras ne'e."))
		if self.instance.pk:
			for g in QuotaGroup.values:
				sold = SailingQuota(sailing=self.instance, quota_group=g).sold
				if cd.get(f'cap_{g}') is not None and cd[f'cap_{g}'] < sold:
					self.add_error(f'cap_{g}', _("La bele menus husi %(n)d (faan ona).") % {'n': sold})
		return cd

	@transaction.atomic
	def save(self, commit=True):
		s = super().save(commit=commit)
		if commit:
			self.save_quotas(s)
		return s

	def save_quotas(self, sailing):
		for g in QuotaGroup.values:
			SailingQuota.objects.update_or_create(sailing=sailing, quota_group=g, defaults={'capacity': self.cleaned_data[f'cap_{g}']})


class DelayForm(forms.Form):
	new_departure = dt_field(_("Data no oras foun"))
	reason = forms.CharField(label=_("Razaun (ba pasajeiru)"), max_length=200)

	def __init__(self, *args, sailing=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.sailing = sailing
		self.fields['new_departure'].initial = sailing.departure
		self.helper = FormHelper(); self.helper.form_tag = False

	def clean_new_departure(self):
		d = self.cleaned_data['new_departure']
		if d <= timezone.now():
			raise forms.ValidationError(_("Partida tenke iha futuru."))
		if d == self.sailing.departure:
			raise forms.ValidationError(_("Oras hanesan ho uluk."))
		return d


def future_same_route(sailing, user):
	qs = scoped_sailings(user, Sailing.objects.filter(route=sailing.route, departure__gt=timezone.now(),
		status__in=[Sailing.Status.SCHEDULED, Sailing.Status.DELAYED])).exclude(pk=sailing.pk)
	return qs.select_related('vessel', 'route')


class CancelForm(forms.Form):
	reason = forms.CharField(label=_("Razaun (ba pasajeiru)"), max_length=200)
	move_to = forms.ModelChoiceField(label=_("Muda bilhete ba viajen"), queryset=Sailing.objects.none(), required=False,
		empty_label=_("— La muda agora —"))

	def __init__(self, *args, sailing=None, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['move_to'].queryset = future_same_route(sailing, user)
		self.helper = FormHelper(); self.helper.form_tag = False


class MoveForm(forms.Form):
	move_to = forms.ModelChoiceField(label=_("Muda bilhete ba viajen"), queryset=Sailing.objects.none())

	def __init__(self, *args, sailing=None, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['move_to'].queryset = future_same_route(sailing, user)
		self.helper = FormHelper(); self.helper.form_tag = False


class AnnouncementForm(forms.ModelForm):
	send_email = forms.BooleanField(label=_("Haruka email ba bilhete nain viajen ne'e"), required=False)

	class Meta:
		model = Announcement
		fields = ['title', 'body', 'sailing', 'is_public']
		labels = {'title': _("Títulu"), 'body': _("Mensajen"), 'sailing': _("Viajen (opsionál)"), 'is_public': _("Hatudu iha pájina públiku")}
		widgets = {'body': forms.Textarea(attrs={'rows': 4})}

	def __init__(self, *args, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.user = user
		self.fields['title'].required = True
		self.fields['body'].required = True
		self.fields['sailing'].queryset = scoped_sailings(user, Sailing.objects.filter(
			departure__gte=timezone.now() - timedelta(days=1))).select_related('vessel', 'route')
		if not is_global(user):
			self.fields['sailing'].required = True  # operators may only announce about their own sailings
		self.helper = FormHelper(); self.helper.form_tag = False


class TicketCancelForm(forms.Form):
	KINDS = [('refund', _("Fila fali osan — razaun saúde")), ('void', _("Kansela (sala emisaun) — la fila osan"))]
	kind = forms.ChoiceField(label=_("Tipu"), choices=KINDS, widget=forms.RadioSelect)
	reason = forms.CharField(label=_("Razaun / detallu"), min_length=5, max_length=200)

	def __init__(self, *args, user=None, ticket=None, **kwargs):
		super().__init__(*args, **kwargs)
		allowed = []
		free = ticket is not None and ticket.payment_method == Ticket.Payment.COMPLIMENTARY  # a bonus ticket paid nothing: nothing to refund
		if user.has_perm('ticketing.refund_ticket') and not free:
			allowed.append(self.KINDS[0])
		if user.has_perm('ticketing.cancel_ticket'):
			allowed.append(self.KINDS[1])
		self.fields['kind'].choices = allowed
		self.helper = FormHelper(); self.helper.form_tag = False
