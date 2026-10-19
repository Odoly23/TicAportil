from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
	path("login/", views.StaffLoginView.as_view(), name="login"),
	path("logout/", views.StaffLogoutView.as_view(), name="logout"),
	path("account/", views.Account, name="account"),
	path("account/password/", views.PasswordChange.as_view(), name="password_change"),
	path("password-reset/", views.PasswordReset.as_view(), name="password_reset"),
	path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="auth/password_reset_done.html"), name="password_reset_done"),
	path("password-reset/confirm/<uidb64>/<token>/", views.PasswordResetConfirm.as_view(), name="password_reset_confirm"),
	path("password-reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="auth/password_reset_complete.html"), name="password_reset_complete"),
	path("users/", views.UserList, name="user-list"),
	path("users/add/", views.UserAdd, name="user-add"),
	path("users/<int:pk>/edit/", views.UserEdit, name="user-edit"),
	path("users/<int:pk>/password/", views.UserPassword, name="user-password"),
	path("users/<int:pk>/send-link/", views.UserSendLink, name="user-send-link"),
	path("audit/", views.AuditList, name="audit-list"),
]
