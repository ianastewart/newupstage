from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("page/<slug:slug>/", views.webpage, name="webpage"),
    path("auditions/", views.auditions, name="auditions"),
    path("pages/", views.page_list, name="page-list"),
    path("pages/new/", views.page_create, name="page-create"),
    path("pages/<int:pk>/edit/", views.page_edit, name="page-edit"),
    path("pages/<int:page_pk>/blocks/new/", views.block_create, name="block-create"),
    path("pages/<int:page_pk>/blocks/<int:pk>/edit/", views.block_edit, name="block-edit"),
]
