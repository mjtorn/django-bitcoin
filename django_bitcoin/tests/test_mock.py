from . import mock_bitcoin_objects

import mock


@mock.patch('django_bitcoin.bitcoind.bitcoind', new=mock_bitcoin_objects.mock_bitcoind)
def test_address():
    from django_bitcoin.bitcoind import bitcoind

    print bitcoind.create_address()

