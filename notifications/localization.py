class LocaleHelper(object):
    def __init__(self, locale, encoding='utf-8'):
        super(LocaleHelper, self).__init__()
        self.locale_dict = locale
        self.encoding = encoding

    def get_string_for_key(self, key):
        val = self.locale_dict.get(key)
        return val if val is not None else "err_unknown_key"
