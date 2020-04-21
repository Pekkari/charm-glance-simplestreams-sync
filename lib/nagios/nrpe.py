import logging
import yaml

class NRPE(object):
    nagios_logdir = '/var/log/nagios'
    nagios_exportdir = '/var/lib/nagios/export'
    nrpe_confdir = '/etc/nagios/nrpe.d'
    homedir = '/var/lib/nagios'  # home dir provided by nagios-nrpe-server

    def __init__(self, relation, config, hostname=None, primary=True):
        super(NRPE, self).__init__()
        self.config = config
        self.primary = primary
        self.nagios_context = self.config['nagios_context']
        if 'nagios_servicegroups' in self.config and self.config['nagios_servicegroups']:
            self.nagios_servicegroups = self.config['nagios_servicegroups']
        else:
            self.nagios_servicegroups = self.nagios_context
        self.unit_name = relation.data.our_unit.replace('/', '-')
        if hostname:
            self.hostname = hostname
        else:
            nagios_hostname = get_nagios_hostname()
            if nagios_hostname:
                self.hostname = nagios_hostname
            else:
                self.hostname = "{}-{}".format(self.nagios_context, self.unit_name)
        self.checks = []
        # Iff in an nrpe-external-master relation hook, set primary status
        if relation:
            logging.info("Setting charm primary status {}".format(primary))
            for rid in relation:
                relation.data[self.model.unit]['primary'] = self.primary
        self.remove_check_queue = set()

    def add_check(self, *args, **kwargs):
        shortname = None
        if kwargs.get('shortname') is None:
            if len(args) > 0:
                shortname = args[0]
        else:
            shortname = kwargs['shortname']

        self.checks.append(Check(*args, **kwargs))
        try:
            self.remove_check_queue.remove(shortname)
        except KeyError:
            pass

    def remove_check(self, *args, **kwargs):
        if kwargs.get('shortname') is None:
            raise ValueError('shortname of check must be specified')

        # Use sensible defaults if they're not specified - these are not
        # actually used during removal, but they're required for constructing
        # the Check object; check_disk is chosen because it's part of the
        # nagios-plugins-basic package.
        if kwargs.get('check_cmd') is None:
            kwargs['check_cmd'] = 'check_disk'
        if kwargs.get('description') is None:
            kwargs['description'] = ''

        check = Check(*args, **kwargs)
        check.remove(self.hostname)
        self.remove_check_queue.add(kwargs['shortname'])

    def write(self):
        try:
            nagios_uid = pwd.getpwnam('nagios').pw_uid
            nagios_gid = grp.getgrnam('nagios').gr_gid
        except Exception:
            logging.error("Nagios user not set up, nrpe checks not updated")
            return

        if not os.path.exists(NRPE.nagios_logdir):
            os.mkdir(NRPE.nagios_logdir)
            os.chown(NRPE.nagios_logdir, nagios_uid, nagios_gid)

        nrpe_monitors = {}
        monitors = {"monitors": {"remote": {"nrpe": nrpe_monitors}}}
        for nrpecheck in self.checks:
            nrpecheck.write(self.nagios_context, self.hostname,
                            self.nagios_servicegroups)
            nrpe_monitors[nrpecheck.shortname] = {
                "command": nrpecheck.command,
            }

        # update-status hooks are configured to firing every 5 minutes by
        # default. When nagios-nrpe-server is restarted, the nagios server
        # reports checks failing causing unnecessary alerts. Let's not restart
        # on update-status hooks.
        if not hook_name() == 'update-status':
            service('restart', 'nagios-nrpe-server')

        monitor_ids = relation_ids("local-monitors") + \
            relation_ids("nrpe-external-master")
        if relation.name == "local-monitors" or relation.name == "nrpe-external-master":
            reldata = self.data.our_unit
            if 'monitors' in reldata:
                # update the existing set of monitors with the new data
                old_monitors = yaml.safe_load(reldata['monitors'])
                old_nrpe_monitors = old_monitors['monitors']['remote']['nrpe']
                # remove keys that are in the remove_check_queue
                old_nrpe_monitors = {k: v for k, v in old_nrpe_monitors.items()
                                     if k not in self.remove_check_queue}
                # update/add nrpe_monitors
                old_nrpe_monitors.update(nrpe_monitors)
                old_monitors['monitors']['remote']['nrpe'] = old_nrpe_monitors
                # write back to the relation
                relation.data[self.model.unit]['monitors'] = yaml.dump(old_monitors)
            else:
                # write a brand new set of monitors, as no existing ones.
                relation.data[self.model.unit]['monitors'] = yaml.dump(monitors)

        self.remove_check_queue.clear()

def get_nagios_hostname(relation=None , relation_name='nrpe-external-master'):
    """
    Query relation with nrpe subordinate, return the nagios_hostname

    :param str relation_name: Name of relation nrpe sub joined to
    """
    if relation and relation.name == relation_name:
        if 'nagios_hostname' in relation.data:
            return relation['nagios_hostname']


