from django.urls import include, path

from . import views

# django.contrib.auth.urls supplies login, logout, password_change(+_done),
# password_reset(+_done), password_reset_confirm and password_reset_complete.
urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("", include("django.contrib.auth.urls")),
]
