from django.urls import path
from . import views
urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.user_management_view, name='user_management'),
    path('workmanagement/', views.user_management_view, name='workmanagement'),
    path('users/<int:user_id>/profile/', views.employee_profile_view, name='employee_profile'),
    path('users/<int:user_id>/salary-slip/<int:payroll_id>/pdf/', views.download_salary_slip_pdf, name='download_salary_slip_pdf'),
    path('users/<int:user_id>/salary-slip/latest/pdf/', views.download_salary_slip_pdf, name='download_latest_salary_slip_pdf'),
    path('reports/', views.reports_view, name='reports'),
    path('pl/', views.pl_dashboard_view, name='pl_dashboard'),
    path('', views.dashboard_view, name='dashboard'),
]

