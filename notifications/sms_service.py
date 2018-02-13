import requests

from togetherapi.settings import SMS_SERVICE_URL, SMS_AUTH_LOGIN, SMS_AUTH_PASSWD, SMS_LIFETIME, SMS_FROM, SMS_ALLOWED
from togetherapi.utils import get_custom_logger

logger = get_custom_logger()


class SmsService(object):
    exceptions = []

    class SmsMessage(object):
        scheduled = False

        def __init__(self, phone_no, text, lifetime):
            self.phone_no = phone_no
            self.lifetime = lifetime
            self.text = text

    def _prepare(self):
        r = requests.get(SMS_SERVICE_URL + '/user/sessionid',
                         params={'login': SMS_AUTH_LOGIN, 'password': SMS_AUTH_PASSWD})
        if r.status_code == requests.codes.ok:
            self.sessionId = str(r.text).strip('"')
            logger.debug('SMS provider session acquired: %s' % self.sessionId)
            return True
        else:
            logger.error('SMS provider error: %s' % r.text)
            return False

    def _send(self, sms_message):
        if sms_message.phone_no not in self.exceptions:
            r = requests.post(SMS_SERVICE_URL + '/Sms/Send', data={
                'SessionId': self.sessionId,
                'DestinationAddress': sms_message.phone_no,
                'SourceAddress': SMS_FROM,
                'Data': sms_message.text,
                'Validity': sms_message.lifetime
            })
            if r.status_code == requests.codes.ok:
                sms_message.scheduled = True
                logger.debug('Message delivery scheduled.')
            else:
                logger.error('Error is message delivery process: %s' % r.text)
        else:
            sms_message.scheduled = True
        return sms_message

    def send_text_message(self, phone, text, lifetime=SMS_LIFETIME):
        if not SMS_ALLOWED:
            logger.warn('SMS delivery has been disabled manually (see settings.py for details).')
            return True
        logger.debug('Sending SMS to phone no.: %s with lifetime of %d min.' % (phone, lifetime))
        if self._prepare():
            message = self.SmsMessage(phone, text, lifetime)
            return True if self._send(message).scheduled else False
        else:
            logger.error('Message could not be delivered due an interaction error with SMS provider.')
        return False
