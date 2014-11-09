from django.core.cache import cache

from django_bitcoin import settings
from pywallet import privkey2address

from . import utils

import decimal
import jsonrpc


class BitcoindConnection(object):
    def __init__(self, connection_string, main_account_name):
        self.bitcoind_api = jsonrpc.ServiceProxy(connection_string)
        self.account_name = main_account_name

    def total_received(self, address, minconf=settings.BITCOIN_MINIMUM_CONFIRMATIONS):
        if settings.BITCOIN_TRANSACTION_CACHING:
            cache_key = address + "_" + str(minconf)
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            cached = decimal.Decimal(
                self.bitcoind_api.getreceivedbyaddress(address, minconf))
            cache.set(cache_key, cached, 5)
            return cached
        return decimal.Decimal(
            self.bitcoind_api.getreceivedbyaddress(address, minconf)
        )

    def send(self, address, amount, *args, **kwargs):
        #print "sending", address, amount
        return self.bitcoind_api.sendtoaddress(address, float(amount), *args, **kwargs)

    def sendmany(self, address_amount_dict, *args, **kwargs):
        #print "sending", address, amount
        return self.bitcoind_api.sendmany(self.account_name, address_amount_dict, *args, **kwargs)

    def create_address(self, for_account=None, *args, **kwargs):
        return self.bitcoind_api.getnewaddress(
            for_account or self.account_name, *args, **kwargs)

    def gettransaction(self, txid, *args, **kwargs):
        # dir (self.bitcoind_api)
        return self.bitcoind_api.gettransaction(txid, *args, **kwargs)

    # if address_to is defined, also empties the private key to that address
    def importprivatekey(self, key):
        # import private key functionality here later
        # NOTE: only
        label = "import"
        address_from = privkey2address(key)
        if not address_from or not address_from.startswith("1"):
            print address_from
            return None
        # print address_from
        try:
            self.bitcoind_api.importprivkey(key, label)
        except jsonrpc.JSONRPCException:
            pass
        unspent_transactions = self.bitcoind_api.listunspent(1, 9999999, [address_from])
        return (address_from, utils.quantitize_bitcoin(decimal.Decimal(sum([decimal.Decimal(x['amount'])
                    for x in unspent_transactions])))
                )

    def redeemprivatekey(self, key, address_from, address_to):
        if type(address_to) == str or type(address_to) == unicode:
            address_to = ((address_to, None),)
        if address_from != privkey2address(key):
            return None
        unspent_transactions = self.bitcoind_api.listunspent(1, 9999999, [address_from])
        tot_amount = sum([decimal.Decimal(x['amount']) for x in unspent_transactions])
        tot_fee = len(unspent_transactions) * settings.BITCOIN_PRIVKEY_FEE
        tot_spend = tot_fee
        if tot_amount > tot_spend:
            final_arr = {}
            for addr in address_to:
                if addr[1] and addr[1] < 0:
                    raise Exception("No negative spend values allowed")
                if addr[1] and tot_amount > addr[1] + tot_spend:
                    final_arr[addr[0]] = utils.decimal_float(addr[1])
                    tot_spend += addr[1]
                elif not addr[1] and tot_amount > tot_spend:
                    final_arr[addr[0]] = utils.decimal_float((tot_amount - tot_spend))
                    break
                else:
                    return None  # raise Exception("Invalid amount parameters")
            # print final_arr
            # print unspent_transactions
            spend_transactions = [{"txid": ut['txid'], "vout": ut['vout']} for ut in unspent_transactions]
            spend_transactions_sign = [{"txid": ut['txid'],
                                        "vout": ut['vout'],
                                        "scriptPubKey": ut['scriptPubKey']
                                        }
                                        for ut in unspent_transactions]
            raw_transaction = self.bitcoind_api.createrawtransaction(spend_transactions, final_arr)
            raw_transaction_signed = self.bitcoind_api.signrawtransaction(raw_transaction, spend_transactions_sign, [key])
            # print raw_transaction, raw_transaction_signed
            return self.bitcoind_api.sendrawtransaction(raw_transaction_signed['hex'])
        else:
            return None

        # return self.bitcoind_api.gettransaction(txid, *args, **kwargs)


bitcoind = BitcoindConnection(settings.BITCOIND_CONNECTION_STRING,
                              settings.MAIN_ACCOUNT)



