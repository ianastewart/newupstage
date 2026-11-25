from django.contrib import admin

# Register your models here.


from backstage.models import Palette, PaletteColour


class PaletteColourInline(admin.TabularInline):
    model = PaletteColour
    extra = 0
    max_num = Palette.SIZE  # a palette has at most 8 colours
    ordering = ("position",)


@admin.register(Palette)
class PaletteAdmin(admin.ModelAdmin):
    list_display = ("name", "is_complete")
    inlines = [PaletteColourInline]
