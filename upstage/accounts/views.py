from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import redirect, render

from .forms import SignUpForm


@login_not_required
def signup(request):
    """Create an account, then log the new user in."""
    if request.user.is_authenticated:
        return redirect("home")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")
    return render(request, "registration/signup.html", {"form": form})
