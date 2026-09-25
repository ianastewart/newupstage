from neapolitan.views import CRUDView, Role

from backstage import models


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
    fields = ["first_name", "last_name", "email", "mobile", "biography", "gender", "dob", "image"]


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
