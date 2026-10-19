from django import forms
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column

from .models import FareItem, Operator, Port, QuotaGroup, Route, Vessel


class CrispyModelForm(forms.ModelForm):
	layout = None  # optional: list of rows, each a list of (field, bootstrap col width)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.helper = FormHelper()
		self.helper.form_tag = False
		if self.layout:
			self.helper.layout = Layout(*[Row(*[Column(f, css_class=f'col-md-{w}') for f, w in row]) for row in self.layout])


class PortForm(CrispyModelForm):
	layout = [[('code', 4), ('name', 8)]]

	class Meta:
		model = Port
		fields = ['code', 'name']
		labels = {'code': _("Kódigu"), 'name': _("Naran")}

	def clean_code(self):
		return self.cleaned_data['code'].strip().upper()


class RouteForm(CrispyModelForm):
	layout = [[('origin', 5), ('destination', 5), ('is_active', 2)]]

	class Meta:
		model = Route
		fields = ['origin', 'destination', 'is_active']
		labels = {'origin': _("Husi"), 'destination': _("Ba"), 'is_active': _("Ativu")}

	def clean(self):
		cd = super().clean()
		if cd.get('origin') and cd.get('origin') == cd.get('destination'):
			raise forms.ValidationError(_("Husi no ba la bele hanesan."))
		return cd


class OperatorForm(CrispyModelForm):
	layout = [[('name', 6), ('is_active', 6)], [('email', 6), ('phone', 6)]]

	class Meta:
		model = Operator
		fields = ['name', 'email', 'phone', 'is_active']
		labels = {'name': _("Naran"), 'email': _("Email (ba notifikasaun)"), 'phone': _("Telefone"), 'is_active': _("Ativu")}


class VesselForm(CrispyModelForm):
	layout = [[('operator', 5), ('name', 5), ('is_active', 2)]]

	class Meta:
		model = Vessel
		fields = ['operator', 'name', 'is_active']
		labels = {'operator': _("Operadór"), 'name': _("Naran"), 'is_active': _("Ativu")}


class FareItemForm(CrispyModelForm):
	layout = [[('name_tet', 6), ('name_pt', 6)], [('name_en', 6), ('name_id', 6)],
		[('quota_group', 4), ('sort_order', 4), ('is_active', 4)],
		[('age_min', 3), ('age_max', 3), ('foreigner_only', 3), ('requires_plate', 3)], [('is_block', 12)]]

	class Meta:
		model = FareItem
		fields = ['name_tet', 'name_pt', 'name_en', 'name_id', 'quota_group', 'sort_order', 'is_active',
			'age_min', 'age_max', 'foreigner_only', 'requires_plate', 'is_block']
		labels = {'quota_group': _("Kuota"), 'sort_order': _("Orden"), 'is_active': _("Ativu"), 'age_min': _("Idade minimu"),
			'age_max': _("Idade maximu"), 'foreigner_only': _("Estranjeiru (pasaporte) de'it"), 'requires_plate': _("Presiza nú. plaka"),
			'is_block': _("Aluga parte (blok): ema ida aluga kursi / veíkulu / sasán balu de'it")}

	def clean(self):
		cd = super().clean()
		g, lo, hi = cd.get('quota_group'), cd.get('age_min'), cd.get('age_max')
		if lo is not None and hi is not None and lo > hi:
			self.add_error('age_max', _("Idade maximu tenke boot liu minimu."))
		if g and g != QuotaGroup.PASSENGER:
			if lo is not None or hi is not None or cd.get('foreigner_only'):
				raise forms.ValidationError(_("Idade no estranjeiru ba pasajeiru de'it."))
		if cd.get('is_block'):
			if g == QuotaGroup.CHARTER:
				raise forms.ValidationError(_("Aluga ró tomak la presiza blok. Hili kuota seluk ba aluga parte."))
			if lo is not None or hi is not None or cd.get('foreigner_only') or cd.get('requires_plate'):
				raise forms.ValidationError(_("Blok la uza idade, estranjeiru ka plaka."))
		if g and g != QuotaGroup.VEHICLE and cd.get('requires_plate'):
			raise forms.ValidationError(_("Nú. plaka ba veíkulu de'it."))
		return cd
