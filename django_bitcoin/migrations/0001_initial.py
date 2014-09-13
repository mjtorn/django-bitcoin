# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import datetime
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='BitcoinAddress',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('address', models.CharField(unique=True, max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('active', models.BooleanField(default=False)),
                ('least_received', models.DecimalField(default=Decimal('0'), max_digits=16, decimal_places=8)),
                ('least_received_confirmed', models.DecimalField(default=Decimal('0'), max_digits=16, decimal_places=8)),
                ('label', models.CharField(default=None, max_length=50, null=True, blank=True)),
                ('migrated_to_transactions', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name_plural': 'Bitcoin addresses',
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='DepositTransaction',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('amount', models.DecimalField(default=Decimal('0'), max_digits=16, decimal_places=8)),
                ('description', models.CharField(default=None, max_length=100, null=True, blank=True)),
                ('under_execution', models.BooleanField(default=False)),
                ('confirmations', models.IntegerField(default=0)),
                ('txid', models.CharField(max_length=100, null=True, blank=True)),
                ('address', models.ForeignKey(to='django_bitcoin.BitcoinAddress')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='HistoricalPrice',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('price', models.DecimalField(max_digits=16, decimal_places=2)),
                ('params', models.CharField(max_length=50)),
                ('currency', models.CharField(max_length=10)),
            ],
            options={
                'verbose_name': 'HistoricalPrice',
                'verbose_name_plural': 'HistoricalPrices',
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='OutgoingTransaction',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField(auto_now_add=True)),
                ('executed_at', models.DateTimeField(default=None, null=True)),
                ('under_execution', models.BooleanField(default=False)),
                ('to_bitcoinaddress', models.CharField(max_length=50, blank=True)),
                ('amount', models.DecimalField(default=Decimal('0.0'), max_digits=16, decimal_places=8)),
                ('txid', models.CharField(default=None, max_length=100, null=True, blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('description', models.CharField(max_length=255, blank=True)),
                ('address', models.CharField(max_length=50)),
                ('amount', models.DecimalField(default=Decimal('0.0'), max_digits=16, decimal_places=8)),
                ('amount_paid', models.DecimalField(default=Decimal('0.0'), max_digits=16, decimal_places=8)),
                ('active', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField()),
                ('paid_at', models.DateTimeField(default=None, null=True)),
                ('withdrawn_total', models.DecimalField(default=Decimal('0.0'), max_digits=16, decimal_places=8)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('amount', models.DecimalField(default=Decimal('0.0'), max_digits=16, decimal_places=8)),
                ('address', models.CharField(max_length=50)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Wallet',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField()),
                ('label', models.CharField(max_length=50, blank=True)),
                ('transaction_counter', models.IntegerField(default=1)),
                ('last_balance', models.DecimalField(default=Decimal('0'), max_digits=16, decimal_places=8)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='WalletTransaction',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('to_bitcoinaddress', models.CharField(max_length=50, blank=True)),
                ('amount', models.DecimalField(default=Decimal('0.0'), max_digits=16, decimal_places=8)),
                ('description', models.CharField(max_length=100, blank=True)),
                ('txid', models.CharField(max_length=100, null=True, blank=True)),
                ('deposit_address', models.ForeignKey(to='django_bitcoin.BitcoinAddress', null=True)),
                ('deposit_transaction', models.OneToOneField(null=True, to='django_bitcoin.DepositTransaction')),
                ('from_wallet', models.ForeignKey(related_name=b'sent_transactions', to='django_bitcoin.Wallet', null=True)),
                ('outgoing_transaction', models.ForeignKey(default=None, to='django_bitcoin.OutgoingTransaction', null=True)),
                ('to_wallet', models.ForeignKey(related_name=b'received_transactions', to='django_bitcoin.Wallet', null=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='wallet',
            name='transactions_with',
            field=models.ManyToManyField(to='django_bitcoin.Wallet', through='django_bitcoin.WalletTransaction'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='payment',
            name='transactions',
            field=models.ManyToManyField(to='django_bitcoin.Transaction'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='deposittransaction',
            name='transaction',
            field=models.ForeignKey(default=None, to='django_bitcoin.WalletTransaction', null=True),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='deposittransaction',
            name='wallet',
            field=models.ForeignKey(to='django_bitcoin.Wallet'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='bitcoinaddress',
            name='wallet',
            field=models.ForeignKey(related_name=b'addresses', to='django_bitcoin.Wallet', null=True),
            preserve_default=True,
        ),
    ]
