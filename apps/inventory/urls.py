from django.urls import path
from . import views

urlpatterns = [
    path('', views.inventory_dashboard_view, name='inventory_dashboard'),
]
