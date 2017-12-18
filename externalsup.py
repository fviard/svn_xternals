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

class ComponentType:
    SVN = 'svn'
    GIT = 'git'

class Component(object):
    def __init__(self, path, uri, scm_type=ComponentType.SVN, rev=None):
        self.path = path
        self.uri = uri
        self.rev = rev
        self.scm_type = scm_type

        self.workdir_uri = None
        self.workdir_rev = None
        self.result = None
        self.conflicts = []


class ClientSVN(object):
    def __init__(self, verbosity=0):
        self.client = pysvn.Client()
        self.verbose = verbosity

    def clean_uri(self, uri, rev=None):
        """ Return: URI, REV
        """
        if uri:
            if '@' in uri:
                uri, rev_arobase = uri.rsplit('@', 1)
                if rev is None and rev_arobase:
                    rev = rev_arobase

            uri = uri.rstrip('/')
        return uri, rev

    def info(self, path):
        """
        Return (URL, REV)
        with rev (revision) as a string
        """
        url = path
        rev = 0

        try:
            entry = self.client.info(path)
        except Exception, e:
            return (None, None)
        if not entry:
            return (None, None)
        # Use commit_revision instead?
        # commit_revision: last commit
        # revision: current revision of the working dir
        rev = entry.revision.number
        if rev <= 0:
            rev = 0
        url = entry.url

        return(url, str(rev))

    def set_op_monitor(self, verbose=0, conflict_list=None):
        if conflict_list is None and not verbose:
            return

        def notify_callback(change_info_dict):
            # Todo, if verbose != 0
            # Output a list of updated files

            if conflict_list is not None:
                if change_info_dict.get('content_state') == pysvn.wc_notify_state.conflicted:
                    conflict_list.append(change_info_dict.get('path', 'unknown'))
            return

        self.client.callback_notify = notify_callback

    def disable_op_monitor(self):
        self.client.callback_notify = None

    def check_rev_result(self, rev_entry):
        if not rev_entry:
            return False
        if isinstance(rev_entry, list):
            if len(rev_entry) < 1:
                return False
            rev_entry = rev_entry[0]

        try:
            rev = int(rev_entry.number)
            if rev == -1:
                return False
        except ValueError:
            return False
        return True

    def update(self, path, rev=None):
        if rev:
            pyrev = pysvn.Revision(pysvn.opt_revision_kind.number, int(rev))
        else:
            pyrev = pysvn.Revision(pysvn.opt_revision_kind.head)
        ret = self.client.update(path, revision=pyrev, ignore_externals=True)
        return self.check_rev_result(ret)

    def switch(self, path, uri, rev=None):
        if rev:
            pyrev = pysvn.Revision(pysvn.opt_revision_kind.number, int(rev))
        else:
            pyrev = pysvn.Revision(pysvn.opt_revision_kind.head)
        ret = self.client.switch(path, uri, revision=pyrev)
        return self.check_rev_result(ret)

    def checkout(self, path, uri, rev=None):
        if rev:
            pyrev = pysvn.Revision(pysvn.opt_revision_kind.number, int(rev))
        else:
            pyrev = pysvn.Revision(pysvn.opt_revision_kind.head)
        ret = self.client.checkout(uri, path, revision=pyrev, ignore_externals=True)
        return self.check_rev_result(ret)


class ClientGIT(object):
    """
    For the GIT client, revision == Branch (but could be a commit id)
    """
    def __init__(self, verbosity=0):
        self.verbose = verbosity

    def clean_uri(self, uri, rev=None):
        """ Return: URI, REV
        """
        if uri:
            if '.git@' in uri:
                uri, rev_arobase = uri.rsplit('.git@', 1)
                if rev is None and rev_arobase:
                    rev = rev_arobase

            uri = uri.rstrip('/')
        return uri, rev

    def info(self, path):
        """
        Return (URL, REV)
        with rev (revision) as a string
        """
        """
        url = path
        rev = 0


        # help
        # $ git -C components/s3cmd/ remote -v
        #origin  git@github.com:fviard/s3cmd.git (fetch)
        #origin  git@github.com:fviard/s3cmd.git (push)
        # $ git -C components/s3cmd/ branch --no-color
        #  fix-remote2local-input
        #* master
        #  master_test
        #  new_test
        #* (détaché de e045859)
        #* (détaché de v7.1.1)

        """
        return (None, '')

    def set_op_monitor(self, verbose=0, conflict_list=None):
        return

    def disable_op_monitor(self):
        return

    def git_cwd_cmd(self, path, command):
        cmd = ['git', '-C', path]
        cmd += command
        if not self.verbose:
            cmd += ['-q']
        if not run_command(cmd):
            return False

        return True

    def get_default_branch(self, path):
        #$ git symbolic-ref refs/remotes/origin/HEAD
        #refs/remotes/origin/1.0
        # or:
        #$ git branch -r
        #origin/1.0
        #origin/1.0-fsm
        #origin/HEAD -> origin/1.0
        #if not self.git_cwd_cmd(path, ['branch', '-r']
        #    # Parse the output
        #    return ''
        return 'master'

    def update(self, path, rev=None):
        # If the repo and branch are the same, we can just pull
        if not self.git_cwd_cmd(path, ['pull', '--ff-only']):
            return False

        return True

    def switch(self, path, uri, rev=None):
        verbose = False
        cmd = ['fetch']
        if self.verbose:
            cmd += ['--verbose']
        if not self.git_cwd_cmd(path, cmd):
            return False

        if not rev:
            rev = self.get_default_branch(path)

        if not rev:
            return False

        if not self.git_cwd_cmd(path, ['checkout', rev]):
            return False

        if not self.git_cwd_cmd(path, ['pull', '--ff-only']):
            return False
        return True

    def checkout(self, path, uri, rev=None):
        cmd = ['git', 'clone']
        cmd += ['--progress']
        if self.verbose:
            cmd += ['--verbose']
        if rev:
            # Clone directly the right branch if any
            cmd += ['-b', rev]
        cmd += [uri, path]

        if not run_command(cmd):
            return False
        return True


def run_command(command_list):
    if call(command_list) != 0:
        return False
    else:
        return True


def detect_scm_type_from_uri(uri):
    # git external with @branch
    if '.git@' in uri:
        return ComponentType.GIT
    # git external without @branch
    if uri.endswith('.git'):
        return ComponentType.GIT

    return ComponentType.SVN


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

    scm_type = detect_scm_type_from_uri(uri)

    compo = Component(folder, uri, scm_type)
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

    scm_type = detect_scm_type_from_uri(uri)
    compo = Component(folder, uri, scm_type)
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

def is_same_compo(uri, other_uri):
    #logging.debug("is same: %r : %r | %r : %r", uri, rev, other_uri, other_rev)
    if uri != other_uri:
        return False

    return True

def scm_checkout_update_switch_worker(component):

    path = component.path
    uri = component.uri
    scm_type = component.scm_type

    # One per thread
    if scm_type == ComponentType.SVN:
        scm_client = ClientSVN()
        scm_client.set_op_monitor(conflict_list=component.conflicts)
    elif scm_type == ComponentType.GIT:
        scm_client = ClientGIT()
    else:
        logging.error("Unsupported scm: %s", scm_type)
        component.result = "Error"
        return component

    req_uri, req_rev = scm_client.clean_uri(uri, None)

    try:
        if scm_type == ComponentType.SVN:
            if os.path.isdir(path):
                # switch or update
                path_info = scm_client.info(path)
                path_uri, path_rev = scm_client.clean_uri(path_info[0], path_info[1])

                if is_same_compo(req_uri, path_uri):
                    # update
                    if req_rev:
                        logging.debug("Update of %s to rev %s", path, req_rev)
                    else:
                        logging.debug("Update of %s", path)
                    if scm_client.update(path, req_rev):
                        component.result = "Update"
                    else:
                        logging.debug("Error during update of %s", path)
                        component.result = "UpdateError"
                else:
                    # Switch
                    logging.debug("Switch of %s:\n\t%s -> %s", path, path_uri, req_uri)
                    if scm_client.switch(path, req_uri, req_rev):
                        component.result = "Switch"
                    else:
                        logging.debug("Error during switch of %s", path)
                        component.result = "SwitchError"

            elif not os.path.exists(path):
                # checkout
                if req_rev:
                    logging.debug("Checkout of %s rev/branch %s [%s]", req_uri, req_rev, path)
                else:
                    logging.debug("Checkout of %s [%s]", req_uri, path)
                if scm_client.checkout(path, req_uri, req_rev):
                    component.result = "Checkout"
                else:
                    logging.debug("Error during update of %s", path)
                    component.result = "CheckoutError"
            else:
                logging.debug("Path: %s exists and is not a dir ", path)
                component.result = "Error"
        elif scm_type == ComponentType.GIT:
            if os.path.isdir(path):
                # Switch
                logging.debug("Switch of %s: -> %s", path, req_uri)
                if scm_client.switch(path, req_uri, req_rev):
                    component.result = "Switch"
                else:
                    logging.debug("Error during switch of %s", path)
                    component.result = "SwitchError"
            elif not os.path.exists(path):
                if req_rev:
                    logging.debug("Checkout of %s rev/branch %s [%s]", req_uri, req_rev, path)
                else:
                    logging.debug("Checkout of %s [%s]", req_uri, path)
                if scm_client.checkout(path, req_uri, req_rev):
                    component.result = "Checkout"
                else:
                    logging.debug("Error during update of %s", path)
                    component.result = "CheckoutError"
            else:
                logging.debug("Path: %s exists and is not a dir ", path)
                component.result = "Error"

    except:
        logging.exception("Worker unexpected error.")
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
            logging.error("Scm failed to update '%s'", component_path)
        if entry.conflicts:
            ret = False
            for conflict in entry.conflicts:
                logging.warning("Scm conflict: '%s'", conflict)

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
    if not ret:
        return 1

    return 0


if __name__ == '__main__':
    logging.basicConfig(format='%(levelname)s: %(message)s',
                        level=logging.INFO)
    exit(main())
