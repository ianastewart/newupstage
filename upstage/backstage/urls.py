from backstage import views

urlpatterns = [
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
