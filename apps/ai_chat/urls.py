from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_interface, name='chat_interface'),
    path('api/', views.api_chat, name='api_chat'),
    path('api/tts/', views.api_tts, name='api_tts'),
]
