from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from neapolitan.views import CRUDView, Role

from backstage import forms, models


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
        return redirect("production-images", pk=production.pk)

    production_images = production.images.select_related("image").order_by("-id")
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
    fields = ["image", "description", "image_type"]
    paginate_by = 24

    def get_image_type(self):
        image_type = self.request.GET.get("type")
        return image_type if image_type in models.Image.ImageType.values else None

    def get_queryset(self):
        queryset = super().get_queryset().order_by("-id")
        if image_type := self.get_image_type():
            queryset = queryset.filter(image_type=image_type)
        return queryset

    def get_context_data(self, **kwargs):
        kwargs["image_types"] = models.Image.ImageType.choices
        kwargs["current_type"] = self.get_image_type()
        return super().get_context_data(**kwargs)

    def get_success_url(self):
        # After uploading or deleting, go back to the library.
        if self.role in (Role.CREATE, Role.DELETE):
            return Role.LIST.reverse(self)
        return super().get_success_url()


class PersonView(CRUDView):
    model = models.Person
    form_class = forms.PersonForm
    # Columns shown in the list. Create/update use PersonForm and detail has its own template.
    fields = ["first_name", "last_name", "email", "mobile", "gender", "dob", "image"]

    def get_context_data(self, **kwargs):
        if self.role in (Role.CREATE, Role.UPDATE):
            # Lets the form preview the selected photo.
            kwargs["image_urls"] = {
                str(image.pk): image.image.url for image in models.Image.objects.exclude(image="")
            }
        return super().get_context_data(**kwargs)


class TicketSiteView(CRUDView):
    model = models.TicketSite
    fields = ["name", "url"]


class VenueView(CRUDView):
    model = models.Venue
    fields = ["name", "address"]


class EventView(CRUDView):
    model = models.Event
    fields = ["title", "description", "venue", "ticket_site"]


class EventDateTimeView(CRUDView):
    model = models.EventDateTime
    fields = ["event", "datetime"]


class ProductionView(CRUDView):
    model = models.Production
    fields = ["title", "strap_line", "description", "writer", "state", "type", "event"]
    paginate_by = 24

    def get_state(self):
        state = self.request.GET.get("state")
        return state if state in models.Production.ProductionState.values else None

    def get_queryset(self):
        queryset = super().get_queryset().order_by("-id")
        if self.role == Role.LIST:
            # First attached image is used as the cover in the list.
            queryset = queryset.prefetch_related(
                Prefetch("images", queryset=models.ProductionImage.objects.select_related("image").order_by("id"))
            )
            if state := self.get_state():
                queryset = queryset.filter(state=state)
        return queryset

    def get_context_data(self, **kwargs):
        kwargs["states"] = models.Production.ProductionState.choices
        kwargs["current_state"] = self.get_state()
        return super().get_context_data(**kwargs)


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
