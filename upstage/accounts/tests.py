import re

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import CustomUser

PASSWORD = "a-Long-pa55word!"


class AccountPagesTests(TestCase):
    def test_pages_render(self):
        for name in ("login", "signup", "password_reset", "password_reset_done", "password_reset_complete"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_signup_creates_user_and_logs_in(self):
        response = self.client.post(reverse("signup"), {
            "username": "newbie", "first_name": "New", "last_name": "Bie", "email": "newbie@example.com",
            "password1": PASSWORD, "password2": PASSWORD,
        })
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertTrue(CustomUser.objects.filter(username="newbie", email="newbie@example.com").exists())
        self.assertIn("_auth_user_id", self.client.session)

    def test_signup_rejects_duplicate_email(self):
        CustomUser.objects.create_user("first", "dupe@example.com", PASSWORD)
        response = self.client.post(reverse("signup"), {
            "username": "second", "email": "DUPE@example.com", "password1": PASSWORD, "password2": PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CustomUser.objects.filter(username="second").exists())

    def test_login_and_logout(self):
        CustomUser.objects.create_user("member", "member@example.com", PASSWORD)
        response = self.client.post(reverse("login"), {"username": "member", "password": PASSWORD})
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.client.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_change(self):
        user = CustomUser.objects.create_user("member", "member@example.com", PASSWORD)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 200)
        new = "another-Long-pa55word!"
        response = self.client.post(reverse("password_change"), {
            "old_password": PASSWORD, "new_password1": new, "new_password2": new,
        })
        self.assertRedirects(response, reverse("password_change_done"))
        user.refresh_from_db()
        self.assertTrue(user.check_password(new))

    def test_password_reset_by_email(self):
        user = CustomUser.objects.create_user("member", "member@example.com", PASSWORD)
        self.client.post(reverse("password_reset"), {"email": "member@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://[^/\s]+(/accounts/reset/\S+/)", mail.outbox[0].body).group(1)
        # The emailed link redirects to a set-password form, then the new password can be saved.
        response = self.client.get(link, follow=True)
        self.assertEqual(response.status_code, 200)
        new = "brand-new-Long-pa55word!"
        response = self.client.post(response.request["PATH_INFO"], {"new_password1": new, "new_password2": new})
        self.assertRedirects(response, reverse("password_reset_complete"))
        user.refresh_from_db()
        self.assertTrue(user.check_password(new))

    def test_password_reset_unknown_email_is_not_revealed(self):
        response = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)


class LoginRequiredTests(TestCase):
    def test_public_pages_need_no_login(self):
        for name in ("home", "auditions"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_other_pages_redirect_to_login(self):
        for name in ("production-list", "person-list", "image-list", "page-list"):
            url = reverse(name)
            self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}", msg_prefix=name)

    def test_logged_in_user_can_see_them(self):
        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", PASSWORD))
        self.assertEqual(self.client.get(reverse("production-list")).status_code, 200)
