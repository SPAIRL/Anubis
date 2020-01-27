from sqlalchemy.exc import IntegrityError
from email.mime.text import MIMEText
from dataclasses import dataclass
from functools import wraps
from flask import request
from smtplib import SMTP
from redis import Redis
from os import environ
from rq import Queue

from .jobs import test_repo
from .models import Events
from .app import db


"""
We will use rq to enqueue and dequeue jobs.
"""
def enqueue(func, *args):
    """
    Enqueues a job on the redis cache

    :func callable: any callable object
    :args tuple: ordered arguments for function
    """
    with Redis(host='redis') as conn:
        q = Queue(connection=conn)
        q.enqueue(func, *args)


def enqueue_webhook_job(*args):
    """
    Enqueues a test job

    :repo_url str: github repo url (eg https://github.com/os3224/...)
    """
    enqueue(
        test_repo,
        *args
    )


def get_request_ip():
    """
    Since we are using a request forwarder,
    the real client IP will be added as a header.
    This function will search the expected headers
    to find that ip.
    """
    def check(header):
        """get header from request else empty string"""
        return request.headers[
            header
        ] if header in request.headers else ''

    def check_(headers, n=0):
        """check headers based on ordered piority"""
        if n == len(headers):
            return ''
        return check(headers[n]) or check_(headers, n+1)

    return str(check_([
        'x-forwarded-for', # highest priority
        'X-Forwarded-For',
        'x-real-ip',
        'X-Real-Ip',       # lowest priority
    ]) or request.remote_addr or 'N/A')


def log_event(log_type, message_func):
    """
    Use this to decorate a route and add logging.
    The message_func should be a calleble object
    that returns a string to be logged.

    eg.

    @log_event('LOG-TYPE', lambda: 'somefunction was just called')
    def somefunction(arg1, arg2):
        ....

    :log_type str: log type to noted in event
    :message_func callable: function to return message to be logged
    """
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            prefix='{} :: '.format(
                get_request_ip(),
            )
            event = Events(
                type=log_type,
                message=prefix + message_func()
            )
            db.session.add(event)
            try:
                db.session.commit()
            except IntegrityError as e:
                print('EVENT LOG ERROR', e)
            return function(*args, **kwargs)
        return wrapper
    return decorator


def send_noreply_email(msg, subject, to):
    """
    Use this function to send a noreply email to a user (ie student).

    * This will only work on the computer that has the dns pointed to it (ie the server)

    If you set up the dns with namecheap, you can really easily just set
    the email dns setting to private email. Once that is set, it configures
    all the spf stuff for you. Doing to MX and spf records by hand are super
    annoying.

    eg:
    send_noreply_email('this is the message', 'this is the subject', 'netid@nyu.edu')

    :msg str: email body or message to send
    :subject str: subject for email
    :to str: recipient of email (should be their nyu email)
    """

    if environ.get('DEBUG', False):
        return

    msg = MIMEText(msg, "plain")
    msg["Subject"] = subject

    msg["From"] = "dev.null@nyu.singles"
    msg["To"] = to

    s = SMTP("smtp")
    s.send_message(msg)
    s.quit()