import six
import logging

from network.ip import format_ipv6_addr
from openstack.utils import config_flags_parser

DEFAULT_OSLO_MESSAGING_DRIVER = "messagingv2"

class OSContextGenerator(object):
    """Base class for all context generators."""
    interfaces = []
    related = False
    complete = False
    missing_data = []

    def __call__(self):
        raise NotImplementedError

    def context_complete(self, ctxt):
        """Check for missing data for the required context data.
        Set self.missing_data if it exists and return False.
        Set self.complete if no missing data and return True.
        """
        # Fresh start
        self.complete = False
        self.missing_data = []
        for k, v in six.iteritems(ctxt):
            if v is None or v == '':
                if k not in self.missing_data:
                    self.missing_data.append(k)

        if self.missing_data:
            self.complete = False
            logging.info('Missing required data: %s' % ' '.join(self.missing_data))
        else:
            self.complete = True
        return self.complete

    def get_related(self):
        """Check if any of the context interfaces have relation ids.
        Set self.related and return True if one of the interfaces
        has relation ids.
        """
        # Fresh start
        self.related = False
        try:
            for interface in self.interfaces:
                if relation_ids(interface):
                    self.related = True
            return self.related
        except AttributeError as e:
            logging.info("{} {}"
                "".format(self, e))
            return self.related


class MirrorsConfigServiceContext(OSContextGenerator):
    """Context for mirrors.yaml template.

    Uses image-modifier relation if available to set
    modify_hook_scripts config value.

    """
    interfaces = ['simplestreams-image-service']

    def __call__(self, relation, config):
        logging.info("Generating template ctxt for simplestreams-image-service")

        modify_hook_scripts = []
        if relation.name == 'image-modifier':
            im = image_modifiers[0]
            try:
                modify_hook_scripts.append(relation.data['script-path'])

            except KeyError as ke:
                logging.info('relation {} yielded '
                            'exception {} - ignoring.'.format(repr(relation),
                                                              repr(ke)))

            # default no-op so that None still means "missing" for config
            # validation (see elsewhere)
            if len(modify_hook_scripts) == 0:
                modify_hook_scripts.append('/bin/true')

            return dict(mirror_list=config['mirror_list'],
                        modify_hook_scripts=', '.join(modify_hook_scripts),
                        name_prefix=config['name_prefix'],
                        content_id_template=config['content_id_template'],
                        use_swift=config['use_swift'],
                        region=config['region'],
                        cloud_name=config['cloud_name'],
                        user_agent=config['user_agent'],
                        custom_properties=config['custom_properties'],
                        hypervisor_mapping=config['hypervisor_mapping'])


class IdentityServiceContext(OSContextGenerator):
    interfaces = ['identity-service']

    def __call__(self, relation):
        logging.debug('Generating template context for identity-service')
        ctxt = {}
        for unit in relation.units:
            rdata = relation.data[unit]
            serv_host = rdata.get('service_host')
            serv_host = format_ipv6_addr(serv_host) or serv_host
            auth_host = rdata.get('auth_host')
            auth_host = format_ipv6_addr(auth_host) or auth_host
            svc_protocol = rdata.get('service_protocol') or 'http'
            auth_protocol = rdata.get('auth_protocol') or 'http'
            ctxt = {'service_port': rdata.get('service_port'),
                    'service_host': serv_host,
                    'auth_host': auth_host,
                    'auth_port': rdata.get('auth_port'),
                    'admin_tenant_name': rdata.get('service_tenant'),
                    'admin_user': rdata.get('service_username'),
                    'admin_password': rdata.get('service_password'),
                    'service_protocol': svc_protocol,
                    'auth_protocol': auth_protocol}
            if self.context_complete(ctxt):
                # NOTE(jamespage) this is required for >= icehouse
                # so a missing value just indicates keystone needs
                # upgrading
                ctxt['admin_tenant_id'] = rdata.get('service_tenant_id')
                return ctxt

        return {}


class SSLIdentityServiceContext(IdentityServiceContext):
    """Modify the IdentityServiceContext to include an SSL option.

    This is just a simple way of getting the CA to the
    glance-simplestreams-sync.py script.
    """
    def __call__(self, relation, config):
        ctxt = super(SSLIdentityServiceContext, self).__call__(relation)
        ssl_ca = config['ssl_ca']
        if ctxt and ssl_ca:
            ctxt['ssl_ca'] = ssl_ca
        return ctxt

class AMQPContext(OSContextGenerator):

    def __init__(self, ssl_dir=None, relation=None, rel_name='amqp',
		 relation_prefix=None, relation_id=None):
        self.ssl_dir = ssl_dir
        self.relation = relation
        self.relation_prefix = relation_prefix
        self.interfaces = [relation.name]

    def __call__(self, relation, config, bind_address):
        logging.debug('Generating template context for amqp')
        if self.relation_prefix:
            user_setting = '%s-rabbit-user' % (self.relation_prefix)
            vhost_setting = '%s-rabbit-vhost' % (self.relation_prefix)
        else:
            user_setting = 'rabbit-user'
            vhost_setting = 'rabbit-vhost'

        try:
            username = config[user_setting]
            vhost = config[vhost_setting]
        except KeyError as e:
            logging.error('Could not generate shared_db context. Missing required charm '
                'config options: %s.' % e)
            raise OSContextError

        ctxt = {}
        rids = [relation.id]
        for rid in rids:
            ha_vip_only = False
            self.related = True
            transport_hosts = None
            rabbitmq_port = '5672'
            for unit in relation.units:
                if 'clustered' in relation.data:
                    ctxt['clustered'] = True
                    vip = relation.data['vip']
                    vip = format_ipv6_addr(vip) or vip
                    ctxt['rabbitmq_host'] = vip
                    transport_hosts = [vip]
                else:
                    host = bind_address
                    host = format_ipv6_addr(host) or host
                    ctxt['rabbitmq_host'] = host
                    transport_hosts = [host]

                ctxt.update({
                    'rabbitmq_user': username,
                    'rabbitmq_password': relation.data['password'],
                    'rabbitmq_virtual_host': vhost,
                })

                ssl_port = relation.data['ssl_port']
                if ssl_port:
                    ctxt['rabbit_ssl_port'] = ssl_port
                    rabbitmq_port = ssl_port

                ssl_ca = relation.data['ssl_ca']
                if ssl_ca:
                    ctxt['rabbit_ssl_ca'] = ssl_ca

                if relation.data['ha_queues'] is not None:
                    ctxt['rabbitmq_ha_queues'] = True

                ha_vip_only = relation.data['ha-vip-only'] is not None

                if self.context_complete(ctxt):
                    if 'rabbit_ssl_ca' in ctxt:
                        if not self.ssl_dir:
                            logging.info("Charm not setup for ssl support but ssl ca "
                                "found")
                            break

                        ca_path = os.path.join(
                            self.ssl_dir, 'rabbit-client-ca.pem')
                        with open(ca_path, 'wb') as fh:
                            fh.write(b64decode(ctxt['rabbit_ssl_ca']))
                            ctxt['rabbit_ssl_ca'] = ca_path

                    # Sufficient information found = break out!
                    break

            # Used for active/active rabbitmq >= grizzly
            if (('clustered' not in ctxt or ha_vip_only) and
                    len(related_units(rid)) > 1):
                rabbitmq_hosts = []
                for unit in related_units(rid):
                    host = bind_address
                    host = format_ipv6_addr(host) or host
                    rabbitmq_hosts.append(host)

                rabbitmq_hosts = sorted(rabbitmq_hosts)
                ctxt['rabbitmq_hosts'] = ','.join(rabbitmq_hosts)
                transport_hosts = rabbitmq_hosts

            if transport_hosts:
                transport_url_hosts = ','.join([
                    "{}:{}@{}:{}".format(ctxt['rabbitmq_user'],
                                         ctxt['rabbitmq_password'],
                                         host_,
                                         rabbitmq_port)
                    for host_ in transport_hosts])
                ctxt['transport_url'] = "rabbit://{}/{}".format(
                    transport_url_hosts, vhost)

        oslo_messaging_flags = config['oslo-messaging-flags']
        if oslo_messaging_flags:
            ctxt['oslo_messaging_flags'] = config_flags_parser(
                oslo_messaging_flags)

        oslo_messaging_driver = conf.get(
            'oslo-messaging-driver', DEFAULT_OSLO_MESSAGING_DRIVER)
        if oslo_messaging_driver:
            ctxt['oslo_messaging_driver'] = oslo_messaging_driver

        notification_format = config.get('notification-format', None)
        if notification_format:
            ctxt['notification_format'] = notification_format

        notification_topics = config.get('notification-topics', None)
        if notification_topics:
            ctxt['notification_topics'] = notification_topics

        send_notifications_to_logs = config.get('send-notifications-to-logs', None)
        if send_notifications_to_logs:
            ctxt['send_notifications_to_logs'] = send_notifications_to_logs

        if not self.complete:
            return {}

        return ctxt
