"""Shared setup for business tests."""
from django.contrib.auth import get_user_model

from .access import BUSINESS, create_business
from .models import Dashboard, Membership, Role, UserDashboardAccess


def make_farm(owner_name="owner", staff_role=Role.DATA_ENTRY):
    User = get_user_model()
    owner = User.objects.create_user(owner_name, password="x")
    staff = User.objects.create_user(owner_name + "_staff", password="x")
    dash = Dashboard.objects.get(code=BUSINESS)
    for u in (owner, staff):
        UserDashboardAccess.objects.create(user=u, dashboard=dash)
    business = create_business(owner, "Farm " + owner_name)
    Membership.objects.create(business=business, user=staff, role=staff_role)
    return business, owner, staff
