from django.core.management.base import NoArgsCommand
from django_bitcoin.models import refill_payment_queue, update_payments


class Command(NoArgsCommand):
    help = 'Create a profile object for users which do not have one.'

    def handle_noargs(self, **options):
        refill_payment_queue()
        update_payments()

