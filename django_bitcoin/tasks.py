from __future__ import with_statement

from django.core.cache import cache
from django.core.mail import mail_admins

from django.db import transaction as db_transaction
from django.utils import timezone

from decimal import Decimal

from .bitcoind import bitcoind
from .locking import NonBlockingCacheLock

from . import jsonrpc
from . import settings
from . import utils

from celery import task


@task()
def query_transactions():
    # Circularity and locality
    from . import models

    with NonBlockingCacheLock("query_transactions_ongoing"):
        blockcount = bitcoind.bitcoind_api.getblockcount()
        max_query_block = blockcount - settings.BITCOIN_MINIMUM_CONFIRMATIONS - 1
        if cache.get("queried_block_index"):
            query_block = min(int(cache.get("queried_block_index")), max_query_block)
        else:
            query_block = blockcount - 100
        blockhash = bitcoind.bitcoind_api.getblockhash(query_block)
        # print query_block, blockhash
        transactions = bitcoind.bitcoind_api.listsinceblock(blockhash)
        # print transactions
        transactions = [tx for tx in transactions["transactions"] if tx["category"] == "receive"]
        print transactions
        for tx in transactions:
            ba = models.BitcoinAddress.objects.filter(address=tx[u'address'])
            if ba.count() > 1:
                raise Exception(u"Too many addresses!")
            if ba.count() == 0:
                print "no address found, address", tx[u'address']
                continue
            ba = ba[0]
            dps = models.DepositTransaction.objects.filter(txid=tx[u'txid'], amount=tx['amount'], address=ba)
            if dps.count() > 1:
                raise Exception(u"Too many deposittransactions for the same ID!")
            elif dps.count() == 0:
                deposit_tx = models.DepositTransaction.objects.create(wallet=ba.wallet,
                                                                      address=ba,
                                                                      amount=tx['amount'],
                                                                      txid=tx[u'txid'],
                                                                      confirmations=int(tx['confirmations']))
                if deposit_tx.confirmations >= settings.BITCOIN_MINIMUM_CONFIRMATIONS:
                    ba.query_bitcoin_deposit(deposit_tx)
                else:
                    ba.query_unconfirmed_deposits()
            elif dps.count() == 1 and not dps[0].under_execution:
                deposit_tx = dps[0]
                if int(tx['confirmations']) >= settings.BITCOIN_MINIMUM_CONFIRMATIONS:
                    ba.query_bitcoin_deposit(deposit_tx)
                if int(tx['confirmations']) > deposit_tx.confirmations:
                    models.DepositTransaction.objects.filter(id=deposit_tx.id).update(confirmations=int(tx['confirmations']))
            elif dps.count() == 1:
                print "already processed", dps[0].txid, dps[0].transaction
            else:
                print "FUFFUFUU"

        cache.set("queried_block_index", max_query_block)


@task()
def check_integrity():
    from django_bitcoin import models
    from django_bitcoin.bitcoind import bitcoind
    from django.db.models import Max, Sum
    from decimal import Decimal

    import sys
    from cStringIO import StringIO
    backup = sys.stdout
    sys.stdout = StringIO()

    bitcoinaddress_sum = models.BitcoinAddress.objects.filter(active=True)\
        .aggregate(Sum('least_received_confirmed'))['least_received_confirmed__sum'] or Decimal(0)
    print "Total received, sum", bitcoinaddress_sum
    transaction_wallets_sum = models.WalletTransaction.objects.filter(from_wallet__id__gt=0, to_wallet__id__gt=0)\
        .aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
    print "Total transactions, sum", transaction_wallets_sum
    transaction_out_sum = models.WalletTransaction.objects.filter(from_wallet__id__gt=0)\
        .exclude(to_bitcoinaddress="").exclude(to_bitcoinaddress="")\
        .aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
    print "Total outgoing, sum", transaction_out_sum
    # for x in models.WalletTransaction.objects.filter(from_wallet__id__gt=0, to_wallet__isnull=True, to_bitcoinaddress=""):
    #   print x.amount, x.created_at
    fee_sum = models.WalletTransaction.objects.filter(from_wallet__id__gt=0, to_wallet__isnull=True, to_bitcoinaddress="")\
        .aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
    print "Fees, sum", fee_sum
    print "DB balance", (bitcoinaddress_sum - transaction_out_sum - fee_sum)
    print "----"
    bitcoind_balance = bitcoind.bitcoind_api.getbalance()
    print "Bitcoind balance", bitcoind_balance
    print "----"
    print "Wallet quick check"
    total_sum = Decimal(0)
    for w in models.Wallet.objects.filter(last_balance__lt=0):
        if w.total_balance() < 0:
            bal = w.total_balance()
            # print w.id, bal
            total_sum += bal
    print "Negatives:", models.Wallet.objects.filter(last_balance__lt=0).count(), "Amount:", total_sum
    print "Migration check"
    tot_received = models.WalletTransaction.objects.filter(from_wallet=None)
    tot_received = tot_received.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
    tot_received_bitcoinaddress = models.BitcoinAddress.objects.filter(migrated_to_transactions=True)\
        .aggregate(Sum('least_received_confirmed'))['least_received_confirmed__sum'] or Decimal(0)
    tot_received_unmigrated = models.BitcoinAddress.objects.filter(migrated_to_transactions=False)\
        .aggregate(Sum('least_received_confirmed'))['least_received_confirmed__sum'] or Decimal(0)
    if tot_received != tot_received_bitcoinaddress:
        print "wrong total receive amount! " + str(tot_received) + ", " + str(tot_received_bitcoinaddress)
    print "Total " + str(tot_received) + " BTC deposits migrated, unmigrated " + str(tot_received_unmigrated) + " BTC"
    print "Migration check #2"
    dts = models.DepositTransaction.objects.filter(address__migrated_to_transactions=False).exclude(transaction=None)
    if dts.count() > 0:
        print "Illegal transaction!", dts
    if models.WalletTransaction.objects.filter(from_wallet=None, deposit_address=None).count() > 0:
        print "Illegal deposit transactions!"
    print "Wallet check"
    for w in models.Wallet.objects.filter(last_balance__gt=0):
        lb = w.last_balance
        tb_sql = w.total_balance_sql()
        tb = w.total_balance()
        if lb != tb or w.last_balance != tb or tb != tb_sql:
            print "Wallet balance error!", w.id, lb, tb_sql, tb
            print w.sent_transactions.all().count()
            print w.received_transactions.all().count()
            print w.sent_transactions.all().aggregate(Max('created_at'))['created_at__max']
            print w.received_transactions.all().aggregate(Max('created_at'))['created_at__max']
            # models.Wallet.objects.filter(id=w.id).update(last_balance=w.total_balance_sql())
    # print w.created_at, w.sent_transactions.all(), w.received_transactions.all()
        # if random.random() < 0.001:
        #     sleep(1)
    print "Address check"
    for ba in models.BitcoinAddress.objects.filter(least_received_confirmed__gt=0, migrated_to_transactions=True):
        dts = models.DepositTransaction.objects.filter(address=ba, wallet=ba.wallet)
        s = dts.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        if s != ba.least_received:
            print "DepositTransaction error", ba.address, ba.least_received, s
            print "BitcoinAddress check"
    for ba in models.BitcoinAddress.objects.filter(migrated_to_transactions=True):
        dts = ba.deposittransaction_set.filter(address=ba, confirmations__gte=settings.BITCOIN_MINIMUM_CONFIRMATIONS)
        deposit_sum = dts.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        wt_sum = models.WalletTransaction.objects.filter(deposit_address=ba)
        wt_sum = wt_sum.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        if wt_sum != deposit_sum or ba.least_received_confirmed != deposit_sum:
            print "Bitcoinaddress integrity error!", ba.address, deposit_sum, wt_sum, ba.least_received_confirmed
        # if random.random() < 0.001:
        #     sleep(1)

    integrity_test_output = sys.stdout.getvalue()  # release output
    # ####

    sys.stdout.close()  # close the stream
    sys.stdout = backup  # restore original stdout
    mail_admins("Integrity check", integrity_test_output)


@task()
def update_wallet_balance(wallet_id):
    # Circularity and locality
    from . import models

    w = models.Wallet.objects.get(id=wallet_id)
    models.Wallet.objects.filter(id=wallet_id).update(last_balance=w.total_balance_sql())


@task()
@db_transaction.autocommit
def process_outgoing_transactions():
    # Circularity and locality
    from . import models

    if models.OutgoingTransaction.objects.filter(executed_at=None, expires_at__lte=timezone.now()).count() > 0 or \
            models.OutgoingTransaction.objects.filter(executed_at=None).count() > 6:
        blockcount = bitcoind.bitcoind_api.getblockcount()
        with NonBlockingCacheLock('process_outgoing_transactions'):
            ots_ids = utils.filter_doubles(models.OutgoingTransaction.objects.filter(executed_at=None).order_by("expires_at")[:15])
            ots = models.OutgoingTransaction.objects.filter(executed_at=None, id__in=ots_ids)
            update_wallets = []
            transaction_hash = {}
            for ot in ots:
                transaction_hash[ot.to_bitcoinaddress] = float(ot.amount)
            updated = models.OutgoingTransaction.objects.filter(id__in=ots_ids,
                                                                executed_at=None).select_for_update().update(executed_at=timezone.now())
            if updated == len(ots):
                try:
                    result = bitcoind.sendmany(transaction_hash)
                except jsonrpc.JSONRPCException as e:
                    if e.error == u"{u'message': u'Insufficient funds', u'code': -4}" or \
                            e.error == u"{u'message': u'Insufficient funds', u'code': -6}":
                        u2 = models.OutgoingTransaction.objects.filter(id__in=ots_ids, under_execution=False
                                                                       ).select_for_update().update(executed_at=None)
                    else:
                        u2 = models.OutgoingTransaction.objects.filter(id__in=ots_ids, under_execution=False
                                                                       ).select_for_update().update(under_execution=True, txid=e.error)
                    raise
                models.OutgoingTransaction.objects.filter(id__in=ots_ids).update(txid=result)
                transaction = bitcoind.gettransaction(result)
                if Decimal(transaction['fee']) < Decimal(0):
                    fw = utils.fee_wallet()
                    fee_amount = Decimal(transaction['fee']) * Decimal(-1)
                    orig_fee_transaction = models.WalletTransaction.objects.create(
                        amount=fee_amount,
                        from_wallet=fw,
                        to_wallet=None)
                    i = 1
                    for ot_id in ots_ids:
                        wt = models.WalletTransaction.objects.get(outgoing_transaction__id=ot_id)
                        update_wallets.append(wt.from_wallet_id)
                        fee_transaction = models.WalletTransaction.objects.create(
                            amount=(fee_amount / Decimal(i)).quantize(Decimal("0.00000001")),
                            from_wallet_id=wt.from_wallet_id,
                            to_wallet=fw,
                            description="fee")
                        i += 1
                else:
                    raise Exception("Updated amount not matchinf transaction amount!")
            for wid in update_wallets:
                update_wallet_balance.delay(wid)
    # elif models.OutgoingTransaction.objects.filter(executed_at=None).count()>0:
    #     next_run_at = models.OutgoingTransaction.objects.filter(executed_at=None).aggregate(Min('expires_at'))['expires_at__min']
    #     if next_run_at:
    #         process_outgoing_transactions.retry(
    #             countdown=max(((next_run_at - timezone.now(pytz.utc)) + datetime.timedelta(seconds=5)).total_seconds(), 5))

