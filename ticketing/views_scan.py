import json
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.templatetags.static import static
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from config.decorators import perm_required
from users.models import AuditLog

from . import scanning
from .models import Sailing, Ticket

SCAN = 'ticketing.scan_ticket'
MAX_SYNC = 500
STATIC_SHELL = [
	'main/css/bootstrap.min.css', 'main/css/main.css', 'main/font-awesome/css/font-awesome.min.css',
	'main/font-awesome/fonts/fontawesome-webfont.woff2', 'main/js/jquery.min.js', 'main/js/bootstrap.bundle.min.js',
	'main/css/dataTables.bootstrap4.min.css', 'main/js/jquery.dataTables.min.js', 'main/js/dataTables.bootstrap4.min.js',
	'main/js/main.js', 'main/js/html5-qrcode.min.js', 'main/js/scan.js', 'main/images/logo.png',
	'main/images/icon-192.png', 'main/images/favicon.png',
]


def api(view):
	"""JSON API guard: 401/403 as JSON (a redirect to the login page would break offline sync)."""
	@wraps(view)
	def wrapper(request, *args, **kwargs):
		if not request.user.is_authenticated:
			return JsonResponse({'error': 'auth'}, status=401)
		if not request.user.has_perm(SCAN):
			return JsonResponse({'error': 'forbidden'}, status=403)
		return view(request, *args, **kwargs)
	return wrapper


def boarding_sailings(now=None):
	"""Sailings an inspector can board: from 6h after departure back to 18h before it."""
	now = now or timezone.now()
	return (Sailing.objects.filter(departure__gte=now - timedelta(hours=6), departure__lte=now + timedelta(hours=18))
		.exclude(status__in=[Sailing.Status.CANCELLED, Sailing.Status.COMPLETED])
		.select_related('vessel', 'route__origin', 'route__destination').order_by('departure'))


@login_required
@perm_required(SCAN)
def ScanPage(request):
	sailings = [{'id': s.pk, 'label': f"{timezone.localtime(s.departure):%d/%m %H:%M} · {s.route} · {s.vessel}"}
		for s in boarding_sailings()]
	context = {'title': 'Scan QR', 'legend': 'Scan QR', 'sailings_json': sailings, 'i18n': js_strings()}
	return render(request, 'ticketing/scan.html', context)


def js_strings():
	"""Texts used by scan.js (the scanner must also work with no network, so they ship with the page)."""
	return {
		'ok': _("Bele tama ro"), 'duplicate': _("Tama ona ro ona!"), 'wrong_sailing': _("Viajen la los"),
		'cancelled': _("Bilhete kansela / fila osan ona"), 'sailing_cancelled': _("Viajen kansela"),
		'invalid': _("QR la válidu — bilhete falsu?"), 'not_found': _("Bilhete la hetan"),
		'unknown': _("La bele verifika (offline) — rai ba sinkronizasaun"), 'error': _("Sala"),
		'online': _("Online"), 'offline': _("Offline"), 'choose': _("Hili viajen uluk."),
		'downloaded': _("Lista download ona: %s bilhete."), 'download_fail': _("La konsege download lista."),
		'pending': _("Hein sinkroniza: %s"), 'syncing': _("Sinkroniza..."), 'synced': _("Sinkroniza ona: %s."),
		'conflicts': _("Tenke haree:"), 'relogin': _("Sesaun remata. Login fali hodi sinkroniza (dadus seguru iha telemovel)."),
		'no_net': _("La iha internet. Scan rai iha telemovel."), 'cam_start': _("Hahú kámera"), 'cam_stop': _("Para kámera"),
		'cam_error': _("Kámera la bele loke. Uza input manual."), 'clear_confirm': _("Hamoos dadus offline husi telemovel ne'e?"),
		'clear_blocked': _("Sinkroniza uluk — iha scan seidauk haruka."), 'cleared': _("Dadus offline hamoos ona."),
		'boarded_at': _("Tama iha"), 'by': _("husi"), 'goes_to': _("Bilhete ne'e ba")
	}


def _json(request):
	try:
		return json.loads(request.body or b'{}')
	except ValueError:
		return None


def _sailing_or_none(pk):
	try:
		return Sailing.objects.select_related('route', 'vessel').get(pk=int(pk))
	except (Sailing.DoesNotExist, TypeError, ValueError):
		return None


@api
@require_POST
def ApiValidate(request):
	data = _json(request)
	sailing = _sailing_or_none((data or {}).get('sailing'))
	if not data or not sailing or not isinstance(data.get('token'), str):
		return JsonResponse({'error': 'bad_request'}, status=400)
	return JsonResponse(scanning.process_scan(request.user, sailing, data['token']))


@api
@require_GET
def ApiManifest(request, sailing_id):
	s = get_object_or_404(boarding_sailings().filter(pk=sailing_id))
	tickets = Ticket.objects.filter(sailing=s, status__in=[Ticket.Status.ISSUED, Ticket.Status.BOARDED]).select_related('item')
	AuditLog.record('scan_manifest', user=request.user, request=request, detail=f'sailing={s.pk} n={len(tickets)}')
	return JsonResponse({
		'sailing': s.pk, 'label': f"{timezone.localtime(s.departure):%d/%m %H:%M} · {s.route} · {s.vessel}",
		'generated_at': timezone.now().isoformat(),
		# p = full signed QR payload, so an offline phone can verify authenticity by exact match (no secret key on the phone)
		'tickets': [{'p': t.qr_payload, 's': t.serial, 'n': t.full_name, 'i': t.item.display_name(), 'q': t.quantity,
			'b': t.status == Ticket.Status.BOARDED} for t in tickets],
	})


@api
@require_POST
def ApiSync(request):
	data = _json(request)
	items = (data or {}).get('items')
	if not isinstance(items, list) or len(items) > MAX_SYNC:
		return JsonResponse({'error': 'bad_request'}, status=400)
	parsed = []
	for i, it in enumerate(items):
		sailing = _sailing_or_none(it.get('sailing')) if isinstance(it, dict) else None
		token = it.get('token') if isinstance(it, dict) else None
		if not sailing or not isinstance(token, str):
			parsed.append((i, None, None, None))
			continue
		when = parse_datetime(it.get('scanned_at') or '') if isinstance(it.get('scanned_at'), str) else None
		if when is not None and timezone.is_naive(when):
			when = timezone.make_aware(when)
		parsed.append((i, sailing, token, when))
	results = [None] * len(items)
	# Oldest scan first, so when two phones scanned the same ticket offline the earlier one wins.
	for i, sailing, token, when in sorted(parsed, key=lambda p: (p[3] or timezone.now(), p[0])):
		results[i] = ({'result': 'error'} if sailing is None
			else scanning.process_scan(request.user, sailing, token, scanned_at=when, offline=True))
		results[i]['index'] = i
	AuditLog.record('scan_sync', user=request.user, request=request, detail=f'n={len(items)}')
	return JsonResponse({'results': results})


def WebManifest(request):
	icon = lambda n: {'src': static(f'main/images/icon-{n}.png'), 'sizes': f'{n}x{n}', 'type': 'image/png', 'purpose': 'any maskable'}
	resp = JsonResponse({
		'name': 'APORTIL Scan', 'short_name': 'Scan', 'start_url': '/ticketing/scan/', 'scope': '/ticketing/scan/',
		'display': 'standalone', 'background_color': '#112c66', 'theme_color': '#112c66',
		'icons': [icon(192), icon(512)],
	})
	resp['Content-Type'] = 'application/manifest+json'
	return resp


def ServiceWorker(request):
	shell = [static(p) for p in STATIC_SHELL]
	resp = render(request, 'ticketing/sw.js', {'shell': json.dumps(shell), 'version': settings.APP_VERSION},
		content_type='application/javascript')
	resp['Cache-Control'] = 'no-cache'
	return resp
