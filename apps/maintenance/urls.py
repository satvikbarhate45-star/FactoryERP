from django.urls import path
from . import views

urlpatterns = [
    path('equipment/', views.equipment_view, name='equipment'),
    path('equipment/<int:machine_id>/history/', views.machine_history_view, name='machine_history'),
    path('work-orders/', views.work_orders_view, name='work_orders'),
    path('api/predict/', views.trigger_predictions, name='trigger_predictions'),
    path('api/work-orders/generate/', views.generate_work_orders_api, name='generate_work_orders'),
    path('api/work-orders/sync-loop/', views.closed_loop_sync_api, name='closed_loop_sync'),
]
