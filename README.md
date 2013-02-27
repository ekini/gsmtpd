## gsmtpd

_gsmtpd_ is a Python library implementing SMTP and LMTP protocols. It is similar to smtpd shipped with Python but it's based on gevent instead of asyncore.

For LMTPServer `process_message` function can return `None` or a list of SMTP statuses for each recipient in the same order.

## Examples

```python
from gsmtpd import SMTPServer

class TestServer(SMTPServer):
def process_message(self, peer, mailfrom, rcpttos, data):
    print peer, mailfrom, rcpttos, len(data)

s = TestServer(("127.1", 4000))
s.serve_forever()
```

For LMTP:
```python
from gsmtpd import LMTPServer

class TestServer(LMTPServer):
def process_message(self, peer, mailfrom, rcpttos, data):
    for rcpt in rcpttos:
        print peer, mailfrom, rcpt, len(data)
        yield "250 Ok"

s = TestServer(("127.1", 4000))
s.serve_forever()
```

