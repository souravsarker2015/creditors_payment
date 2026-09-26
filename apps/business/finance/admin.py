from django.contrib import admin

from .models import Account, Category

admin.site.register(Category)
admin.site.register(Account)
