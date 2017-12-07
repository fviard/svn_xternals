#!/usr/bin/python
# -*- coding: utf-8 -*-

# Summary: Svn update your externals in parallel to be faster
# Author: Florent Viard
# License: MIT
# Copyright (c) 2017, Florent Viard

# Run with: python externalsup.py

import argparse
import logging
import os
from multiprocessing.pool import ThreadPool
import pysvn
from subprocess import call

DEFAULT_MAX_JOBS = 4
DEFAULT_EXTERNALS_FILE = 'externals.conf'

class component(object):
    def __init__(self, path, uri, rev=None):
        self.path = path
        self.uri = uri
        self.rev = None

        self.workdir_uri = None
        self.workdir_rev = None
        self.result = None

def load_externals_from_file(ext_file):
    components_list = []

    return components_list

def load_externals_from_svn(workdir):
    components_list = []

    return components_list

def scm_update_worker(component):
    # Test operation needed

    ret = call(['svn', 'update', component.uri)
    if ret != 0:
        component.result = 'Failed'
    return component

def externals_update_main(workdir, ext_file, maxjobs=4, recursive=False):
    ret = True

    # Step 1: loading components/path list:

    if ext_file:
       components_list = load_externals_from_file(workdir, ext_file)
    else:
       components_list =  load_externals_from_svn(workdir)

    # Step 2: Run thread pool on these externals
    p = ThreadPool(maxjobs)
    result = p.map(scm_update_worker, components_list)

    # Step 3: Process and display the results
    for entry in result:
        if entry.path and entry.path.startswith(workdir):
            component_path = entry.path[len(workdir):]
        else:
            component_path = entry.path
        if entry.result not in ['Update', 'Checkout', 'Switch', None]:
            ret = False
            logging.error("Svn failed to update '%s'", component_path)

    return ret

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
