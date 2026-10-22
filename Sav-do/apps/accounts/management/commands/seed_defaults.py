from django.core.management.base import BaseCommand

from apps.catalog.models import Unit
from apps.inventory.models import Warehouse

UNITS = [
    # nomi, qisqa, kasr qabul qiladimi
    ("Dona", "dona", False),
    ("Kilogramm", "kg", True),
    ("Gramm", "g", True),
    ("Litr", "l", True),
    ("Metr", "m", True),
    ("Quti", "quti", False),
    ("Pachka", "pachka", False),
    ("Qop", "qop", False),
    ("Juft", "juft", False),
    ("Komplekt", "kmpl", False),
    ("Rulon", "rulon", False),
]


class Command(BaseCommand):
    help = "Boshlang'ich o'lchov birliklari va asosiy omborni yaratadi (qayta ishga tushirsa ham xavfsiz)."

    def handle(self, *args, **options):
        created = 0
        for name, short, fraction in UNITS:
            _, was_created = Unit.objects.get_or_create(
                name=name, defaults={"short_name": short, "allows_fraction": fraction}
            )
            created += was_created
        if not Warehouse.objects.exists():
            Warehouse.objects.create(name="Asosiy ombor", is_default=True)
            self.stdout.write("Asosiy ombor yaratildi.")
        self.stdout.write(self.style.SUCCESS(f"Tayyor. Yangi birliklar: {created}."))
