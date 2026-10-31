from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

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

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += staticfiles_urlpatterns()
