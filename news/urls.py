from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('page/<int:page_num>/', views.index, name='index_paginated'),
]