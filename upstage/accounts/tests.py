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
        self.assertRedirects(response, reverse("production-list"), fetch_redirect_response=False)
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
        from home.models import WebPage

        WebPage.objects.create(title="Home", slug="home")  # the home view shows the page with this slug
        for name in ("home", "auditions"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_other_pages_redirect_to_login(self):
        for name in ("production-list", "person-list", "image-list", "page-list"):
            url = reverse(name)
            self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}", msg_prefix=name)

    def test_logged_in_user_can_see_them(self):
        self.client.force_login(backstage_user("member", "member@example.com", PASSWORD))
        self.assertEqual(self.client.get(reverse("production-list")).status_code, 200)


class PublicActorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from backstage.models import Image, Person, Role

        actor = Role.objects.get_or_create(name="Actor")[0]
        cls.with_image = Person.objects.create(first_name="Ann", last_name="Pictured", biography="<p>Likes acting.</p>",
                                               email="ann@example.com", mobile="07000 000000", publish_consent=True)
        # Only the file's name is stored: nothing is written to the media folder.
        image = Image.objects.create(description="Ann", image="images/test-ann.jpg")
        cls.with_image.image = image
        cls.with_image.save()
        cls.without_image = Person.objects.create(first_name="Bob", last_name="Unpictured")
        cls.writer = Person.objects.create(first_name="Wendy", last_name="Writer", image=image)
        for person in (cls.with_image, cls.without_image):
            person.roles.add(actor)

    def test_list_is_public_and_only_shows_actors_with_images(self):
        response = self.client.get(reverse("public-actors"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ann Pictured")
        self.assertNotContains(response, "Bob Unpictured")
        self.assertNotContains(response, "Wendy Writer")

    def test_detail_shows_name_photo_and_bio_only(self):
        response = self.client.get(reverse("public-actor", args=[self.with_image.pk]))
        self.assertContains(response, "Ann Pictured")
        self.assertContains(response, "Likes acting.")
        self.assertNotContains(response, "ann@example.com")
        self.assertNotContains(response, "07000 000000")
        self.assertNotContains(response, "badge")

    def test_detail_hidden_for_actors_without_image_and_non_actors(self):
        for person in (self.without_image, self.writer):
            self.assertEqual(self.client.get(reverse("public-actor", args=[person.pk])).status_code, 404)

    def test_detail_shows_productions_and_credits(self):
        from backstage.models import Cast, Production, ProductionTeam, Role

        play = Production.objects.create(title="The Test Play")
        Cast.objects.create(production=play, character_name="Hamlet", actor=self.with_image)
        directed = Production.objects.create(title="Directed By Ann")
        ProductionTeam.objects.create(
            production=directed, person=self.with_image, role=Role.objects.get_or_create(name="Director")[0]
        )
        response = self.client.get(reverse("public-actor", args=[self.with_image.pk]))
        for text in ("Cast in", "The Test Play", "Hamlet", "Directed", "Directed By Ann"):
            self.assertContains(response, text)
        self.assertNotContains(response, "badge")

    def test_backstage_person_page_still_shows_credits(self):
        from backstage.models import Cast, Production

        play = Production.objects.create(title="The Test Play")
        Cast.objects.create(production=play, character_name="Hamlet", actor=self.with_image)
        self.client.force_login(backstage_user("member", "member@example.com", PASSWORD))
        response = self.client.get(reverse("person-detail", args=[self.with_image.pk]))
        self.assertContains(response, "The Test Play")
        self.assertContains(response, "Hamlet")


class UserAdminTests(TestCase):
    """Users can be listed, added and changed in the Django admin."""

    def setUp(self):
        self.admin = CustomUser.objects.create_superuser("boss", "boss@example.com", "pw12345!x")
        self.client.force_login(self.admin)

    def test_the_user_screens_open(self):
        for url in ("/admin/accounts/customuser/", "/admin/accounts/customuser/add/", f"/admin/accounts/customuser/{self.admin.pk}/change/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_a_user_can_be_added(self):
        response = self.client.post(
            "/admin/accounts/customuser/add/",
            {"username": "newbie", "password1": "Str0ng-pass-123", "password2": "Str0ng-pass-123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CustomUser.objects.get(username="newbie").check_password("Str0ng-pass-123"))



from django.contrib.auth.models import Group  # noqa: E402
from django.test import override_settings  # noqa: E402

from .access import BACKSTAGE_GROUP, SANDBOX_GROUP  # noqa: E402
from .testing import backstage_user  # noqa: E402


class BackstageGroupTests(TestCase):
    def setUp(self):
        self.backstage = reverse("production-list")

    def test_the_groups_exist(self):
        self.assertTrue(Group.objects.filter(name=BACKSTAGE_GROUP).exists())
        self.assertTrue(Group.objects.filter(name=SANDBOX_GROUP).exists())

    def test_anonymous_visitors_are_sent_to_log_in(self):
        self.assertEqual(self.client.get(self.backstage).status_code, 302)

    def test_a_logged_in_user_outside_the_group_is_refused(self):
        self.client.force_login(CustomUser.objects.create_user("plain", "plain@example.com", PASSWORD))
        self.assertEqual(self.client.get(self.backstage).status_code, 403)
        self.assertEqual(self.client.get(reverse("page-list")).status_code, 403)  # the page editor too
        self.assertEqual(self.client.post(reverse("public-theme")).status_code, 403)

    def test_a_staff_flag_alone_is_not_enough(self):
        self.client.force_login(CustomUser.objects.create_user("flag", "flag@example.com", PASSWORD, is_staff=True))
        self.assertEqual(self.client.get(self.backstage).status_code, 403)

    def test_a_group_member_and_a_superuser_get_in(self):
        self.client.force_login(backstage_user("member", "member@example.com", PASSWORD))
        self.assertEqual(self.client.get(self.backstage).status_code, 200)
        self.client.force_login(CustomUser.objects.create_superuser("boss", "boss@example.com", PASSWORD))
        self.assertEqual(self.client.get(self.backstage).status_code, 200)

    def test_the_public_pages_and_the_account_pages_stay_open(self):
        self.client.force_login(CustomUser.objects.create_user("plain", "plain@example.com", PASSWORD))
        for name in ("stage-shows", "password_change"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_the_backstage_link_is_only_for_the_group(self):
        link = f'href="{self.backstage}"'
        self.client.force_login(CustomUser.objects.create_user("plain", "plain@example.com", PASSWORD))
        self.assertNotContains(self.client.get(reverse("stage-shows")), link)
        self.client.force_login(backstage_user("member", "member@example.com", PASSWORD))
        self.assertContains(self.client.get(reverse("stage-shows")), link)


@override_settings(SITE_MODE="sandbox")
class SandboxSiteTests(TestCase):
    def test_anonymous_visitors_see_the_login_form_on_the_home_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<form method="POST" action="{reverse("login")}">')
        self.assertContains(response, 'name="next" value="/"')
        self.assertContains(response, "SANDBOX")
        self.assertNotContains(response, "Create an account")
        self.assertContains(response, 'style="background-color: #1e40af; color: #fff;"')  # the dark blue login box
        self.assertNotContains(response, "tracking-widest text-primary")  # the backstage navbar's "Backstage" label
        self.assertContains(response, 'href="/stage-shows/"')  # the public navbar
        self.assertNotContains(self.client.get(reverse("login")), "tracking-widest text-primary")

    def test_any_other_page_sends_them_to_the_home_page_remembering_where_they_were_going(self):
        for name in ("stage-shows", "sitemap", "production-list"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertEqual(response["Location"], f"/?next={reverse(name).replace('/', '%2F')}", name)
        response = self.client.get("/?next=/stage-shows/")
        self.assertContains(response, 'name="next" value="/stage-shows/"')
        self.assertContains(self.client.get("/?next=https://evil.example/"), 'name="next" value="/"')

    def test_logging_in_from_the_home_page_lets_a_sandbox_member_in(self):
        user = CustomUser.objects.create_user("tester", "tester@example.com", PASSWORD)
        user.groups.add(Group.objects.get(name=SANDBOX_GROUP))
        response = self.client.post(reverse("login"), {"username": "tester", "password": PASSWORD, "next": "/stage-shows/"})
        self.assertRedirects(response, "/stage-shows/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/stage-shows/").status_code, 200)

    def test_anonymous_visitors_can_fetch_a_logo_but_no_other_media(self):
        from backstage.models import Image

        Image.objects.create(image="images/logo_test.png", description="A logo", image_type=Image.ImageType.LOGO)
        Image.objects.create(image="images/secret_test.png", description="Other", image_type=Image.ImageType.PRODUCTION)
        # (the files do not exist, so a logo is let through to a 404; anything else is sent to the login form)
        self.assertEqual(self.client.get("/media/images/logo_test.png").status_code, 404)
        response = self.client.get("/media/images/secret_test.png")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/?next=%2Fmedia%2Fimages%2Fsecret_test.png")
        self.assertEqual(self.client.get("/media/images/nothing.png").status_code, 302)

    def test_robots_txt_is_open_so_that_search_engines_are_told_to_keep_out(self):
        response = self.client.get(reverse("robots"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "User-agent: *\nDisallow: /\n")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_the_login_pages_are_open(self):
        for name in ("login", "password_reset"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_signup_is_closed(self):
        self.assertEqual(self.client.get(reverse("signup")).status_code, 302)

    def test_a_user_outside_the_sandbox_group_is_refused_but_can_log_out(self):
        self.client.force_login(backstage_user("member", "member@example.com", PASSWORD))
        response = self.client.get(reverse("stage-shows"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "sandbox group", status_code=403)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)

    def test_a_sandbox_member_sees_the_public_pages_but_not_the_backstage(self):
        user = CustomUser.objects.create_user("tester", "tester@example.com", PASSWORD)
        user.groups.add(Group.objects.get(name=SANDBOX_GROUP))
        self.client.force_login(user)
        response = self.client.get(reverse("stage-shows"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SANDBOX")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.client.get(reverse("production-list")).status_code, 403)

    def test_a_member_of_both_groups_and_a_superuser_get_everything(self):
        both = backstage_user("both", "both@example.com", PASSWORD)
        both.groups.add(Group.objects.get(name=SANDBOX_GROUP))
        for user in (both, CustomUser.objects.create_superuser("boss", "boss@example.com", PASSWORD)):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("stage-shows")).status_code, 200)
            self.assertEqual(self.client.get(reverse("production-list")).status_code, 200)

    def test_robots_txt_disallows_everything(self):
        user = CustomUser.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("robots")).content.decode(), "User-agent: *\nDisallow: /\n")


class LiveSiteTests(TestCase):
    PUBLIC_PAGES = (
        "home", "auditions", "radio-archive", "stage-shows", "musicals", "films", "public-writers", "public-crew",
        "public-actors", "robots", "sitemap", "login",
    )

    def test_everyone_can_see_the_public_pages_whatever_their_groups(self):
        """Visitors, users in no group, and members of either group: no redirect to log in and no 403."""
        sandbox_only = CustomUser.objects.create_user("sb", "sb@example.com", PASSWORD)
        sandbox_only.groups.add(Group.objects.get(name=SANDBOX_GROUP))
        visitors = [None, CustomUser.objects.create_user("plain", "plain@example.com", PASSWORD), sandbox_only,
                    backstage_user("member", "member@example.com", PASSWORD)]
        for visitor in visitors:
            self.client.logout()
            if visitor:
                self.client.force_login(visitor)
            for name in self.PUBLIC_PAGES:
                status = self.client.get(reverse(name)).status_code
                self.assertNotIn(status, (302, 403), f"{name} for {visitor}")
    def test_no_sandbox_banner_or_gate_on_the_live_site(self):
        response = self.client.get(reverse("stage-shows"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "SANDBOX")
        self.assertNotIn("X-Robots-Tag", response)


class LoginPlaceTests(TestCase):
    """The log in / backstage / log out control is at the top right of the public pages, not in the footer."""

    def navbar_end(self):
        html = self.client.get(reverse("stage-shows")).content.decode()
        return html.split('<div class="navbar-end">')[1].split('<div class="dropdown dropdown-end sm:hidden">')[0]

    def test_a_visitor_sees_log_in_top_right(self):
        end = self.navbar_end()
        self.assertIn(f'href="{reverse("login")}"', end)
        self.assertNotIn("Log out", end)
        self.assertNotIn("Backstage", end)

    def test_a_user_without_backstage_access_sees_log_out(self):
        self.client.force_login(CustomUser.objects.create_user("plain", "plain@example.com", PASSWORD))
        end = self.navbar_end()
        self.assertIn(f'action="{reverse("logout")}"', end)
        self.assertIn("Log out", end)
        self.assertNotIn("Backstage", end)

    def test_a_user_with_backstage_access_sees_backstage(self):
        self.client.force_login(backstage_user("member", "member@example.com", PASSWORD))
        end = self.navbar_end()
        self.assertIn(f'href="{reverse("production-list")}"', end)
        self.assertNotIn("Log out", end)

    def test_the_footer_no_longer_has_it(self):
        html = self.client.get(reverse("stage-shows")).content.decode()
        footer = html.split('<div id="footer">')[1]
        self.assertNotIn("Log in", footer)
        self.assertNotIn("Log out", footer)
