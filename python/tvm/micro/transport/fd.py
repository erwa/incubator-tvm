# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Defines an implementation of Transport that uses file descriptors."""

import fcntl
import os
import select
import time
from .base import Transport, TransportTimeouts, TransportClosedError, IoTimeoutError


class FdConfigurationError(Exception):
    """Raised when specified file descriptors can't be placed in non-blocking mode."""


class FdTransport(Transport):
    """A Transport implementation that implements timeouts using non-blocking I/O."""

    @classmethod
    def _validate_configure_fd(cls, fd):
        fd = fd if isinstance(fd, int) else fd.fileno()
        flag = fcntl.fcntl(fd, fcntl.F_GETFL)
        if flag & os.O_NONBLOCK != 0:
            return fd

        flag = fcntl.fcntl(fd, fcntl.F_SETFL, os.O_NONBLOCK | flag)
        if flag & os.O_NONBLOCK == 0:
            raise FdConfigurationError('Cannot set file descriptor {fd} to non-blocking')
        return fd

    def __init__(self, read_fd, write_fd):
        self.read_fd = self._validate_configure_fd(read_fd)
        self.write_fd = self._validate_configure_fd(write_fd)

    def open(self):
        pass

    def close(self):
        if self.read_fd is not None:
            os.close(self.read_fd)
        if self.write_fd is not None:
            os.close(self.write_fd)

    def _await_ready(self, rlist, wlist, timeout_sec=None, end_time=None):
        if end_time is None:
            return

        if timeout_sec is None:
            timeout_sec = max(0, end_time - time.monotonic())
        rlist, wlist, xlist = select.select(rlist, wlist, rlist + wlist, timeout_sec)
        if not rlist and not wlist and not xlist:
            raise IoTimeoutError()
        elif xlist:
            return True

    def read(self, n, timeout_sec):
        end_time = None if timeout_sec is None else time.monotonic() + timeout_sec

        self._await_ready([self.read_fd], [], end_time=end_time)
        to_return = os.read(self.read_fd, n)

        if not to_return:
            self.close()
            raise TransportClosedError()

        return to_return

    def write(self, data, timeout_sec):
        end_time = None if timeout_sec is None else time.monotonic() + timeout_sec

        data_len = len(data)
        while data:
            self._await_ready(end_time, [], [self.write_fd])
            num_written = os.write(self.write_fd, data)
            if not num_written:
                self.close()
                raise TransportClosedError()

            data = data[num_written:]

        return data_len
