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

import logging
import yaml

from collections import OrderedDict

from ubuntu.apt import apt_cache

OPENSTACK_RELEASES = (
    'mitaka',
    'newton',
    'ocata',
    'pike',
    'queens',
    'rocky',
    'stein',
    'train',
    'ussuri',
)

UBUNTU_OPENSTACK_RELEASE = OrderedDict([
    ('xenial', 'mitaka'),
    ('yakkety', 'newton'),
    ('zesty', 'ocata'),
    ('artful', 'pike'),
    ('bionic', 'queens'),
    ('cosmic', 'rocky'),
    ('disco', 'stein'),
    ('eoan', 'train'),
    ('focal', 'ussuri'),
])

def get_os_codename_package(package, origin=None, fatal=True):
    '''Derive OpenStack release codename from an installed package.'''

    if snap_install_requested(origin):
        cmd = ['snap', 'list', package]
        try:
            out = subprocess.check_output(cmd)
            if six.PY3:
                out = out.decode('UTF-8')
        except subprocess.CalledProcessError:
            return None
        lines = out.split('\n')
        for line in lines:
            if package in line:
                # Second item in list is Version
                return line.split()[1]

    cache = apt_cache()

    try:
        pkg = cache[package]
    except Exception:
        if not fatal:
            return None
        # the package is unknown to the current apt cache.
        e = 'Could not determine version of package with no installation '\
            'candidate: %s' % package
        error_out(e)

    if not pkg.current_ver:
        if not fatal:
            return None
        # package is known, but no version is currently installed.
        e = 'Could not determine version of uninstalled package: %s' % package
        error_out(e)

    vers = apt.upstream_version(pkg.current_ver.ver_str)
    if 'swift' in pkg.name:
        # Fully x.y.z match for swift versions
        match = re.match(r'^(\d+)\.(\d+)\.(\d+)', vers)
    else:
        # x.y match only for 20XX.X
        # and ignore patch level for other packages
        match = re.match(r'^(\d+)\.(\d+)', vers)

    if match:
        vers = match.group(0)

    # Generate a major version number for newer semantic
    # versions of openstack projects
    major_vers = vers.split('.')[0]
    # >= Liberty independent project versions
    if (package in PACKAGE_CODENAMES and
            major_vers in PACKAGE_CODENAMES[package]):
        return PACKAGE_CODENAMES[package][major_vers]

def snap_install_requested(origin=None):
    """ Determine if installing from snaps
    If openstack-origin is of the form snap:track/channel[/branch]
    and channel is in SNAPS_CHANNELS return True.
    """
    if not origin.startswith('snap:'):
        return False

    _src = origin[5:]
    if '/' in _src:
        channel = _src.split('/')[1]
    else:
        # Handle snap:track with no channel
        channel = 'stable'
    return valid_snap_channel(channel)

def config_flags_parser(config_flags):
    """Parses config flags string into dict.

    This parsing method supports a few different formats for the config
    flag values to be parsed:

      1. A string in the simple format of key=value pairs, with the possibility
         of specifying multiple key value pairs within the same string. For
         example, a string in the format of 'key1=value1, key2=value2' will
         return a dict of:

             {'key1': 'value1', 'key2': 'value2'}.

      2. A string in the above format, but supporting a comma-delimited list
         of values for the same key. For example, a string in the format of
         'key1=value1, key2=value3,value4,value5' will return a dict of:

             {'key1': 'value1', 'key2': 'value2,value3,value4'}

      3. A string containing a colon character (:) prior to an equal
         character (=) will be treated as yaml and parsed as such. This can be
         used to specify more complex key value pairs. For example,
         a string in the format of 'key1: subkey1=value1, subkey2=value2' will
         return a dict of:

             {'key1', 'subkey1=value1, subkey2=value2'}

    The provided config_flags string may be a list of comma-separated values
    which themselves may be comma-separated list of values.
    """
    # If we find a colon before an equals sign then treat it as yaml.
    # Note: limit it to finding the colon first since this indicates assignment
    # for inline yaml.
    colon = config_flags.find(':')
    equals = config_flags.find('=')
    if colon > 0:
        if colon < equals or equals < 0:
            return ordered(yaml.safe_load(config_flags))

    if config_flags.find('==') >= 0:
        logging.error("config_flags is not in expected format (key=value)")
        raise OSContextError

    # strip the following from each value.
    post_strippers = ' ,'
    # we strip any leading/trailing '=' or ' ' from the string then
    # split on '='.
    split = config_flags.strip(' =').split('=')
    limit = len(split)
    flags = OrderedDict()
    for i in range(0, limit - 1):
        current = split[i]
        next = split[i + 1]
        vindex = next.rfind(',')
        if (i == limit - 2) or (vindex < 0):
            value = next
        else:
            value = next[:vindex]

        if i == 0:
            key = current
        else:
            # if this not the first entry, expect an embedded key.
            index = current.rfind(',')
            if index < 0:
                logging.error("Invalid config value(s) at index %s" % (i))
                raise OSContextError
            key = current[index + 1:]

        # Add to collection.
        flags[key.strip(post_strippers)] = value.rstrip(post_strippers)

    return flags
