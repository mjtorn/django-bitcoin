from . import currency


def bitcoinprice(request):
    return {
        'bitcoinprice_eur': currency.exchange.get_rate("EUR"),
        'bitcoinprice_usd': currency.exchange.get_rate("USD"),
    }

