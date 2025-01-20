from django.urls import path, include

urlpatterns = [
    path('', include('agriculture.urls')),  # Redirect root URL to the agriculture app
]
