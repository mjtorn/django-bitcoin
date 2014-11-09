# vim: tabstop=4 expandtab autoindent shiftwidth=4 fileencoding=utf-8

from django.core.cache import cache

import decimal


def quantitize_bitcoin(d):
    return d.quantize(decimal.Decimal("0.00000001"))


def decimal_float(d):
    return float(d.quantize(decimal.Decimal("0.00000001")))


def fee_wallet():
    # Avoid circular imports
    from . import models

    master_wallet_id = cache.get("django_bitcoin_fee_wallet_id")
    if master_wallet_id:
        return models.Wallet.objects.get(id=master_wallet_id)
    try:
        mw = models.Wallet.objects.get(label="django_bitcoin_fee_wallet")
    except models.Wallet.DoesNotExist:
        mw = models.Wallet.objects.create(label="django_bitcoin_fee_wallet")
        mw.save()
    cache.set("django_bitcoin_fee_wallet_id", mw.id)
    return mw


def filter_doubles(outgoing_list):
    ot_ids = []
    ot_addresses = []
    for ot in outgoing_list:
        if ot.to_bitcoinaddress not in ot_addresses:
            ot_ids.append(ot.id)
            ot_addresses.append(ot.to_bitcoinaddress)
    return ot_ids

