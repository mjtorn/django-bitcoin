# vim: tabstop=4 expandtab autoindent shiftwidth=4 fileencoding=utf-8

import decimal


def quantitize_bitcoin(d):
    return d.quantize(decimal.Decimal("0.00000001"))


def decimal_float(d):
    return float(d.quantize(decimal.Decimal("0.00000001")))

