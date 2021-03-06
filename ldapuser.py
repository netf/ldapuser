#!/usr/bin/env python

"""
The ldapuser command-line client issues calls to a LDAP servers.

Usage: ldapuser <command> [<args>...]

Subcommands, use ``ldapuser help [subcommand]`` to learn more::

  user          manage users
  group         manage groups

"""

__version__ = 0.2

from docopt import docopt
from docopt import DocoptExit
from string import ascii_lowercase, ascii_uppercase, digits
from ConfigParser import ConfigParser, NoOptionError, NoSectionError
from random import choice
import os
import sys
import ldap
import hashlib
import base64
import logging

# logger settings
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
ch = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - '
                              '%(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.propagate = False
logger.addHandler(ch)

# ldapuser configuration file
CONFIG = '/etc/ldapuser/ldapuser.conf'


class ldapuser():
    def __init__(self):
        config = ConfigParser()
        try:
            config.read(CONFIG)
            [setattr(self,section + '_' + option, config.get(section, option))
             for section in config.sections() for option in config.options(section)]
        except (IOError, NoOptionError, NoSectionError) as e:
            logger.error("%s" % e)
            sys.exit(1)

        try:
            self.conn = ldap.initialize(self.ldap_server)
            if getattr(self, 'ldap_timeout', None):
                self.conn.set_option(ldap.OPT_NETWORK_TIMEOUT, float(self.ldap_timeout))
            self.conn.simple_bind_s(self.ldap_binddn, self.ldap_bindpw)
            logger.info("LDAP connection to (%s) initialized" % self.ldap_server)
        except ldap.SERVER_DOWN:
            logger.error("Cant connect to LDAP server (%s)" % self.ldap_server)
            sys.exit(1)

    def user(self):
        """
        Valid commands are:

        user create         Create a new user
        user update         Updates an user
        user delete         Deletes an user
        user show           Shows info about user(s)

        Use `ldapuser help [command]` to learn more
        """
        sys.exit(1)

    def user_create(self, args):
        """
        Create a new user

        Usage: ldapuser user create [--uid UID] [--gid GID] [--group GROUP ...] [--pass PASSWORD]
                                  [--home HOME] [--shell SHELL] [--gecos GECOS] [--sshkey SSHKEY]
                                  [--host HOST ...] [--mail MAIL] <user>

        Options:
        --uid UID               User ID
        --gid GID               Group ID
        --group GROUP           Additional groups user belongs to
        --pass PASSWORD         Password
        --home HOME             Home directory
        --shell SHELL           Default shell
        --gecos GECOS           Gecos
        --sshkey SSHKEY         Public SSH key
        --host HOST             Hosts user has an access to
        --mail MAIL

        """
        user = args.get('<user>')
        uid = self._getuid(uid=args.get('--uid'))
        gid = self._getgid(gid=args.get('--gid'))
        groups = args.get('--group')
        password = self._getpass(password=args.get('--pass'))
        home = args.get('--home')
        shell = args.get('--shell')
        gecos = args.get('--gecos')
        sshkey = args.get('--sshkey')
        host = self._gethosts(args.get('--host'))
        mail = args.get('--mail')

        if not home:
            home = '/home/%s' % user
        if not shell:
            shell = '/bin/bash'
        if not gecos:
            gecos = user
        if not host:
            host = 'None'
        if not mail:
            mail = "%s@o2.com" % user

        if sshkey:
            try:
                with open(sshkey) as f:
                    sshkey = f.readlines()[0].strip()
            except:
                logger.error("Can't open ssh key file: %s" % sshkey)
                sys.exit(1)
        else:
            sshkey = 'None'

        user_record = [
            ('objectClass',
             ['top', 'inetOrgPerson',
              'posixAccount', 'shadowAccount',
              'hostObject', 'ldapPublicKey']),
            ('cn', [user]),
            ('sn', [user]),
            ('uid', [user]),
            ('uidNumber', [uid]),
            ('gidNumber', [gid]),
            ('homeDirectory', [home]),
            ('mail', [mail]),
            ('loginShell', [shell]),
            ('userPassword', [password[1]]),
            ('sshPublicKey', [sshkey]),
            ('host', host)]

        user_dn = "uid=%s,%s" % (user, self.user_basedn)

        try:
            self.conn.add_s(user_dn, user_record)
            logger.info("User '%s' created successfully with password: %s" %
                        (user, password[0]))
            self.group_create({'--gid': gid, '<group>': user})
            if groups:
                for group in groups:
                    self.group_create_member({'user': user, 'group': group})
        except ldap.ALREADY_EXISTS:
            logger.error("User '%s' already exists" % user)

    def user_update(self, args):
        """
        Updates an user

        Usage: ldapuser user update [--uid UID] [--gid GID] [--group GROUP ...] [--pass PASSWORD]
                                  [--home HOME] [--shell SHELL] [--gecos GECOS] [--sshkey SSHKEY]
                                  [--host HOST ...]  [--mail MAIL] <user>

        Options:
        --uid UID               User ID
        --gid GID               Group ID
        --group GROUP           Additional groups user belongs to
        --pass PASSWORD         Password
        --home HOME             Home directory
        --shell SHELL           Default shell
        --gecos GECOS           Gecos
        --sshkey SSHKEY         Public SSH key
        --host HOST             Hosts user has an access to
        --mail MAIL             User email address

        """
        user = args.get('<user>')
        uidNumber = args.get('--uid')
        gidNumber = args.get('--gid')
        groups = args.get('--group')
        userPassword = args.get('--pass')
        homeDirectory = args.get('--home')
        loginShell = args.get('--shell')
        givenName = args.get('--gecos')
        sshPublicKey = args.get('--sshkey')
        host = self._gethosts(args.get('--host'))
        mail = args.get('--mail')

        if userPassword:
            userPassword = self._getpass(userPassword)
            clearTextPassword = userPassword[0]
        else:
            clearTextPassword = "*UNCHANGED*"

        if sshPublicKey:
            try:
                with open(sshPublicKey) as f:
                    sshPublicKey = f.readlines()[0].strip()
            except:
                logger.error("Can't open ssh key file: %s" % sshPublicKey)
                sys.exit(1)

        user_dn = "uid=%s,%s" % (user, self.user_basedn)
        try:
            user_records = self.conn.search_s(user_dn, ldap.SCOPE_SUBTREE, '(objectclass=posixAccount)')
        except ldap.NO_SUCH_OBJECT:
            logger.error("No such user: '%s'" % user)
            sys.exit(1)
        new_user_record = []
        for record in user_records[0]:
            if isinstance(record, dict):
                for k, v in record.iteritems():
                        new_user_record.append((ldap.MOD_REPLACE, k, v))

        for idx, record in enumerate(new_user_record):
            if uidNumber and 'uidNumber' in record:
                new_user_record[idx] = (ldap.MOD_REPLACE, 'uidNumber', uidNumber)
            if gidNumber and 'gidNumber' in record:
                new_user_record[idx] = (ldap.MOD_REPLACE, 'gidNumber', gidNumber)
            if userPassword and 'userPassword' in record:
                new_user_record[idx] = (ldap.MOD_REPLACE, 'userPassword', [userPassword[1]])
            if homeDirectory and 'homeDirectory' in record:
                new_user_record[idx] = (ldap.MOD_REPLACE, 'homeDirectory', homeDirectory)
            if loginShell and 'loginShell' in record:
                new_user_record[idx] = (ldap.MOD_REPLACE, 'loginShell', loginShell)
            if givenName and 'givenName' in record:
                new_user_record[idx] = (ldap.MOD_REPLACE, 'givenName', givenName)
            if sshPublicKey and 'sshPublicKey' in record:
                new_user_record[idx] = (ldap.MOD_REPLACE, 'sshPublicKey', sshPublicKey)
            if host and 'host' in record:
                new_user_record[idx] = (ldap.MOD_REPLACE, 'host', host)
            if mail and 'mail' in record:
                new_user_record[idx] = (ldap.MOD_REPLACE, 'mail', mail)

        try:
            self.conn.modify_s(user_dn, new_user_record)
            logger.info("User '%s' updated successfuly with password: %s" %
                        (user, clearTextPassword))
            if groups:
                group_basedn = self.group_basedn
                if not '' in groups:
                    for group in groups:
                        group_dn = "cn=%s,%s" % (group, self.group_basedn)
                        try:
                            ret = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE,
                                         '(objectClass=*)', ['member', 'memberUid'])
                        except Exception:
                            logger.error("Invalid group: %s" % group)
                            sys.exit(1)

                all_groups = self.conn.search_s(group_basedn, ldap.SCOPE_SUBTREE,
                                     '(objectClass=*)', ['member', 'memberUid'])
                for group in all_groups:
                    members = group[1]
                    group_dn = group[0]
                    if members.get('member') or members.get('memberUid'):
                        for k, v in members.iteritems():
                            user_dn = "uid=%s,%s" % (user, self.user_basedn)
                            if user in v or user_dn in v:
                                group = group_dn.split(',')[0].split('cn=')[1]
                                if group not in groups:
                                    self.group_delete_member({'group': group, 'user': user})
                for grp in groups:
                    if grp != '':
                        self.group_create_member({'group': grp, 'user': user})

        except ldap.TYPE_OR_VALUE_EXISTS:
            logger.error("User '%s' has a duplicate host value" % user)

    def user_delete(self, args):
        """
        Deletes a user

        Usage: ldapuser user delete <user>

        """
        user = group = args.get('<user>')
        user_dn = "uid=%s,%s" % (user, self.user_basedn)

        try:
            self.conn.delete_s(user_dn)
            logger.info("User '%s' deleted successfully" % user)
            self.group_delete({'<group>': group})
        except ldap.NO_SUCH_OBJECT:
            logger.error("User '%s' doesnt exist" % user)
            sys.exit(1)

    def user_show(self, args):
        """
        Create a new user

        Usage: ldapuser user show [--json] [<user>]

        Options:
        --json              Shows information in JSON format

        """
        user = args.get('<user>')
        if user:
            user_dn = "uid=%s,%s" % (user, self.user_basedn)
        else:
            user_dn = self.user_basedn
        try:
            users = self.conn.search_s(user_dn, ldap.SCOPE_SUBTREE, '(objectclass=posixAccount)')
        except ldap.NO_SUCH_OBJECT:
            logger.error("User not found '%s'" % user)
            sys.exit(1)

        logger.info(' Searching for user data...')
        print ""
        for idx, user in enumerate(users):
            user_dn, user_attributes = user[0], user[1]
            print "[%d] => NAME: %s, DN: %s" % (idx, user_dn.split(',')[0].split('uid=')[1], user_dn)
            print "----------------------------------------------------------------------------------"
            group_dn = self.group_basedn
            groups = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE,
                                        '(objectClass=*)', ['memberUid', 'member'])
            user_attributes['group'] = []
            for group in groups:
                group_memberUid, group_member = group[1].get('memberUid'), group[1].get('member')
                if group_memberUid:
                    if user_attributes['uid'][0] in group_memberUid:
                        user_attributes['group'].append(group[0].split(',')[0].split('cn=')[1])
                if group_member:
                    if "uid=%s,%s" % (user_attributes['uid'][0], self.user_basedn) in group_member:
                        user_attributes['group'].append(group[0].split(',')[0].split('cn=')[1])

            for attribute_key, attribute_value in user_attributes.iteritems():
                if 'cn' in attribute_key or \
                   'sn' in attribute_key or \
                   'objectClass' in attribute_key:
                    pass
                else:
                    if len(attribute_value) > 1:
                        for attribute in attribute_value:
                            print "%s: %s" % (attribute_key, attribute)
                    elif len(attribute_value) == 1:
                        print "%s: %s" % (attribute_key, attribute_value[0])
                    else:
                        print "%s: %s" % (attribute_key, '')
            print ""

    def group(self):
        """
        Valid commands are:

        group create         Create a new group
        group update         Updates a group
        group delete         Deletes a group
        group show           Shows info about a group(s)
        group member         Manages group members

        Use `ldapuser help [command]` to learn more
        """
        sys.exit(1)

    def group_member(self, args):
        """
        Manages group members

        Usage: ldapuser group member <group>
               ldapuser group member [--add <user>] <group>
               ldapuser group member [--del <user>] <group>
               ldapuser group member [--update <user> ...] <group>

               <group> Shows group memberships
               --add <user> <group>  Adds comma separated list of users to a group membership
               --del <user> <group>  Removes comma separated list of users from a group membership
               --update <user> <group> Updates membership
        """
        delete = args.get('--del')
        add = args.get('--add')
        update = args.get('--update')
        group = args.get('<group>')

        if add:
            self.group_create_member({'group': group, 'user': add})
        elif delete:
            self.group_delete_member({'group': group, 'user': delete})
        elif update:
            self.group_update_member({'group': group, 'user': update})
        else:
            self.group_show_member({'group': group})

    def group_create(self, args):
        """
        Create a new group

        Usage: ldapuser group create [(--groupofnames --member USER ...) | --gid GID [--member USER ...]] <group>

        --gid <gid>             Group ID
        --groupofnames          Specifies groupOfNames type [default: posixGroup]
        --member USER ...       Specifies members that belong to the group

        """

        group = args.get('<group>')
        gid = self._getgid(gid=args.get('--gid'))
        groupOfNames = args.get('--groupofnames')
        members = args.get('--member')

        group_dn = "cn=%s,%s" % (group, self.group_basedn)
        group_record = [('cn', [group])]
        if groupOfNames:
            group_record.append(('objectClass', ['top', 'groupOfNames']))
            group_record.append(('member', ["uid=%s,%s" % (member, self.user_basedn) for member in members]))
        else:
            group_record.append(('objectClass', ['top', 'posixGroup']))
            group_record.append(('gidNumber', [gid]))
            if members:
                group_record.append(('memberUid', members))

        try:
            self.conn.add_s(group_dn, group_record)
            logger.info("Group '%s' created successfully" % group)
        except ldap.ALREADY_EXISTS:
            logger.error("Group '%s' already exists" % group)

    def group_delete(self, args):
        """
        Deletes a group

        Usage: ldapuser group delete <group>

        """
        group = args.get('<group>')
        group_dn = "cn=%s,%s" % (group, self.group_basedn)

        try:
            self.conn.delete_s(group_dn)
            logger.info("Group '%s' deleted successfully" % group)
        except ldap.NO_SUCH_OBJECT:
            logger.error("Group '%s' doesnt exist" % group)

    def group_update(self, args):
        """
        Updates a  group

        Usage: ldapuser group update [options] <group>

        --gid <gid>             Group ID

        """
        group = args.get('<group>')
        gid = args.get('--gid')

        group_dn = "cn=%s,%s" % (group, self.group_basedn)
        group_record = [(ldap.MOD_REPLACE, 'objectClass', ['top', 'posixGroup']),
                        (ldap.MOD_REPLACE, 'cn', [group])]
        try:
            res = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE, '(objectclass=posixGroup)')
        except ldap.NO_SUCH_OBJECT:
            logger.error("Group not found '%s'" % group)
            sys.exit(1)
        for k, v in res[0][1].iteritems():
            if k != 'objectClass' and k != 'cn':
                if gid:
                    if k != 'gidNumber':
                        group_record.append((ldap.MOD_REPLACE, k, v))
                    else:
                        group_record.append((ldap.MOD_REPLACE, k, v))
        if gid:
            group_record.append((ldap.MOD_REPLACE, 'gidNumber', [gid]))

        try:
            self.conn.modify_s(group_dn, group_record)
            logger.info("Group '%s' modified successfully" % group)
        except Exception as e:
            logger.error("Error modyfing group '%s' '%s'" % (group,e ))

    def group_show(self, args):
        """
        Shows group information

        Usage: ldapuser group show [--json] [<group>]

        Options:
        --json              Shows information in JSON format

        """
        group = args.get('<group>')
        if group:
            group_dn = "cn=%s,%s" % (group, self.group_basedn)
        else:
            group_dn = self.group_basedn
        try:
            group = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE, '(|(objectclass=posixGroup)(objectclass=groupOfNames))')
        except ldap.NO_SUCH_OBJECT:
            logger.error("Group not found '%s'" % group)
            sys.exit(1)

        logger.info('Searching for group data...')
        print ""
        for idx, group in enumerate(group):
            group_dn, group_attributes = group[0], group[1]
            print "[%d] => NAME: %s, DN: %s" % (idx, group_dn.split(',')[0].split('cn=')[1], group_dn)
            print "----------------------------------------------------------------------------------"

            for attribute_key, attribute_value in group_attributes.iteritems():
                if 'cn' in attribute_key or \
                   'sn' in attribute_key:
                    pass
                else:
                    if len(attribute_value) > 1:
                        for attribute in attribute_value:
                            print "%s: %s" % (attribute_key, attribute)
                    elif len(attribute_value) == 1:
                        print "%s: %s" % (attribute_key, attribute_value[0])
                    else:
                        print "%s: %s" % (attribute_key, '')
            print ""

    def group_create_member(self, args):
        """
        Creates a new memberUid entry in a group(s)

        """
        group = args.get('group')
        member = args.get('user')
        group_dn = "cn=%s,%s" % (group, self.group_basedn)
        try:
            try:
                members = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE,
                                        '(objectClass=*)', ['memberUid', 'member'])[0][1]['memberUid']
                members.append(member)
                group_record = [(ldap.MOD_REPLACE, 'objectClass', ['top', 'posixGroup']),
                                (ldap.MOD_REPLACE, 'cn', [group]),
                                (ldap.MOD_REPLACE, 'memberUid', list(set(members)))]
            except:
                members = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE,
                                         '(objectClass=*)', ['memberUid', 'member'])[0][1]['member']
                member_dn = "uid=%s,%s" % (member, self.user_basedn)
                members.append(member_dn)
                group_record = [(ldap.MOD_REPLACE, 'objectClass', ['top', 'groupOfNames']),
                                (ldap.MOD_REPLACE, 'cn', [group]),
                                (ldap.MOD_REPLACE, 'member', list(set(members)))]
        except ldap.NO_SUCH_OBJECT:
            logger.error("Adding member to a group - group (%s) does not exit." % group)
            sys.exit(1)

        try:
            self.conn.modify_s(group_dn, group_record)
            logger.info("Added '%s' to group '%s'" % (member, group))
        except Exception as e:
            logger.error("Error adding '%s' to a group '%s': '%s'" % (member, group, e))

    def group_delete_member(self, args):
        """
        Deletes a member from the group
        """
        group = args.get('group')
        member = args.get('user')
        group_dn = "cn=%s,%s" % (group, self.group_basedn)
        try:
            try:
                members = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE,
                                         '(objectClass=*)', ['memberUid', 'member'])[0][1]['memberUid']
                members.remove(member)
                group_record = [(ldap.MOD_REPLACE, 'objectClass', ['top', 'posixGroup']),
                        (ldap.MOD_REPLACE, 'cn', [group]),
                        (ldap.MOD_REPLACE, 'memberUid', list(set(members)))]

            except:
                members = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE,
                                         '(objectClass=*)', ['memberUid', 'member'])[0][1]['member']
                member_dn = "uid=%s,%s" % (member, self.user_basedn)
                members.remove(member_dn)
                group_record = [(ldap.MOD_REPLACE, 'objectClass', ['top', 'groupOfNames']),
                        (ldap.MOD_REPLACE, 'cn', [group]),
                        (ldap.MOD_REPLACE, 'member', list(set(members)))]

        except ldap.NO_SUCH_OBJECT:
            logger.error("Deleting member from a group - group (%s) does not exit." % group)

        try:
            self.conn.modify_s(group_dn, group_record)
            logger.info("Deleted '%s' from a group '%s'" % (member, group))
        except Exception:
            logger.error("Error deleting '%s' from a group '%s'" % (member, group))

    def group_update_member(self, args):
        """
        Updates group memberUid attribute
        """
        group = args.get('group')
        members = args.get('user')
        group_dn = "cn=%s,%s" % (group, self.group_basedn)
        try:
            group_record = [(ldap.MOD_REPLACE, 'objectClass', ['top', 'posixGroup']),
                        (ldap.MOD_REPLACE, 'cn', [group]),
                        (ldap.MOD_REPLACE, 'memberUid', list(set(members)))]
            self.conn.modify_s(group_dn, group_record)
            logger.info("Updated members of '%s'. Current members" % group)
            for idx, member in enumerate(members):
                print "[%s] '%s'" % (idx, member)
        except:
            members = ["uid=%s,%s" % (user, self.user_basedn) for user in members]
            group_record = [(ldap.MOD_REPLACE, 'objectClass', ['top', 'groupOfNames']),
                        (ldap.MOD_REPLACE, 'cn', [group]),
                        (ldap.MOD_REPLACE, 'member', list(set(members)))]
            self.conn.modify_s(group_dn, group_record)
            logger.info("Updated members of '%s'. Current members:" % group)
            for idx, member in enumerate(members):
                print "[%s] '%s'" % (idx, member)



    def group_show_member(self, args):
        """
        Shows members of a group
        """
        group = args.get('group')
        group_dn = "cn=%s,%s" % (group, self.group_basedn)
        try:
            members = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE,
                                     '(objectClass=*)', ['memberUid'])[0][1]['memberUid']
        except:
            members = self.conn.search_s(group_dn, ldap.SCOPE_SUBTREE,
                                     '(objectClass=*)', ['member'])[0][1]['member']
        logger.info("Searching group '%s'. Current members:" % group)
        for idx, member in enumerate(members):
            print "[%s] '%s'" % (idx, member)


    def _getuid(self, uid=None):
        """
        Return valid UID

        If no UID provided use the last available one
        Raise an exception if provided UID already exists
        """
        users = self.conn.search_s(self.user_basedn,
                                   ldap.SCOPE_SUBTREE,
                                   'objectClass=posixAccount',
                                   ['uidNumber'])
        uids = []
        minuid = int(getattr(self, 'user_minuid', 1500))
        maxuid = int(getattr(self, 'user_maxuid', 2000))
        if uid:
            uid = int(uid)
            if minuid < uid < maxuid:
                for dn, u in users:
                    if str(uid) in u['uidNumber']:
                        # UID already exists - rise exception
                        raise Exception("UID (%s) already exists" % uid)
                return str(uid)
            else:
                raise Exception("Invalid UID: %s, Valid range: %s..%s" % (uid, minuid, maxuid))
        else:
            for dn, uid  in users:
                uid = int(uid['uidNumber'][0])
                if minuid < uid < maxuid:
                    uids.append(uid)
            uid = minuid if len(uids) == 0 else sorted(uids)[-1] + 1
            return str(uid)

    def _getgid(self, gid=None):
        """
        Return valid GID

        If no GID provided use the last available one
        """
        groups = self.conn.search_s(self.group_basedn,
                                    ldap.SCOPE_SUBTREE,
                                    'objectClass=posixGroup',
                                    ['gidNumber'])
        gids = []
        mingid = int(getattr(self, 'user_mingid', 1500))
        maxgid = int(getattr(self, 'user_maxgid', 2000))
        if gid:
            gid = int(gid)
            if mingid < gid < maxgid:
                return str(gid)
            else:
                raise Exception("Invalid GID: %s, Valid range: %s..%s" % (gid, mingid, maxgid))
        else:
            for dn, gid in groups:
                gid = int(gid['gidNumber'][0])
                if mingid < gid < maxgid:
                    gids.append(gid)
            gid = mingid if len(gids) == 0 else sorted(gids)[-1] + 1
            return str(gid)

    def _getpass(self, password=None, size=9, chars=ascii_lowercase + ascii_uppercase + digits):
        if not password:
            password = ''.join(choice(chars) for x in range(size))
        salt = os.urandom(4)
        h = hashlib.sha1(password)
        h.update(salt)
        return password, '{SSHA}' + base64.encodestring(h.digest() + salt)[:-1]

    def _gethosts(self, host=None):
        for h in host:
            if h and (h.startswith('/') or h.startswith('./')):
                try:
                    host_file = open(h)
                except IOError:
                    logger.error("Can't open host file: %s" % host)
                    sys.exit(1)
                hosts = []
                for line in host_file.readlines():
                    hosts.append(line.rstrip())
                return hosts
            elif h and ',' in host:
                return h.split(',')
            else:
                return host
        return None


def trim(docstring):
    """
    Function to trim whitespace from docstring

    c/o PEP 257 Docstring Conventions
    <http://www.python.org/dev/peps/pep-0257/>
    """
    if not docstring:
        return ''
    # Convert tabs to spaces (following the normal Python rules)
    # and split into a list of lines:
    lines = docstring.expandtabs().splitlines()
    # Determine minimum indentation (first line doesn't count):
    indent = sys.maxint
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))
    # Remove indentation (first line is special):
    trimmed = [lines[0].strip()]
    if indent < sys.maxint:
        for line in lines[1:]:
            trimmed.append(line[indent:].rstrip())
    # Strip off trailing and leading blank lines:
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    while trimmed and not trimmed[0]:
        trimmed.pop(0)
    # Return a single string:
    return '\n'.join(trimmed)

USER_SHORTCUTS = dict([
    ('create', 'user:create'),
    ('update', 'user:update'),
    ('delete', 'user:delete'),
    ('show', 'user:show')
])

GROUP_SHORTCUTS = dict([
    ('create', 'group:create'),
    ('update', 'group:update'),
    ('delete', 'group:delete'),
    ('show', 'group:show'),
    ('member', 'group:member'),
])

SHORTCUTS = dict([
    ('user', USER_SHORTCUTS),
    ('group', GROUP_SHORTCUTS),
])


def parse_args(cmd):
    """
    Parse command-line args applying shortcuts and looking for help flags
    """
    if cmd == 'help':
        try:
            cmd = sys.argv[2]
            subcmd = sys.argv[3]
        except IndexError:
            subcmd = None
        help_flag = True
    else:
        try:
            cmd = sys.argv[1]
            subcmd = sys.argv[2]
            help_flag = False
        except IndexError:
            subcmd = None
            help_flag = True

    # swap cmd with shortcut
    if cmd in SHORTCUTS:
        if subcmd in SHORTCUTS[cmd]:
            cmd = SHORTCUTS[cmd][subcmd]
        else:
            help_flag = True

    # convert : to _ for matching method names and docstrings
    if ':' in cmd:
        cmd = '_'.join(cmd.split(':'))
    return cmd, help_flag


def _dispatch_cmd(method, args):
    try:
        method(args)
    except Exception as e:
        logger.error(e)
        sys.exit(1)


def main():
    """
    Create a client, parse the arguments received on the command line, and
    call the appropriate method on the client.
    """

    cli = ldapuser()
    args = docopt(__doc__, version='ldapuser CLI {}',
                  options_first=True)

    cmd = args['<command>']
    cmd, help_flag = parse_args(cmd)
    # print help if it was asked for
    if help_flag:
        if cmd != 'help' and cmd in dir(cli):
            print(trim(getattr(cli, cmd).__doc__))
            return
        docopt(__doc__, argv=['--help'])
    # unless cmd needs to use sys.argv directly
    if hasattr(cli, cmd):
        method = getattr(cli, cmd)
    else:
        raise DocoptExit('Found no matching command, try `ldapuser help`')
    docstring = trim(getattr(cli, cmd).__doc__)
    if 'Usage: ' in docstring:
            args.update(docopt(docstring))
    # dispatch the CLI command
    _dispatch_cmd(method, args)


if __name__ == '__main__':
    main()
    sys.exit(0)
