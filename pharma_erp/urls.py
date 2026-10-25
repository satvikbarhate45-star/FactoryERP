from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.accounts.urls')),
    path('production/', include('apps.production.urls')),
    path('supervisor/', include([
        path('', include('apps.production.urls')),
    ])),
    path('maintenance/', include('apps.maintenance.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('ai/', include('apps.ai_chat.urls')),
]
