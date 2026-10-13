from datetime import timedelta

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column

from custom.models import Operator, Route, Vessel
from ticketing.services import is_global

from .services import Filters

MAX_DAYS = 1100


class DateInput(forms.DateInput):
	input_type = 'date'


class ReportFilterForm(forms.Form):
	start = forms.DateField(label=_("Husi"), widget=DateInput(format='%Y-%m-%d'))
	end = forms.DateField(label=_("To'o"), widget=DateInput(format='%Y-%m-%d'))
	route = forms.ModelChoiceField(label=_("Rota"), queryset=Route.objects.all(), required=False, empty_label=_("— Hotu —"))
	vessel = forms.ModelChoiceField(label=_("Ró"), queryset=Vessel.objects.none(), required=False, empty_label=_("— Hotu —"))
	operator = forms.ModelChoiceField(label=_("Operadór"), queryset=Operator.objects.all(), required=False, empty_label=_("— Hotu —"))

	def __init__(self, data=None, user=None):
		today = timezone.localdate()
		super().__init__(data or None, initial={'start': today.replace(day=1), 'end': today})
		self.user = user
		vessels = Vessel.objects.select_related('operator')
		if not is_global(user):
			vessels = vessels.filter(operator_id=user.operator_id) if user.operator_id else vessels.none()
			del self.fields['operator']  # an operator only ever sees their own figures
		self.fields['vessel'].queryset = vessels
		self.helper = FormHelper()
		self.helper.form_tag = False
		cols = [Column('start', css_class='col-6 col-md-2'), Column('end', css_class='col-6 col-md-2'),
			Column('route', css_class='col-md-3'), Column('vessel', css_class='col-md-3')]
		if 'operator' in self.fields:
			cols.append(Column('operator', css_class='col-md-2'))
		self.helper.layout = Layout(Row(*cols))

	def clean(self):
		cd = super().clean()
		s, e = cd.get('start'), cd.get('end')
		if s and e:
			if e < s:
				raise forms.ValidationError(_("Data final tenke depois data inísiu."))
			if (e - s).days > MAX_DAYS:
				raise forms.ValidationError(_("Períodu naruk liu."))
		return cd

	def filters(self):
		"""Filters for the submitted range, or this month when the form was not submitted."""
		if self.is_bound and self.is_valid():
			cd = self.cleaned_data
			return Filters(self.user, cd['start'], cd['end'], cd['route'] and cd['route'].pk, cd['vessel'] and cd['vessel'].pk,
				cd.get('operator') and cd['operator'].pk)
		i = self.initial
		return Filters(self.user, i['start'], i['end'])
