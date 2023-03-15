import argparse
import RouterOS

# https://github.com/andrewradke/MikroTik-upgrade/blob/master/upgrade-routeros.py

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--timeout', type=int, help='SSH timeout in seconds', default=60)
    parser.add_argument('-R', '--sshretries', type=int, help='SSH retries', default=3)
    parser.add_argument('-r', '--reboot_timeout', type=int, help='Timeout after reboot before upgrade considered failed', default=180)
    parser.add_argument('-u', '--username', help='Username for access to RouterOS, default: local username')
    parser.add_argument('-p', '--password', required=True, help='password for access to RouterOS, default:')
    parser.add_argument('-v', '--verbose', action="count", help='Verbose output')
    parser.add_argument('hosts', metavar='HOST', type=str, nargs='+', help='RouterOS host to upgrade')
    args = parser.parse_args()

    routerOsUpgrade = RouterOS.RouterOsUpgrade(timeout=args.timeout, sshretries=args.timeout, reboot_timeout=args.reboot_timeout,
                                               username=args.username, password=args.password, verbose=args.verbose)

    upgradeStatus = {}

    for hostname in args.hosts:
        print("\n\n\n*** {} ***".format(hostname))

        routerOsStatus, routerOsVersion = routerOsUpgrade.makeOSUpgrade(hostname)
        if routerOsStatus:
            firmwareStatus, firmwareVersion = routerOsUpgrade.makeFirmwareUpdate(hostname)
        else:
            firmwareStatus = False
            firmwareVersion = None

        upgradeStatus[hostname] = (routerOsStatus, routerOsVersion, firmwareStatus, firmwareVersion)

    print("\n\n\n{:<16}: {:^12}: {:^12}".format("Hostname", "RouterOS", "Firmware"))
    for k, v in upgradeStatus.items():
        print("{:<16}: {:<6} {:>4} : {:<6} {:>4}".format(k, str(v[0]), str(v[1]), str(v[2]), str(v[3])))
