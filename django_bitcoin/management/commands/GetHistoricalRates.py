from django.core.management.base import NoArgsCommand
import datetime
from django_bitcoin.models import get_historical_price

import pytz  # 3rd party


class Command(NoArgsCommand):
    help = 'Create a profile object for users which do not have one.'

    def handle_noargs(self, **options):
        u = datetime.datetime.utcnow()
        u = u.replace(tzinfo=pytz.utc)
        print u, get_historical_price()

