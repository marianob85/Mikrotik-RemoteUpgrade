import re
import paramiko
import time
import packaging.version
from multiping import multi_ping


RouterOS_regex = re.compile('^ *([^:]*): (.*)')
MikroTik_version_regex = re.compile('^([^ ]*)')


class RouterOSCommand:
    def __init__(self, message, attributes=None, verbose=None):
        for attribute in attributes:
            setattr(self, attribute, None)
        for line in message:
            line = line.rstrip('\r\n')
            if verbose and verbose >= 3:
                print('... ' + line)
            m = RouterOS_regex.match(line)
            if m:
                key = m.group(1).replace('-', '_')
                value = m.group(2)
                if attributes and key in attributes:
                    setattr(self, key, value)
                    if verbose and verbose >= 2:
                        print(f"\t{key}: {value}")


class RouterOsUpgrade:
    def __init__(self, timeout, sshretries, reboot_timeout, username, password, verbose=0):
        self.timeout = timeout
        self.sshretries = sshretries
        self.reboot_timeout = reboot_timeout
        self.username = username
        self.password = password
        self.verbose = verbose

    def connect(self, hostname):
        SSHClient = paramiko.SSHClient()
        SSHClient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        retries = 0
        connected = False
        while not connected:
            try:
                SSHClient.connect(hostname, username=self.username, password=self.password, timeout=self.timeout)
                connected = True
                break
            except:
                if retries > self.sshretries:
                    break
                print("SSH connection failed. Retrying.")
                retries += 1
                time.sleep(retries)

        if not connected:
            print("ERROR: SSH connection failed.")
            SSHClient.close()
            return None
        return SSHClient

    def checkForNewVersion(self, sshclient):
        retries = 1
        while retries:
            retries -= 1
            sshclient.exec_command('/system package update check-for-updates once')
            time.sleep(10)
            _, stdout, _ = sshclient.exec_command('/system package update print')
            mtUpgradeInfo = RouterOSCommand(stdout, attributes=['installed_version', 'latest_version', 'status'], verbose=self.verbose)
            if mtUpgradeInfo.latest_version:
                return mtUpgradeInfo
        return None

    def mapVersion(self, version):
        m = MikroTik_version_regex.match(version)
        if m:
            version = m.group(1)
            return packaging.version.parse(version)
        return ""

    def waitForResponse(self, hostname):
        reboot_time = time.time()
        timeout = time.time() + self.reboot_timeout
        while time.time() < timeout:
            no_responses = None
            try:
                _, no_responses = multi_ping([hostname], timeout=10, retry=2)
            except Exception as err:
                pass
            if not no_responses:
                return True, time.time() - reboot_time
            print('{:.0f} seconds since reboot...\n'.format(time.time() - reboot_time))
        return False

    def makeOSUpgrade(self, hostname):
        if self.verbose:
            print("Checking RouterOS version")
        try:
            SSHClient = self.connect(hostname)
            if not SSHClient:
                return False, None

            stdin, stdout, stderr = SSHClient.exec_command('/system resource print')
            mtResources = RouterOSCommand(stdout, attributes=['version', 'architecture_name', 'board_name', 'bad_blocks'], verbose=self.verbose)

            if not mtResources.version:
                print("Failed to get current RouterOS version. Skipping upgrade.")
                return False, None
            else:
                CurVersion = self.mapVersion(mtResources.version)

            if (mtResources.architecture_name == ""):
                print("Failed to get RouterOS architecture-name. Skipping upgrade.")
                return False, None

            mtUpgradeInfo = self.checkForNewVersion(SSHClient)
            if not mtUpgradeInfo:
                print("Failed to get RouterOS latest version information. Skipping upgrade.")
                return False, None

            if mtUpgradeInfo.installed_version == mtUpgradeInfo.latest_version:
                print("RouterOS version already {}".format(mtUpgradeInfo.latest_version))
                return True, mtUpgradeInfo.latest_version

            print("RouterOS version from {} to {}".format(mtUpgradeInfo.installed_version, mtUpgradeInfo.latest_version))
            SSHClient.exec_command('/system package update install')

            time.sleep(30)
            host_up, reboot_time = self.waitForResponse(hostname)
            if not host_up:
                print("ERROR: {} has NOT come back online within {} seconds. ".format(hostname, self.reboot_timeout))
                return False, None
            if host_up:
                print('{} is back online after {:.0f} seconds. Checking status'.format(hostname, reboot_time), flush=True)
                time.sleep(5)  # Wait 5 seconds for the device to fully boot

                SSHClient = self.connect(hostname)
                if not SSHClient:
                    return False, None

                stdin, stdout, stderr = SSHClient.exec_command('/system resource print')
                mtResources = RouterOSCommand(stdout, attributes=['version'], verbose=self.verbose)

                if not mtResources.version:
                    print("ERROR: Could not confirm RouterOS version.")
                    return False, None

                CurVersion = self.mapVersion(mtResources.version)
                LastVersion = packaging.version.parse(mtUpgradeInfo.latest_version)
                if (CurVersion < LastVersion):
                    print("ERROR: Upgrade of {} did not occur, current RouterOS version {}".format(hostname, mtResources.version))
                    return False, mtResources.version
                else:
                    print("{} RouterOS successfully upgraded. Version now {}".format(hostname, mtResources.version))
                    return True, mtResources.version
        except Exception as err:
            print("{} RouterOS Unknown exception {}".format(err))
            if SSHClient: 
                SSHClient.close()
                return False, None
        finally:
            if SSHClient: 
                SSHClient.close()

    def makeFirmwareUpdate(self, hostname):
        if self.verbose:
            print("Checking firmware version")
        try:
            SSHClient = self.connect(hostname)
            if not SSHClient:
                return False, None

            stdin, stdout, stderr = SSHClient.exec_command('/system routerboard print')
            mtResources = RouterOSCommand(stdout, attributes=['current_firmware', 'upgrade_firmware'], verbose=self.verbose)

            if not mtResources.current_firmware or not mtResources.upgrade_firmware:
                print("Failed to get current firmware version. Skipping upgrade.")
                return False, None

            NewVersion = packaging.version.parse(mtResources.upgrade_firmware)
            CurVersion = packaging.version.parse(mtResources.current_firmware)
            if CurVersion >= NewVersion:
                print("Firmware version already {}".format(mtResources.current_firmware))
                return True, mtResources.current_firmware

            print("Firmware version from {} to {}".format(mtResources.current_firmware, mtResources.upgrade_firmware))
            SSHClient.exec_command('/system routerboard upgrade')

            if self.verbose:
                print("Rebooting in 15 seconds.")
            time.sleep(15)
            print("Rebooting {}".format(hostname))
            SSHClient.exec_command('/system reboot')
            time.sleep(5)
            host_up, reboot_time = self.waitForResponse(hostname)
            if not host_up:
                print("ERROR: {} has NOT come back online within {} seconds. ".format(hostname, self.reboot_timeout))
                return False, None
            if host_up:
                print('{} is back online after {:.0f} seconds. Checking status'.format(hostname, reboot_time), flush=True)
                time.sleep(5)  # Wait 5 seconds for the device to fully boot

                SSHClient = self.connect(hostname)
                if not SSHClient:
                    return False, None

                stdin, stdout, stderr = SSHClient.exec_command('/system routerboard print')
                mtResources = RouterOSCommand(stdout, attributes=['current_firmware', 'upgrade_firmware'], verbose=self.verbose)

                if not mtResources.current_firmware or not mtResources.upgrade_firmware:
                    print("Failed to get current firmware version. Skipping upgrade.")
                    return False, None

                NewVersion = packaging.version.parse(mtResources.upgrade_firmware)
                CurVersion = packaging.version.parse(mtResources.current_firmware)
                if (CurVersion < NewVersion):
                    print("ERROR: Upgrade of {} Firmware did not occur, current Firmware version {}".format(hostname, mtResources.current_firmware))
                    return False, mtResources.current_firmware
                else:
                    print("{} Firmware successfully upgraded. Version now {}".format(hostname, mtResources.current_firmware))
                    return True, mtResources.current_firmware
        except:
            if SSHClient: 
                SSHClient.close()
            return False, None
        finally:
            if SSHClient: 
                SSHClient.close()