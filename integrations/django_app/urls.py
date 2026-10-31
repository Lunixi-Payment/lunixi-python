from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponse
from django.urls import path

from .shop import views

urlpatterns = [
    path("accounts/login/", LoginView.as_view(template_name="registration/login.html")),
    path("accounts/logout/", LogoutView.as_view()),
    path("checkout/<str:key>", views.checkout),
    path("status/<str:key>", views.status),
    path("return/<str:key>", views.returned),
    path("webhook", views.webhook),
    path("assets/lunixi-logo.svg", views.logo),
    path("", lambda request: HttpResponse("Lunixi", headers={"Cache-Control": "no-store"})),
]
