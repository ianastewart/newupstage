from django.contrib import admin

from .forms import BlockForm
from .models import Block, BlockColumn, PageBlock, WebPage


class PageBlockInline(admin.TabularInline):
    model = PageBlock
    extra = 1
    autocomplete_fields = ["block"]
    ordering = ["position", "id"]


@admin.register(WebPage)
class WebPageAdmin(admin.ModelAdmin):
    list_display = ["title", "slug"]
    prepopulated_fields = {"slug": ["title"]}
    search_fields = ["title"]
    inlines = [PageBlockInline]


class BlockColumnInline(admin.StackedInline):
    model = BlockColumn
    extra = 0
    max_num = Block.MAX_COLUMNS
    ordering = ["position", "id"]


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    form = BlockForm
    inlines = [BlockColumnInline]
    list_display = ["name", "block_type", "layout", "image_size"]
    list_filter = ["block_type"]
    search_fields = ["name"]
