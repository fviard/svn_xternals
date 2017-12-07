#!/usr/bin/python
# -*- coding: utf-8 -*-

# Summary: Svn update your externals in parallel to be faster
# Author: Florent Viard
# License: MIT
# Copyright (c) 2017, Florent Viard

# Run with: python externalsup.py

import logging
import os
import pysvn
import argparse
from subprocess import call
from multiprocessing.pool import ThreadPool

DEFAULT_MAX_JOBS = 4
DEFAULT_EXTERNALS_FILE = 'externals.conf'
URL_PADDING = 100

global_stop = False

class Component(object):
    def __init__(self, path, uri, rev=None):
        self.path = path
        self.uri = uri
        self.rev = None

        self.workdir_uri = None
        self.workdir_rev = None
        self.result = None

def run_command(command_list):
    if call(command_list) != 0:
        return False
    else:
        return True


def parse_gclient_compo_line(line):
    line = line.strip()
    if not line:
        return None
    if line.startswith("#"):
        return None
    folder, uri = line.split(':', 1)
    folder = folder.strip()
    folder = folder.strip("'")

    uri = uri.strip()
    uri = uri.rstrip(',')
    uri = uri.strip("'")
    compo = Component(folder, uri)
    return compo


def load_externals_from_gclient_file(workdir, ext_file):
    components_list = []
    with open(ext_file, "r") as ext_fp:
        in_dep = False
        for line in ext_fp.readlines():
            if not in_dep:
                if line.startswith('deps = {'):
                    in_dep = True
                    continue
                else:
                    continue

            if line.startswith('}'):
                in_dep = False
                continue

            compo = parse_gclient_compo_line(line)
            if not compo or not compo.path or not compo.uri:
                continue

            components_list.append(compo)
    return components_list


def parse_externals_compo_line(line):
    line = line.strip()
    if not line:
        return None
    if line.startswith("#"):
        return None
    folder, uri = line.split(None, 1)

    compo = Component(folder, uri)
    return compo

def load_externals_from_file(workdir, ext_file):
    components_list = []
    with open(ext_file, "r") as ext_fp:
        for line in ext_fp.readlines():
            compo = parse_externals_compo_line(line)
            if not compo or not compo.path or not compo.uri:
                continue

            components_list.append(compo)

    return components_list


def load_externals_from_svn(workdir):
    components_list = []

    logging.error("Loading for real externals not yet supported")

    return components_list

def svn_info(path):
    # One per thread
    svn_client = pysvn.Client()
    url = path
    rev = 0

    try:
        entry = svn_client.info(path)
    except Exception, e:
        return (None, None)
    if not entry:
        return (None, None)
    # Use revision instead?
    rev = entry.commit_revision.number
    if rev <= 0:
        rev = 0
    url = entry.url

    return(url, str(rev))

def is_same_compo(uri, rev, other_uri, other_rev):
    if rev is None and '@' in uri:
        uri, rev = uri.split('@', 1)
    if other_rev is None and '@' in other_uri:
        other_uri, other_rev = uri.split('@', 1)

    if rev:
        if other_rev:
            if rev != other_rev:
                return False
    if uri != other_uri:
        return False

    return True

def scm_checkout_update_switch_worker(component):
    path = component.path
    uri = component.uri

    if os.path.isdir(path):
        # switch or update
        path_info = svn_info(path)
        if not is_same_compo(uri, None, path_info[0], path_info[1]):
            logging.debug("Url difference for %s: %s->%s"%(path, path_info[0], uri))
            # Switch
        else:
            # update
            logging.debug("Start update of %s"% path)
            if not run_command(['svn', 'update', path]):
                logging.debug("Error during update of %s"%path)
                component.result = "UpdateError"
                return component
            component.result = "Update"
            return component

    elif not os.path.exists(path):
        # checkout
        component.result = "Checkout"
        return component
    else:
        logging.debug("Path: %s exists and is not a dir "%path)
        component.result = "Error"
        return component


def externals_update_main(workdir, ext_file, maxjobs=4, recursive=False):
    ret = True

    # Step 1: loading components/path list:

    if ext_file:
        components_list = load_externals_from_file(workdir, ext_file)
    else:
        components_list = load_externals_from_svn(workdir)
    if not components_list:
        logging.error("Nothing found in externals")
        return False

    # Step 2: Run thread pool on these externals
    p = ThreadPool(maxjobs)
    logging.debug("Starting the jobs...")
    result = p.map(scm_checkout_update_switch_worker, components_list)
    logging.debug("Completed all the update jobs")

    # Step 3: Process and display the results
    for entry in result:
        if not entry:
            continue
        if entry.path and entry.path.startswith(workdir):
            component_path = entry.path[len(workdir):]
        else:
            component_path = entry.path
        if entry.result not in ['Update', 'Checkout', 'Switch', None]:
            ret = False
            logging.error("Svn failed to update '%s'", component_path)

    return ret

def set_real_external_from_file(ext_file, components):
    """DO NOT USE, WORK IN PROGRESS
    """
    tmp_ext_path = "externals.ext"
    with open(tmp_ext_path, "w") as tmp_ext_fp:
        tmp_ext_fp.write("# Externals auto-generated by externalsup script\n")
        for entry in components:
            url_svn = entry.uri.ljust(URL_PADDING)
            tmp_ext_fp.write("%s\t%s\n"% (url_svn, entry.path))
    # TODO: run command svn ps


def main():
    parser = argparse.ArgumentParser(description='Svn update your externals in parallel to be faster')
    parser.add_argument('workdir', metavar='W', nargs='?',
                        help='path to the workdir to operate within')
    parser.add_argument('-j', '--maxjobs', type=int,
                        default=DEFAULT_MAX_JOBS,
                        help='number of parallel jobs to run')
    parser.add_argument('-r', '--recursive', action='store_true')
    parser.add_argument('-c', '--from-file')
    parser.add_argument('-e', '--from-externals', action='store_true')
    parser.add_argument('-f', '--from-default-file', action='store_true')
    parser.add_argument('-v', '--verbose', action='count', default=0)


    args = parser.parse_args()

    # Treat options
    if args.verbose > 0:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.recursive:
        logging.error("--recursive option is not yet supported")
        return 1


    if args.workdir:
        workdir = os.path.realpath(args.workdir)
    else:
        workdir = os.path.realpath(os.getcwd())

    if not os.path.isdir(workdir):
        logging.error("Specified workdir doesn't exist or is not a directory")
        return 1

    logging.debug("Updating externals in '%s' with %d parallel jobs...", workdir, args.maxjobs)

    if (args.from_file or args.from_externals or args.from_externals) \
       and not (bool(args.from_file) ^ bool(args.from_externals) ^ bool(args.from_default_file)):
        logging.error("Only a single externals source can be specified")
        return 1

    if args.from_file:
        ext_file = args.from_file
    elif args.from_default_file:
        ext_file = os.path.join(workdir, DEFAULT_EXTERNALS_FILE)
    elif args.from_externals:
        ext_file = None
    else:
        # default value, use externals file
        ext_file = os.path.join(workdir, DEFAULT_EXTERNALS_FILE)


    if ext_file and not os.path.exists(ext_file):
        logging.error("External file '%s' not found!", ext_file)
        return 1

    ret = externals_update_main(workdir, ext_file, args.maxjobs, args.recursive)
    return ret and 1 or 0


if __name__ == '__main__':
    logging.basicConfig(format='%(levelname)s: %(message)s',
                        level=logging.INFO)

    exit(main())
