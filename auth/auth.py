from mongoengine import DoesNotExist, MultipleObjectsReturned

from togetherapi.utils import get_custom_logger

__author__ = 'Usachev'

from rest_framework import authentication
from rest_framework import exceptions
from Api.models import User

logger = get_custom_logger()


class CustomAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        token = request.META.get('HTTP_X_USER_TOKEN')
        if token is None:
            # logger.error('Token not present')
            raise exceptions.AuthenticationFailed('Token not present')
        else:
            # logger.debug('Incoming token: ' + token)
            try:
                user = User.objects.get(UserToken=token)
                if user.UserEnabled:
                    return user, token
                elif user.UserEnabled is None:
                    user.UserEnabled = True
                    user.save()
                    return user, token
                else:
                    # logger.error('User account is disabled')
                    raise exceptions.AuthenticationFailed('User with token %s is disabled' % token)
            except MultipleObjectsReturned:
                # logger.error('User token %s is ambiguous.' % token)
                raise exceptions.AuthenticationFailed('User token %s is ambiguous.' % token)
            except DoesNotExist:
                # logger.error('Token not found')
                raise exceptions.AuthenticationFailed('User with token %s were not found' % token)
