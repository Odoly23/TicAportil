from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Div

from config.utils import shrink_image
from custom.models import Fare, FareItem, QuotaGroup, order_items
from .models import DocumentType, Ticket
from .services import bonus_violation

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
	custom_price = forms.DecimalField(label=_("Presu aluga (USD) — husik mamuk = tarif"), required=False, min_value=0,
		max_value=99999, max_digits=7, decimal_places=2)

	class Meta:
		model = Ticket
		fields = ['item', 'quantity', 'full_name', 'birth_date', 'sex', 'nationality', 'document_type',
			'document_number', 'document_photo', 'plate_number', 'contact_email', 'contact_whatsapp',
			'notes', 'payment_method', 'bonus_reference', 'transfer_reference', 'transfer_proof']
		labels = {
			'bonus_reference': _("Referénsia bonus (karta / ministériu / naran ofisiál)"),
			'item': _("Tipu bilhete"), 'quantity': _("Kuantidade"), 'full_name': _("Naran kompletu"),
			'sex': _("Sexu"), 'nationality': _("Nasionalidade"), 'document_type': _("Tipu dokumentu"),
			'document_number': _("Nú. dokumentu"), 'document_photo': _("Foto dokumentu"),
			'plate_number': _("Nú. plaka"), 'contact_email': _("Email"),
			'contact_whatsapp': _("WhatsApp"), 'notes': _("Observasaun"),
			'payment_method': _("Pagamentu"), 'transfer_reference': _("Nú. referénsia transferénsia"),
			'transfer_proof': _("Prova transferénsia"),
		}
		widgets = {'item': ItemSelect(), 'quantity': forms.NumberInput(attrs={'min': 1})}

	def __init__(self, *args, sailing=None, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.sailing, self.user = sailing, user
		can_charter = user is None or user.has_perm('ticketing.issue_charter')
		can_bonus = user is None or user.has_perm('ticketing.issue_complimentary')
		fares = {f.item_id: f.price for f in Fare.objects.filter(route=sailing.route, item__is_active=True).select_related('item')}
		items = order_items(FareItem.objects.filter(pk__in=fares.keys()))
		if not can_charter:  # charters and rented blocks are sold only by people the admin has trusted with them
			items = items.exclude(quota_group=QuotaGroup.CHARTER).exclude(is_block=True)
		self.fares = fares
		if not can_bonus:
			self.fields['payment_method'].choices = [c for c in Ticket.Payment.choices if c[0] != Ticket.Payment.COMPLIMENTARY]
		self.fields['item'].queryset = items
		self.fields['item'].label_from_instance = lambda i: f"{i.display_name()} — ${fares[i.pk]}"
		self.fields['item'].widget.option_data = {
			i.pk: {'data-group': i.quota_group, 'data-price': str(fares[i.pk]), 'data-plate': '1' if i.requires_plate else '0',
				'data-block': '1' if i.is_block else '0'}
			for i in items
		}
		self.fields['quantity'].initial = 1
		self.fields['quantity'].required = False  # hidden for passengers/charter; empty means 1
		self.fields['quantity'].validators += [MinValueValidator(1), MaxValueValidator(500)]
		self.fields['nationality'].initial = 'Timor-Leste'
		self.fields['document_photo'].widget.attrs.update({'accept': 'image/*', 'capture': 'environment'})
		self.fields['transfer_proof'].widget.attrs.update({'accept': 'image/*'})
		self.helper = FormHelper()
		self.helper.form_tag = False
		self.helper.layout = Layout(
			Row(Column('item', css_class='col-md-8'), Column('quantity', css_class='col-md-4')),
			Div(Row(Column('custom_price', css_class='col-md-6')), css_id='charter-fields'),
			Div(
				Row(Column('full_name', css_class='col-md-6'), Column('contact_whatsapp', css_class='col-md-3'),
					Column('contact_email', css_class='col-md-3')),
				css_id='named-fields'),
			Div(
				Row(Column('birth_date', css_class='col-md-4'), Column('sex', css_class='col-md-4'),
					Column('nationality', css_class='col-md-4')),
				Row(Column('document_type', css_class='col-md-4'), Column('document_number', css_class='col-md-4'),
					Column('document_photo', css_class='col-md-4')),
				css_id='passenger-fields'),
			Div('plate_number', css_id='plate-fields'),
			Row(Column('payment_method', css_class='col-md-4'),
				Div(Row(Column('transfer_reference', css_class='col-md-6'), Column('transfer_proof', css_class='col-md-6')),
					css_id='transfer-fields', css_class='col-md-8'),
				Div('bonus_reference', css_id='bonus-fields', css_class='col-md-8')),
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

	def _fits_age(self, item, age):
		return not ((item.age_min is not None and age < item.age_min) or (item.age_max is not None and age > item.age_max))

	def _foreign_category_exists(self, age):
		"""True when the admin has defined a foreigner-only passenger tariff on this route that fits this age."""
		return any(i.foreigner_only and i.quota_group == QuotaGroup.PASSENGER and i.pk in self.fares and self._fits_age(i, age)
			for i in FareItem.objects.filter(is_active=True, foreigner_only=True))

	def clean(self):
		cd = super().clean()
		s = self.sailing
		if not s.sales_open:
			raise forms.ValidationError(_("Faan bilhete ba viajen ne'e taka ona."))
		item = cd.get('item')
		if not item:
			return cd
		qty = cd['quantity'] = cd.get('quantity') or 1
		group = item.quota_group
		is_block = item.is_block
		is_pax = group == QuotaGroup.PASSENGER and not is_block      # a rented block of seats has no individual passenger data
		is_charter = group == QuotaGroup.CHARTER
		pay = cd.get('payment_method')
		valid = Ticket.objects.filter(sailing=s, status__in=[Ticket.Status.ISSUED, Ticket.Status.BOARDED])
		if is_charter:
			cd['quantity'] = qty = 1
			if valid.exists():
				raise forms.ValidationError(_("Viajen ne'e iha bilhete ona, la bele aluga hotu."))
			if not cd.get('full_name'):
				self.add_error('full_name', _("Naran ema/instituisaun ne'ebé aluga obrigatóriu."))
			if not (cd.get('contact_whatsapp') or cd.get('contact_email')):
				self.add_error('contact_whatsapp', _("Kontaktu (WhatsApp ka email) obrigatóriu."))
		elif s.is_chartered:
			raise forms.ValidationError(_("Viajen ne'e aluga ona (charter). La bele faan bilhete seluk."))
		if is_block:
			if not cd.get('full_name'):
				self.add_error('full_name', _("Naran ema/instituisaun ne'ebé aluga obrigatóriu."))
			if not (cd.get('contact_whatsapp') or cd.get('contact_email')):
				self.add_error('contact_whatsapp', _("Kontaktu (WhatsApp ka email) obrigatóriu."))
		if is_pax:
			cd['quantity'] = qty = 1
			for f in ('full_name', 'birth_date', 'sex', 'document_type', 'document_number'):
				if not cd.get(f):
					self.add_error(f, _("Obrigatóriu."))
			if not self.cleaned_data.get('document_photo'):
				self.add_error('document_photo', _("Foto dokumentu obrigatóriu."))
			birth, doc = cd.get('birth_date'), cd.get('document_type')
			age = None
			if birth:
				age = age_on(birth, s.departure.date())
				if age < 0:
					self.add_error('birth_date', _("Data moris la los."))
					age = None
				elif not self._fits_age(item, age):
					self.add_error('item', _("Idade pasajeiru (%(a)d) la tuir kategoria ne'e.") % {'a': age})
			if doc:
				foreign = doc == DocumentType.PASSPORT
				if item.foreigner_only and not foreign:
					self.add_error('item', _("Kategoria ne'e ba estranjeiru ho pasaporte de'it."))
				elif foreign and not item.foreigner_only and age is not None and self._foreign_category_exists(age):
					# only forced when the admin really defined a separate foreigner tariff; otherwise foreigners use the normal ones
					self.add_error('item', _("Pasaporte uza kategoria estranjeiru."))
		elif item.requires_plate and not is_block and not cd.get('plate_number'):
			self.add_error('plate_number', _("Nú. plaka obrigatóriu."))
		if pay == Ticket.Payment.COMPLIMENTARY:
			if not is_pax:
				self.add_error('payment_method', _("Bonus ba pasajeiru de'it."))
			if len((cd.get('bonus_reference') or '').strip()) < 5:
				self.add_error('bonus_reference', _("Referénsia bonus obrigatóriu (minimu karakter 5)."))
			elif is_pax:
				hit = bonus_violation(s, cd.get('document_type'), cd.get('document_number'))
				if hit and hit[0] == 'sailing':
					self.add_error('payment_method', _("Batas bonus ba viajen ne'e to'o ona (%(n)d).") % {'n': hit[1]})
				elif hit:
					self.add_error('payment_method', _("Ema ne'e uza ona bonus %(n)d iha fulan ne'e (batas).") % {'n': hit[1]})
		if pay == Ticket.Payment.TRANSFER:
			if not cd.get('transfer_reference'):
				self.add_error('transfer_reference', _("Obrigatóriu."))
			if not self.cleaned_data.get('transfer_proof'):
				self.add_error('transfer_proof', _("Prova transferénsia obrigatóriu."))
		q = s.quotas.filter(quota_group=group).first()
		if not q or q.remaining < qty:
			raise forms.ValidationError(_("Kuota la to'o. Sobra: %(n)d.") % {'n': q.remaining if q else 0})
		return cd

	def clean_document_photo(self):
		return self._image('document_photo')

	def clean_transfer_proof(self):
		return self._image('transfer_proof')
