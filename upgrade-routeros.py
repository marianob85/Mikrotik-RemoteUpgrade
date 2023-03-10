#!/usr/bin/python3

import sys
import os
import shutil
import re
import time
import getpass
import packaging.version
from multiping import multi_ping
import paramiko


import argparse
parser = argparse.ArgumentParser()
parser.add_argument('-t', '--timeout',			type=int,	help='SSH timeout in seconds, default: 60')
parser.add_argument('-s', '--sshstop',   action="store_true",	help='Stop upgrades of further devices if SSH fails on initial connection, default: false')
parser.add_argument('-R', '--sshretries',		type=int,	help='SSH retries, default: 3')
parser.add_argument('-r', '--reboot_timeout',			help='Timeout after reboot before upgrade considered failed, default: 180')
parser.add_argument('-u', '--username',				help='Username for access to RouterOS, default: local username')
parser.add_argument('-p', '--password',	required=True,				help='password for access to RouterOS, default:')
parser.add_argument('-v', '--verbose',   action="count",	help='Verbose output')
parser.add_argument('hosts', metavar='HOST', type=str, nargs='+', help='RouterOS host to upgrade')
args = parser.parse_args()

class bcolors:
	HEADER = '\033[95m'
	OKBLUE = '\033[94m'
	OKGREEN = '\033[92m'
	WARNING = '\033[103;30m'
	FAIL = '\033[91m'
	ENDC = '\033[0m'
	BOLD = '\033[1m'
	UNDERLINE = '\033[4m'


if args.username:
	username = args.username
else:
	username = getpass.getuser()

if args.timeout:
	timeout = args.timeout
else:
	timeout = 10

if args.sshretries:
	sshretries = args.sshretries
else:
	sshretries = 10

if args.reboot_timeout:
	reboot_timeout = int(args.reboot_timeout)
else:
	reboot_timeout = 180

password = args.password

if args.verbose:
	print("Verbose output enabled")
	print("Verbose level {}".format(args.verbose))
	print("Username: '{}'".format(username))
	print("Timeout: {} seconds".format(timeout))

MikroTik_regex = re.compile('^ *([^:]*): (.*)')
MikroTik_version_regex = re.compile('^([^ ]*)')

for hostname in args.hosts:
	if sys.stdout.isatty():
		print(bcolors.BOLD + bcolors.UNDERLINE, end='')
	print("\n*** {} ***".format(hostname))
	if sys.stdout.isatty():
		print(bcolors.ENDC, end='')
	if args.verbose:
		print("Checking RouterOS version")
	version	= ""
	architecture_name = ""
	board_name = ""
	bad_blocks = ""

	SSHClient = paramiko.SSHClient()
	SSHClient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
	connected = False
	retries   = 0
	while not connected:
		try:
			SSHClient.connect(hostname, username=username, password=password, timeout=timeout)
			connected = True
			break
		except:
			if retries > sshretries:
				break
			print(bcolors.WARNING + "SSH connection failed. Retrying." + bcolors.ENDC)
			retries += 1
			time.sleep(retries)
			
	if not connected:
		if sys.stdout.isatty():
			print(bcolors.FAIL, end='')
		print("ERROR: SSH connection failed.")
		if args.sshstop:
			print("Updates to ALL FURTHER devices cancelled!")
		if sys.stdout.isatty():
			print(bcolors.ENDC, end='')
		SSHClient.close()
		if not args.sshstop:
			continue
		if not args.noop:
			sys.exit(2)
		else:
			print(bcolors.WARNING + "NOOP: skipping to next host due to being a dry run" + bcolors.ENDC)
			continue

	stdin, stdout, stderr = SSHClient.exec_command('/system resource print')

	for line in stdout:
		line = line.rstrip('\r\n')
		if args.verbose and args.verbose >= 3:
			print('... ' + line)
		m = MikroTik_regex.match(line)
		if m:
			if (m.group(1) == 'version'):
				version = m.group(2)
			if (m.group(1) == 'architecture-name'):
				architecture_name = m.group(2)
			if (m.group(1) == 'board-name'):
				board_name = m.group(2)
			if (m.group(1) == 'bad-blocks'):
				bad_blocks = m.group(2)

	if args.verbose and args.verbose >= 2:
		print("\tversion: " + version)
		print("\tarchitecture-name: " + architecture_name)
		print("\tboard-name: " + board_name)
		print("\tbad-blocks: " + bad_blocks)

	if (version == ""):
		print("Failed to get current RouterOS version. Skipping upgrade.")
		SSHClient.close()
		continue
	else:
		m = MikroTik_version_regex.match(version)
		if m:
			version = m.group(1)
		CurVersion = packaging.version.parse(version)

	if (architecture_name == ""):
		print("Failed to get RouterOS architecture-name. Skipping upgrade.")
		SSHClient.close()
		continue

	if (board_name == "CHR"):
		architecture_name = "x86"

	# Check if newer version
	SSHClient.exec_command('/system package update check-for-updates once')
	time.sleep(3)
	stdin, stdout, stderr = SSHClient.exec_command('/system package update print')
	
	for line in stdout:
		line = line.rstrip('\r\n')
		if args.verbose and args.verbose >= 3:
			print('... ' + line)
		m = MikroTik_regex.match(line)
		if m:
			if (m.group(1) == 'installed-version'):
				installed_version = m.group(2)
			if (m.group(1) == 'latest-version'):
				latest_version = m.group(2)
			if (m.group(1) == 'status'):
				status = m.group(2)

	if args.verbose and args.verbose >= 2:
		print("\tinstalled-version: " + installed_version)
		print("\tlatest-version: " + latest_version)
		print("\tstatus: " + status)

	if installed_version != latest_version:
		print("RouterOS version from {} to {}".format(installed_version,latest_version))

		stdin, stdout, stderr = SSHClient.exec_command('/system package update install')

		reboot_time = time.time()
		time.sleep(5)

		host_up = False
		timeout = time.time() + reboot_timeout
		while time.time() < timeout:
			#pingable = os.system("fping -q " + hostname + " 2>/dev/null")
			responses, no_responses = multi_ping([hostname], timeout=1, retry=1)
			if not no_responses:
				host_up = True
				break
			if sys.stdout.isatty():
				print('\r{:.0f} seconds since reboot...'.format(time.time() - reboot_time), end='', flush=True)
		if sys.stdout.isatty():
			print('\r', end='')
			for i in range(0,shutil.get_terminal_size().columns):
				print(' ', end='')
			print('\r', end='')

		if host_up:
			reboot_time = time.time() - reboot_time
			print('{} is back online after {:.0f} seconds. Checking status'.format(hostname, reboot_time), flush=True)
			time.sleep(5)	# Wait 5 seconds for the device to fully boot

			version	= ""
			uptime	= ""
			CurVersion = ""
			connected = False
			retries   = 0
			while not connected:
				try:
					SSHClient.connect(hostname, username=username, password=password, timeout=timeout)
					connected = True
					break
				except paramiko.SSHException as e:
					if retries > sshretries:
						break
					print(bcolors.WARNING + "SSH connection failed with '{}'. Retrying.".format(e) + bcolors.ENDC)
					retries += 1
					time.sleep(retries)
			if not connected:
				if sys.stdout.isatty():
					print(bcolors.FAIL, end='')
				print("ERROR: SSH connection failed. Updates to ALL FURTHER devices cancelled!")
				if sys.stdout.isatty():
					print(bcolors.ENDC, end='')
				SSHClient.close()
				if not args.noop:
					sys.exit(2)
				else:
					print(bcolors.WARNING + "NOOP: skipping to next host due to being a dry run" + bcolors.ENDC)
					continue

			stdin, stdout, stderr = SSHClient.exec_command('/system resource print')

			for line in stdout:
				line = line.rstrip('\r\n')
				if args.verbose and args.verbose >= 3:
					print('... ' + line)
				m = MikroTik_regex.match(line)
				if m:
					if (m.group(1) == 'version'):
						version = m.group(2)
					if (m.group(1) == 'uptime'):
						uptime = m.group(2)

			if (version == ""):
				if sys.stdout.isatty():
					print(bcolors.FAIL, end='')
				print("ERROR: Could not confirm RouterOS version. Updates to ALL FURTHER devices cancelled!")
				if sys.stdout.isatty():
					print(bcolors.ENDC, end='')
				SSHClient.close()
				if not args.noop:
					sys.exit(2)
				else:
					print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)

			m = MikroTik_version_regex.match(version)
			if m:
				version = m.group(1)
			CurVersion = packaging.version.parse(version)
			LastVersion = packaging.version.parse(latest_version)
			if (CurVersion < LastVersion):
				if sys.stdout.isatty():
					print(bcolors.FAIL, end='')
				print("ERROR: Upgrade of {} did not occur, current RouterOS version {}. Updates to ALL FURTHER devices cancelled!".format(hostname,version))
				if sys.stdout.isatty():
					print(bcolors.ENDC, end='')
				SSHClient.close()
				if not args.noop:
					sys.exit(2)
				else:
					print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)
			else:
				if sys.stdout.isatty():
					print(bcolors.OKGREEN, end='')
				print("{} RouterOS successfully upgraded. Version now {}".format(hostname,version))
				if sys.stdout.isatty():
					print(bcolors.ENDC, end='')

		else:
			if sys.stdout.isatty():
				print(bcolors.FAIL, end='')
			print("ERROR: {} has NOT come back online within {} seconds. Updates to ALL FURTHER devices cancelled!".format(hostname,reboot_timeout))
			if sys.stdout.isatty():
				print(bcolors.ENDC, end='')
			if not args.noop:
				sys.exit(2)
			else:
				print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)

	else:
		print("RouterOS version already {}".format(version))

	SSHClient.close()
	print()
