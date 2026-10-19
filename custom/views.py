import re
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _, gettext_lazy as _l

from config.decorators import perm_required
from users.models import AuditLog

from .forms import FareItemForm, OperatorForm, PortForm, RouteForm, VesselForm
from .models import Fare, FareItem, Operator, Port, QuotaGroup, Route, Vessel, order_items


def _group(request):
	return request.user.groups.all()[0].name if request.user.groups.exists() else 'admin'


class Crud:
	"""List / add / edit / delete views for one master-data model. Everything needs the model's `change` permission."""

	def __init__(self, key, model, form, title, columns, queryset=None):
		self.key, self.model, self.form, self.title, self.columns = key, model, form, title, columns
		self.qs = queryset or (lambda: model.objects.all())
		app = model._meta.app_label
		name = model._meta.model_name
		self.perm = f'{app}.change_{name}'
		self.add_perm, self.del_perm = f'{app}.add_{name}', f'{app}.delete_{name}'

	def _ctx(self, request, **kw):
		return {'group': _group(request), 'title': self.title, 'key': self.key, **kw}

	def list(self, request):
		rows = [{'obj': o, 'cells': [c(o) for _h, c in self.columns]} for o in self.qs()]
		ctx = self._ctx(request, legend=self.title, headers=[h for h, _c in self.columns], rows=rows,
			warnings=age_coverage_warnings() if self.key == 'fareitem' else [],
			can_add=request.user.has_perm(self.add_perm), can_delete=request.user.has_perm(self.del_perm))
		return render(request, 'custom/list.html', ctx)

	def add(self, request):
		if not request.user.has_perm(self.add_perm):
			return render(request, 'home/403.html', status=403)
		form = self.form(request.POST or None)
		if request.method == 'POST' and form.is_valid():
			obj = form.save()
			AuditLog.record(f'{self.key}_added', user=request.user, request=request, detail=str(obj))
			messages.success(request, _("Rai ona."))
			return redirect(f'{self.key}-list')
		return render(request, 'custom/form.html', self._ctx(request, form=form, legend=f'{self.title} — {_("Aumenta")}'))

	def edit(self, request, pk):
		obj = get_object_or_404(self.model, pk=pk)
		form = self.form(request.POST or None, instance=obj)
		if request.method == 'POST' and form.is_valid():
			form.save()
			AuditLog.record(f'{self.key}_changed', user=request.user, request=request, detail=f'{obj} {sorted(form.changed_data)}')
			messages.success(request, _("Atualiza ona."))
			return redirect(f'{self.key}-list')
		return render(request, 'custom/form.html', self._ctx(request, form=form, legend=f'{self.title} — {obj}'))

	def delete(self, request, pk):
		if not request.user.has_perm(self.del_perm):
			return render(request, 'home/403.html', status=403)
		obj = get_object_or_404(self.model, pk=pk)
		if request.method == 'POST':
			label = str(obj)
			try:
				obj.delete()
			except ProtectedError:
				messages.error(request, _("La bele hamoos %(o)s: iha dadus ne'ebé uza ona. Hasai ativu de'it.") % {'o': label})
			else:
				AuditLog.record(f'{self.key}_deleted', user=request.user, request=request, detail=label)
				messages.success(request, _("Hamoos ona."))
		return redirect(f'{self.key}-list')

	def urls(self):
		from django.urls import path
		wrap = lambda v: login_required(perm_required(self.perm)(v))
		k, p = self.key, self.key + 's'
		return [path(f'{p}/', wrap(self.list), name=f'{k}-list'), path(f'{p}/add/', wrap(self.add), name=f'{k}-add'),
			path(f'{p}/<int:pk>/edit/', wrap(self.edit), name=f'{k}-edit'), path(f'{p}/<int:pk>/delete/', wrap(self.delete), name=f'{k}-delete')]


yes = lambda b: '✓' if b else '—'
CRUDS = [
	Crud('port', Port, PortForm, 'Porta', [(_l("Kódigu"), lambda o: o.code), (_l("Naran"), lambda o: o.name)]),
	Crud('route', Route, RouteForm, 'Rota', [(_l("Rota"), str), (_l("Ativu"), lambda o: yes(o.is_active))]),
	Crud('operator', Operator, OperatorForm, 'Operadór', [(_l("Naran"), lambda o: o.name), (_l("Email"), lambda o: o.email or '—'),
		(_l("Telefone"), lambda o: o.phone or '—'), (_l("Ativu"), lambda o: yes(o.is_active))]),
	Crud('vessel', Vessel, VesselForm, 'Ró', [(_l("Naran"), lambda o: o.name), (_l("Operadór"), lambda o: o.operator.name),
		(_l("Ativu"), lambda o: yes(o.is_active))], queryset=lambda: Vessel.objects.select_related('operator')),
	Crud('fareitem', FareItem, FareItemForm, 'Kategoria', [(_l("Naran"), lambda o: o.name_tet), (_l("Kuota"), lambda o: o.get_quota_group_display()),
		(_l("Idade"), lambda o: f"{o.age_min if o.age_min is not None else ''}–{o.age_max if o.age_max is not None else ''}" if (o.age_min is not None or o.age_max is not None) else '—'),
		(_l("Estranjeiru"), lambda o: yes(o.foreigner_only)), (_l("Plaka"), lambda o: yes(o.requires_plate)), (_l("Ativu"), lambda o: yes(o.is_active))],
		queryset=lambda: order_items(FareItem.objects.all())),
]


def _runs(counts, bad):
	"""'0-4, 7' style ranges of ages whose category count satisfies `bad`."""
	out, start = [], None
	for age, c in enumerate(counts + [None]):  # sentinel closes a run that reaches the last age
		hit = c is not None and bad(c)
		if hit and start is None:
			start = age
		elif not hit and start is not None:
			out.append(str(start) if start == age - 1 else f'{start}–{age - 1}')
			start = None
	return out


def age_coverage_warnings():
	"""Gaps and overlaps in the ages (0-110) of the active, non-foreigner passenger categories."""
	items = list(FareItem.objects.filter(is_active=True, quota_group=QuotaGroup.PASSENGER, foreigner_only=False))
	if not items:
		return []
	counts = [sum(1 for i in items if (i.age_min is None or a >= i.age_min) and (i.age_max is None or a <= i.age_max)) for a in range(111)]
	out = []
	gaps, overlaps = _runs(counts, lambda c: c == 0), _runs(counts, lambda c: c > 1)
	if gaps:
		out.append(_("Idade ne'ebé la iha kategoria") + ': ' + ', '.join(gaps))
	if overlaps:
		out.append(_("Idade ne'ebé iha kategoria liu ida") + ': ' + ', '.join(overlaps))
	return out


# ------------------------------------------------------------------------------------- fare matrix
def _cell(item, route):
	return f'p_{item.pk}_{route.pk}'


@login_required
@perm_required('custom.change_fare')
def FareMatrix(request):
	items = list(order_items(FareItem.objects.filter(is_active=True)))
	routes = list(Route.objects.filter(is_active=True).select_related('origin', 'destination'))
	current = {(f.item_id, f.route_id): f.price for f in Fare.objects.filter(item__in=items, route__in=routes)}
	values, errors = {}, {}
	if request.method == 'POST':
		changes = []
		for it in items:
			for r in routes:
				raw = (request.POST.get(_cell(it, r)) or '').strip().replace(',', '.')
				values[_cell(it, r)] = raw
				old = current.get((it.pk, r.pk))
				if raw == '':
					new = None
				else:
					# plain money only: up to 4 digits, optional 1-2 decimals (no signs, exponents or spaces)
					if not re.fullmatch(r'\d{1,4}(\.\d{1,2})?', raw):
						errors[_cell(it, r)] = True
						continue
					new = Decimal(raw)
				if (old is None) != (new is None) or (old is not None and new is not None and old != new):
					changes.append((it, r, old, new))
		if errors:
			messages.error(request, _("Presu la válidu. La rai ruma."))
		else:
			with transaction.atomic():
				for it, r, old, new in changes:
					if new is None:
						Fare.objects.filter(item=it, route=r).delete()
					else:
						Fare.objects.update_or_create(item=it, route=r, defaults={'price': new})
					AuditLog.record('fare_changed', user=request.user, request=request, detail=f'{it} / {r}: {old} -> {new}')
			messages.success(request, _("Presu atualiza ona (%(n)d). Bilhete ne'ebé faan ona la muda.") % {'n': len(changes)})
			return redirect('fare-matrix')
	rows = []
	for it in items:
		cells = []
		for r in routes:
			name = _cell(it, r)
			val = values[name] if name in values else ('' if current.get((it.pk, r.pk)) is None else f'{current[(it.pk, r.pk)]:.2f}')
			cells.append({'name': name, 'value': val, 'error': name in errors})
		rows.append({'item': it, 'cells': cells})
	context = {'group': _group(request), 'routes': routes, 'rows': rows, 'title': 'Presu', 'legend': 'Presu Bilhete'}
	return render(request, 'custom/fare_matrix.html', context)
