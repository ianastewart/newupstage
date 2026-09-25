from neapolitan.views import CRUDView
from backstage.models import Production

class ProductionView(CRUDView):
    model = Production
    fields = ["title", "description"]


from django.shortcuts import render

# Create your views here.
