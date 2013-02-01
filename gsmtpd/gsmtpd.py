#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Overview:
#
# This file implements the minimal SMTP protocol as defined in RFC 821.  It
# has a hierarchy of classes which implement the backend functionality for the
# smtpd.  A number of classes are provided:
#
#   SMTPServer - the base class for the backend.  Raises NotImplementedError
#   if you try to use it.
#

import sys
#import os
import errno
import gevent
from gevent.server import StreamServer
import functools
import time
import logging
import logging.handlers
from gevent import socket

__all__ = ["SMTPServer", "LMTPServer"]

program = sys.argv[0]
__version__ = 'Python Gevent SMTP server version 0.1'


logger = logging.getLogger('gsmtpd')
logger.setLevel(logging.DEBUG)
#handler = logging.handlers.SysLogHandler(address='/dev/log', facility="mail")
handler = logging.StreamHandler()
formatter = logging.Formatter("%(name)s:%(levelname)s:%(message)s")

handler.setFormatter(formatter)
logger.addHandler(handler)


class SMTPChannel(object):

    def __init__(self, server, conn, addr):
        self.__datastate = False
        self.__close = False
        self.__server = server
        self.__conn = conn
        self.__file = conn.makefile()
        self.__addr = addr
        self.__greeting = 0
        self.__mailfrom = None
        self.__rcpttos = []
        self.__fqdn = socket.getfqdn()
        try:
            self.__peer = conn.getpeername()
        except socket.error, err:
            # a race condition  may occur if the other end is closing
            # before we can get the peername
            self.close()
            if err[0] != errno.ENOTCONN:
                raise
            return
        logger.debug('Peer: %s:%s', *self.__peer)
        self.push('220 %s %s' % (self.__fqdn, __version__))
        self.chat()

    def push(self, msg):
        self.__conn.send("".join([msg, '\r\n']))

    def chat(self):
        body = []
        while not self.__close:
            line = self.__file.readline()
            if not line:
                logger.debug("client disconnected")
                break
            logger.debug('Data: %r', line)
            if not self.__datastate:
                line = line.strip()
                i = line.find(' ')
                if i < 0:
                    command = line.upper()
                    arg = None
                else:
                    command = line[:i].upper()
                    arg = line[i + 1:].strip()
                method = getattr(self, 'smtp_' + command, None)
                if not method:
                    self.push('502 Error: command "%s" not implemented' % command)
                    continue
                method(arg)
            else:
                if line != ".\r\n":
                    if line[:2] == "..":
                        body.append(line[1:])
                    else:
                        body.append(line)
                else:
                    statuses = self.__server.process_message(self.__peer,
                                                             self.__mailfrom,
                                                             self.__rcpttos,
                                                             "".join(body))
                    self.__rcpttos = []
                    self.__mailfrom = None
                    self.__datastate = False
                    if statuses:
                        for status in statuses:
                            if not status:
                                self.push('250 Ok')
                            else:
                                self.push(status)
                    else:
                        for n in xrange(len(self.__rcpttos) + 1):
                            self.push('250 Ok')
        logger.info("closing connection")
        self.__file.close()
        self.__conn.close()

    # SMTP and ESMTP commands
    def smtp_HELO(self, arg):
        if not arg:
            self.push('501 Syntax: HELO hostname')
            return
        if self.__greeting:
            self.push('503 Duplicate HELO/EHLO')
        else:
            self.__greeting = arg
            self.push('250 %s' % self.__fqdn)

    def smtp_NOOP(self, arg):
        if arg:
            self.push('501 Syntax: NOOP')
        else:
            self.push('250 Ok')

    def smtp_QUIT(self, arg):
        # args is ignored
        self.push('221 Bye')
        self.__close = True

    # factored
    def __getaddr(self, keyword, arg):
        address = None
        keylen = len(keyword)
        if arg[:keylen].upper() == keyword:
            address = arg[keylen:].strip()
            if not address:
                pass
            elif address[0] == '<' and address[-1] == '>' and address != '<>':
                # Addresses can be in the form <person@dom.com> but watch out
                # for null address, e.g. <>
                address = address[1:-1]
        return address

    def smtp_MAIL(self, arg):
        logger.debug('===> MAIL %s', arg)
        address = self.__getaddr('FROM:', arg) if arg else None
        if not address:
            self.push('501 Syntax: MAIL FROM:<address>')
            return
        if self.__mailfrom:
            self.push('503 Error: nested MAIL command')
            return
        self.__mailfrom = address
        logger.debug('sender: %s', self.__mailfrom)
        self.push('250 Ok')

    def smtp_RCPT(self, arg):
        logger.debug('===> RCPT %s', arg)
        if not self.__mailfrom:
            self.push('503 Error: need MAIL command')
            return
        address = self.__getaddr('TO:', arg) if arg else None
        if not address:
            self.push('501 Syntax: RCPT TO: <address>')
            return
        self.__rcpttos.append(address)
        logger.debug('recips: %s', self.__rcpttos)
        self.push('250 Ok')

    def smtp_RSET(self, arg):
        if arg:
            self.push('501 Syntax: RSET')
            return
        # Resets the sender, recipients, and data, but not the greeting
        self.__mailfrom = None
        self.__rcpttos = []
        self.push('250 Ok')

    def smtp_DATA(self, arg):
        if not self.__rcpttos:
            self.push('503 Error: need RCPT command')
            return
        if arg:
            self.push('501 Syntax: DATA')
            return
        self.__datastate = True
        self.push('354 End data with <CR><LF>.<CR><LF>')


class LMTPChannel(SMTPChannel):
    def smtp_LHLO(self, arg):
        self.smtp_HELO(arg)


class SMTPServer(object):
    def __init__(self, localaddr):
        self._localaddr = localaddr
        self.server = StreamServer(localaddr, self._get_channel())

        logger.info('%s started at %s\n\tLocal addr: %s\n' % (
            self.__class__.__name__, time.ctime(time.time()),
            localaddr))

    def _get_channel(self):
        return functools.partial(SMTPChannel, self)

    def serve_forever(self):
        self.server.serve_forever()

    # API for "doing something useful with the message"
    def process_message(self, peer, mailfrom, rcpttos, data):
        """Override this abstract method to handle messages from the client.

        peer is a tuple containing (ipaddr, port) of the client that made the
        socket connection to our smtp port.

        mailfrom is the raw address the client claims the message is coming
        from.

        rcpttos is a list of raw addresses the client wishes to deliver the
        message to.

        data is a string containing the entire full text of the message,
        headers (if supplied) and all.  It has been `de-transparencied'
        according to RFC 821, Section 4.5.2.  In other words, a line
        containing a `.' followed by other text has had the leading dot
        removed.

        This function should return None, for a normal `250 Ok' response;
        otherwise it returns the desired response string in RFC 821 format.

        """
        raise NotImplementedError


class LMTPServer(SMTPServer):
    def _get_channel(self):
        return functools.partial(LMTPChannel, self)

    def process_message(self, peer, mailfrom, rcpttos, data):
        """Override this abstract method to handle messages from the client.

        This function can return None, for a normal "250 Ok"response;
        otherwise it returns the desired response as a list
        for each recipient

        """
        raise NotImplementedError


if __name__ == "__main__":
    class TestServer(SMTPServer):
        def process_message(self, peer, mailfrom, rcpttos, data):
            print peer, mailfrom, rcpttos, len(data)

    s = TestServer(("127.1", 4000))
    s.serve_forever()
