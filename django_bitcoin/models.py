from __future__ import with_statement

from django.core.cache import cache
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _

from django.core import urlresolvers
from django.db import transaction as db_transaction
from django.db import models
from django.utils import importlib, timezone

from decimal import Decimal

from . import settings

from .fields.utils import is_valid_btc_address
from .bitcoind import bitcoind
from .locking import CacheLock

from . import currency
from . import utils
from . import tasks

import django.dispatch

import datetime


# initialize the conversion module

for dottedpath in settings.BITCOIN_CURRENCIES:
    mod, func = urlresolvers.get_mod_func(dottedpath)
    klass = getattr(importlib.import_module(mod), func)
    currency.exchange.register_currency(klass())

balance_changed = django.dispatch.Signal(providing_args=["changed", "transaction", "bitcoinaddress"])
balance_changed_confirmed = django.dispatch.Signal(providing_args=["changed", "transaction", "bitcoinaddress"])


class Transaction(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    amount = models.DecimalField(
        max_digits=16,
        decimal_places=8,
        default=Decimal("0.0"))
    address = models.CharField(max_length=50)


class DepositTransaction(models.Model):

    created_at = models.DateTimeField(auto_now_add=True)
    address = models.ForeignKey('BitcoinAddress')

    amount = models.DecimalField(max_digits=16, decimal_places=8, default=Decimal(0))
    description = models.CharField(max_length=100, blank=True, null=True, default=None)

    wallet = models.ForeignKey("Wallet")

    under_execution = models.BooleanField(default=False)  # execution fail
    transaction = models.ForeignKey('WalletTransaction', null=True, default=None)

    confirmations = models.IntegerField(default=0)
    txid = models.CharField(max_length=100, blank=True, null=True)

    def __unicode__(self):
        return self.address.address + u", " + unicode(self.amount)


class OutgoingTransaction(models.Model):

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, default=None)
    under_execution = models.BooleanField(default=False)  # execution fail
    to_bitcoinaddress = models.CharField(
        max_length=50,
        blank=True)
    amount = models.DecimalField(
        max_digits=16,
        decimal_places=8,
        default=Decimal("0.0"))
    # description = models.CharField(max_length=100, blank=True)

    txid = models.CharField(max_length=100, blank=True, null=True, default=None)

    def __unicode__(self):
        return unicode(self.created_at) + ": " + self.to_bitcoinaddress + u", " + unicode(self.amount)


class BitcoinAddress(models.Model):
    address = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=False)
    least_received = models.DecimalField(max_digits=16, decimal_places=8, default=Decimal(0))
    least_received_confirmed = models.DecimalField(max_digits=16, decimal_places=8, default=Decimal(0))
    label = models.CharField(max_length=50, blank=True, null=True, default=None)

    wallet = models.ForeignKey("Wallet", null=True, related_name="addresses")

    migrated_to_transactions = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Bitcoin addresses'

    def query_bitcoin_deposit(self, deposit_tx):
        if deposit_tx.transaction:
            print "Already has a transaction!"
            return
        with CacheLock('query_bitcoind'):
            r = bitcoind.total_received(self.address, minconf=settings.BITCOIN_MINIMUM_CONFIRMATIONS)
            received_amount = r - self.least_received_confirmed

            if received_amount >= deposit_tx.amount and not deposit_tx.under_execution:
                if settings.BITCOIN_TRANSACTION_SIGNALING:
                    if self.wallet:
                        balance_changed_confirmed.send(sender=self.wallet,
                                                       changed=(deposit_tx.amount), bitcoinaddress=self)

                updated = BitcoinAddress.objects.select_for_update().filter(id=self.id,
                                                                            least_received_confirmed=self.least_received_confirmed).update(
                    least_received_confirmed=self.least_received_confirmed + deposit_tx.amount)

                if self.wallet and updated:
                    DepositTransaction.objects.select_for_update().filter(id=deposit_tx.id).update(under_execution=True)
                    deposit_tx.under_execution = True
                    self.least_received_confirmed = self.least_received_confirmed + deposit_tx.amount
                    if self.least_received < self.least_received_confirmed:
                        updated = BitcoinAddress.objects.select_for_update().filter(id=self.id).update(
                            least_received=self.least_received_confirmed)
                    if self.migrated_to_transactions:
                        wt = WalletTransaction.objects.create(to_wallet=self.wallet, amount=deposit_tx.amount, description=self.address,
                                                              deposit_address=self)
                        deposit_tx.transaction = wt
                        DepositTransaction.objects.select_for_update().filter(id=deposit_tx.id).update(transaction=wt)
                    self.wallet.update_last_balance(deposit_tx.amount)
                else:
                    print "transaction not updated!"
            else:
                print "This path should not occur, but whatever."
                # raise Exception("Should be never this way")
            return r

    def query_unconfirmed_deposits(self):
        r = bitcoind.total_received(self.address, minconf=0)
        if r > self.least_received:
            transaction_amount = r - self.least_received
            if settings.BITCOIN_TRANSACTION_SIGNALING:
                if self.wallet:
                    balance_changed.send(sender=self.wallet, changed=(transaction_amount), bitcoinaddress=self)
            updated = BitcoinAddress.objects.select_for_update().filter(id=self.id, least_received=self.least_received).update(least_received=r)
            if updated:
                self.least_received = r

    def received(self, minconf=settings.BITCOIN_MINIMUM_CONFIRMATIONS):
        if settings.BITCOIN_TRANSACTION_SIGNALING:
            if minconf >= settings.BITCOIN_MINIMUM_CONFIRMATIONS:
                return self.least_received_confirmed
            else:
                return self.least_received
        return self.query_bitcoind(minconf)

    def __unicode__(self):
        if self.label:
            return u'%s (%s)' % (self.label, self.address)
        return self.address


def new_bitcoin_address():
    while True:
        db_transaction.enter_transaction_management()
        db_transaction.commit()
        bp = BitcoinAddress.objects.filter(Q(active=False) & Q(wallet__isnull=True) &
                                           Q(least_received__lte=0))
        if len(bp) < 1:
            refill_payment_queue()
            db_transaction.commit()
            print "refilling queue...", bp
        else:
            bp = bp[0]
            updated = BitcoinAddress.objects.select_for_update().filter(Q(id=bp.id) & Q(active=False) & Q(wallet__isnull=True) &
                                                                        Q(least_received__lte=0)).update(active=True)
            db_transaction.commit()
            if updated:
                print 'returning bp', bp
                return bp
            else:
                print "wallet transaction concurrency:", bp.address


class Payment(models.Model):
    description = models.CharField(
        max_length=255,
        blank=True)
    address = models.CharField(
        max_length=50)
    amount = models.DecimalField(
        max_digits=16,
        decimal_places=8,
        default=Decimal("0.0"))
    amount_paid = models.DecimalField(
        max_digits=16,
        decimal_places=8,
        default=Decimal("0.0"))
    active = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField()

    paid_at = models.DateTimeField(null=True, default=None)

    withdrawn_total = models.DecimalField(
        max_digits=16,
        decimal_places=8,
        default=Decimal("0.0"))

    transactions = models.ManyToManyField(Transaction)

    def calculate_amount(self, proportion):
        return utils.quantitize_bitcoin(
            Decimal((proportion / Decimal("100.0")) * self.amount))

    def add_transaction(self, amount, address):
        self.withdrawn_total += amount
        bctrans = self.transactions.create(
            amount=amount,
            address=address)
        self.save()

        return bctrans

    def withdraw_proportion(self, address, proportion):
        if proportion <= Decimal("0") or proportion > Decimal("100"):
            raise Exception("Illegal proportion.")

        amount = self.calculate_amount(proportion)

        if self.amount - self.withdrawn_total > amount:
            raise Exception("Trying to withdraw too much.")

        self.add_transaction(amount, address)
        bitcoind.send(address, amount)

    @classmethod
    def withdraw_proportion_all(cls, address, bitcoin_payments_proportions):
        """hash BitcoinPayment -> Proportion"""
        final_amount = Decimal("0.0")
        print bitcoin_payments_proportions
        for bp, proportion in bitcoin_payments_proportions.iteritems():
            am = bp.calculate_amount(proportion)
            final_amount += am
            bp.add_transaction(am, address)
        bitcoind.send(address, final_amount)
        return True

    def withdraw_amounts(self, addresses_shares):
        """hash address -> percentage (string -> Decimal)"""
        if self.amount_paid < self.amount:
            raise Exception("Not paid.")
        if self.withdrawn_at:
            raise Exception("Trying to withdraw again.")
        if sum(addresses_shares.values()) > 100:
            raise Exception("Sum of proportions must be <=100.")
        # self.withdraw_addresses=",".join(addresses)
        #self.withdraw_proportions=",".join([str(x) for x in proportions])
        amounts = []
        for p in addresses_shares.values():
            if p <= 0:
                raise Exception()
            am = utils.quantitize_bitcoin(Decimal((p / Decimal("100.0")) * self.amount))
            amounts.append(am)
        # self.withdraw_proportions=",".join([str(x) for x in ])
        if sum(amounts) > self.amount:
            raise Exception("Sum of calculated amounts exceeds funds.")
        return amounts

    @classmethod
    def calculate_amounts(cls, bitcoinpayments, addresses_shares):
        amounts_all = [Decimal("0.0") for _i in addresses_shares]
        for amount, payment in zip(amounts_all, bitcoinpayments):
            withdrawn = payment.withdraw_amounts(addresses_shares)
            amounts_all = [(w + total) for w, total in zip(withdrawn, amounts_all)]
        return amounts_all

    @classmethod
    def withdraw_all(cls, bitcoinpayments, addresses_shares):
        # if len(bitcoinpayments)!=len(addresses_shares):
        #    raise Exception("")
        amounts_all = Payment.calculate_amounts(bitcoinpayments, addresses_shares)
        for bp in bitcoinpayments:
            am = bp.withdraw_amounts(addresses_shares)
            bp.withdraw_addresses = ",".join(addresses_shares.keys())
            bp.withdraw_proportions = ",".join(
                [str(x) for x in addresses_shares.values()])
            bp.withdraw_amounts = ",".join(
                [str(x) for x in am])
            bp.withdrawn_at = timezone.now()
            bp.withdrawn_total = sum(am)
            bp.save()
        for i, share in enumerate(addresses_shares.keys()):
            bitcoind.send(share, amounts_all[i])
        return True

    def is_paid(self, minconf=1):
        if self.paid_at:
            return True
        self.update_payment(minconf=minconf)
        return self.amount_paid >= self.amount

    def getbalance(self, minconf=1):
        return bitcoind.total_received(self.address, minconf=minconf)

    def update_payment(self, minconf=1):
        new_amount = Decimal(bitcoind.total_received(self.address, minconf=minconf))
        print "blaa", new_amount, self.address
        if new_amount >= self.amount:
            self.amount_paid = new_amount
            self.paid_at = timezone.now()
            self.save()
        # elif (timezone.now()-self.updated_at)>datetime.timedelta(hours=PAYMENT_VALID_HOURS):
        #    self.deactivate()

    def deactivate(self):
        return False
        if self.amount_paid > Decimal("0"):
            return False
        self.active = False
        self.description = ""
        self.save()
        return True

    def save(self, **kwargs):
        self.updated_at = timezone.now()
        return super(Payment, self).save(**kwargs)

    def __unicode__(self):
        return unicode(self.amount_paid)

    @models.permalink
    def get_absolute_url(self):
        return ('view_or_url_name',)


class WalletTransaction(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    from_wallet = models.ForeignKey(
        'Wallet',
        null=True,
        related_name="sent_transactions")
    to_wallet = models.ForeignKey(
        'Wallet',
        null=True,
        related_name="received_transactions")
    to_bitcoinaddress = models.CharField(
        max_length=50,
        blank=True)
    outgoing_transaction = models.ForeignKey('OutgoingTransaction', null=True, default=None)
    amount = models.DecimalField(
        max_digits=16,
        decimal_places=8,
        default=Decimal("0.0"))
    description = models.CharField(max_length=100, blank=True)

    deposit_address = models.ForeignKey(BitcoinAddress, null=True)
    txid = models.CharField(max_length=100, blank=True, null=True)
    deposit_transaction = models.OneToOneField(DepositTransaction, null=True)

    def __unicode__(self):
        if self.from_wallet and self.to_wallet:
            return u"Wallet transaction " + unicode(self.amount)
        elif self.from_wallet and self.to_bitcoinaddress:
            return u"Outgoing bitcoin transaction " + unicode(self.amount)
        elif self.to_wallet and not self.from_wallet:
            return u"Deposit " + unicode(self.amount)
        return u"Fee " + unicode(self.amount)

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.from_wallet and not self.to_wallet:
            raise ValidationError('Wallet transaction error - define a wallet.')

    def confirmation_status(self,
                            minconf=settings.BITCOIN_MINIMUM_CONFIRMATIONS,
                            transactions=None):
        """
        Returns the confirmed and unconfirmed parts of this transfer.
        Also accepts and returns a list of transactions that are being
        currently used.

        The sum of the two amounts is the total transaction amount.
        """

        if not transactions:
            transactions = {}

        if minconf == 0 or self.to_bitcoinaddress:
            return (0, self.amount, transactions)

        _, confirmed, txs = self.from_wallet.balance(minconf=minconf,
                                                     timeframe=self.created_at,
                                                     transactions=transactions)
        transactions.update(txs)

        if confirmed > self.amount:
            confirmed = self.amount
        unconfirmed = self.amount - confirmed

        return (unconfirmed, confirmed, transactions)


class Wallet(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    label = models.CharField(max_length=50, blank=True)
    # DEPRECATED: changed to foreign key
    # addresses = models.ManyToManyField(BitcoinAddress, through="WalletBitcoinAddress")
    transactions_with = models.ManyToManyField(
        'self',
        through=WalletTransaction,
        symmetrical=False)

    transaction_counter = models.IntegerField(default=1)
    last_balance = models.DecimalField(default=Decimal(0), max_digits=16, decimal_places=8)

    # track_transaction_value = models.BooleanField(default=False)

    # tries to update instantly, if not succesful updates using sql query (celery task)
    def update_last_balance(self, amount):
        if self.__class__.objects.filter(id=self.id, last_balance=self.last_balance
                                         ).update(last_balance=(self.last_balance + amount)) < 1:
            tasks.update_wallet_balance.apply_async((self.id,), countdown=1)

    def __unicode__(self):
        return u"%s: %s" % (self.label,
                            self.created_at.strftime('%Y-%m-%d %H:%M'))

    def receiving_address(self, fresh_addr=True):
        while True:
            usable_addresses = self.addresses.filter(active=True).order_by("id")
            if fresh_addr:
                usable_addresses = usable_addresses.filter(least_received=Decimal(0))
            if usable_addresses.count():
                return usable_addresses[0].address
            addr = new_bitcoin_address()
            updated = BitcoinAddress.objects.select_for_update().filter(Q(id=addr.id) & Q(active=True) & Q(least_received__lte=0) & Q(wallet__isnull=True))\
                .update(active=True, wallet=self)
            print "addr_id", addr.id, updated
            db_transaction.commit()
            if updated:
                return addr.address
            else:
                raise Exception("Concurrency error!")

    def static_receiving_address(self):
        ''' Returns a static receiving address for this Wallet object.'''
        return self.receiving_address(fresh_addr=False)

    def send_to_wallet(self, otherWallet, amount, description=''):

        if not isinstance(amount, Decimal):
            amount = Decimal(amount)
        amount = amount.quantize(Decimal('0.00000001'))

        with db_transaction.autocommit():
            db_transaction.enter_transaction_management()
            db_transaction.commit()
            if settings.BITCOIN_UNCONFIRMED_TRANSFERS:
                avail = self.total_balance_unconfirmed()
            else:
                avail = self.total_balance()
            updated = Wallet.objects.filter(Q(id=self.id)).update(last_balance=avail)

            if self == otherWallet:
                raise Exception(_("Can't send to self-wallet"))
            if not otherWallet.id or not self.id:
                raise Exception(_("Some of the wallets not saved"))
            if amount <= 0:
                raise Exception(_("Can't send zero or negative amounts"))
            if amount > avail:
                raise Exception(_("Trying to send too much"))
            # concurrency check
            new_balance = avail - amount
            updated = Wallet.objects.filter(Q(id=self.id) & Q(transaction_counter=self.transaction_counter) &
                                            Q(last_balance=avail))\
                .update(last_balance=new_balance, transaction_counter=self.transaction_counter + 1)
            if not updated:
                print "wallet transaction concurrency:", new_balance, avail, self.transaction_counter, self.last_balance, self.total_balance()
                raise Exception(_("Concurrency error with transactions. Please try again."))
            # db_transaction.commit()
            # concurrency check end
            transaction = WalletTransaction.objects.create(
                amount=amount,
                from_wallet=self,
                to_wallet=otherWallet,
                description=description)
            # db_transaction.commit()
            self.transaction_counter = self.transaction_counter + 1
            self.last_balance = new_balance
            # updated = Wallet.objects.filter(Q(id=otherWallet.id))\
            #   .update(last_balance=otherWallet.total_balance_sql())
            otherWallet.update_last_balance(amount)

            if settings.BITCOIN_TRANSACTION_SIGNALING:
                balance_changed.send(sender=self,
                                     changed=(Decimal(-1) * amount), transaction=transaction)
                balance_changed.send(sender=otherWallet,
                                     changed=(amount), transaction=transaction)
                balance_changed_confirmed.send(sender=self,
                                               changed=(Decimal(-1) * amount), transaction=transaction)
                balance_changed_confirmed.send(sender=otherWallet,
                                               changed=(amount), transaction=transaction)
            return transaction

    def send_to_address(self, address, amount, description='', expires_seconds=settings.BITCOIN_OUTGOING_DEFAULT_DELAY_SECONDS):
        if settings.BITCOIN_DISABLE_OUTGOING:
            raise Exception("Outgoing transactions disabled! contact support.")
        address = address.strip()

        if not isinstance(amount, Decimal):
            amount = Decimal(amount)
        amount = amount.quantize(Decimal('0.00000001'))

        if not is_valid_btc_address(str(address)):
            raise Exception(_("Not a valid bitcoin address") + ":" + address)
        if amount <= 0:
            raise Exception(_("Can't send zero or negative amounts"))
        # concurrency check
        with db_transaction.autocommit():
            db_transaction.enter_transaction_management()
            db_transaction.commit()
            avail = self.total_balance()
            updated = Wallet.objects.filter(Q(id=self.id)).update(last_balance=avail)
            if amount > avail:
                raise Exception(_("Trying to send too much"))
            new_balance = avail - amount
            updated = Wallet.objects.filter(Q(id=self.id) & Q(transaction_counter=self.transaction_counter) &
                                            Q(last_balance=avail))\
                .update(last_balance=new_balance, transaction_counter=self.transaction_counter + 1)
            if not updated:
                print "address transaction concurrency:", new_balance, avail, self.transaction_counter, self.last_balance, self.total_balance()
                raise Exception(_("Concurrency error with transactions. Please try again."))
            # concurrency check end
            outgoing_transaction = OutgoingTransaction.objects.create(amount=amount, to_bitcoinaddress=address,
                                                                      expires_at=timezone.now() + datetime.timedelta(seconds=expires_seconds))
            bwt = WalletTransaction.objects.create(
                amount=amount,
                from_wallet=self,
                to_bitcoinaddress=address,
                outgoing_transaction=outgoing_transaction,
                description=description)
            tasks.process_outgoing_transactions.apply_async((), countdown=(expires_seconds + 1))
            # try:
            #     result = bitcoind.send(address, amount)
            # except jsonrpc.JSONRPCException:
            #     bwt.delete()
            #     updated2 = Wallet.objects.filter(Q(id=self.id) & Q(last_balance=new_balance)).update(last_balance=avail)
            #     raise
            self.transaction_counter = self.transaction_counter + 1
            self.last_balance = new_balance

            # check if a transaction fee exists, and deduct it from the wallet
            # TODO: because fee can't be known beforehand, can result in negative wallet balance.
            # currently isn't much of a issue, but might be in the future, depending of the application
            # transaction = bitcoind.gettransaction(result)
            # fee_transaction = None
            # total_amount = amount
            # if Decimal(transaction['fee']) < Decimal(0):
            #     fee_transaction = WalletTransaction.objects.create(
            #         amount=Decimal(transaction['fee']) * Decimal(-1),
            #         from_wallet=self)
            #     total_amount += fee_transaction.amount
            #     updated = Wallet.objects.filter(Q(id=self.id))\
            #         .update(last_balance=new_balance-fee_transaction.amount)
            if settings.BITCOIN_TRANSACTION_SIGNALING:
                balance_changed.send(sender=self,
                                     changed=(Decimal(-1) * amount), transaction=bwt)
                balance_changed_confirmed.send(sender=self,
                                               changed=(Decimal(-1) * amount), transaction=bwt)
            return (bwt, None)

    def update_transaction_cache(self,
                                 mincf=settings.BITCOIN_MINIMUM_CONFIRMATIONS):
        """
        Finds the timestamp from the oldest transaction found with wasn't yet
        confirmed. If none, returns the current timestamp.
        """
        if mincf == 0:
            return timezone.now()

        transactions_checked = "bitcoin_transactions_checked_%d" % mincf
        oldest_unconfirmed = "bitcoin_oldest_unconfirmed_%d" % mincf

        if cache.get(transactions_checked):
            return cache.get(oldest_unconfirmed)
        else:
            cache.set(transactions_checked, True, 60 * 15)
            current_timestamp = timezone.now()
            transactions = WalletTransaction.objects.all()
            oldest = cache.get(oldest_unconfirmed)
            if oldest:
                transactions = transactions.filter(created_at__gte=oldest)

            transactions_cache = {}
            for t in transactions.order_by('created_at'):
                unc, _, txs = t.confirmation_status(minconf=mincf, transactions=transactions_cache)
                transactions_cache.update(txs)
                if unc:
                    cache.set(oldest_unconfirmed, t.created_at)
                    return t.created_at
            cache.set(oldest_unconfirmed, current_timestamp)
            return current_timestamp

    def balance(self, minconf=settings.BITCOIN_MINIMUM_CONFIRMATIONS,
                timeframe=None, transactions=None):
        """
        Returns a "greater or equal than minimum"  total ammount received at
        this wallet with the given confirmations at the given timeframe.
        """
        if minconf == settings.BITCOIN_MINIMUM_CONFIRMATIONS:
            return self.total_balance_sql(True)
        elif minconf == 0:
            return self.total_balance_sql(False)
        raise Exception("Incorrect minconf parameter")

    def total_balance_sql(self, confirmed=True):
        from django.db import connection
        cursor = connection.cursor()
        if confirmed is False:
            sql = """
             SELECT IFNULL((SELECT SUM(least_received) FROM django_bitcoin_bitcoinaddress ba WHERE ba.wallet_id=%(id)s), 0)
            + IFNULL((SELECT SUM(amount) FROM django_bitcoin_wallettransaction wt WHERE wt.to_wallet_id=%(id)s AND wt.from_wallet_id>0), 0)
            - IFNULL((SELECT SUM(amount) FROM django_bitcoin_wallettransaction wt WHERE wt.from_wallet_id=%(id)s), 0) as total_balance;
            """ % {'id': self.id}
            cursor.execute(sql)
            return cursor.fetchone()[0]
        else:
            sql = """
             SELECT IFNULL((SELECT SUM(least_received_confirmed) FROM django_bitcoin_bitcoinaddress ba WHERE ba.wallet_id=%(id)s AND ba.migrated_to_transactions=0), 0)
            + IFNULL((SELECT SUM(amount) FROM django_bitcoin_wallettransaction wt WHERE wt.to_wallet_id=%(id)s), 0)
            - IFNULL((SELECT SUM(amount) FROM django_bitcoin_wallettransaction wt WHERE wt.from_wallet_id=%(id)s), 0) as total_balance;
            """ % {'id': self.id}
            cursor.execute(sql)
            self.last_balance = cursor.fetchone()[0]
            return self.last_balance

    def total_balance(self, minconf=settings.BITCOIN_MINIMUM_CONFIRMATIONS):
        """
        Returns the total confirmed balance from the Wallet.
        """
        if not settings.BITCOIN_UNCONFIRMED_TRANSFERS:
            # if settings.BITCOIN_TRANSACTION_SIGNALING:
            #     if minconf == settings.BITCOIN_MINIMUM_CONFIRMATIONS:
            #         return self.total_balance_sql()
            #     elif mincof == 0:
            #         self.total_balance_sql(False)
            if minconf >= settings.BITCOIN_MINIMUM_CONFIRMATIONS:
                self.last_balance = self.total_received(minconf) - self.total_sent()
                return self.last_balance
            else:
                return self.total_received(minconf) - self.total_sent()
        else:
            return self.balance(minconf)[1]

    def total_balance_historical(self, balance_date, minconf=settings.BITCOIN_MINIMUM_CONFIRMATIONS):
        if settings.BITCOIN_TRANSACTION_SIGNALING:
            if minconf == settings.BITCOIN_MINIMUM_CONFIRMATIONS:
                s = self.addresses.filter(
                    created_at__lte=balance_date,
                    migrated_to_transactions=False).aggregate(
                    models.Sum("least_received_confirmed"))['least_received_confirmed__sum'] or Decimal(0)
            elif minconf == 0:
                s = self.addresses.filter(
                    created_at__lte=balance_date,
                    migrated_to_transactions=False).aggregate(
                    models.Sum("least_received"))['least_received__sum'] or Decimal(0)
            else:
                s = sum([a.received(minconf=minconf) for a in self.addresses.filter(created_at__lte=balance_date, migrated_to_transactions=False)])
        else:
            s = sum([a.received(minconf=minconf) for a in self.addresses.filter(created_at__lte=balance_date)])
        rt = self.received_transactions.filter(created_at__lte=balance_date).aggregate(models.Sum("amount"))['amount__sum'] or Decimal(0)
        received = (s + rt)
        sent = self.sent_transactions.filter(created_at__lte=balance_date).aggregate(models.Sum("amount"))['amount__sum'] or Decimal(0)
        return received - sent

    def total_balance_unconfirmed(self):
        if not settings.BITCOIN_UNCONFIRMED_TRANSFERS:
            return self.total_received(0) - self.total_sent()
        else:
            x = self.balance()
            return x[0] + x[1]

    def unconfirmed_balance(self):
        if not settings.BITCOIN_UNCONFIRMED_TRANSFERS:
            return self.total_received(0) - self.total_sent()
        else:
            return self.balance()[0]

    def total_received(self, minconf=settings.BITCOIN_MINIMUM_CONFIRMATIONS):
        """Returns the raw ammount ever received by this wallet."""
        if settings.BITCOIN_TRANSACTION_SIGNALING:
            if minconf == settings.BITCOIN_MINIMUM_CONFIRMATIONS:
                s = self.addresses.filter(
                    migrated_to_transactions=False).aggregate(
                    models.Sum("least_received_confirmed"))['least_received_confirmed__sum'] or Decimal(0)
            elif minconf == 0:
                s = self.addresses.all().aggregate(models.Sum("least_received"))['least_received__sum'] or Decimal(0)
            else:
                s = sum([a.received(minconf=minconf) for a in self.addresses.filter(migrated_to_transactions=False)])
        else:
            s = sum([a.received(minconf=minconf) for a in self.addresses.filter(migrated_to_transactions=False)])
        if minconf == 0:
            rt = self.received_transactions.filter(from_wallet__gte=1).aggregate(models.Sum("amount"))['amount__sum'] or Decimal(0)
        else:
            rt = self.received_transactions.aggregate(models.Sum("amount"))['amount__sum'] or Decimal(0)
        return (s + rt)

    def total_sent(self):
        """Returns the raw ammount ever sent by this wallet."""
        return self.sent_transactions.aggregate(models.Sum("amount"))['amount__sum'] or Decimal(0)

    def has_history(self):
        """Returns True if this wallet was any transacion history."""
        if self.received_transactions.all().count():
            return True
        if self.sent_transactions.all().count():
            return True
        if filter(lambda x: x.received(), self.addresses.all()):
            return True
        return False

    def merge_wallet(self, other_wallet):
        if self.id > 0 and other_wallet.id > 0:
            from django.db import connection, transaction
            cursor = connection.cursor()
            cursor.execute("UPDATE django_bitcoin_bitcoinaddress SET wallet_id=" + str(other_wallet.id) +
                           " WHERE wallet_id=" + str(self.id))
            cursor.execute("UPDATE django_bitcoin_wallettransaction SET from_wallet_id=" + str(other_wallet.id) +
                           " WHERE from_wallet_id=" + str(self.id))
            cursor.execute("UPDATE django_bitcoin_wallettransaction SET to_wallet_id=" + str(other_wallet.id) +
                           " WHERE to_wallet_id=" + str(self.id))
            cursor.execute("DELETE FROM django_bitcoin_wallettransaction WHERE to_wallet_id=from_wallet_id")
            transaction.commit_unless_managed()


def refill_payment_queue():
    c = BitcoinAddress.objects.filter(active=False, wallet=None).count()
    # print "count", c
    if settings.BITCOIN_ADDRESS_BUFFER_SIZE > c:
        for i in range(0, settings.BITCOIN_ADDRESS_BUFFER_SIZE - c):
            BitcoinAddress.objects.create(address=bitcoind.create_address(), active=False)


# Historical prie storage


class HistoricalPrice(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    price = models.DecimalField(max_digits=16, decimal_places=2)
    params = models.CharField(max_length=50)
    currency = models.CharField(max_length=10)

    class Meta:
        verbose_name = _('HistoricalPrice')
        verbose_name_plural = _('HistoricalPrices')

    def __unicode__(self):
        return str(self.created_at) + " - " + str(self.price) + " - " + str(self.params)

    @classmethod
    def set_historical_price(self, curr="EUR"):
        markets = currency.markets_chart()
        # print markets
        markets_currency = sorted(filter(lambda m: m['currency'] == curr and m['volume'] > 1 and not m['symbol'].startswith("mtgox"),
                                         markets.values()), key=lambda m: -m['volume'])[:3]
        # print markets_currency
        price = sum([m['avg'] for m in markets_currency]) / len(markets_currency)
        hp = HistoricalPrice.objects.create(price=Decimal(str(price)), params=",".join([m['symbol'] + "_avg" for m in markets_currency]), currency=curr,
                                            created_at=timezone.now())
        print "Created new", hp
        return hp

    @classmethod
    def get_historical_price_object(self, dt=None, curr="EUR"):
        query = HistoricalPrice.objects.filter(currency=curr)
        if dt:
            try:
                query = query.filter(created_at__lte=dt).order_by("-created_at")
                return query[0]
            except IndexError:
                return None
        try:
            # print timezone.now()
            query = HistoricalPrice.objects.filter(currency=curr,
                                                   created_at__gte=timezone.now() - datetime.timedelta(minutes=settings.HISTORICALPRICES_FETCH_TIMESPAN_MINUTES)).\
                order_by("-created_at")
            # print query
            return query[0]
        except IndexError:
            return self.set_historical_price()

