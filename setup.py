import os
from setuptools import setup

setup(
    name = "gsmtpd",
    version = "0.0.3",
    author = "Eugene Dementiev",
    author_email = "eugene@dementiev.eu",
    description = ("SMTP server based on gevent"),
    license = "BSD",
    keywords = "gevent smtpd",
    url = "http://dementiev.eu",
    packages=['gsmtpd'],
    install_requires=["gevent"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Topic :: Utilities",
        "License :: OSI Approved :: BSD License",
    ],
)
