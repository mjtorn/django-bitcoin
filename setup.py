# vim: fileencoding=utf-8

from setuptools import setup


template_patterns = ['templates/*.html',
                     'templates/*/*.html',
                     'templates/*/*/*.html',
                     ]

package_name = 'django-bitcoin'
packages = ['django_bitcoin',
            'django_bitcoin.management',
            'django_bitcoin.management.commands',
            'django_bitcoin.templatetags',
            'django_bitcoin.templates',
            'django_bitcoin.migrations',
            'django_bitcoin.jsonrpc']

long_description = open("README.md").read()

setup(name='django-bitcoin',
      version='0.3.0',
      description='Bitcoin application integration for Django web framework',
      long_description=long_description,
      author=u'Jeremias Kangas and Markus Törnqvist',
      url='https://github.com/mjtorn/django-bitcoin',
      license="MIT",
      packages=packages,
      package_data=dict((package_name, template_patterns) for package_name in packages),
      )
