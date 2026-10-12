from django import forms
from django.db.models import Case, IntegerField, Value, When
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Div

from config.utils import shrink_image
from custom.models import Fare, FareItem, QuotaGroup
from .models import DocumentType, Ticket

MAX_UPLOAD = 10 * 1024 * 1024


class DateInput(forms.DateInput):
	input_type = 'date'


class ItemSelect(forms.Select):
	"""Select that exposes per-item data (group, price, flags) so the page can show the right fields."""
	option_data = {}

	def create_option(self, name, value, *args, **kwargs):
		option = super().create_option(name, value, *args, **kwargs)
		key = getattr(value, 'value', value)
		if key in self.option_data:
			option['attrs'].update(self.option_data[key])
		return option


def age_on(birth, day):
	return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


class TicketForm(forms.ModelForm):
	birth_date = forms.DateField(label=_("Data Moris"), widget=DateInput(), required=False)

	class Meta:
		model = Ticket
		fields = ['item', 'quantity', 'full_name', 'birth_date', 'sex', 'nationality', 'document_type',
			'document_number', 'document_photo', 'plate_number', 'contact_email', 'contact_whatsapp',
			'notes', 'payment_method', 'transfer_reference', 'transfer_proof']
		labels = {
			'item': _("Tipu bilhete"), 'quantity': _("Kuantidade"), 'full_name': _("Naran kompletu"),
			'sex': _("Sexu"), 'nationality': _("Nasionalidade"), 'document_type': _("Tipu dokumentu"),
			'document_number': _("Nú. dokumentu"), 'document_photo': _("Foto dokumentu"),
			'plate_number': _("Nú. plaka"), 'contact_email': _("Email (opsionál)"),
			'contact_whatsapp': _("WhatsApp (opsionál)"), 'notes': _("Observasaun"),
			'payment_method': _("Pagamentu"), 'transfer_reference': _("Nú. referénsia transferénsia"),
			'transfer_proof': _("Prova transferénsia"),
		}
		widgets = {'item': ItemSelect(), 'quantity': forms.NumberInput(attrs={'min': 1})}

	def __init__(self, *args, sailing=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.sailing = sailing
		fares = {f.item_id: f.price for f in Fare.objects.filter(route=sailing.route, item__is_active=True).select_related('item')}
		order = Case(When(quota_group=QuotaGroup.PASSENGER, then=Value(0)), When(quota_group=QuotaGroup.VEHICLE, then=Value(1)),
			default=Value(2), output_field=IntegerField())
		items = FareItem.objects.filter(pk__in=fares.keys()).order_by(order, 'sort_order', 'name_tet')
		self.fares = fares
		self.fields['item'].queryset = items
		self.fields['item'].label_from_instance = lambda i: f"{i.display_name()} — ${fares[i.pk]}"
		self.fields['item'].widget.option_data = {
			i.pk: {'data-group': i.quota_group, 'data-price': str(fares[i.pk]), 'data-plate': '1' if i.requires_plate else '0'}
			for i in items
		}
		self.fields['quantity'].initial = 1
		self.fields['nationality'].initial = 'Timor-Leste'
		self.fields['document_photo'].widget.attrs.update({'accept': 'image/*', 'capture': 'environment'})
		self.fields['transfer_proof'].widget.attrs.update({'accept': 'image/*'})
		self.helper = FormHelper()
		self.helper.form_tag = False
		self.helper.layout = Layout(
			Row(Column('item', css_class='col-md-8'), Column('quantity', css_class='col-md-4')),
			Div(
				Row(Column('full_name', css_class='col-md-6'), Column('birth_date', css_class='col-md-3'),
					Column('sex', css_class='col-md-3')),
				Row(Column('document_type', css_class='col-md-4'), Column('document_number', css_class='col-md-4'),
					Column('nationality', css_class='col-md-4')),
				Row(Column('document_photo', css_class='col-md-6'), Column('contact_whatsapp', css_class='col-md-3'),
					Column('contact_email', css_class='col-md-3')),
				css_id='passenger-fields'),
			Div('plate_number', css_id='plate-fields'),
			Row(Column('payment_method', css_class='col-md-4'),
				Div(Row(Column('transfer_reference', css_class='col-md-6'), Column('transfer_proof', css_class='col-md-6')),
					css_id='transfer-fields', css_class='col-md-8')),
			'notes',
		)

	def _image(self, name):
		f = self.cleaned_data.get(name)
		if not f:
			return f
		if f.size > MAX_UPLOAD:
			raise forms.ValidationError(_("Imajen boot liu (maximu 10 MB)."))
		try:
			return shrink_image(f)
		except Exception:
			raise forms.ValidationError(_("Ficheiru la'ós imajen válidu."))

	def clean(self):
		cd = super().clean()
		s = self.sailing
		if not s.sales_open:
			raise forms.ValidationError(_("Faan bilhete ba viajen ne'e taka ona."))
		item = cd.get('item')
		if not item:
			return cd
		qty = cd.get('quantity') or 1
		is_pax = item.quota_group == QuotaGroup.PASSENGER
		if is_pax:
			cd['quantity'] = qty = 1
			for f in ('full_name', 'birth_date', 'sex', 'document_type', 'document_number'):
				if not cd.get(f):
					self.add_error(f, _("Obrigatóriu."))
			if not self.cleaned_data.get('document_photo'):
				self.add_error('document_photo', _("Foto dokumentu obrigatóriu."))
			birth, doc = cd.get('birth_date'), cd.get('document_type')
			if birth:
				age = age_on(birth, s.departure.date())
				if age < 0:
					self.add_error('birth_date', _("Data moris la los."))
				else:
					if item.age_min is not None and age < item.age_min or item.age_max is not None and age > item.age_max:
						self.add_error('item', _("Idade pasajeiru (%(a)d) la tuir kategoria ne'e.") % {'a': age})
			if doc:
				foreign = doc == DocumentType.PASSPORT
				if item.foreigner_only and not foreign:
					self.add_error('item', _("Kategoria ne'e ba estranjeiru ho pasaporte de'it."))
				elif foreign and not item.foreigner_only:
					self.add_error('item', _("Pasaporte uza kategoria estranjeiru."))
		elif item.requires_plate and not cd.get('plate_number'):
			self.add_error('plate_number', _("Nú. plaka obrigatóriu."))
		if cd.get('payment_method') == Ticket.Payment.TRANSFER:
			if not cd.get('transfer_reference'):
				self.add_error('transfer_reference', _("Obrigatóriu."))
			if not self.cleaned_data.get('transfer_proof'):
				self.add_error('transfer_proof', _("Prova transferénsia obrigatóriu."))
		q = s.quotas.filter(quota_group=item.quota_group).first()
		if not q or q.remaining < qty:
			raise forms.ValidationError(_("Kuota la to'o. Sobra: %(n)d.") % {'n': q.remaining if q else 0})
		return cd

	def clean_document_photo(self):
		return self._image('document_photo')

	def clean_transfer_proof(self):
		return self._image('transfer_proof')
