from django.urls import path

from . import views, views_lookups, views_payments

urlpatterns = [
    path('health/', views.health, name='health'),
    path('', views.home, name='home'),
    path('display-currency/', views.set_display_currency, name='set_display_currency'),

    path('years/add/', views.year_add, name='year_add'),
    path('years/<int:year>/', views.year_detail, name='year_detail'),
    path('years/<int:year>/notes/', views.year_notes, name='year_notes'),
    path('years/<int:year>/delete/', views.year_delete, name='year_delete'),
    path('years/<int:year>/months/<int:month>/add/', views.month_add, name='month_add'),
    path('years/<int:year>/months/<int:month>/', views.month_detail, name='month_detail'),
    path('years/<int:year>/months/<int:month>/delete/', views.month_delete, name='month_delete'),
    path('years/<int:year>/months/<int:month>/payments/new/', views_payments.payment_add, name='payment_add'),

    path('payments/<int:pk>/', views_payments.payment_detail, name='payment_detail'),
    path('payments/<int:pk>/edit/', views_payments.payment_edit, name='payment_edit'),
    path('payments/<int:pk>/delete/', views_payments.payment_delete, name='payment_delete'),
    path('payments/<int:pk>/recalculate/', views_payments.payment_recalculate, name='payment_recalculate'),

    path('organisations/', views_lookups.lookup_list, {'kind': 'organisation'}, name='organisation_list'),
    path('organisations/new/', views_lookups.lookup_edit, {'kind': 'organisation'}, name='organisation_add'),
    path('organisations/<int:pk>/edit/', views_lookups.lookup_edit, {'kind': 'organisation'}, name='organisation_edit'),
    path('organisations/<int:pk>/delete/', views_lookups.lookup_delete, {'kind': 'organisation'}, name='organisation_delete'),
    path('categories/', views_lookups.lookup_list, {'kind': 'category'}, name='category_list'),
    path('categories/new/', views_lookups.lookup_edit, {'kind': 'category'}, name='category_add'),
    path('categories/<int:pk>/edit/', views_lookups.lookup_edit, {'kind': 'category'}, name='category_edit'),
    path('categories/<int:pk>/delete/', views_lookups.lookup_delete, {'kind': 'category'}, name='category_delete'),
]
