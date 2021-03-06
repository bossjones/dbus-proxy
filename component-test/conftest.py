
# Copyright (C) 2013-2016 Pelagicore AB  <joakim.gross@pelagicore.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor,
# Boston, MA  02110-1301, USA.
#
# For further information see LICENSE


import pytest

import os
from os import environ
import sys
import tempfile
from time import sleep
from subprocess import Popen, call


""" Component test fixtures.

    This module makes the following assumptions:

    * py.test is invoked from the same directory as this module is located
    * start_outside_service.py is located in the same directory
    * dbus-proxy is found in a build/ directory one level above, i.e. "../build/dbus-proxy"
"""


OUTSIDE_SOCKET = "/tmp/dbus_proxy_outside_socket"
INSIDE_SOCKET = "/tmp/dbus_proxy_inside_socket"


# Setup an environment for the fixtures to share so the bus address is the same for all
environment = environ.copy()
environment["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + OUTSIDE_SOCKET


@pytest.fixture(scope="function")
def session_bus(request):
    """ Create a session bus.

        The dbus-deamon will be torn down at the end of the test.
    """
    # TODO: Parametrize the socket path.

    dbus_daemon = None
    # The 'exec' part is a workaround to make the whole process group be killed
    # later when kill() is caled and not just the shell. This is only needed when
    # 'shell' is set to True like in the later Popen() call below.
    start_dbus_daemon_command = [
        "exec",
        " dbus-daemon",
        " --session",
        " --nofork",
        " --address=" + "unix:path=" + OUTSIDE_SOCKET
    ]
    try:
        # For some reason shell needs to be set to True, which is the reason the command
        # is passed as a string instead as an argument list, as recommended in the docs.
        dbus_daemon = Popen(
            "".join(start_dbus_daemon_command),
            env=environment,
            shell=True,
            stdout=sys.stdout)
        # Allow time for the bus daemon to start
        sleep(0.3)
    except OSError as e:
        print "Error starting dbus-daemon: " + str(e)
        sys.exit(1)

    def teardown():
        dbus_daemon.kill()
        os.remove(OUTSIDE_SOCKET)

    request.addfinalizer(teardown)


@pytest.fixture(scope="function")
def service_on_outside(request):
    """ Start the service on the "outside" as seen from the proxy.

        The service is torn down at the end of the test.
    """
    # TODO: Make it more robust w.r.t. where to find the service file.

    outside_service = None
    try:
        outside_service = Popen(
            [
                "python",
                "service_stubs.py"
            ],
            env=environment,
            stdout=sys.stdout)
        # Allow time for the service to show up on the bus before consuming tests
        # can try to use it.
        sleep(0.3)
    except OSError as e:
        print "Error starting service on outside: " + str(e)
        sys.exit(1)

    def teardown():
        outside_service.kill()

    request.addfinalizer(teardown)


@pytest.fixture(scope="function")
def dbus_proxy(request):
    """ Start dbus-proxy.

        The dbus-proxy is torn down at the end of the test.
    """
    # TODO: Make bus type parametrized so we can use the system bus as well.
    # TODO: Make path to dbus-proxy parametrized.

    dbus_proxy = None

    # We later redirect a named pipe to dbus-proxy (compared to redirecting a file containing
    # the configuration). This so we can defer passing the config to a later stage so the
    # consuming test can be responsible for that.
    tempdir = tempfile.mkdtemp()
    fifo_filename = os.path.join(tempdir, "dbus_proxy_fifo")
    try:
        os.mkfifo(fifo_filename)
    except OSError as e:
        print "Error creating pipe for dbus-proxy fixture" + str(e)

    # The 'exec' part is a workaround to make the whole process group be killed
    # later when kill() is caled and not just the shell. This is only needed when
    # 'shell' is set to True like in the later Popen() call below.
    start_proxy_command = [
        "exec",
        " ../build/dbus-proxy",
        " " + INSIDE_SOCKET,
        " session",
        " <",
        fifo_filename
    ]

    try:
        # For some reason shell needs to be set to True, which is the reason the command
        # is passed as a string instead as an argument list, as recommended in the docs.
        dbus_proxy = Popen(
            "".join(start_proxy_command),
            env=environment,
            shell=True,
            stdout=sys.stdout)
    except OSError as e:
        print "Error starting dbus-proxy: " + str(e)
        sys.exit(1)

    def teardown():
        dbus_proxy.kill()
        # dbus-proxy creates the socket passed to it as argument at startup
        os.remove(INSIDE_SOCKET)
        os.remove(fifo_filename)
        os.rmdir(tempdir)

    request.addfinalizer(teardown)

    return DBusProxyHelper(fifo_filename)


class DBusProxyHelper(object):
    """ This helper is used by the tests to interact with dbus-proxy.

        Currently the only thing the tests needs/can do is to pass
        a configuration string to dbus-proxy.
    """

    def __init__(self, fifo):
        self.__fifo = fifo
        # Tests should get the socket paths from here
        self.INSIDE_SOCKET = "unix:path=" + INSIDE_SOCKET
        self.OUTSIDE_SOCKET = "unix:path=" + OUTSIDE_SOCKET

    def set_config(self, config):
        """ Write json config to dbus-proxy
        """
        with open(self.__fifo, "w") as fh:
            fh.write(config)
        # Allow some time for the proxy to be setup before tests start using the
        # "inside" socket.
        sleep(0.3)
