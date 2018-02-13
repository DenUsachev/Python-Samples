import json
from multiprocessing import Process
from struct import *
from time import time

import tornado
import tornadoredis
from mongoengine import DoesNotExist
from tornado import websocket, httpserver, ioloop, web
from tornadoredis.pubsub import SocketIOSubscriber

from Api.models import User
from togetherapi.settings import DEBUG
from togetherapi.sockets import LISTEN, PROD_LISTEN
from togetherapi.utils import singleton, get_custom_logger, backgroundExec

__author__ = 'arclite'


class EchoWebSocket(websocket.WebSocketHandler):
    @backgroundExec(5)
    def poll(self):
        if self.ping_count >= 5:
            self.on_close()
        try:
            if not self.syncValue:
                self.renew_sync()
            bin_data = pack("%ds" % len(self.syncValue), self.syncValue)
            self.ping(bin_data)
            self.ping_count += 1
            self.logger.debug("Ping remote host with payload: %s", self.syncValue)
        except BaseException, ex:
            # self.logger.error("Can't ping remote host: %s", ex.message)
            self.poller_kill_handler.set()

    def __init__(self, application, request, **kwargs):
        super(EchoWebSocket, self).__init__(application, request, **kwargs)
        self.logger = get_custom_logger()
        self.user = None
        self.pubsub = SocketIOSubscriber(tornadoredis.Client())
        self.ping_count = 0
        self.payload = None
        self.syncValue = None
        self.poller_kill_handler = None

    def open(self):
        self.stream.set_nodelay(True)
        # self.logger.debug("WebSocket opened")
        self.payload = self.channel
        self.poller_kill_handler = self.poll()

    def on_message(self, message):
        try:
            self.write_message(message)
        except BaseException, e:
            self.write_message(json.dumps({"error": e.message}))
            self.close(-1, e.message)

    def sub(self):
        self.pubsub.subscribe(self.channel, self)

    def renew_sync(self):
        self.syncValue = str(int(time())).encode('utf-8')
        self.logger.debug("Sync value set: %s for channel %s." % (self.syncValue, self.channel))

    def unsub(self):
        if self.pubsub.is_subscribed:
            self.pubsub.unsubscribe(self.channel, self)
            self.pubsub.close()
            self.user.UserConnected = False
            self.user.save()
            self.logger.debug("Client unsubscribed")

    def on_pong(self, data):
        try:
            if data == self.syncValue:
                self.logger.debug("Ping ok: %s - connection is sync." % data)
                self.ping_count = 0
                self.renew_sync()
            else:
                self.logger.error(
                    "Ping error: %s - connection is out of sync (should be: %s)." % (data, self.syncValue))
                self.on_close()
                self.close()
                self.logger.error("Socket closed forcedly in cause of a network problem.")
        except BaseException, e:
            self.logger.debug("Got pong error %s" % e.message)
            self.on_close()

    def on_connection_close(self):
        super(EchoWebSocket, self).on_connection_close()
        self.on_close()

    def on_close(self):
        try:
            self.unsub()
            self.poller_kill_handler.set()
        except AttributeError:
            pass
            # self.logger.debug("WebSocket closed")

    def check_origin(self, origin):
        token = self.request.headers.get("X-User-Token")
        self.logger.debug("Token present:%s" % token)
        try:
            u = User.objects.get(UserToken=token)
            u.UserConnected = True
            u.save()
            self.user = u
            self.channel = u.UserPhone
            self.sub()
            return True
        except DoesNotExist:
            return False


application = tornado.web.Application([
    (r'/ws', EchoWebSocket),
])


@singleton
class SocketServerRunner:
    def __init__(self):
        self.proc_handler = None
        self.logger = get_custom_logger()
        self.logger.debug('Socket server runner initialized')

    def _proc_runner(self):
        http_server = tornado.httpserver.HTTPServer(application, ssl_options=None)
        if DEBUG:
            http_server.listen(LISTEN)
        else:
            http_server.listen(PROD_LISTEN)
        try:
            ioloop.IOLoop.instance().start()
        except Exception:
            pass

    def run_server(self):
        p = Process(target=self._proc_runner)
        self.proc_handler = p
        p.start()

    def __del__(self):
        if self.proc_handler is not None:
            self.proc_handler.join()
