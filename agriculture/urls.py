from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', views.home, name='home'),  # This maps the root URL to the home page
    path('loading-to-results/', views.home_to_loading, name='loading_to_results'),
    path('result/', views.result, name='result'),
    path('loading-to-prediction/', views.results_to_loading, name='loading_to_prediction'),
    path('prediction/', views.prediction_model, name='prediction'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)