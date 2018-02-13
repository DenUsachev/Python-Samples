import json
import uuid

import tornadoredis

from Api.models import Message, Attachment, SystemAttachment, User
from Api.serializers import MessageSerializer
from togetherapi.notifications.localization import LocaleHelper
from togetherapi.notifications.ru_locale import RU_LOCALE
from togetherapi.rest.v1 import EVENT_TYPE_CHAT
from togetherapi.utils import get_custom_logger, current_timestamp, event_id_gen


class ServiceNotificationHelper(object):
    def __init__(self):
        self.pubsub = tornadoredis.Client()

    def notify_client(self, event_info):
        event_info.get_payload_json()

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        pass


class EventInfoBase(object):
    def __init__(self, user, event, **kwargs):
        self.current_user = user
        self.current_event = event
        self.kwargs = kwargs
        self.logger = get_custom_logger()
        self.message_text = ''
        self.locale_helper = LocaleHelper(RU_LOCALE)

    def _create_message(self):
        msg = Message(
            MessageId=event_id_gen(32),
            EventId=self.current_event.EventId,
            MessageFK=str(uuid.uuid4()),
            MessageText=self.message_text,
            MessageAuthor=self.current_user,
            MessagePublic=False,
            MessageStatus=3,
            MessageCreated=current_timestamp(),
            MessageUpdated=current_timestamp()
        )
        msg.save(force_insert=True)
        self.message = msg
        self.logger.debug("Message: %s created with text: %s" % (msg.MessageId, msg.MessageText))

    def _configure_payload(self):
        self.payload = dict()
        self.payload['author'] = self.current_user.UserPhone
        self.payload['event'] = self.current_event.EventId

    def get_payload_json(self):
        try:
            self._configure_payload()
            self._create_message()
            return None
        except BaseException, e:
            self.logger.error("Payload serialization error: %s" % e.message)
            return json.dumps({'error', e.message})


class AttachedEventInfo(EventInfoBase):
    def __init__(self, user, event, **kwargs):
        super(AttachedEventInfo, self).__init__(user, event, **kwargs)
        self.members = []
        self.members_packed = []
        self.revoke_requested = False

    def _revoke_request(self):
        self.revoke_requested = True

    def format_user_name(self):
        '{0} {1}'.format(self.current_user.UserFirstName.encode('utf-8'),
                         self.current_user.UserLastName.encode('utf-8'))

    def _create_message(self):
        att = SystemAttachment(AttachmentText=self.message_text)
        for k in self.members:
            for y in k.keys():
                name_components = str.split(k[y], ' ', 2)
                self.members_packed.append(
                    User(UserPhone=y, UserFirstName=name_components[0], UserLastName=name_components[1]))

        att.AttachmentMembers = self.members_packed
        msg = Message(
            MessageId=event_id_gen(32),
            EventId=self.current_event.EventId,
            MessageFK=str(uuid.uuid4()),
            MessageText=None,
            MessageAuthor=self.current_user,
            MessagePublic=False,
            MessageCreated=current_timestamp(),
            MessageUpdated=current_timestamp(),
        )
        if self.revoke_requested:
            msg.MessageAttachment.append(
                Attachment(AttachmentType="REVOKE", AttachmentSystem=att)
            )
            msg.MessageCreated -= 1
            msg.MessageUpdated -= 1
        else:
            msg.MessageAttachment.append(
                Attachment(AttachmentType="SYSTEM", AttachmentSystem=att)
            )
        msg.save(force_insert=True)
        self.message = msg

    def get_payload_json(self):
        try:
            super(AttachedEventInfo, self).get_payload_json()
            for a in self.message.MessageAttachment:
                if a.AttachmentType == "LINK":
                    a.AttachmentLink = [a.AttachmentLink]
            response = MessageSerializer(self.message)
            j_response = response.data
            j_response['EventType'] = self.current_event.EventType           
            return None
        except BaseException, e:
            self.logger.error("Payload serialization error: %s" % e.message)
            return json.dumps({'error', e.message})


class UserAddedInfo(AttachedEventInfo):
    def _configure_payload(self):
        super(UserAddedInfo, self)._configure_payload()
        self.message_text = '%@ {0} %@'.format(self.locale_helper.get_string_for_key('added').encode('utf-8')) if \
            self.kwargs.get('user_phone') != self.current_user.UserPhone else \
            '%@ {0}'.format(self.locale_helper.get_string_for_key('join').encode('utf-8'))
        self.members.append(
            {self.current_user.UserPhone: '{0} {1}'.format(self.current_user.UserFirstName.encode('utf-8'),
                                                           self.current_user.UserLastName.encode('utf-8'))})
        self.members.append({self.kwargs.get('user_phone'): self.kwargs.get('user_name')})
        self.payload['act'] = 'added'
        self.payload['user'] = self.kwargs.get('user_name')


class UsersAddedInfo(AttachedEventInfo):
    def _configure_payload(self):
        super(UsersAddedInfo, self)._configure_payload()
        self.message_text = '%@ {0} {1} {2}'.format(
            self.locale_helper.get_string_for_key('added').encode('utf-8'),
            self.kwargs.get('qty'),
            self.locale_helper.get_string_for_key('users_genitive_plural').encode('utf-8')
        )
        self.members.append(
            {self.current_user.UserPhone: '{0} {1}'.format(self.current_user.UserFirstName.encode('utf-8'),
                                                           self.current_user.UserLastName.encode('utf-8'))})
        self.payload['act'] = 'added'
        self.payload['qty'] = self.kwargs.get('qty')


class RequesterRevokedInfo(AttachedEventInfo):
    def _configure_payload(self):
        super(RequesterRevokedInfo, self)._configure_payload()
        self._revoke_request()
        self.message_text = '{0}'.format(
            self.locale_helper.get_string_for_key('revoked').encode('utf-8'))
        self.payload['act'] = 'revoked'


class UserRemovedInfo(AttachedEventInfo):
    def _configure_payload(self):
        super(UserRemovedInfo, self)._configure_payload()
        if self.kwargs.get('user_phone') != self.current_user.UserPhone:
            self.message_text = '%@ {0} %@'.format(self.locale_helper.get_string_for_key('removed').encode('utf-8'))
        else:
            if self.current_event.EventType == EVENT_TYPE_CHAT:
                self.message_text = '%@ {0}'.format(self.locale_helper.get_string_for_key('left_group').encode('utf-8'))
            else:
                self.message_text = '%@ {0}'.format(self.locale_helper.get_string_for_key('left_event').encode('utf-8'))
        self.members.append(
            {self.current_user.UserPhone: '{0} {1}'.format(self.current_user.UserFirstName.encode('utf-8'),
                                                           self.current_user.UserLastName.encode('utf-8'))})
        self.members.append({self.kwargs.get('user_phone'): self.kwargs.get('user_name')})
        self.payload['act'] = 'removed'
        self.payload['user'] = self.kwargs.get('user_name')


class UsersRemovedInfo(AttachedEventInfo):
    def _configure_payload(self):
        super(UsersRemovedInfo, self)._configure_payload()
        self.message_text = '%@ {0} {1} {2}'.format(
            self.locale_helper.get_string_for_key('removed').encode('utf-8'),
            self.kwargs.get('qty'),
            self.locale_helper.get_string_for_key('users_genitive_plural').encode('utf-8')
        )
        self.members.append(
            {self.current_user.UserPhone: '{0} {1}'.format(self.current_user.UserFirstName.encode('utf-8'),
                                                           self.current_user.UserLastName.encode('utf-8'))})
        self.payload['act'] = 'removed'
        self.payload['qty'] = self.kwargs.get('qty')


class ImageChangedInfo(AttachedEventInfo):
    def _configure_payload(self):
        super(ImageChangedInfo, self)._configure_payload()
        if self.current_event.EventType == EVENT_TYPE_CHAT:
            self.message_text = '%@ {0} {1}'.format(
                self.locale_helper.get_string_for_key('changed').encode('utf-8'),
                self.locale_helper.get_string_for_key('group_pic_accusative').encode('utf-8')
            )
        else:
            self.message_text = '%@ {0} {1}'.format(
                self.locale_helper.get_string_for_key('changed').encode('utf-8'),
                self.locale_helper.get_string_for_key('event_pic_accusative').encode('utf-8')
            )
        self.members.append(
            {self.current_user.UserPhone: '{0} {1}'.format(self.current_user.UserFirstName.encode('utf-8'),
                                                           self.current_user.UserLastName.encode('utf-8'))})
        self.payload['act'] = 'pic_changed'


class DateChangedInfo(AttachedEventInfo):
    def _configure_payload(self):
        super(DateChangedInfo, self)._configure_payload()
        self.message_text = '%@ {0} {1}'.format(
            self.locale_helper.get_string_for_key('changed').encode('utf-8'),
            self.locale_helper.get_string_for_key('event_date_accusative').encode('utf-8')
        )
        self.members.append(
            {self.current_user.UserPhone: '{0} {1}'.format(self.current_user.UserFirstName.encode('utf-8'),
                                                           self.current_user.UserLastName.encode('utf-8'))})
        self.payload['act'] = 'date_changed'


class LocationChangedInfo(AttachedEventInfo):
    def _configure_payload(self):
        super(LocationChangedInfo, self)._configure_payload()
        self.message_text = '%@ {0} {1}'.format(
            self.locale_helper.get_string_for_key('changed').encode('utf-8'),
            self.locale_helper.get_string_for_key('event_location').encode('utf-8')
        )
        self.members.append(
            {self.current_user.UserPhone: '{0} {1}'.format(self.current_user.UserFirstName.encode('utf-8'),
                                                           self.current_user.UserLastName.encode('utf-8'))})
        self.payload['act'] = 'geo_changed'


class TitleChangedInfo(AttachedEventInfo):
    def _configure_payload(self):
        super(TitleChangedInfo, self)._configure_payload()
        if self.current_event.EventType == EVENT_TYPE_CHAT:
            self.message_text = '%@ {0} {1}'.format(
                self.locale_helper.get_string_for_key('changed').encode('utf-8'),
                self.locale_helper.get_string_for_key('group_title').encode('utf-8')
            )
        else:
            self.message_text = '%@ {0} {1}'.format(
                self.locale_helper.get_string_for_key('changed').encode('utf-8'),
                self.locale_helper.get_string_for_key('event_title').encode('utf-8')
            )
        self.members.append(
            {self.current_user.UserPhone: '{0} {1}'.format(self.current_user.UserFirstName.encode('utf-8'),
                                                           self.current_user.UserLastName.encode('utf-8'))})
        self.payload['act'] = 'title_changed'
