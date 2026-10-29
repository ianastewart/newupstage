from django.urls import path
from neapolitan.views import Role

from backstage import views

urlpatterns = [
    path("public-theme/", views.set_public_theme, name="public-theme"),
    path("actors/", views.actor_list, name="actor-list"),
    path("actors/new/", views.actor_new, name="actor-new"),
    path("actors/<int:pk>/roles/", views.actor_roles, name="actor-roles"),
    path("auditions/", views.audition_list, name="backstage-auditions"),
    path("contacts/", views.contact_list, name="contact-list"),
    path("writers/", views.writer_list, name="writer-list"),
    path("writers/new/", views.writer_new, name="writer-new"),
    path("writers/<int:pk>/roles/", views.writer_roles, name="writer-roles"),
    path("others/", views.other_list, name="other-list"),
    path("others/new/", views.other_new, name="other-new"),
    path("others/<int:pk>/roles/", views.other_roles, name="other-roles"),
    path("production/<int:pk>/images/", views.production_images, name="production-images"),
    path("production/<int:pk>/events/", views.production_events, name="production-events"),
    path("production/<int:pk>/cast/", views.production_cast, name="production-cast"),
    path("production/<int:pk>/team/", views.production_team, name="production-team"),
    *views.UpstageView.get_urls(),
    *views.ImageView.get_urls(),
    *views.PersonView.get_urls(),
    *views.TicketSiteView.get_urls(),
    *views.VenueView.get_urls(),
    *views.EventView.get_urls(),
    *views.EventDateTimeView.get_urls(),
    *views.ProductionView.get_urls(),
    *views.ParentProductionView.get_urls(roles=[Role.CREATE]),
    *views.CastView.get_urls(),
    *views.RoleView.get_urls(),
    *views.ProductionTeamView.get_urls(),
    *views.ProductionImageView.get_urls(),
]
