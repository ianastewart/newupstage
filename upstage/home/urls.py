from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("page/<slug:slug>/", views.webpage, name="webpage"),
    path("auditions/", views.auditions, name="auditions"),
    path("auditions/<int:pk>/", views.audition_detail, name="audition-detail"),
    path("productions/<int:pk>/", views.public_production, name="public-production"),
    path("events/<int:pk>/", views.event_detail, name="public-event"),
    path("radio-archive/", views.radio_archive, name="radio-archive"),
    path("radio-archive/<int:pk>/", views.radio_play, name="radio-play"),
    path("actors/", views.actor_list, name="public-actors"),
    path("actors/<int:pk>/", views.actor_detail, name="public-actor"),
    path("team/<int:pk>/", views.team_member_detail, name="public-team-member"),
    path("pages/", views.page_list, name="page-list"),
    path("pages/new/", views.page_create, name="page-create"),
    path("pages/<int:pk>/copy/", views.page_copy, name="page-copy"),
    path("pages/<int:pk>/replace-original/", views.page_replace_original, name="page-replace-original"),
    path("pages/<int:pk>/edit/", views.page_edit, name="page-edit"),
    path("pages/<int:page_pk>/blocks/new/", views.block_create, name="block-create"),
    path("pages/<int:page_pk>/blocks/<int:pk>/edit/", views.block_edit, name="block-edit"),
]
