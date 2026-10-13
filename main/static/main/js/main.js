// Mobile sidebar: slides in under the navbar and pushes the page content.
(function () {
	var btn = document.getElementById('btnHam');
	var sb = document.getElementById('sidebar');
	if (!btn || !sb) return;
	function set(open) {
		sb.classList.toggle('active', open);
		document.body.classList.toggle('sb-open', open);
		btn.setAttribute('aria-expanded', open ? 'true' : 'false');
	}
	btn.addEventListener('click', function () { set(!sb.classList.contains('active')); });
	window.addEventListener('resize', function () { if (window.innerWidth >= 992) set(false); });
})();
