#
# Django field type for a Bitcoin Address
#

from django.forms.util import ValidationError
from django import forms
from . import utils
import re


class BCAddressField(forms.CharField):
    default_error_messages = {
        'invalid': 'Invalid Bitcoin address.',
    }

    def __init__(self, *args, **kwargs):
        super(BCAddressField, self).__init__(*args, **kwargs)

    def clean(self, value):
        if not value and not self.required:
            return None

        if not value.startswith(u"1") and not value.startswith(u"3"):
            raise ValidationError(self.error_messages['invalid'])
        value = value.strip()

        if "\n" in value:
            raise ValidationError(u"Multiple lines in the bitcoin address")

        if " " in value:
            raise ValidationError(u"Spaces in the bitcoin address")

        if re.match(r"[a-zA-Z1-9]{27,35}$", value) is None:
            raise ValidationError(self.error_messages['invalid'])
        version = utils.get_bcaddress_version(value)
        if version is None:
            raise ValidationError(self.error_messages['invalid'])
        return value

