#!/usr/bin/python3

import sys
import logging
import subprocess
from . import ubuntu_pkg

def install_python_apt():
    try:
        subprocess.check_output(['apt', 'install', 'python3-apt', "--yes"])
    except subprocess.CalledProcessError:
        logging.error("Apt configuration is broken, please check your installation.")

try:
    import apt
except ModuleNotFoundError:
    install_python_apt()
    import apt

def apt_install(packages):
    cache = apt.cache.Cache()
    cache.update()
    cache.open()

    for package in packages:
        pkg = cache[package]
        if pkg.is_installed:
            logging.info(f"{package} already installed")
        else:
            pkg.mark_install()

    try:
        cache.commit()
    except Exception as error:
        logging.error(f"Failed to install package: {package}"
            "with error: {error}"
        )

def apt_remove(packages):
    cache = apt.cache.Cache()
    cache.update()
    cache.open()

    for package in packages:
        pkg = cache[package]
        if not pkg.is_installed:
            logging.info(f"{package} already removed")
        else:
            pkg.mark_delete()

    try:
        cache.commit()
    except Exception as error:
        logging.error(f"Failed to remove package: {package}"
            "with error: {error}"
        )

def apt_update():
    cache = apt.cache.Cache()
    cache.update()

def add_source(source, key=None):
    if key:
        add_source_key('gsss-source', key)
    try:
        subprocess.check_output(['add-apt-repository', source, '--yes'])
    except subprocess.CalledProcessError:
        logging.warning("add-apt-repository not present, installing.")
        apt_install("software-properties-common")
        subprocess.check_output(['add-apt-repository', source, '--yes'])

def add_source_key(key_name, key):
    tmp_file = '/tmp/{}.asc'.format(key_name)
    with open(tmp_file, 'wb') as keyf:
        keyf.write(key.encode())
    try:
        subprocess.check_output(['apt-key', 'add', tmp_file])
    except subprocess.CalledProcessError:
        logging.error(f"Failed to add key: {key}")

def apt_cache(*_, **__):
    """Shim returning an object simulating the apt_pkg Cache.
    :param _: Accept arguments for compability, not used.
    :type _: any
    :param __: Accept keyword arguments for compability, not used.
    :type __: any
    :returns:Object used to interrogate the system apt and dpkg databases.
    :rtype:ubuntu_apt_pkg.Cache
    """
    if 'apt_pkg' in sys.modules:
        # NOTE(fnordahl): When our consumer use the upstream ``apt_pkg`` module
        # in conjunction with the apt_cache helper function, they may expect us
        # to call ``apt_pkg.init()`` for them.
        #
        # Detect this situation, log a warning and make the call to
        # ``apt_pkg.init()`` to avoid the consumer Python interpreter from
        # crashing with a segmentation fault.
        logging.warning('Support for use of upstream ``apt_pkg`` module in conjunction'
            'with charm-helpers is deprecated since 2019-06-25')
        sys.modules['apt_pkg'].init()
    return ubuntu_pkg.Cache()
 
if __name__ == "__main__":
    apt_update()
    apt_install(["nginx"])
    apt_remove(["nginx"])
