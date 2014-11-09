# vim: tabstop=4 expandtab autoindent shiftwidth=4 fileencoding=utf-8

import decimal
import os
import hashlib
import base64


def quantitize_bitcoin(d):
    return d.quantize(decimal.Decimal("0.00000001"))


def decimal_float(d):
    return float(d.quantize(decimal.Decimal("0.00000001")))


# generate a random hash
def generateuniquehash(length=43, extradata=''):
    # cryptographically safe random
    r=str(os.urandom(64))
    m = hashlib.sha256()
    m.update(r+str(extradata))
    key=m.digest()
    key=base64.urlsafe_b64encode(key)
    return key[:min(length, 43)]

import string

ALPHABET = string.ascii_uppercase + string.ascii_lowercase + \
           string.digits + '_-'
ALPHABET_REVERSE = dict((c, i) for (i, c) in enumerate(ALPHABET))
BASE = len(ALPHABET)
SIGN_CHARACTER = '%'

def int2base64(n):
    if n < 0:
        return SIGN_CHARACTER + num_encode(-n)
    s = []
    while True:
        n, r = divmod(n, BASE)
        s.append(ALPHABET[r])
        if n == 0: break
    return ''.join(reversed(s))

def base642int(s):
    if s[0] == SIGN_CHARACTER:
        return -num_decode(s[1:])
    n = 0
    for c in s:
        n = n * BASE + ALPHABET_REVERSE[c]
    return n
