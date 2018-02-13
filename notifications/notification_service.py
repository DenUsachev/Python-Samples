import json
import os
import random
from multiprocessing import Process

import redis
from apns import APNs, Payload, PayloadAlert
from mongoengine import DoesNotExist

from Api.models import User
from togetherapi.locks.lock import FileLock
from togetherapi.notifications import APNS_QUEUE_CHANNEL, APNS_SERVER_CERT_SANDBOX, APNS_SERVER_KEY_SANDBOX
from togetherapi.utils import singleton, get_custom_logger


class NotificationServiceBase:
    def __init__(self, certfile, channel, keyfile=None):
        self.certfile = certfile
        self.keyfile = keyfile
        self.redis = redis.Redis()
        self.pubsub = self.redis.pubsub()
        self.channel = channel
        self.logger = get_custom_logger()
        self.logger.debug("Certificate file set: %s" % self.certfile)
        self.lock = FileLock('notification_lock')
        if os.access(APNS_SERVER_CERT_SANDBOX, os.R_OK | os.F_OK):
            self.logger.debug('Access to APNS certificate is ok')
        else:
            self.logger.error('Count not open cert. file. Service will not operate properly!!!')
    
    def run_server(self):
        self.lock.acquire()
        print 'Lock handle obtained'
        self.pubsub.subscribe((self.channel,))
        for item in self.pubsub.listen():
            if item['data'] == "KILL":
                self.pubsub.unsubscribe()
                print self, "Service process is going to be terminated"
                break
            else:
                self.on_message(item)

    def _deliver_message(self, msg, mem, mem_to, loc_key, custom=None):
        pass

    def on_message(self, packed_object):
        try:
            if isinstance(packed_object, dict) and packed_object['data'] == 1:
                return
            message = json.loads(packed_object['data'])
            if message.get('MessageAuthor'):
                member = message['MessageAuthor']
            else:
                member = message['CommentAuthor']
            member_to = message['MessageRcpt']
            loc_key = message['loc-key']
            if loc_key == 'KEY_NEW_MESSAGE':
                custom = {'EventType': message['EventType']}
            else:
                custom = None
            self._deliver_message(message, member, member_to, loc_key, custom)
        except BaseException, e:
            self.logger.error(e)

    def __del__(self):
        if self.lock is not None:
            self.lock.release()
            print 'Lock handle released'
        if self.pubsub.is_subscribed:
            self.pubsub.unsubscribe(self.channel, self)
            self.pubsub.close()
            self.logger.debug("APNS service unsubscribed")


class AppleNotificationService(NotificationServiceBase):
    def __init__(self, certfile, channel, keyfile):
        """
        Performs an initialization of the notification service
        :param certfile: path to the certificate pem file
        :param channel:  channel which this service will listen to
        """
        NotificationServiceBase.__init__(self, certfile, channel, keyfile)
        self.endpoint = APNs(use_sandbox=False, cert_file=self.certfile, enhanced=True)
        self.endpoint.gateway_server.register_response_listener(self._response_listener)

    def run_server(self):
        """
        Performs service startup
        """
        self.logger.debug("APNS notification service has subscribed on the channel: %s" % self.channel)
        NotificationServiceBase.run_server(self)

    def _response_listener(self, error_response):
        self.logger.debug("client get error-response: " + str(error_response))

    def _deliver_message(self, msg, mem, mem_to, loc_key, custom=None):
        """
        Sends a notification payload to the messaging server
        :param msg: message object
        :param mem: member who sends a messaged
        :param mem_to: member for whom the message is being delivered
        """
        try:
            user = User.objects.get(UserPhone=mem_to['UserPhone'])
            events = user.get_events()
            total_unread = 0
            for e in events:
                member_data = e.get_member_data(user)
                total_unread += member_data.UserUnreadMessages + member_data.FeedUnreadMessages \
                    if member_data.FeedUnreadMessages is not None \
                    else member_data.UserUnreadMessages
            self.logger.debug('Total unread messages: %d' % total_unread)
            for device in user.UserDevices:
                if device.DeviceCMToken is not None and len(device.DeviceCMToken) > 0:
                    alert = None
                    member_name_to = ''.join([mem['UserFirstName'], u' ', mem['UserLastName']])
                    if msg.get('MessageText'):
                        alert = PayloadAlert(loc_key=loc_key, loc_args=[member_name_to, msg['MessageText']])
                    elif msg.get('CommentText'):
                        alert = PayloadAlert(loc_key=loc_key, loc_args=[member_name_to, msg['CommentText']])
                    elif loc_key == 'KEY_YOU_INVITED':
                        alert = PayloadAlert(loc_key=loc_key, loc_args=[member_name_to, msg['EventName']])
                    elif loc_key == 'KEY_REQUEST_SUBSCRIBE':
                        alert = PayloadAlert(loc_key=loc_key, loc_args=[member_name_to])

                    payload = Payload(
                        alert=alert,
                        sound='sound1.caf',
                        badge=total_unread,
                        custom={
                            'EventId': msg.get('EventId'),
                            'EventType': custom.get('EventType') if custom is not None else None
                        })
                    identifier = random.getrandbits(32)
                    self.logger.debug('Sending payload to APNS with device token: %s' % device.DeviceCMToken)
                    self.endpoint.gateway_server.send_notification(device.DeviceCMToken.replace(' ', ''), payload,
                                                                   identifier=identifier)
        except BaseException, e:
            if e is DoesNotExist:
                self.logger.error("User %s was not found. Unable to deliver the notification." % mem_to['UserPhone'])
            else:
                self.logger.error("Unexpected error occurred:%s" % e.message)

    def __del__(self):
        self.logger.debug("APNS notification service service unsubscribed from channel: %s" % self.channel)
        self.endpoint.gateway_server.force_close()


@singleton
class ApnsServiceRunner:
    def __init__(self):
        self.proc_handler = None
        self.logger = get_custom_logger()
        self.logger.debug('APNS service runner initialized')

    def _proc_runner(self):
        apns_server = AppleNotificationService(APNS_SERVER_CERT_SANDBOX, APNS_QUEUE_CHANNEL,
                                               APNS_SERVER_KEY_SANDBOX)
        apns_server.run_server()
        self.logger.debug('***  APNS Service Started  ***')

    def run_server(self):
        p = Process(target=self._proc_runner)
        self.proc_handler = p
        p.start()

    def __del__(self):
        if self.proc_handler is not None:
            self.proc_handler.join()
