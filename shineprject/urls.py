"""
URL configuration for shineprject project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from django.urls import path, include
from django.views.i18n import set_language
from django.contrib import admin
from hours_tracker import views as hours_tracker_views

handler404 = hours_tracker_views.custom_page_not_found_view
handler500 = hours_tracker_views.custom_server_error_view
urlpatterns = [
    # path("admin/", admin.site.urls),
    path('', include('hours_tracker.urls')),
    path('set-language/', hours_tracker_views.set_language, name='set_language'),
    path('admin/', admin.site.urls),
]
