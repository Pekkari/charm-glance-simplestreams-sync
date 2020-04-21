#!/usr/bin/env python3
#
# Copyright 2020 Canonical Ltd
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

"""Operator Charm main library."""
# Load modules from lib directory
import sys
import logging
sys.path.append('lib')

from ops.main import main
from ops.charm import CharmBase  # noqa:E402
from ops.framework import StoredState  # noqa:E402
from ops.model import (  # noqa:E402
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus
)

from ubuntu.apt import add_source, apt_install, apt_update
from openstack.utils import get_os_codename_package
from nagios.nrpe import NRPE, get_nagios_hostname

from interfaces import (
    IdentityServiceInterfaceRequires
)

from openstack.context import (
    OSContextGenerator,
    MirrorsConfigServiceContext,
    IdentityServiceContext,
    SSLIdentityServiceContext,
    AMQPContext
)
from openstack.templating import OSConfigRenderer

import glob
import os
import shutil
import sys

CONF_FILE_DIR = '/etc/glance-simplestreams-sync'
USR_SHARE_DIR = '/usr/share/glance-simplestreams-sync'

MIRRORS_CONF_FILE_NAME = os.path.join(CONF_FILE_DIR, 'mirrors.yaml')
ID_CONF_FILE_NAME = os.path.join(CONF_FILE_DIR, 'identity.yaml')

SYNC_SCRIPT_NAME = "glance-simplestreams-sync.py"
SCRIPT_WRAPPER_NAME = "glance-simplestreams-sync.sh"

CRON_D = '/etc/cron.d/'
CRON_JOB_FILENAME = 'glance_simplestreams_sync'
CRON_POLL_FILENAME = 'glance_simplestreams_sync_fastpoll'
CRON_POLL_FILEPATH = os.path.join(CRON_D, CRON_POLL_FILENAME)

ERR_FILE_EXISTS = 17


class GlanceSimplestreamsSyncCharm(CharmBase):
    """Class reprisenting this Operator charm."""

    _stored = StoredState()

    PACKAGES = ['python3-simplestreams', 'python3-glanceclient',
                'python3-yaml', 'python3-keystoneclient',
                'python3-kombu',
                'python3-swiftclient', 'ubuntu-cloudimage-keyring']

    def __init__(self, *args):
        """Initialize charm and configure states and events to observe."""
        super().__init__(*args)
        # self.unit = self.framework.model.unit
        # -- standard hook observation
        self.framework.observe(self.on.start, self)
        self.framework.observe(self.on.install, self)
        self.framework.observe(self.on.config_changed, self)
        self.framework.observe(self.on.upgrade_charm, self)
        # -- example action observation
        # self.framework.observe(self.on.example_action, self)
        # -- example relation / interface observation, disabled by default
        self.framework.observe(self.on.identity_service_relation_joined, self)
        self.framework.observe(self.on.identity_service_relation_changed, self)
        self.keystone = IdentityServiceInterfaceRequires(self, 'identity-service')

    def on_start(self, event):
        """Handle start state."""
        # do things on start, like install packages
        # once done, mark state as done
        self.unit.status = MaintenanceStatus("Installing charm software")
        # perform installation and common configuration bootstrap tasks
        self.unit.status = MaintenanceStatus("Software installed, performing configuration")
        self._stored._started = True

    def on_config_changed(self, event):
        """Handle config changed hook."""
        # if software is installed and DB related, configure software
        try:
            if self._stored._started and self._stored._identity_service_relation_joined:
                # configure your software
                self.config = self.model.config
                self.unit.status = ActiveStatus("Configuring software")
                configs = self._get_configs(event)
                configs.write(MIRRORS_CONF_FILE_NAME)
                self._ensure_perms()

                self.update_nrpe_config(event.relation)

                config = self.model.config()

                if config.changed('frequency'):
                    logging.info("'frequency' changed, removing cron job")
                    uninstall_cron_script()

                if config['run']:
                    logging.info("installing to cronjob to "
                                "/etc/cron.{}".format(config['frequency']))
                    logging.info("installing {} for polling".format(CRON_POLL_FILEPATH))
                    self._install_cron_poll()
                    self._install_cron_script()
                else:
                    logging.info("'run' set to False, removing cron jobs")
                    self._uninstall_cron_script()
                    self._uninstall_cron_poll()

                self._stored._configured = True
            else:
                logging.info("Waiting for keystone to be related.")
        except AttributeError:
            logging.info("Waiting on configuration to run, and keystone to be related.")
            self.unit.status = BlockedStatus("Waiting for keystone to be related")

    def update_nrpe_config(self, relation=None):
        hostname = get_nagios_hostname(relation)
        if relation:
            nrpe_setup = NRPE(relation, self.model.config, hostname=hostname)
            nrpe_setup.write()

    def on_upgrade_charm(self, event):
        self.on_install(event)
        self._ensure_perms()

    def on_identity_service_relation_joined(self, event):
        config = self.model.config

        # Generate temporary bogus service URL to make keystone charm
        # happy. The sync script will replace it with the endpoint for
        # swift, because when this hook is fired, we do not yet
        # necessarily know the swift endpoint URL (it might not even exist
        # yet).

        url = 'http://' + self.model.get_binding('public').network.bind_address

        event.relation.data[self.model.unit]['service'] = 'image-stream'
        event.relation.data[self.model.unit]['region'] = config['region']
        event.relation.data[self.model.unit]['public_url'] = url
        event.relation.data[self.model.unit]['admin_url'] = url
        event.relation.data[self.model.unit]['internal_url'] = url
        self._stored._identity_service_relation_joined = True

    def on_identity_service_relation_changed(self, event):
        configs = self._get_configs(event)
        configs.write(ID_CONF_FILE_NAME)
        self._ensure_perms()

    def on_install(self, event):
        add_source(self.model.config['source'], self.model.config['key'])
        for directory in [CONF_FILE_DIR, USR_SHARE_DIR]:
            logging.info(f"creating config dir at {directory}")
            if not os.path.isdir(directory):
                if os.path.exists(directory):
                    logging.error(f"error: {directory} exists but is not a directory."
                                " exiting.")
                    return
                os.mkdir(directory)

        if not self.model.config["use_swift"]:
            logging.info('Configuring for local hosting of product stream.')
            self.PACKAGES += ["apache2"]

        apt_update()
        apt_install(self.PACKAGES)
        self._stored._installed = True
        logging.info('end install hook.')

    def _get_configs(self, event):
        configs = OSConfigRenderer(templates_dir='templates/',
                                   openstack_release=self._get_release())

        mirror_config_service_context = MirrorsConfigServiceContext()
        ssl_identity_service_context = SSLIdentityServiceContext()
        amqp_context = AMQPContext()
        configs.register(MIRRORS_CONF_FILE_NAME, [
            mirror_config_service_context(event.relation, self.model.config)
        ])
        configs.register(ID_CONF_FILE_NAME,
            [
                ssl_identity_service_context(event.relation, self.model.config),
                amqp_context(
                    event.relation,
                    self.model.config,
                    self.model.get_binding('public').network.bind_address
                ),
                self.model.unit
            ]
        )
        return configs

    def _get_release(self):
        return get_os_codename_package('glance-common', self.model.config['source'],
            fatal=False)

    def _ensure_perms(self):
        """Ensure gss file permissions."""
        if os.path.isfile(ID_CONF_FILE_NAME):
            os.chmod(ID_CONF_FILE_NAME, 0o640)

        if os.path.isfile(MIRRORS_CONF_FILE_NAME,):
            os.chmod(MIRRORS_CONF_FILE_NAME, 0o640)

    def _install_cron_poll(self):
        "Installs /etc/cron.d every-minute job in crontab for quick polling."
        poll_file_source = os.path.join("files", CRON_POLL_FILENAME)
        shutil.copy(poll_file_source, CRON_D)

    def _install_cron_script(self):
        """Installs cron job in /etc/cron.$frequency/ for repeating sync

        Script is not a template but we always overwrite, to ensure it is
        up-to-date.

        """
        for fn in [SYNC_SCRIPT_NAME, SCRIPT_WRAPPER_NAME]:
            shutil.copy(os.path.join("files", fn), USR_SHARE_DIR)

        config = self.model.config
        installed_script = os.path.join(USR_SHARE_DIR, SCRIPT_WRAPPER_NAME)
        linkname = '/etc/cron.{f}/{s}'.format(f=config['frequency'],
                                              s=CRON_JOB_FILENAME)
        try:
            logging.info("Creating symlink: %s -> %s" % (installed_script,
                                                        linkname))
            os.symlink(installed_script, linkname)
        except OSError as ex:
            if ex.errno == ERR_FILE_EXISTS:
                logging.info('symlink %s already exists' % linkname)
            else:
                raise ex

    def _uninstall_cron_script(self):
        "Removes sync program from any cron place it might be"
        for fn in glob.glob("/etc/cron.*/" + CRON_JOB_FILENAME):
            if os.path.exists(fn):
                os.remove(fn)

    def _uninstall_cron_poll(self):
        "Removes cron poll"
        if os.path.exists(CRON_POLL_FILEPATH):
            os.remove(CRON_POLL_FILEPATH)

if __name__ == '__main__':
    main(GlanceSimplestreamsSyncCharm)
