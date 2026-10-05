from django.contrib import admin

# Register your models here.


from backstage.models import Contact


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email", "newsletter", "acting", "backstage", "created")
    list_filter = ("newsletter", "acting", "backstage")
    search_fields = ("first_name", "last_name", "email")
