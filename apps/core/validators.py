"""Rules every money form shares, kept on the models so no form can forget them."""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _

above_zero = MinValueValidator(Decimal("0.01"), _("Enter an amount above zero."))
