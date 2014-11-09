from django.core.management.base import NoArgsCommand
from django_bitcoin.models import Wallet


class Command(NoArgsCommand):
    help = """fix balances
    """

    def handle_noargs(self, **options):
        print "starting..."
        for w in Wallet.objects.all():
            w.last_balance = w.total_balance()
            w.save()
