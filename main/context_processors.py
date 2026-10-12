def role(request):
	"""Expose the user's navigation role ('admin', 'resepsionista', 'inspector', 'operator')."""
	user = request.user
	if not user.is_authenticated:
		return {'role': None}
	if user.is_superuser:
		return {'role': 'admin'}
	g = user.groups.first()
	return {'role': g.name if g else None}
