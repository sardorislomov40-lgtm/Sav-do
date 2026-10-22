from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import User

ADMIN = User.Role.ADMIN
CASHIER = User.Role.CASHIER
STOREKEEPER = User.Role.STOREKEEPER


def role_required(*roles):
    """Tizimga kirgan va roli ruxsat etilganlar ro'yxatida (yoki Admin) bo'lgan foydalanuvchi."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.has_role(*roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return login_required(wrapped)

    return decorator


# Tayyor to'plamlar
any_role = role_required(CASHIER, STOREKEEPER)  # Admin avtomatik kiradi
stock_staff = role_required(STOREKEEPER)  # Omborchi + Admin
admin_only = role_required()  # faqat Admin
