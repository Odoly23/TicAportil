import hashlib
import os
import secrets
from datetime import datetime


def getlastid(table_name):
	result = table_name.objects.last()
	if result:
		lastid = result.id
		newid = lastid + 1
	else:
		lastid = 0
		newid = 1
	return lastid, newid


def getnewid(table_name):
	result = table_name.objects.last()
	newid = result.id + 1 if result else 1
	hashid = hashlib.sha256(str(newid).encode())
	return newid, hashid.hexdigest()


def getjustnewid(table_name):
	result = table_name.objects.last()
	return result.id + 1 if result else 1


def hash_sha256(strhash):
	return hashlib.sha256(strhash.encode()).hexdigest()


def split_string(string):
	return string.split()[0].lower()


MONTHS = ["Janeiru", "Fevreiru", "Marsu", "Abril", "Maiu", "Junhu",
	"Julhu", "Agustu", "Setembru", "Outubru", "Novembru", "Dezembru"]


def getMonthName(num):
	return MONTHS[num - 1]


def _private_name(folder, filename):
	ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
	return os.path.join(folder, '{:%Y/%m}'.format(datetime.now()), '{}.{}'.format(secrets.token_hex(16), ext))


def document_photo(instance, filename):
	"""Passenger ID document photo (retained 30 days, admin-only)."""
	return _private_name('documents', filename)


def transfer_proof(instance, filename):
	"""Bank transfer proof image."""
	return _private_name('proofs', filename)
