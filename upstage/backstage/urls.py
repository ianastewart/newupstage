from django.urls import path

from backstage import views

urlpatterns = [
    path("actors/", views.actor_list, name="actor-list"),
    path("writers/", views.writer_list, name="writer-list"),
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
    *views.CastView.get_urls(),
    *views.RoleView.get_urls(),
    *views.ProductionTeamView.get_urls(),
    *views.ProductionImageView.get_urls(),
]
