# Copyright 2014-2020 Canonical Limited.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import six

from ubuntu.apt import apt_install, apt_update

try:
    import netifaces
except ImportError:
    apt_update()
    if six.PY2:
        apt_install(['python-netifaces'])
    else:
        apt_install(['python3-netifaces'])
    import netifaces

try:
    import netaddr
except ImportError:
    apt_update()
    if six.PY2:
        apt_install(['python-netaddr'])
    else:
        apt_install(['python3-netaddr'])
    import netaddr


def is_ipv6(address):
    """Determine whether provided address is IPv6 or not."""
    try:
        address = netaddr.IPAddress(address)
    except netaddr.AddrFormatError:
        # probably a hostname - so not an address at all!
        return False

    return address.version == 6


def format_ipv6_addr(address):
    """If address is IPv6, wrap it in '[]' otherwise return None.

    This is required by most configuration files when specifying IPv6
    addresses.
    """
    if is_ipv6(address):
        return "[%s]" % address

    return None
