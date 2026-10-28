from django.urls import path
from . import views
urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.user_management_view, name='user_management'),
    path('workmanagement/', views.user_management_view, name='workmanagement'),
    path('reports/', views.reports_view, name='reports'),
    path('', views.dashboard_view, name='dashboard'),
]

