import io
from datetime import date, datetime, timedelta

import qrcode
import qrcode.image.svg
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from config.decorators import perm_required
from custom.models import Fare, QuotaGroup
from users.models import AuditLog

from .forms import TicketForm
from .models import Sailing, SailingQuota, Ticket


def _group(request):
	return request.user.groups.all()[0].name if request.user.groups.exists() else 'admin'


def _quota_rows(sailing):
	quotas = {q.quota_group: q for q in sailing.quotas.all()}
	return [(label, quotas.get(code)) for code, label in QuotaGroup.choices]


@login_required
@perm_required('ticketing.issue_ticket')
def SellSailings(request):
	now = timezone.now()
	sailings = (Sailing.objects.filter(departure__gte=now - timedelta(hours=2), departure__lte=now + timedelta(days=7))
		.exclude(status__in=[Sailing.Status.CANCELLED, Sailing.Status.COMPLETED])
		.select_related('vessel__operator', 'route__origin', 'route__destination').prefetch_related('quotas'))
	rows = [{'obj': s, 'quotas': _quota_rows(s)} for s in sailings]
	context = {'group': _group(request), 'rows': rows, 'title': 'Sosa Bilhete', 'legend': 'Sosa Bilhete — Hili Viajen'}
	return render(request, 'ticketing/sell_sailings.html', context)


@login_required
@perm_required('ticketing.issue_ticket')
def TicketSell(request, sailing_id):
	sailing = get_object_or_404(Sailing.objects.select_related('vessel__operator', 'route__origin', 'route__destination'), pk=sailing_id)
	if not sailing.sales_open:
		messages.warning(request, _("Faan bilhete ba viajen ne'e taka ona."))
		return redirect('sell-sailings')
	if request.method == 'POST':
		form = TicketForm(request.POST, request.FILES, sailing=sailing)
		if form.is_valid():
			try:
				with transaction.atomic():
					# Lock the quota row so two counters cannot oversell the last seats.
					q = SailingQuota.objects.select_for_update().get(sailing=sailing, quota_group=form.cleaned_data['item'].quota_group)
					if q.remaining < form.cleaned_data['quantity']:
						raise ValueError('quota')
					t = form.save(commit=False)
					t.sailing = sailing
					t.unit_price = form.fares[t.item_id]
					t.sold_by = request.user
					t.save()
					AuditLog.record('ticket_sold', user=request.user, request=request, detail=f'{t.serial} ${t.total}')
			except (ValueError, SailingQuota.DoesNotExist):
				form.add_error(None, _("Kuota la to'o. Tenta fali."))
			else:
				return redirect('ticket-print', t.pk)
	else:
		form = TicketForm(sailing=sailing)
	context = {
		'group': _group(request), 'form': form, 'sailing': sailing, 'quotas': _quota_rows(sailing),
		'title': 'Sosa Bilhete', 'legend': f'{sailing.route} · {sailing.vessel}',
	}
	return render(request, 'ticketing/sell_form.html', context)


def _qr_svg(payload):
	img = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
	buf = io.BytesIO()
	img.save(buf)
	return buf.getvalue().decode()


def _visible_tickets(request):
	qs = Ticket.objects.select_related('sailing__vessel', 'sailing__route__origin', 'sailing__route__destination', 'item', 'sold_by')
	if not request.user.has_perm('ticketing.view_reports'):
		qs = qs.filter(sold_by=request.user)  # a counter clerk only sees their own sales
	return qs


@login_required
@perm_required('ticketing.issue_ticket')
def TicketList(request):
	try:
		day = date.fromisoformat(request.GET.get('date', ''))
	except ValueError:
		day = timezone.localdate()
	start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
	objects = _visible_tickets(request).filter(created_at__gte=start, created_at__lt=start + timedelta(days=1))
	total = sum(t.total for t in objects if t.status in (Ticket.Status.ISSUED, Ticket.Status.BOARDED))
	context = {'group': _group(request), 'objects': objects, 'day': day, 'total': total,
		'title': 'Lista Bilhete', 'legend': 'Lista Bilhete'}
	return render(request, 'ticketing/list.html', context)


@login_required
@perm_required('ticketing.issue_ticket')
def TicketDetail(request, pk):
	t = get_object_or_404(_visible_tickets(request), pk=pk)
	context = {'group': _group(request), 'obj': t, 'qr': _qr_svg(t.qr_payload),
		'title': 'Bilhete', 'legend': f'Bilhete {t.serial}'}
	return render(request, 'ticketing/detail.html', context)


@login_required
@perm_required('ticketing.issue_ticket')
def TicketPrint(request, pk):
	t = get_object_or_404(_visible_tickets(request), pk=pk)
	AuditLog.record('ticket_print', user=request.user, request=request, detail=t.serial)
	return render(request, 'ticketing/print.html', {'obj': t, 'qr': _qr_svg(t.qr_payload)})


def _private_file(request, pk, field, action):
	t = get_object_or_404(Ticket, pk=pk)
	f = getattr(t, field)
	if not f:
		raise Http404
	AuditLog.record(action, user=request.user, request=request, detail=t.serial)
	return FileResponse(f.open('rb'), content_type='image/jpeg')


@login_required
@perm_required('ticketing.view_documents')
def TicketDocument(request, pk):
	return _private_file(request, pk, 'document_photo', 'document_view')


@login_required
@perm_required('ticketing.view_documents')
def TicketProof(request, pk):
	return _private_file(request, pk, 'transfer_proof', 'proof_view')
