from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

from .access import can_backstage, can_sandbox

# The account pages a visitor to the sandbox needs before they can be let in (or to leave).
SANDBOX_OPEN_URL_NAMES = {
    "login", "logout", "password_reset", "password_reset_done", "password_reset_confirm", "password_reset_complete",
}
# Pages any logged in user may use, whether or not they are in the backstage group.
BACKSTAGE_EXEMPT_URL_NAMES = {"logout", "password_change", "password_change_done"}


class SandboxGateMiddleware:
    """
    On the sandbox site (settings.SITE_MODE == "sandbox") nothing can be seen without logging in as a member of the
    sandbox group (or a superuser), not even the public pages. It runs before LoginRequiredMiddleware, so it also
    covers the views marked @login_not_required. A visitor who is not logged in sees the login form on the home page (any
    other address sends them there, remembering where they were going). Search engines are told not to index the
    sandbox. On the live site it does nothing.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.SITE_MODE != "sandbox":
            return self.get_response(request)
        response = self.gate(request) or self.get_response(request)
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response

    def gate(self, request):
        """A response if the visitor is not let in, else None."""
        try:
            url_name = resolve(request.path_info).url_name
        except Resolver404:
            url_name = None
        if url_name in SANDBOX_OPEN_URL_NAMES and (url_name != "logout" or request.user.is_authenticated):
            return None
        if not request.user.is_authenticated:
            if request.path_info != "/":
                return redirect(f"/?{urlencode({'next': request.get_full_path()})}")
            going_to = request.GET.get("next", "")
            if not url_has_allowed_host_and_scheme(going_to, allowed_hosts={request.get_host()}):
                going_to = "/"
            return render(request, "registration/login.html", {"form": AuthenticationForm(request), "next": going_to})
        if not can_sandbox(request.user):
            return render(request, "registration/sandbox_forbidden.html", status=403)
        return None


class BackstageAccessMiddleware:
    """
    Every view that needs a login (all but those marked @login_not_required, so the backstage and the page editor)
    needs the user to be in the backstage group (or a superuser). Runs after LoginRequiredMiddleware, which has already sent
    anonymous visitors to the login page. The admin has its own is_staff check, and the account pages for changing a password
    are open to any logged in user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not getattr(view_func, "login_required", True):
            return None
        match = request.resolver_match
        if match and (match.url_name in BACKSTAGE_EXEMPT_URL_NAMES or "admin" in match.namespaces):
            return None
        if can_backstage(request.user):
            return None
        return render(request, "403_backstage.html", status=403)
