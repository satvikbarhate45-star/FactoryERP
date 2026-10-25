import os

def create_file(path, content):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content.strip() + '\n')

def scaffold_project():
    print("Scaffolding PharmaERP Modular Project...")

    # 1. Core Project Settings
    create_file('pharma_erp/__init__.py', '')
    create_file('pharma_erp/settings.py', '''
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = 'django-insecure-dummy-key-for-scaffolding'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Modular Apps
    'apps.accounts',
    'apps.production',
    'apps.maintenance',
    'apps.inventory',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'pharma_erp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'pharma_erp.wsgi.application'
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3', # Start with sqlite for scaffolding, switch to PostgreSQL later
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'accounts.User'
''')

    create_file('pharma_erp/urls.py', '''
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.accounts.urls')),
    path('production/', include('apps.production.urls')),
    path('maintenance/', include('apps.maintenance.urls')),
    path('inventory/', include('apps.inventory.urls')),
]
''')

    create_file('manage.py', '''
#!/usr/bin/env python
import os
import sys

def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
''')

    # 2. Accounts App (Users, Roles, Auth)
    create_file('apps/accounts/__init__.py', '')
    create_file('apps/accounts/apps.py', '''
from django.apps import AppConfig
class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'
''')
    create_file('apps/accounts/models.py', '''
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _

class Shift(models.Model):
    name = models.CharField(max_length=50)
    start_time = models.TimeField()
    end_time = models.TimeField()

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'AD', _('Admin')
        PROD_MANAGER = 'PM', _('Production Manager')
        EMPLOYEE = 'EM', _('Employee')

    role = models.CharField(max_length=2, choices=Role.choices, default=Role.EMPLOYEE)
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True)
''')
    create_file('apps/accounts/views.py', '''
from django.shortcuts import render
def dashboard_view(request):
    return render(request, 'dashboard.html')
''')
    create_file('apps/accounts/urls.py', '''
from django.urls import path
from . import views
urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
]
''')

    # 3. Production App (Logs, Targets)
    create_file('apps/production/__init__.py', '')
    create_file('apps/production/apps.py', '''
from django.apps import AppConfig
class ProductionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.production'
''')
    create_file('apps/production/models.py', '''
from django.db import models
from apps.accounts.models import User

class ProductionLog(models.Model):
    date = models.DateField()
    employee = models.ForeignKey(User, on_delete=models.CASCADE)
    output_kg = models.DecimalField(max_digits=10, decimal_places=2)
''')
    create_file('apps/production/urls.py', 'from django.urls import path\nurlpatterns = []')

    # 4. Maintenance App (Machines, Tickets)
    create_file('apps/maintenance/__init__.py', '')
    create_file('apps/maintenance/apps.py', '''
from django.apps import AppConfig
class MaintenanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.maintenance'
''')
    create_file('apps/maintenance/models.py', '''
from django.db import models

class Machine(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default='Operational')
''')
    create_file('apps/maintenance/urls.py', 'from django.urls import path\nurlpatterns = []')

    # 5. Inventory App (Warehouse)
    create_file('apps/inventory/__init__.py', '')
    create_file('apps/inventory/apps.py', '''
from django.apps import AppConfig
class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.inventory'
''')
    create_file('apps/inventory/models.py', '''
from django.db import models

class WarehouseStock(models.Model):
    material = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
''')
    create_file('apps/inventory/urls.py', 'from django.urls import path\nurlpatterns = []')


    # 6. Frontend Templates (UI/UX)
    create_file('templates/base.html', '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PharmaERP</title>
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background-color: #f8fafc; }
        .sidebar { background-color: #0f4c81; color: white; }
    </style>
</head>
<body class="flex h-screen overflow-hidden">
    <!-- Sidebar -->
    <aside class="sidebar w-64 flex flex-col hidden md:flex">
        <div class="h-16 flex items-center px-6 font-bold text-xl border-b border-blue-800">
            PHARMACORE ERP
        </div>
        <nav class="flex-1 px-4 py-6 space-y-2">
            <a href="#" class="block px-4 py-2 bg-blue-800 rounded-md">Dashboard</a>
            <a href="#" class="block px-4 py-2 hover:bg-blue-800 rounded-md">Equipment</a>
            <a href="#" class="block px-4 py-2 hover:bg-blue-800 rounded-md">Work Orders</a>
            <a href="#" class="block px-4 py-2 hover:bg-blue-800 rounded-md">Inventory</a>
        </nav>
    </aside>

    <!-- Main Content -->
    <div class="flex-1 flex flex-col overflow-y-auto">
        <header class="h-16 bg-white shadow-sm flex items-center justify-between px-6">
            <div class="text-gray-500">Search...</div>
            <div class="flex items-center space-x-4">
                <div class="w-8 h-8 bg-gray-200 rounded-full"></div>
                <span class="font-medium text-gray-700">J. Smith</span>
            </div>
        </header>
        <main class="p-6">
            {% block content %}{% endblock %}
        </main>
    </div>
</body>
</html>
''')

    create_file('templates/dashboard.html', '''
{% extends 'base.html' %}

{% block content %}
<div class="mb-6">
    <h1 class="text-2xl font-bold text-gray-800">Factory Dashboard</h1>
    <p class="text-gray-500">Real-time metrics and alerts</p>
</div>

<!-- Status Cards -->
<div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-6">
    <!-- Operational -->
    <div class="bg-white p-6 rounded-lg shadow-sm border-t-4 border-emerald-500">
        <div class="flex items-center justify-between">
            <h3 class="text-emerald-500 font-bold uppercase text-sm">Operational</h3>
            <span class="bg-emerald-100 text-emerald-800 text-xs px-2 py-1 rounded">Vibrant Green</span>
        </div>
        <div class="mt-4 flex justify-between items-end">
            <div>
                <div class="text-3xl font-bold text-gray-800">94.2%</div>
                <div class="text-sm text-gray-500">Uptime</div>
            </div>
            <div>
                <div class="text-3xl font-bold text-gray-800">31</div>
                <div class="text-sm text-gray-500">Units</div>
            </div>
        </div>
    </div>

    <!-- Pending -->
    <div class="bg-white p-6 rounded-lg shadow-sm border-t-4 border-amber-500">
        <div class="flex items-center justify-between">
            <h3 class="text-amber-500 font-bold uppercase text-sm">Pending</h3>
        </div>
        <div class="mt-4 flex justify-between items-end">
            <div>
                <div class="text-3xl font-bold text-gray-800">12</div>
                <div class="text-sm text-gray-500">Issues</div>
            </div>
        </div>
    </div>

    <!-- Maintenance -->
    <div class="bg-white p-6 rounded-lg shadow-sm border-t-4 border-rose-500">
        <div class="flex items-center justify-between">
            <h3 class="text-rose-500 font-bold uppercase text-sm">Under Maintenance</h3>
        </div>
        <div class="mt-4 flex justify-between items-end">
            <div>
                <div class="text-3xl font-bold text-gray-800">07</div>
                <div class="text-sm text-gray-500">Assets</div>
            </div>
        </div>
    </div>
</div>

<!-- Data Table Concept -->
<div class="bg-white rounded-lg shadow-sm overflow-hidden">
    <div class="px-6 py-4 border-b border-gray-100 flex justify-between items-center">
        <h3 class="font-bold text-gray-800">Machine Metrics & Status</h3>
    </div>
    <div class="overflow-x-auto">
        <table class="w-full text-left border-collapse">
            <thead>
                <tr class="bg-gray-50 text-gray-500 text-sm">
                    <th class="px-6 py-3 border-b">ID</th>
                    <th class="px-6 py-3 border-b">Equipment Name</th>
                    <th class="px-6 py-3 border-b">Status</th>
                    <th class="px-6 py-3 border-b">Next Service</th>
                </tr>
            </thead>
            <tbody class="text-sm text-gray-700">
                <tr>
                    <td class="px-6 py-4 border-b">PH-R4</td>
                    <td class="px-6 py-4 border-b font-medium">Bioreactor-A</td>
                    <td class="px-6 py-4 border-b"><span class="bg-emerald-100 text-emerald-800 px-2 py-1 rounded-full text-xs font-medium">Operational</span></td>
                    <td class="px-6 py-4 border-b">2023-11-15</td>
                </tr>
                <tr>
                    <td class="px-6 py-4 border-b">PH-P7</td>
                    <td class="px-6 py-4 border-b font-medium">Packaging-C</td>
                    <td class="px-6 py-4 border-b"><span class="bg-rose-100 text-rose-800 px-2 py-1 rounded-full text-xs font-medium">Under Maintenance</span></td>
                    <td class="px-6 py-4 border-b">2023-10-02</td>
                </tr>
            </tbody>
        </table>
    </div>
</div>
{% endblock %}
''')

    print("Scaffolding complete. Run 'python manage.py runserver' to view.")

if __name__ == '__main__':
    scaffold_project()
