from django.urls import path
from . import views

urlpatterns = [
    path('', views.admin_production_view, name='production_dashboard'),
    path('manager/', views.production_manager_view, name='production_manager_dashboard'),
    path('supervisor_erp/', views.supervisor_dashboard_view, name='supervisor_portal'),
    path('supervisor/', views.supervisor_dashboard_view, name='supervisor_portal_alias'),
    path('supervisor_erp/employees/', views.supervisor_employee_overview, name='supervisor_employee_overview'),
    path('supervisor_erp/tasks/', views.supervisor_daily_tasks, name='supervisor_daily_tasks'),
    path('supervisor_erp/approvals/', views.supervisor_floor_approvals, name='supervisor_floor_approvals'),
    path('manager/employees/', views.employee_monitoring_view, name='employee_monitoring'),
    path('manager/targets/', views.manager_targets_view, name='manager_targets'),
    path('manager/exports/', views.manager_exports_view, name='manager_exports'),
    path('manager/imports/', views.manager_imports_view, name='manager_imports'),
]
