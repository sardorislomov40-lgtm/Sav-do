from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        CASHIER = "cashier", "Sotuvchi / Kassir"
        STOREKEEPER = "storekeeper", "Omborchi"

    role = models.CharField("Rol", max_length=20, choices=Role.choices, default=Role.CASHIER)

    @property
    def is_admin_role(self) -> bool:
        return self.is_superuser or self.role == self.Role.ADMIN

    def has_role(self, *roles: str) -> bool:
        """Admin (va superuser) hamma joyga kira oladi."""
        return self.is_admin_role or self.role in roles

    @property
    def can_manage_stock(self) -> bool:
        return self.has_role(self.Role.STOREKEEPER)

    @property
    def can_edit_prices(self) -> bool:
        return self.is_admin_role or (
            self.role == self.Role.STOREKEEPER and settings.STOREKEEPER_CAN_EDIT_PRICES
        )
