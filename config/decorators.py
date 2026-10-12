from functools import wraps

from django.shortcuts import redirect, render


def unauthenticated_user(view_func):
	@wraps(view_func)
	def wrapper_func(request, *args, **kwargs):
		if request.user.is_authenticated:
			return redirect('home')
		return view_func(request, *args, **kwargs)
	return wrapper_func


def allowed_users(allowed_roles=[]):
	"""Allow users who belong to ANY of the given groups (superusers always pass)."""
	def decorator(view_func):
		@wraps(view_func)
		def wrapper_func(request, *args, **kwargs):
			user = request.user
			if user.is_superuser or user.groups.filter(name__in=allowed_roles).exists():
				return view_func(request, *args, **kwargs)
			return render(request, 'home/403.html', status=403)
		return wrapper_func
	return decorator
