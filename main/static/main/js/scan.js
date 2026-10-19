/* APORTIL boarding scanner (PWA). Online: every scan is validated by the server.
   Offline: validated against a downloaded list of the sailing's signed QR payloads, queued in IndexedDB and
   replayed to the server when the connection returns (the server stays the source of truth). */
(function () {
	'use strict';
	var I = JSON.parse(document.getElementById('i18n-data').textContent);
	var SAILINGS = JSON.parse(document.getElementById('sailings-data').textContent);
	var BASE = '/ticketing/scan/';
	var el = function (id) { return document.getElementById(id); };
	var sel = el('sailing'), box = el('result'), chip = el('chip');
	var manifests = {};            // sailingId -> {label, generated_at, byPayload, bySerial, total}
	var localBoarded = {};         // sailingId -> {serial: true}   (boarded offline, not yet synced)
	var forcedOffline = false, syncing = false, scanner = null, last = {token: '', at: 0}, lastStats = {};

	// ---------------------------------------------------------------- IndexedDB (tiny promise wrapper)
	var dbp = new Promise(function (res, rej) {
		var r = indexedDB.open('aportil-scan', 1);
		r.onupgradeneeded = function () {
			r.result.createObjectStore('manifest', {keyPath: 'sailing'});
			r.result.createObjectStore('queue', {keyPath: 'id', autoIncrement: true});
		};
		r.onsuccess = function () { res(r.result); };
		r.onerror = function () { rej(r.error); };
	});
	function store(name, mode, fn) {
		return dbp.then(function (db) {
			return new Promise(function (res, rej) {
				var t = db.transaction(name, mode), req = fn(t.objectStore(name));
				t.oncomplete = function () { res(req && req.result); };
				t.onerror = function () { rej(t.error); };
			});
		});
	}
	var dbAll = function (n) { return store(n, 'readonly', function (s) { return s.getAll(); }); };
	var dbPut = function (n, v) { return store(n, 'readwrite', function (s) { return s.put(v); }); };
	var dbDel = function (n, k) { return store(n, 'readwrite', function (s) { return s.delete(k); }); };
	var dbClear = function (n) { return store(n, 'readwrite', function (s) { return s.clear(); }); };

	// ---------------------------------------------------------------------------------------- helpers
	function fmt(s) { var a = [].slice.call(arguments, 1), i = 0; return s.replace(/%s/g, function () { return a[i++]; }); }
	function cookie(name) { var m = document.cookie.match('(?:^|; )' + name + '=([^;]*)'); return m ? decodeURIComponent(m[1]) : ''; }
	function isOnline() { return navigator.onLine && !forcedOffline; }
	function esc(t) { var d = document.createElement('div'); d.textContent = t == null ? '' : t; return d.innerHTML; }

	function call(path, body) {
		var opts = {method: body ? 'POST' : 'GET', credentials: 'same-origin', headers: {'Accept': 'application/json'}};
		if (body) { opts.headers['Content-Type'] = 'application/json'; opts.headers['X-CSRFToken'] = cookie('csrftoken'); opts.body = JSON.stringify(body); }
		return fetch(BASE + 'api/' + path, opts).then(function (r) {
			if (r.status === 401 || r.status === 403) { var e = new Error('auth'); e.auth = true; throw e; }
			if (!r.ok) { var e2 = new Error('http ' + r.status); e2.http = r.status; throw e2; }
			return r.json();
		});
	}

	function beep(good) {
		try {
			if (navigator.vibrate) navigator.vibrate(good ? 80 : [120, 60, 120]);
			var C = window.AudioContext || window.webkitAudioContext; if (!C) return;
			var c = new C(), o = c.createOscillator(), g = c.createGain();
			o.frequency.value = good ? 880 : 220; o.connect(g); g.connect(c.destination); g.gain.value = 0.15;
			o.start(); setTimeout(function () { o.stop(); c.close(); }, good ? 120 : 350);
		} catch (e) { /* feedback is optional */ }
	}

	// ------------------------------------------------------------------------------------------- UI
	function setChip() {
		var on = isOnline();
		chip.textContent = on ? I.online : I.offline;
		chip.className = 'badge ' + (on ? 'badge-success' : 'badge-warning');
	}
	function showStats(sid) {
		var s = lastStats[sid];
		if (!isOnline() || !s) {
			var m = manifests[sid];
			if (m) { var b = Object.keys(localBoarded[sid] || {}).length, base = 0; m.tickets.forEach(function (t) { if (t.b) base++; });
				s = {boarded: base + b, total: m.total}; }
		}
		el('stats').textContent = s ? s.boarded + ' / ' + s.total : '—';
	}
	function showPending() {
		return dbAll('queue').then(function (q) {
			el('pending').textContent = q.length ? fmt(I.pending, q.length) : '';
			return q.length;
		});
	}
	function show(r) {
		var cls = {ok: 'success', duplicate: 'danger', wrong_sailing: 'warning', cancelled: 'danger', sailing_cancelled: 'danger',
			invalid: 'danger', not_found: 'danger', unknown: 'warning', error: 'danger'}[r.result] || 'danger';
		var html = '<div class="result-title">' + esc(I[r.result] || r.result) + '</div>';
		if (r.name) html += '<div class="result-name">' + esc(r.name) + '</div>';
		if (r.item) html += '<div>' + esc(r.item) + (r.qty > 1 ? ' ×' + r.qty : '') + '</div>';
		if (r.serial) html += '<div class="small">' + esc(r.serial) + '</div>';
		if (r.result === 'duplicate' && r.boarded_at) html += '<div>' + esc(I.boarded_at + ' ' + r.boarded_at + (r.boarded_by ? ' ' + I.by + ' ' + r.boarded_by : '')) + '</div>';
		if (r.result === 'wrong_sailing' && r.route) html += '<div>' + esc(I.goes_to + ': ' + r.route + ' ' + (r.departure || '')) + '</div>';
		box.className = 'result-box mt-3 bg-' + cls; box.innerHTML = html; box.hidden = false;
		beep(r.result === 'ok');
		if (r.stats) { lastStats[sel.value] = r.stats; }
		showStats(sel.value);
	}

	// ---------------------------------------------------------------------------------- manifests
	function indexManifest(m) {
		var byP = {}, byS = {};
		m.tickets.forEach(function (t) { byP[t.p] = t; byS[t.s] = t; });
		m.byPayload = byP; m.bySerial = byS; m.total = m.tickets.length;
		manifests[m.sailing] = m;
	}
	function fillSelect() {
		var seen = {}, opts = [];
		SAILINGS.forEach(function (s) { seen[s.id] = 1; opts.push([s.id, s.label]); });
		Object.keys(manifests).forEach(function (id) { if (!seen[id]) opts.push([+id, manifests[id].label]); });
		var cur = sel.value;
		sel.innerHTML = '<option value="">—</option>' + opts.map(function (o) {
			return '<option value="' + o[0] + '">' + esc(o[1] + (manifests[o[0]] ? ' ✓' : '')) + '</option>'; }).join('');
		if (cur) sel.value = cur; else if (opts.length === 1) sel.value = opts[0][0];
	}
	function downloadManifest() {
		if (!sel.value) { alert(I.choose); return; }
		call('manifest/' + sel.value + '/').then(function (m) {
			return dbPut('manifest', m).then(function () {
				indexManifest(m); fillSelect(); showStats(sel.value);
				el('syncLog').textContent = fmt(I.downloaded, m.total);
			});
		}).catch(function (e) { el('syncLog').textContent = e.auth ? I.relogin : I.download_fail; });
	}

	// -------------------------------------------------------------------------------------- scanning
	function offlineScan(token) {
		var sid = sel.value, m = manifests[sid], local = 'unknown', info = {}, t = null;
		if (m) {
			t = token.indexOf('.') >= 0 ? m.byPayload[token] : m.bySerial[token.trim().toUpperCase()];
			if (t) {
				info = {serial: t.s, name: t.n, item: t.i, qty: t.q};
				var lb = localBoarded[sid] = localBoarded[sid] || {};
				if (t.b || lb[t.s]) local = 'duplicate'; else { local = 'ok'; lb[t.s] = true; }
			}
		}
		return dbPut('queue', {token: token, sailing: +sid, scanned_at: new Date().toISOString(), local: local}).then(function () {
			info.result = local; show(info); showPending();
		});
	}
	function handleToken(token) {
		token = (token || '').trim();
		if (!token) return;
		if (!sel.value) { alert(I.choose); return; }
		var now = Date.now();
		if (token === last.token && now - last.at < 3000) return;   // camera sees the same QR many times per second
		last = {token: token, at: now};
		if (!isOnline()) { offlineScan(token); return; }
		call('validate/', {sailing: +sel.value, token: token}).then(function (r) { show(r); sync(); }).catch(function (e) {
			if (e.auth) { show({result: 'error'}); el('syncLog').textContent = I.relogin; return; }
			forcedOffline = true; setChip();           // network trouble: keep the gate moving using the offline list
			offlineScan(token);
		});
	}

	// ------------------------------------------------------------------------------------------ sync
	function sync() {
		if (syncing || !navigator.onLine) return Promise.resolve();
		return dbAll('queue').then(function (q) {
			if (!q.length) { forcedOffline = false; setChip(); return; }
			syncing = true; el('syncLog').textContent = I.syncing;
			var items = q.slice(0, 200);
			return call('sync/', {items: items.map(function (i) { return {token: i.token, sailing: i.sailing, scanned_at: i.scanned_at}; })})
				.then(function (res) {
					var bad = [];
					return Promise.all(items.map(function (it, idx) {
						var r = res.results[idx] || {};
						if (r.result !== 'ok' && (it.local === 'ok' || it.local === 'unknown')) bad.push(r);
						if (r.stats) lastStats[it.sailing] = r.stats;
						return dbDel('queue', it.id);
					})).then(function () {
						forcedOffline = false; setChip(); box.hidden = true;   // stale "saved for sync" banner; the list below is the truth
						var html = fmt(I.synced, items.length);
						if (bad.length) html += ' <strong>' + esc(I.conflicts) + '</strong><ul class="mb-0">' + bad.map(function (r) {
							return '<li>' + esc((r.serial || '?') + ' ' + (r.name || '') + ' — ' + (I[r.result] || r.result)) + '</li>'; }).join('') + '</ul>';
						el('syncLog').innerHTML = html;
						showStats(sel.value);
					});
				})
				.catch(function (e) { el('syncLog').textContent = e.auth ? I.relogin : I.no_net; })
				.then(function () { syncing = false; return showPending(); })
				.then(function (n) { if (n) return sync(); });
		});
	}

	// ---------------------------------------------------------------------------------------- camera
	function toggleCamera() {
		var label = el('camLabel');
		if (scanner) { scanner.stop().catch(function () {}).then(function () { scanner.clear(); scanner = null; label.textContent = I.cam_start; }); return; }
		scanner = new Html5Qrcode('reader');
		scanner.start({facingMode: 'environment'}, {fps: 10, qrbox: function (w, h) { var s = Math.floor(Math.min(w, h) * 0.7); return {width: s, height: s}; }},
			function (text) { handleToken(text); }, function () {})
			.then(function () { label.textContent = I.cam_stop; })
			.catch(function () { scanner = null; el('syncLog').textContent = I.cam_error; });
	}

	// ------------------------------------------------------------------------------------------ init
	function clearData() {
		showPending().then(function (n) {
			if (n) { alert(I.clear_blocked); return; }
			if (!confirm(I.clear_confirm)) return;
			Promise.all([dbClear('manifest'), dbClear('queue')]).then(function () {
				manifests = {}; localBoarded = {}; fillSelect(); showStats(sel.value); el('syncLog').textContent = I.cleared;
			});
		});
	}
	el('btnCamera').addEventListener('click', toggleCamera);
	el('btnDownload').addEventListener('click', downloadManifest);
	el('btnSync').addEventListener('click', sync);
	el('btnClear').addEventListener('click', clearData);
	el('manualForm').addEventListener('submit', function (e) { e.preventDefault(); handleToken(el('manualInput').value); el('manualInput').value = ''; });
	sel.addEventListener('change', function () { showStats(sel.value); });
	window.addEventListener('online', function () { setChip(); sync(); });
	window.addEventListener('offline', setChip);
	window.__scan = {handleToken: handleToken, sync: sync};   // used by the end-to-end test

	Promise.all([dbAll('manifest'), dbAll('queue')]).then(function (r) {
		var DAY = 24 * 3600 * 1000, queued = {};
		r[1].forEach(function (q) { queued[q.sailing] = true; if (q.local === 'ok') { var lb = localBoarded[q.sailing] = localBoarded[q.sailing] || {};
			var m = r[0].filter(function (x) { return x.sailing === q.sailing; })[0]; if (m) { var t = m.tickets.filter(function (x) { return q.token.indexOf(x.s + '.') === 0 || q.token.toUpperCase() === x.s; })[0]; if (t) lb[t.s] = true; } } });
		return Promise.all(r[0].map(function (m) {
			if (Date.now() - Date.parse(m.generated_at) > DAY && !queued[m.sailing]) return dbDel('manifest', m.sailing);  // personal data: drop stale lists
			indexManifest(m);
		}));
	}).catch(function () {}).then(function () {
		fillSelect(); setChip(); showPending(); showStats(sel.value);
		if (navigator.onLine) sync();
		if ('serviceWorker' in navigator) navigator.serviceWorker.register(BASE + 'sw.js', {scope: BASE}).catch(function () {});
	});
})();
