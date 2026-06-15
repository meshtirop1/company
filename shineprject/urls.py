from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from hours_tracker import views as hours_tracker_views

# Custom error handlers
handler404 = hours_tracker_views.custom_page_not_found_view
handler500 = hours_tracker_views.custom_server_error_view
handler403 = hours_tracker_views.custom_permission_denied_view

urlpatterns = [
    path('', include('hours_tracker.urls')),
    path('set-language/', hours_tracker_views.set_language, name='set_language'),
    path('private/', admin.site.urls),

]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
