from django.db.models import CharField, Exists, F, Min, OuterRef, Prefetch, Q, Value
from django.db.models.functions import Coalesce, Lower, NullIf
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.forms import HiddenInput
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from neapolitan.views import CRUDView, Role

from backstage import forms, models
from backstage.themes import is_theme


def _production_members(request, pk, *, related_name, form_class, select_related, order_by, template_name, url_name):
    """List a production's cast or team, with add, edit (?edit=<id>) and remove."""
    production = get_object_or_404(models.Production, pk=pk)
    members = getattr(production, related_name)

    member_id = request.POST.get("member") or request.GET.get("edit") or ""
    instance = members.filter(pk=member_id).first() if member_id.isdigit() else None

    if request.method == "POST":
        if request.POST.get("action") == "remove":
            if instance:
                instance.delete()
            return redirect(url_name, pk=production.pk)
        form = form_class(request.POST, instance=instance)
        if form.is_valid():
            member = form.save(commit=False)
            member.production = production
            member.save()
            return redirect(url_name, pk=production.pk)
    else:
        form = form_class(instance=instance)

    return render(
        request,
        template_name,
        {
            "production": production,
            "members": members.select_related(*select_related).order_by(*order_by),
            "form": form,
            "editing": instance,
        },
    )


def production_cast(request, pk):
    return _production_members(
        request,
        pk,
        related_name="cast",
        form_class=forms.CastForm,
        select_related=["actor__image"],
        order_by=["id"],
        template_name="backstage/production_cast.html",
        url_name="production-cast",
    )


def production_team(request, pk):
    return _production_members(
        request,
        pk,
        related_name="team",
        form_class=forms.ProductionTeamForm,
        select_related=["person__image", "role"],
        order_by=["role__name", "person__last_name", "person__first_name"],
        template_name="backstage/production_team.html",
        url_name="production-team",
    )


def production_events(request, pk):
    """
    A production's events (auditions, rehearsals, performances...) with their dates: create an event
    for the production, delete one, and add or remove an event's dates.
    """
    production = get_object_or_404(models.Production, pk=pk)
    event_form = forms.EventForm()

    if request.method == "POST":
        action = request.POST.get("action")
        event_id = request.POST.get("event", "")
        # Only events linked to this production can be changed from its tab.
        linked_event = production.events.filter(pk=event_id).first() if event_id.isdigit() else None
        if action == "create":
            event_form = forms.EventForm(request.POST)
            if event_form.is_valid():
                production.events.add(event_form.save())
                return redirect("production-events", pk=production.pk)
        else:
            if action == "delete" and linked_event:
                linked_event.delete()  # the event and its dates
            elif action == "add_datetime" and linked_event:
                when = parse_datetime(request.POST.get("datetime", ""))
                if when:
                    if timezone.is_naive(when):
                        when = timezone.make_aware(when)
                    linked_event.datetimes.get_or_create(datetime=when)
            elif action == "remove_datetime":
                datetime_id = request.POST.get("datetime_id", "")
                if datetime_id.isdigit():
                    models.EventDateTime.objects.filter(pk=datetime_id, event__productions=production).delete()
            return redirect("production-events", pk=production.pk)

    events = (
        production.events.select_related("venue", "ticket_site")
        .prefetch_related("datetimes")
        .annotate(first_datetime=Min("datetimes__datetime"))
        .order_by(F("first_datetime").asc(nulls_last=True), "event_type", "pk")
    )
    return render(request, "backstage/production_events.html", {
        "production": production,
        "events": events,
        "event_form": event_form,
        "show_create": event_form.is_bound,  # reopen the New event dialog when the form has errors
    })


def production_images(request, pk):
    """Show a production's images; add images from the library or remove them."""
    production = get_object_or_404(models.Production, pk=pk)

    if request.method == "POST":
        if request.POST.get("action") == "add":
            image_ids = [i for i in request.POST.getlist("images") if i.isdigit()]
            already_added = production.images.values("image_id")
            new_images = models.Image.objects.filter(pk__in=image_ids).exclude(pk__in=already_added)
            models.ProductionImage.objects.bulk_create(
                models.ProductionImage(production=production, image=image) for image in new_images
            )
        elif request.POST.get("action") == "remove":
            production_image_id = request.POST.get("production_image", "")
            if production_image_id.isdigit():
                production.images.filter(pk=production_image_id).delete()
        elif request.POST.get("action") == "default":
            production_image_id = request.POST.get("production_image", "")
            if production_image_id.isdigit() and (
                production_image := production.images.filter(pk=production_image_id).first()
            ):
                production_image.make_default()
        # The first image added, or the next one after the default is removed, becomes the default.
        models.ProductionImage.ensure_default(production)
        return redirect("production-images", pk=production.pk)

    production_images = production.images.select_related("image").order_by("-is_default", "-id")
    available_images = models.Image.objects.exclude(
        pk__in=production_images.values("image_id")
    ).order_by("-id")
    return render(
        request,
        "backstage/production_images.html",
        {
            "production": production,
            "production_images": production_images,
            "available_images": available_images,
        },
    )


class UpstageView(CRUDView):
    model = models.Upstage
    fields = ["name", "introduction", "logo"]


class ImageView(CRUDView):
    """Image library (list), uploader (create/update) and viewer (detail)."""

    model = models.Image
    form_class = forms.ImageForm
    fields = ["image", "description", "image_type"]
    paginate_by = 24

    def get_image_type(self):
        image_type = self.request.GET.get("type")
        return image_type if image_type in models.Image.ImageType.values else None

    def get_form(self, data=None, files=None, **kwargs):
        if wizard_person := (self.get_upload_wizard_person() if self.role == Role.CREATE else None):
            # The new actor wizard's photo step: the description and type are settled, so they are not asked for.
            if data is not None:
                data = data.copy()
                data["image_type"] = models.Image.ImageType.HEADSHOT
                data["description"] = (data.get("description") or str(wizard_person))[:255]
            else:
                initial = kwargs.setdefault("initial", {})
                initial["image_type"] = models.Image.ImageType.HEADSHOT
                initial["description"] = str(wizard_person)[:255]
            form = super().get_form(data, files, **kwargs)
            form.fields["description"].widget = HiddenInput()
            form.fields["image_type"].widget = HiddenInput()
            return form
        if self.role == Role.CREATE and self.get_upload_production():
            # Adding an image from a production's Images tab: only the kinds of image a production uses, starting on Production.
            kinds = models.Image.ImageType
            allowed = [kinds.PRODUCTION, kinds.PROMOTION, kinds.AUDITION, kinds.GALLERY]
            if data is None:
                kwargs.setdefault("initial", {}).setdefault("image_type", kinds.PRODUCTION)
            form = super().get_form(data, files, **kwargs)
            form.fields["image_type"].choices = [(kind.value, kind.label) for kind in allowed]
            form.allowed_types = allowed
            return form
        if data is None and self.role == Role.CREATE:
            initial = kwargs.setdefault("initial", {})
            # The uploader can start on a type of image: /image/new/?type=headshot.
            if image_type := self.get_image_type():
                initial["image_type"] = image_type
            # Started from a person's form (?for_person=new or <pk>, with ?name=...): the description starts as their name.
            if self.get_upload_person_target() and (name := self.request.GET.get("name", "").strip()):
                initial["description"] = name[:255]
        return super().get_form(data, files, **kwargs)

    def get_upload_wizard_person(self):
        """When uploading as step 2 of the new actor wizard (?wizard=1 with ?for_person=<pk>), that person."""
        if self.request.POST.get("wizard") or self.request.GET.get("wizard") == "1":
            target = self.get_upload_person_target()
            return target if isinstance(target, models.Person) else None
        return None

    def get_upload_person_target(self):
        """
        When uploading from a person's form (?for_person=new, or the person's id), where to go back to: "new" for the
        new person form, or the Person being edited. None if the upload didn't come from a person's form.
        """
        target = self.request.POST.get("for_person") or self.request.GET.get("for_person", "")
        if target == "new":
            return "new"
        return models.Person.objects.filter(pk=target).first() if target.isdigit() else None

    def person_form_url(self, image=None):
        """The form to go back to after uploading from a person's form, with the new image chosen on it."""
        target = self.get_upload_person_target()
        base = reverse("person-create") if target == "new" else reverse("person-update", args=[target.pk])
        query = "?restore=1" + (f"&image={image.pk}" if image else "")
        return base + query

    def get_search(self):
        """The search text (?q=...)."""
        return self.request.GET.get("q", "").strip()

    def get_sort(self):
        """"name" (the default) or "newest" (?sort=newest)."""
        return "newest" if self.request.GET.get("sort") == "newest" else "name"

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.get_sort() == "newest":
            queryset = queryset.order_by("-id")
        else:
            # Alphabetical by description (ignoring case); an image with no description is listed by its file name, as
            # that is what its card shows. The id keeps the order steady between pages for images with the same name.
            queryset = queryset.annotate(
                sort_name=Lower(Coalesce(NullIf("description", Value("")), "image", output_field=CharField()))
            ).order_by("sort_name", "id")
        if image_type := self.get_image_type():
            queryset = queryset.filter(image_type=image_type)
        if self.role == Role.LIST:
            # Whether a person has this as their photo, worked out in the same query (the list marks unused headshots).
            queryset = queryset.annotate(has_person=Exists(models.Person.objects.filter(image=OuterRef("pk"))))
        # Search: every word has to be in the image's description or in its file name (ignoring case).
        for word in self.get_search().split():
            queryset = queryset.filter(Q(description__icontains=word) | Q(image__icontains=word))
        return queryset

    def get_context_data(self, **kwargs):
        kwargs["search"] = self.get_search()
        kwargs["image_types"] = models.Image.ImageType.choices
        kwargs["current_type"] = self.get_image_type()
        kwargs["current_sort"] = self.get_sort()
        if self.role == Role.CREATE:
            kwargs["production"] = self.get_upload_production()
            target = self.get_upload_person_target()
            if wizard_person := self.get_upload_wizard_person():
                kwargs["wizard_person"] = wizard_person
                kwargs["wizard_skip_url"] = reverse("actor-roles", args=[wizard_person.pk])
            if target:
                kwargs["for_person"] = "new" if target == "new" else target.pk
                kwargs["person_form_url"] = self.person_form_url()
        if self.role == Role.DETAIL and self.object.image_type == models.Image.ImageType.HEADSHOT:
            # Whose photo it is (usually one person).
            kwargs["people"] = models.Person.objects.filter(image=self.object).order_by("last_name", "first_name")
        if self.role == Role.DETAIL:
            # Opened from a production's Images tab (?production=<pk>): go back there, not to the library.
            production_id = self.request.GET.get("production", "")
            production = (
                models.Production.objects.filter(pk=production_id, images__image=self.object).first()
                if production_id.isdigit() else None
            )
            if production:
                kwargs["back_url"] = reverse("production-images", args=[production.pk])
                kwargs["back_label"] = f"{production} images"
            else:
                kwargs["back_url"] = reverse("image-list")
                kwargs["back_label"] = "Image library"
        return super().get_context_data(**kwargs)

    def get_upload_production(self):
        """When uploading from a production's Images tab (?production=<pk>), that production."""
        production_id = self.request.POST.get("production") or self.request.GET.get("production", "")
        return models.Production.objects.filter(pk=production_id).first() if production_id.isdigit() else None

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.role == Role.CREATE and (production := self.get_upload_production()):
            # The new image goes straight onto the production (as its default if it's the first).
            models.ProductionImage.objects.create(production=production, image=self.object)
            models.ProductionImage.ensure_default(production)
        if self.role == Role.CREATE and (person := self.get_upload_wizard_person()):
            # The new actor wizard: the uploaded photo is the person's photo.
            person.image = self.object
            person.save(update_fields=["image"])
        return response

    def get_success_url(self):
        if self.role == Role.CREATE and (person := self.get_upload_wizard_person()):
            return reverse("actor-roles", args=[person.pk])  # on to step 3
        if self.role == Role.CREATE and self.get_upload_person_target():
            # Back to the person's form, with the new image chosen as their photo.
            return self.person_form_url(self.object)
        if self.role == Role.CREATE and (production := self.get_upload_production()):
            return reverse("production-images", args=[production.pk])
        # After uploading or deleting, go back to the library.
        if self.role in (Role.CREATE, Role.DELETE):
            return Role.LIST.reverse(self)
        return super().get_success_url()


# Headings for a person's production team credits, in the order they're shown.
CREDIT_HEADINGS = {"Writer": "Plays written", "Director": "Directed", "Editor": "Edited"}


def person_productions(person):
    """A person's productions: (cast_in, credits). Used by the backstage and public person pages.

    cast_in is [(production, [character names])], newest first. credits is [(heading, [productions])],
    one section per production team role (writer, director, editor first), newest first.
    """
    parts = (
        person.cast_roles.select_related("production")
        .annotate(broadcast_at=models.broadcast_date("production__"))
        .order_by(F("broadcast_at").desc(nulls_last=True), "production__title", "id")
    )
    characters = {}
    for part in parts:
        characters.setdefault(part.production, []).append(part.character_name)
    credits = {}
    for credit in (
        person.productionteam_set.select_related("production", "role")
        .annotate(broadcast_at=models.broadcast_date("production__"))
        .order_by(F("broadcast_at").desc(nulls_last=True), "production__title")
    ):
        credits.setdefault(credit.role.name, []).append(credit.production)
    order = list(CREDIT_HEADINGS)
    sections = [
        (CREDIT_HEADINGS.get(role, role), productions)
        for role, productions in sorted(
            credits.items(), key=lambda item: (order.index(item[0]) if item[0] in order else len(order), item[0])
        )
    ]
    return list(characters.items()), sections


class PersonView(CRUDView):
    model = models.Person
    form_class = forms.PersonForm
    # Columns shown in the list. Create/update use PersonForm and detail has its own template.
    fields = ["first_name", "last_name", "email", "mobile", "gender", "dob", "image"]

    # Pages that link to a person with ?from=..., and the "back" link the person page shows.
    BACK_LINKS = {
        "actors": ("actor-list", "", "Actors"),
        "actors-details": ("actor-list", "?view=details", "Actors"),
        "writers": ("writer-list", "", "Writers"),
    }

    def get_form(self, data=None, files=None, **kwargs):
        # A new person can start with a role ticked: /person/new/?role=Actor (the "New actor" button).
        if data is None and self.role == Role.CREATE and self.request.GET.get("role"):
            roles = models.Role.objects.filter(name=self.request.GET["role"])
            kwargs.setdefault("initial", {})["roles"] = list(roles)
        # Back from uploading a photo (?image=<pk>): it is chosen as the photo (until the form is saved).
        image_id = self.request.GET.get("image", "")
        if data is None and self.role in (Role.CREATE, Role.UPDATE) and image_id.isdigit():
            if models.Image.objects.filter(pk=image_id, image_type=models.Image.ImageType.HEADSHOT).exists():
                kwargs.setdefault("initial", {})["image"] = int(image_id)
        return super().get_form(data, files, **kwargs)

    def photo_uses(self, person):
        """What else (besides this person) uses their photo, as a list of phrases for the delete page."""
        image = person.image
        uses = []
        if (others := models.Person.objects.filter(image=image).exclude(pk=person.pk).count()):
            uses.append(f"{others} other {'person' if others == 1 else 'people'}")
        if (productions := models.ProductionImage.objects.filter(image=image).count()):
            uses.append(f"{productions} production{'s' if productions != 1 else ''}")
        if (venues := models.Venue.objects.filter(logo=image).count()):
            uses.append(f"{venues} venue{'s' if venues != 1 else ''}")
        return uses

    def process_deletion(self, request, *args, **kwargs):
        """Deleting a person can also delete their photo, if asked (the checkbox on the delete page)."""
        self.object = self.get_object()
        image = self.object.image if request.POST.get("delete_image") else None
        self.object.delete()
        if image:
            image.delete()
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        if self.role == Role.DELETE and self.object.image_id:
            kwargs["photo_uses"] = self.photo_uses(self.object)
        if self.role == Role.DETAIL:
            url_name, query, label = self.BACK_LINKS.get(self.request.GET.get("from"), ("person-list", "", "People"))
            kwargs["back_url"] = reverse(url_name) + query
            kwargs["back_label"] = label
            kwargs["cast_in"], kwargs["credits"] = person_productions(self.object)
        if self.role in (Role.CREATE, Role.UPDATE):
            # Lets the form preview the selected photo.
            photos = kwargs["form"].fields["image"].queryset if "form" in kwargs else models.Image.objects.all()
            kwargs["image_urls"] = {str(image.pk): image.image.url for image in photos.exclude(image="")}
        return super().get_context_data(**kwargs)


def actor_new(request):
    """New actor wizard, step 1 of 3: names, contact details and biography. Saved, then on to the photo."""
    form = forms.PersonDetailsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        person = form.save()
        query = urlencode({"type": "headshot", "for_person": person.pk, "wizard": 1})
        return redirect(f"{reverse('image-create')}?{query}")
    return render(request, "backstage/actor_wizard_details.html", {"form": form})


def actor_roles(request, pk):
    """New actor wizard, step 3 of 3: the person as they will appear, and their roles."""
    person = get_object_or_404(models.Person.objects.select_related("image"), pk=pk)
    initial = {}
    if request.method != "POST" and not person.roles.exists():
        initial["roles"] = models.Role.objects.filter(name="Actor")  # they are being added as an actor
    form = forms.PersonRolesForm(request.POST or None, instance=person, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(f"{reverse('person-detail', args=[person.pk])}?from=actors")
    return render(request, "backstage/actor_wizard_roles.html", {"person": person, "form": form})


def contact_list(request):
    """The people who have filled in a contact form, newest first. ?interest=newsletter|acting|backstage narrows it, ?q= searches."""
    interests = {"newsletter": "Occasional newsletter", "acting": "Acting", "backstage": "Backstage roles"}
    contacts = models.Contact.objects.all()
    interest = request.GET.get("interest")
    if interest in interests:
        contacts = contacts.filter(**{interest: True})
    search = request.GET.get("q", "").strip()
    for word in search.split():
        contacts = contacts.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word) | Q(email__icontains=word))
    return render(
        request, "backstage/contact_list.html",
        {"contacts": contacts, "interests": interests, "interest": interest if interest in interests else "", "search": search},
    )


def writer_list(request):
    """Everyone with the Writer role, with the productions they wrote."""
    writers = (
        models.Person.objects.filter(roles__name="Writer")
        .select_related("image")
        .prefetch_related(
            Prefetch(
                "productionteam_set",
                queryset=models.ProductionTeam.objects.filter(role__name="Writer")
                .select_related("production")
                .annotate(broadcast_at=models.broadcast_date("production__"))
                .order_by(F("broadcast_at").desc(nulls_last=True), "production__title"),
                to_attr="writing_credits",
            )
        )
        # Alphabetical by surname, then first name.
        .order_by(Lower("last_name"), Lower("first_name"))
        .distinct()
    )
    return render(request, "backstage/writer_list.html", {"writers": writers})


def actor_list(request):
    """
    Everyone with the Actor role: photos and names, or with details. Alphabetical by surname, or by first name
    (?sort=first).
    """
    details = request.GET.get("view") == "details"
    sort = "first" if request.GET.get("sort") == "first" else "last"
    if sort == "first":
        order = (Lower("first_name"), Lower("last_name"))
    else:
        # People known by one name ("Divya") sort by that name.
        order = (Coalesce(NullIf(Lower("last_name"), Value("")), Lower("first_name")), Lower("first_name"))
    actors = models.Person.objects.filter(roles__name="Actor").select_related("image").order_by(*order).distinct()
    if details:
        actors = actors.prefetch_related(
            Prefetch(
                "cast_roles",
                queryset=models.Cast.objects.select_related("production")
                .annotate(broadcast_at=models.broadcast_date("production__"))
                .order_by(F("broadcast_at").desc(nulls_last=True), "production__title"),
                to_attr="parts",
            )
        )
    return render(request, "backstage/actor_list.html", {"actors": actors, "details": details, "sort": sort})


class TicketSiteView(CRUDView):
    model = models.TicketSite
    fields = ["name", "url"]


class VenueView(CRUDView):
    model = models.Venue
    fields = ["name", "address", "logo"]


class EventView(CRUDView):
    model = models.Event
    form_class = forms.EventDetailsForm  # the ticket website is typed in, not chosen from a list
    fields = ["event_type", "publish", "description", "venue", "ticket_site"]

    def get_production(self):
        """When editing from a production's Events tab (?production=<pk>), that production: saving or cancelling goes back to it."""
        production_id = self.request.POST.get("production") or self.request.GET.get("production", "")
        if self.role == Role.UPDATE and production_id.isdigit():
            return models.Production.objects.filter(pk=production_id, events=self.object).first()
        return None

    def get_context_data(self, **kwargs):
        if production := self.get_production():
            kwargs["production"] = production
            kwargs["cancel_url"] = reverse("production-events", args=[production.pk])
        return super().get_context_data(**kwargs)

    def get_success_url(self):
        if production := self.get_production():
            return reverse("production-events", args=[production.pk])
        return super().get_success_url()


class EventDateTimeView(CRUDView):
    model = models.EventDateTime
    fields = ["event", "datetime"]


class ProductionView(CRUDView):
    model = models.Production
    fields = ["title", "strap_line", "description", "type", "parent"]
    paginate_by = 24

    def get_type(self):
        production_type = self.request.GET.get("type")
        return production_type if production_type in models.Production.ProductionType.values else None

    # A production is published when it has a Published or Promoted event.
    PUBLISHED_FILTERS = [("published", "Published"), ("not_published", "Not published")]

    def get_published(self):
        published = self.request.GET.get("published")
        return published if published in dict(self.PUBLISHED_FILTERS) else None

    def get_search(self):
        return self.request.GET.get("q", "").strip()

    # By broadcast date (that of its Broadcast event); productions without one go last, most recently added first.
    SORTS = {
        "newest": ("Newest first", [F("broadcast_at").desc(nulls_last=True), "-id"]),
        "oldest": ("Oldest first", [F("broadcast_at").asc(nulls_last=True), "-id"]),
        "title": ("Alphabetical", [Lower("title"), "-id"]),
    }

    def get_sort(self):
        sort = self.request.GET.get("sort")
        return sort if sort in self.SORTS else "newest"

    def get_queryset(self):
        queryset = super().get_queryset().order_by("-id")
        if self.role == Role.LIST:
            queryset = queryset.with_broadcast_date()
            # The default image is used as the cover in the list (Production.default_image).
            queryset = queryset.prefetch_related(
                Prefetch("images", queryset=models.ProductionImage.objects.select_related("image").order_by("id"))
            )
            if production_type := self.get_type():
                queryset = queryset.filter(type=production_type)
            if published := self.get_published():
                shown = models.Event.objects.filter(
                    productions=OuterRef("pk"), publish__in=[models.Event.Publish.PUBLISHED, models.Event.Publish.PROMOTED]
                )
                queryset = queryset.filter(Exists(shown) if published == "published" else ~Exists(shown))
            if search := self.get_search():
                queryset = queryset.filter(title__icontains=search)
            queryset = queryset.order_by(*self.SORTS[self.get_sort()][1])
        return queryset

    def get_context_data(self, **kwargs):
        kwargs["types"] = models.Production.ProductionType.choices
        kwargs["current_type"] = self.get_type()
        kwargs["published_filters"] = self.PUBLISHED_FILTERS
        kwargs["current_published"] = self.get_published()
        kwargs["search"] = self.get_search()
        kwargs["sorts"] = [(value, label) for value, (label, _) in self.SORTS.items()]
        kwargs["current_sort"] = self.get_sort()
        return super().get_context_data(**kwargs)


class ParentProductionView(CRUDView):
    """Making a parent production; after that it is shown and edited like any production (its pk is the production's pk)."""

    model = models.ParentProduction
    fields = ["title", "strap_line", "description", "type"]

    def get_success_url(self):
        return reverse("production-detail", args=[self.object.pk])


class CastView(CRUDView):
    model = models.Cast
    fields = ["character_name", "characteristics", "production", "actor"]


class RoleView(CRUDView):
    model = models.Role
    fields = ["name"]


class ProductionTeamView(CRUDView):
    model = models.ProductionTeam
    fields = ["person", "role", "production"]


class ProductionImageView(CRUDView):
    model = models.ProductionImage
    fields = ["production", "image"]


def set_public_theme(request):
    """Choose the theme the public pages use (POST public_theme: a theme name, or "" for automatic), then go back."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    chosen = request.POST.get("public_theme", "")
    if chosen == "" or is_theme(chosen):
        settings_row = models.SiteSettings.load()
        settings_row.public_theme = chosen
        settings_row.save()
    back = request.POST.get("next") or request.META.get("HTTP_REFERER", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = reverse("production-list")
    return redirect(back)
