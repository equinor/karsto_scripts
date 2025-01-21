class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class Interface:
    def __init__ (self, name):
        self.name = name
        self.description = ""
        self.vlan = []
        self.status = "Not set"
    
    def set_description(self, description):
        self.description = description
    
    def set_vlan(self, vlan):
        self.vlan.append(vlan)

    def set_status(self,status):
        self.status = status
    

    def print_info(self):
        print("-"*30)
        print(f"Name: {self.name}")
        print("Description: ", self.description)
        print("Vlan: ", self.vlan)
        print("Status: ", self.status)

class CiscoDevice:
    """
    Represents a Cisco device.
    Parses configuration files to extract details such as:
    - Hostname
    - Default Gateway
    - Interfaces (regular, disabled, tagged/untagged VLANs)
    - VLAN details
    """

    def __init__(self, config_path: str, netbox_url: str, netbox_token: str, auto_update: bool, interactive: bool):
        self.config_path = config_path
        self.netbox_url = netbox_url
        self.netbox_token = netbox_token
        self.auto_update = auto_update
        self.interactive = interactive

        self.headers = {
            "Authorization": f"Token {self.netbox_token}",
            "accept" : "application/json",
            "Content-Type": "application/json"
        }


    def parse_config(self):
        print(f"{Colors.BOLD}Parsing configuration: {Colors.CYAN}{self.config_path}{Colors.ENDC}")
        try:
            parse = CiscoConfParse(self.config_path)
        except Exception as e:
            raise Exception(f"Failed to parse config file {self.config_path}: {e}")

        self.hostname = self._parse_hostname(parse)
        print(f"Host - {Colors.GREEN}{self.hostname}{Colors.ENDC}")

        self.gateway = self._parse_default_gateway(parse)

        self.all_SVIs, self.regular_interfaces = self._parse_interfaces(parse)
        self.disabled_interfaces = self._parse_disabled_interfaces(parse)
        self.enabled_interfaces = self._parse_enabled_interfaces(parse)
        to_be_removed = []
        for interface in self.disabled_interfaces:
            for intf_enabled in self.enabled_interfaces:
                if interface == intf_enabled:
                    to_be_removed.append(interface)
                    
        for interface in to_be_removed:
            self.disabled_interfaces.remove(interface)

        # VLANs
        self.all_VLANs, self.vlan_mapping, self.tagged_vlans, self.untagged_vlans = self._parse_vlans(parse)
        self.tagged_vlans_intf = self._parse_tagged_interfaces(parse)
        self.untagged_vlans_intf = self._parse_untagged_interfaces(parse)

        # TODO: Add IPs parsing - Limited information from the config
        self.ip_addresses = self._parse_IP_addr_from_config(parse)

    def _parse_hostname(self, parse):
        """Extracts the hostname."""
        hostnames = parse.find_objects(r'^hostname')
        hostnames = [obj.text.split()[1] for obj in hostnames]
        if not hostnames:
            raise Exception(f"No hostname found in {self.config_path}. Aborting!")
        if len(hostnames) > 1:
            raise Exception(f"Multiple hostnames found in {self.config_path}. Aborting!")
        return hostnames[0]

    def _parse_default_gateway(self, parse):
        """Extracts the default gateway."""
        find_gateways = parse.find_objects(r'^ip default-gateway')
        gateways = [obj.text.split()[2] for obj in find_gateways if len(obj.text.split()) > 2]
        if len(gateways) > 1:
            raise Exception(f"Multiple default gateways found in {self.config_path}. Aborting!")
        return gateways[0] if gateways else "Not Configured"

    def _parse_interfaces(self, parse):
        """Extracts all interfaces and separates SVIs."""
        intf_cmds = parse.find_objects(r'^interface')
        all_interfaces = [obj.text.split()[1] for obj in intf_cmds if len(obj.text.split()) > 1]
        all_SVIs = [intf for intf in all_interfaces if "Vlan" in intf]
        regular_interfaces = [intf for intf in all_interfaces if intf not in all_SVIs]
        self.description_mapping = {}
        for interface in intf_cmds:
            int_name = interface.text.strip()
            desc_line = interface.re_search_children(r'^\s+description ')

            if desc_line:
                description = desc_line[0].text.strip().split(' ', 1)[1]
            else:
                description = 'No description'
            self.description_mapping[int_name.replace("interface ", "")] = description

        return all_SVIs, regular_interfaces

    def _parse_disabled_interfaces(self, parse):
        """Extracts all disabled (shutdown) interfaces."""
        shut_intf = parse.find_parent_objects(r'^interface', r'shutdown')
        return [obj.text.split()[1] for obj in shut_intf]
    
    def _parse_enabled_interfaces(self, parse):
        """Extracts all disabled (shutdown) interfaces."""
        shut_intf = parse.find_parent_objects(r'^interface', r'no shutdown')
        return [obj.text.split()[1] for obj in shut_intf]

    def _parse_vlans(self, parse):
        """Extracts all VLANs and builds a mapping of interfaces to VLANs."""
        interfaces = parse.find_objects(r"^interface")
        vlan_mapping = {}
        all_vlans = set()
        tagged_vlans = []
        untagged_vlans = [] 

        # Trunk'd ports
        for interface in interfaces:
            allowed_vlan_lines = interface.re_search_children(r"switchport trunk allowed vlan")
            for line in allowed_vlan_lines:
                vlan_match = re.search(r"switchport trunk allowed vlan (.+)", line.text)

                if vlan_match:
                    vlan_list = vlan_match.group(1)
                    vlan_ids = self._expand_vlans(vlan_list) 
                    if isinstance(vlan_ids, list) and len(vlan_ids) > 1:
                        vlan_ids = [str(vlan)+"T" for vlan in vlan_ids]
                    else:
                        vlan_ids[0] = vlan_ids[0] + "T"

                    vlan_mapping[interface.text.split()[1]] = vlan_ids 
                    all_vlans.update(vlan_ids)
                    tagged_vlans.append(vlan_ids)

            # Access mode
            access_vlan_lines = interface.re_search_children(r"switchport access vlan")
            for line in access_vlan_lines:
                vlan_match = re.search(r"switchport access vlan (.+)", line.text)
                if vlan_match:
                    vlan = vlan_match.group(1)
                    vlan_ids = self._expand_vlans(vlan)  
                    if isinstance(vlan_ids, list):
                        vlan_ids = [str(vlan) for vlan in vlan_ids]  
                    vlan_mapping[interface.text.split()[1]] = [vlan+"U"]
                    untagged_vlans.append(vlan)

        return sorted(all_vlans), vlan_mapping, tagged_vlans, untagged_vlans

    def _parse_tagged_interfaces(self, parse):
        """Finds interfaces with tagged VLANs (trunk mode)."""
        trunk_intf = parse.find_parent_objects(r'^interface', r'switchport trunk encapsulation dot1q')
        return [obj.text.split()[1] for obj in trunk_intf]

    def _parse_untagged_interfaces(self, parse):
        """Finds interfaces with untagged VLANs (access mode)."""
        access_intf = parse.find_parent_objects(r'^interface', r'switchport mode access')
        return [obj.text.split()[1] for obj in access_intf]

    def _expand_vlans(self, vlan_list):
        """Expands VLAN ranges into individual VLAN IDs."""
        expanded = []
        if len(vlan_list.split(',')) > 1:
            for part in vlan_list.split(','):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    expanded.extend(range(start, end + 1))
                else:
                    expanded.append(int(part))
            return expanded
        else:
            return[vlan_list]

    def _parse_IP_addr_from_config(self, parse):
        ip_addresses = []
        
        ip_commands = parse.find_objects(r"ip address")
        for ip_command in ip_commands:
            ip_match = re.search(r"ip address (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)", ip_command.text)
            if ip_match:
                ip_addresses.append(ip_match.group(1))  # Add the IP address to the list

        return ip_addresses


    def print_summary(self):
        print(f"Hostname: {self.hostname}")
        print(f"Default Gateway: {self.gateway}")
        print(f"All SVIs: {self.all_SVIs}")
        print(f"All Interfaces: {self.regular_interfaces}")
        print(f"Disabled Interfaces: {self.disabled_interfaces}")
        print(f"All VLANs: {self.all_VLANs}")
        print(f"VLAN Mapping: {self.vlan_mapping}")
        print(f"Tagged VLANs: {self.tagged_vlans}")
        print(f"Untagged VLANs: {self.untagged_vlans}")
        print(f"Interfaces with Tagged VLANs: {self.tagged_vlans_intf}")
        print(f"Interfaces with Untagged VLANs: {self.untagged_vlans_intf}")
        print(f"IP Addresses: {self.ip_addresses}")
        print("\n")

    
    

    def _check_existence(self, item_type, submitted_item, key, endpoint):
        response = requests.get(endpoint, headers=self.headers)
        item_ipam = response.json()
        found_item = False

        for result in item_ipam['results']:
            if result[key].lower() == submitted_item.lower():
                found_item = True
                return result[key]
        
        if not found_item:
            print(f"{item_type}: {submitted_item}, does not exists in IPAM. Exiting...")
            quit()
        quit()


    def _add_device_to_ipam(self):
        device_type = input("Device type: ")
        role = input("Device Role: ")
        site = input("Site: ")
        
        device_type = self._check_existence(item_type="Device Type", 
                                            submitted_item=device_type, key='model', 
                                            endpoint=f"{self.netbox_url}/api/dcim/device-types/")
       
        role = self._check_existence(item_type="Device Role", 
                                     submitted_item=role, key='name', 
                                     endpoint=f"{self.netbox_url}/api/dcim/device-roles/")

        site = self._check_existence(item_type="Site", 
                                     submitted_item=site, key='name', 
                                     endpoint=f"{self.netbox_url}/api/dcim/sites/")
        


        endpoint = f"{self.netbox_url}/api/dcim/devices/"
        
        device_data = {
            "name": self.hostname,
            "device_type": {"model": device_type},
            "role": {"name": role},  
            "site": {"name": site},  
        }
        response = requests.post(endpoint, json=device_data, headers=self.headers)
        
        if response.status_code == 201:
            print(f"{Colors.CYAN}{self.hostname} {Colors.GREEN}successfully added to IPAM{Colors.ENDC}")
            return response.json()['id']
        else:
            print(f"Failed to create device in IPAM. Status code: {response.status_code}, Reason: {response.reason}\nResponse: {response.text}")
            quit()

    def create_interface_objects(self):
        
        self.interfaces = []
        for intf in self.regular_interfaces:
            self.interfaces.append(Interface(intf))
        
        for intf in self.disabled_interfaces:
            for intfo in self.interfaces:
                if intf == intfo.name:
                    intfo.set_status("Disabled")
        
        for intfo in self.interfaces:
            if intfo.status != "Disabled":
                intfo.set_status("Enabled")

        for intf in self.vlan_mapping:
            for intfo in self.interfaces:
                if intf == intfo.name:
                    for vlan in self.vlan_mapping[intf]:
                        intfo.set_vlan(vlan)
        
        for intf in self.description_mapping:
            for intfo in self.interfaces:
                if intf == intfo.name:
                    intfo.set_description(self.description_mapping[intf])

    def _print_table(self, title, head, data):
        print("\n")
        max_lens = [max(len(str(row[i])) for row in [head] + data) for i in range(len(head))]
        total_width = sum(max_lens) + (3 * len(head)) + 1

        title_row = f"| {title.center(total_width - 4)} |"
        top_border = "+-" + "-" * (total_width - 4) + "-+"

        # Print the title row
        print(top_border)
        print(title_row)
        print(top_border)

        header_row = "| " + " | ".join(f"{head[i]:<{max_lens[i]}}" for i in range(len(head))) + " |"
        separator_row = "+-" + "-+-".join("-" * max_lens[i] for i in range(len(head))) + "-+"

        print(separator_row)
        print(header_row)
        print(separator_row)

        for row in data:
            row_str = "| " + " | ".join(f"{str(row[i]):<{max_lens[i]}}" for i in range(len(row))) + " |"
            print(row_str)

        print(separator_row)
    
    def _format_config_ipam(self, var1, var2):
        if isinstance(var1, list):
            var1_str_list = [str(x) for x in var1]
        else:
            var1_str_list = [str(var1)]
        
        if isinstance(var2, list):
            var2_str_list = [str(x) for x in var2]
        else:
            var2_str_list = [str(var2)]
        
        result1 = ",".join(var1_str_list)
        result2 = ",".join(var2_str_list)
        
        return result1, result2
    

    def _patch_interface(self, intf_id, body):
        response = requests.patch(f"{self.netbox_url}/api/dcim/interfaces/{intf_id}/", data=body, headers=self.headers)
        if response.status_code == 200:
            print(f"{Colors.GREEN}Successfully updated IPAM{Colors.ENDC}")

        else:
            print(response.text)
            print(f"{Colors.FAIL}Patch failed. Code:{response.status_code}, Reason: {response.reason}{Colors.ENDC}")
    
    def _create_vlan(self, vid):
        response = requests.get(f"{self.netbox_url}/api/ipam/vlans/?vid={vid}", headers=self.headers)
        if response.json()['count'] != 0:
            print(f"Cannot create vlan{vid}. It already exists. Check VLAN Groups")
        else: 
            v_name = input("Vlan Name: ")
            choosing = True
            while choosing:
                print("Choose an option:")
                print("1. Active")
                print("2. Reserved")
                print("3. Deprecated")
                        
                choice = input("Enter your choice (1-3): ")

                if choice == '1':
                    choosing = False
                    status = "active"

                elif choice == '2':
                    choosing = False
                    status = "reserved"
        
                elif choice == '3':
                    choosing = False
                    status = "deprecated"

                else:
                    print("Invalid choice, please try again.")
            
            response = requests.post(f"{self.netbox_url}/api/ipam/vlans/", 
                                    data=json.dumps({"name": v_name, "vid": vid, "status": status}), 
                                    headers=self.headers)
            if response.status_code == 201:
                print(f"{Colors.GREEN}Successfully updated created VLAN in IPAM{Colors.ENDC}")

            else:
                print(f"{Colors.FAIL}VLAN creation failed. Code:{response.status_code}, Reason: {response.reason}{Colors.ENDC}")
    
    def _get_vlanid(self, vlan_vid):
        params = ""
        for vid in vlan_vid:
            params = params + f"vid={vid}&"
        
        response = requests.get(f"{self.netbox_url}/api/ipam/vlans/?{params}", headers=self.headers)
        if response.status_code != 200:
            print(f"{Colors.FAIL} Connection failed. Code: {response.status_code}. Reason: {response.reason}{Colors.ENDC}")
        
        response = response.json()
        vlans = response['results']

        ipam_vlan_id = []
        ipam_vid = []

        for v in vlans:
            ipam_vlan_id.append(v["id"])
            ipam_vid.append(v["vid"])
        if not ipam_vlan_id:
            print("There is no VLAN in ipam instance")
        for v in vlan_vid:
            if not int(v) in ipam_vid:
                print(f"VLAN{v} not found in IPAM")
                if (self.auto_update or (self.interactive and input(f"Do you want to create VLAN{v} in IPAM? [y/N]: ").lower() == "y")):
                    self._create_vlan(v)
                    ipam_vlan_id = []
                    ipam_vid = []

                    for v in vlans:
                        ipam_vlan_id.append(v["id"])
                        ipam_vid.append(v["vid"])

                return []
        return ipam_vlan_id
    
    
    def _iterate_interfaces(self):
        self.create_interface_objects()
        try:
            response = requests.get(
                f"{self.netbox_url}/api/dcim/interfaces/?device_id={self.device_id}",
                headers=self.headers
            ).json()
        except requests.RequestException as e:
            print(f"Failed to fetch interfaces: {e}")
            return

        if response.get('count', 0) < 1:
            print("No interfaces found in IPAM. Please create them.")

        if response['count'] != len(self.interfaces):
            print(
                f"IPAM interface count mismatch: {response['count']} != {len(self.interfaces)}"
            )
        
        for intf in response.get('results', []):
            matched_intf = next((i for i in self.interfaces if i.name == intf['name']), None)
            if not matched_intf:
                continue
            
            self._check_and_update_description(matched_intf, intf)
            self._check_and_update_status(matched_intf, intf)
            self._check_and_update_vlans(matched_intf, intf)

    def _check_and_update_description(self, config_intf, ipam_intf):
        if config_intf.description != ipam_intf.get('description'):
            self._handle_conflict(
                title="Conflicting description",
                intf=ipam_intf,
                ipam_value=ipam_intf['description'],
                config_value=config_intf.description,
                patch_data={"description": config_intf.description}
            )

    def _check_and_update_status(self, config_intf, ipam_intf):
        expected_status = config_intf.status == "Enabled"
        if expected_status != ipam_intf.get('enabled'):
            self._handle_conflict(
                title="Conflicting enable status",
                intf=ipam_intf,
                ipam_value=ipam_intf['enabled'],
                config_value=expected_status,
                patch_data={"enabled": expected_status}
            )

    def _check_and_update_vlans(self, config_intf, ipam_intf):
        config_tagged_vlans = [int(v.strip('T')) for v in config_intf.vlan if v.endswith('T')]
        config_untagged_vlan = next((int(v.strip('U')) for v in config_intf.vlan if v.endswith('U')), None)
        ipam_tagged_vlans = [v['vid'] for v in ipam_intf.get('tagged_vlans', [])]
        ipam_untagged_vlan = ipam_intf.get('untagged_vlan')

        if config_untagged_vlan:
            if not ipam_untagged_vlan:
                ipam_untagged_vlan = {}
                ipam_untagged_vlan['vid'] = ""
            if config_untagged_vlan != ipam_untagged_vlan['vid']:
                vid = self._get_vlanid([config_untagged_vlan])
                self._handle_conflict(
                    title="Untagged VLAN mismatch",
                    intf=ipam_intf,
                    ipam_value=ipam_untagged_vlan['vid'],
                    config_value=config_untagged_vlan,
                    patch_data={"mode": "access", "untagged_vlan": {"id": vid[0]}}
                )
        elif config_tagged_vlans:
            if set(config_tagged_vlans) != set(ipam_tagged_vlans):
                self._handle_conflict(
                    title="Tagged VLAN mismatch",
                    intf=ipam_intf,
                    ipam_value=ipam_tagged_vlans,
                    config_value=config_tagged_vlans,
                    patch_data={"mode": "tagged", "tagged_vlans": self._get_vlanid(config_tagged_vlans)}
                )
        else:
            if not (ipam_tagged_vlans == config_tagged_vlans):
                self._handle_conflict(
                        title="VLAN mismatch",
                        intf=ipam_intf,
                        ipam_value=ipam_tagged_vlans,
                        config_value=config_tagged_vlans,
                        patch_data={"mode": None, "tagged_vlans": [], "untagged_vlan": None}
                    )

    def _handle_conflict(self, title, intf, ipam_value, config_value, patch_data):
        head = ["Host", "Interface", "Config", "IPAM"]
        data = [[self.hostname, intf['name'], config_value, ipam_value]]
        self._print_table(title=title, head=head, data=data)

        if self.auto_update or (self.interactive and input("Update IPAM? [y/N]: ").lower() == "y"):
            self._patch_interface(intf['id'], json.dumps(patch_data))
            print("\n")
    

    def compare_netbox(self):

        try:
            response = requests.get(f"{self.netbox_url}/api/dcim/devices/?name={self.hostname}", headers=self.headers)
            
            if response.status_code != 200:
                print(f"{Colors.RED}Get requested failed. {Colors.ENDC}Status code: {response.status_code}.\nReason: {response.reason}")
                quit()

            ipam_device = response.json()

            if ipam_device['count'] < 1:
                print("Device not found in IPAM", self.hostname)
                if (self.auto_update or (self.interactive and input("Would you like to add this device to IPAM [y/N]: ").lower() == "y")):
                    self.device_id = self._add_device_to_ipam()
                    response = requests.get(f"{self.netbox_url}/api/dcim/devices/?id={self.device_id}", headers=self.headers)
                    self.ipam_device = response.json()['results'][0]

            else:
                self.ipam_device = ipam_device["results"][0]
                self.device_id = self.ipam_device['id']

            self._iterate_interfaces()

    
        except Exception as e:
            print(e)
            print("Detailed Error:", repr(e))
            traceback.print_exc()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        help="The path of config file(s)",
        nargs='+',
        required=True
    )
    parser.add_argument(
        "-u",
        help="The NetBox URL",
        required=True
    )
    parser.add_argument(
        "-t",
        help="The NetBox API token",
        required=True
    )

    parser.add_argument(
        "-i",
        help="Interactively prompt for resolution to differences",
        action="store_true"
    )

    parser.add_argument(
        "-a",
        help="Auto update missing data to ipam",
        action="store_true"
    )

    parser.add_argument(
        "-v",
        help="Verbose - Prints summary and other information",
        action="store_true"
    )

    args = parser.parse_args()

    if args.a:
        auto_update = True
    else:
        auto_update = False


    if args.i:
        interactive = True
    else:
        interactive = False

    if args.v:
        verbose = True
    else:
        verbose = False
    
    for conf_file in args.c:
        path = Path(conf_file)
        if not path.is_file():
            print(f"Error: {conf_file} is not a valid file or does not exist.")
            return

    if len(args.c) == 1:
        device = CiscoDevice(config_path=args.c[0], netbox_url=args.u, 
                        netbox_token=args.t, auto_update=auto_update,
                        interactive=interactive)
        device.parse_config()
        if verbose:
            device.print_summary()

        device.compare_netbox()


    else:
        devices = [CiscoDevice(config_path=conf_file, netbox_url=args.n, netbox_token=args.t, auto_update=auto_update) for conf_file in args.c]
        for device in devices:
            device.parse_config()
            if verbose:
                device.print_summary()

            device.compare_netbox()



if __name__ == "__main__":
    print(f"""
{Colors.CYAN} ██████╗██╗███████╗ ██████╗ ██████╗  {Colors.ENDC}   ████████╗ ██████╗
{Colors.CYAN}██╔════╝██║██╔════╝██╔════╝██╔═══██╗ {Colors.ENDC}   ╚══██╔══╝██╔═══██╗
{Colors.CYAN}██║     ██║███████╗██║     ██║   ██║ {Colors.ENDC}      ██║   ██║   ██║
{Colors.CYAN}██║     ██║╚════██║██║     ██║   ██║ {Colors.ENDC}      ██║   ██║   ██║
{Colors.CYAN}╚██████╗██║███████║╚██████╗╚██████╔╝ {Colors.ENDC}      ██║   ╚██████╔╝
{Colors.CYAN} ╚═════╝╚═╝╚══════╝ ╚═════╝ ╚═════╝  {Colors.ENDC}      ╚═╝    ╚═════╝ 
                                                          
{Colors.GREEN}              ██╗██████╗  █████╗ ███╗   ███╗                            
              ██║██╔══██╗██╔══██╗████╗ ████║                               
              ██║██████╔╝███████║██╔████╔██║                            
              ██║██╔═══╝ ██╔══██║██║╚██╔╝██║                            
              ██║██║     ██║  ██║██║ ╚═╝ ██║                            
              ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝     ╚═╝{Colors.ENDC}                            
          """
          )
    try:
        from ciscoconfparse2 import CiscoConfParse  
        import json
        import requests
        import argparse
        import traceback
        from pathlib import Path
        import re
    except Exception as e:
        print(f"""Missing dependencies - {e}\nPlease do the following:
    {Colors.BOLD}For {Colors.GREEN}Linux{Colors.ENDC}:
        python3 -m venv venv
        source venv/bin/activate
        pip3 install -r requirements.txt OR python3 -m pip install -r requirements.txt
              
    {Colors.BOLD}For {Colors.CYAN}Windows{Colors.ENDC}:
        python -m venv venv
        .\\venv\Scripts\Activate.ps1
        pip3 install -r .\\requirements.txt OR python -m pip install -r requirements.txt
              """)
        quit()
    main()