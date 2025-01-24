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
    '''
    Represents an interface on an device, contains data such as:
    name, description, vlan and status.
    '''
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
    '''
    Represents a Cisco device.
    Parses configuration files to extract details such as:
    - Hostname
    - Default Gateway
    - Interfaces (regular, disabled, tagged/untagged VLANs)
    - VLAN details
    '''

    def __init__(self, config_path: str, netbox_url: str, netbox_token: str, auto_update: bool, interactive: bool):
        '''
        Initializes CiscoDevice object
        '''
        self.config_path = config_path
        self.conn = http.client.HTTPConnection(netbox_url)
        
        self.netbox_token = netbox_token
        self.auto_update = auto_update
        self.interactive = interactive

        self.headers = {
            "Authorization": f"Token {self.netbox_token}",
            "accept" : "application/json",
            "Content-Type": "application/json"
        }
        self.conn.request("GET", "/", None, headers=self.headers)
        self.conn.close()


    def parse_config(self):
        '''
        Parses cisco config file populates variables for later use.
        '''
        print(f"{Colors.BOLD}Parsing configuration: {Colors.CYAN}{self.config_path}{Colors.ENDC}")
        try:
            parse = CiscoConfParse(self.config_path, factory=True)
        except Exception as e:
            raise Exception(f"Failed to parse config file {self.config_path}: {e}")

        # Hostname
        self.hostname = self._parse_hostname(parse)
        print(f"Host - {Colors.GREEN}{self.hostname}{Colors.ENDC}")

        # Default Gateway
        self.gateway = self._parse_default_gateway(parse)

        # Interfaces
        self.all_SVIs, self.regular_interfaces = self._parse_interfaces(parse)
        self.disabled_interfaces = self._parse_disabled_interfaces(parse)
        self.enabled_interfaces = self._parse_enabled_interfaces(parse)
        
        # Remove enabled interfaces from the disable interface list
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

        # IP Addresses
        self.ip_addresses = self._parse_IP_addr_from_config(parse)

    def _parse_hostname(self, parse):
        '''
        Extracts the hostname.
        '''
        hostnames = parse.find_objects(r'^hostname')
        hostnames = [obj.text.split()[1] for obj in hostnames]
        if not hostnames:
            raise Exception(f"No hostname found in {self.config_path}. Aborting!")
        if len(hostnames) > 1:
            raise Exception(f"Multiple hostnames found in {self.config_path}. Aborting!")
        return hostnames[0]

    def _parse_default_gateway(self, parse):
        '''
        Extracts the default gateway.
        '''
        find_gateways = parse.find_objects(r'^ip default-gateway')
        gateways = [obj.text.split()[2] for obj in find_gateways if len(obj.text.split()) > 2]
        if len(gateways) > 1:
            raise Exception(f"Multiple default gateways found in {self.config_path}. Aborting!")
        return gateways[0] if gateways else "Not Configured"

    def _parse_interfaces(self, parse):
        '''
        Extracts all interfaces and separates SVIs.
        '''
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
                description = ''
            self.description_mapping[int_name.replace("interface ", "")] = description

        return all_SVIs, regular_interfaces

    def _parse_disabled_interfaces(self, parse):
        '''
        Extracts all disabled (shutdown) interfaces.
        '''
        shut_intf = parse.find_parent_objects(r'^interface', r'shutdown')
        return [obj.text.split()[1] for obj in shut_intf]
    
    def _parse_enabled_interfaces(self, parse):
        '''
        Extracts all disabled (shutdown) interfaces.
        '''
        shut_intf = parse.find_parent_objects(r'^interface', r'no shutdown')
        return [obj.text.split()[1] for obj in shut_intf]

    def _parse_vlans(self, parse):
        '''
        Extracts all VLANs and builds a mapping of interfaces to VLANs
        '''
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
        '''
        Finds interfaces with tagged VLANs (trunk mode)
        '''
        trunk_intf = parse.find_parent_objects(r'^interface', r'switchport trunk encapsulation dot1q')
        return [obj.text.split()[1] for obj in trunk_intf]

    def _parse_untagged_interfaces(self, parse):
        '''
        Finds interfaces with untagged VLANs (access mode).
        '''
        access_intf = parse.find_parent_objects(r'^interface', r'switchport mode access')
        return [obj.text.split()[1] for obj in access_intf]

    def _expand_vlans(self, vlan_list):
        '''
        Expands VLAN ranges into individual VLAN IDs.
        '''
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
        '''
        Parses config file to find ip addresses
        '''
        # Find all IP addresses
        ip_addresses = []
        
        # Search for 'ip address' in the configuration file (common for interfaces and SVIs)
        ip_commands = parse.find_objects(r"ip address")
        for ip_command in ip_commands:
            # Extract the IP address and subnet mask from the 'ip address' command
            ip_match = re.search(r"ip address (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)", ip_command.text)
            if ip_match:
                ip_addresses.append(ip_match.group(1))  # Add the IP address to the list

        return ip_addresses


    def print_summary(self):
        '''
        Prints out all collected data from the config file
        '''
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
        '''
        Checks if a given item already exists in IPAM.
        '''
        self.conn.request("GET", endpoint, headers=self.headers)
        response = self.conn.getresponse()
        
        item_ipam = json.loads(response.read().decode('utf-8'))
        found_item = False

        for result in item_ipam['results']:
            if result[key].lower() == submitted_item.lower():
                found_item = True
                return result[key]
        self.conn.close()
        if not found_item:
            print(f"{item_type}: {submitted_item}, does not exists in IPAM. Exiting...")
            quit()
        quit()


    def _add_device_to_ipam(self):
        '''
        Creates a new device in IPAM. It asks the user for device type, device role and site.
        It then checks if the submitted data exists in IPAM, and if it does, then it will create the device.
        '''
        device_type = input("Device type: ")
        role = input("Device Role: ")
        site = input("Site: ")
        
        # Check if submitted device type exists
        device_type = self._check_existence(item_type="Device Type", 
                                            submitted_item=device_type, key='model', 
                                            endpoint="/api/dcim/device-types/")
       
        # Check if submitted device role exists
        role = self._check_existence(item_type="Device Role", 
                                     submitted_item=role, key='name', 
                                     endpoint="/api/dcim/device-roles/")

        # Check if submitted site exists
        site = self._check_existence(item_type="Site", 
                                     submitted_item=site, key='name', 
                                     endpoint="/api/dcim/sites/")
        


        endpoint = "/api/dcim/devices/"
        
        device_data = {
            "name": self.hostname,
            "device_type": {"model": device_type},
            "role": {"name": role},  
            "site": {"name": site},  
        }
        device_data = json.dumps(device_data)
        # Send POST request to create device in NetBox
        self.conn.request("POST", endpoint, body=device_data, headers=self.headers)
        response = self.conn.getresponse()
        dev_id = json.loads(response.read().decode('utf-8'))['id']
        self.conn.close()
        
        # Check if the request was successful
        if response.code == 201:
            print(f"{Colors.CYAN}{self.hostname} {Colors.GREEN}successfully added to IPAM{Colors.ENDC}")
            return dev_id
        else:
            print(f"Failed to create device in IPAM. Status code: {response.code}, Reason: {response.reason}\nResponse: {response.text}")
            quit()

    def create_interface_objects(self):
        '''
        Creates instances(objects) of the Interface class.
        It takes the data found from the given config file and create these objects with the config data
        '''
        # Create an Interface object for each interface
        self.interfaces = []
        for intf in self.regular_interfaces:
            self.interfaces.append(Interface(intf))
        
        # Set disable for shutdown interfaces
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
        ''''
        Prints the difference table. It automatically sets the size of itself
        based on the length of the given data, and puts the title, header and data in their correct cell.  
        '''
        print("\n")
        max_lens = [max(len(str(row[i])) for row in [head] + data) for i in range(len(head))]
        # Calculate total table width including separators and padding
        total_width = sum(max_lens) + (3 * len(head)) + 1

        # Create the title row (centered)
        title_row = f"| {title.center(total_width - 4)} |"
        top_border = "+-" + "-" * (total_width - 4) + "-+"

        # Print the title row
        print(top_border)
        print(title_row)
        print(top_border)

        # Print the table header
        header_row = "| " + " | ".join(f"{head[i]:<{max_lens[i]}}" for i in range(len(head))) + " |"
        separator_row = "+-" + "-+-".join("-" * max_lens[i] for i in range(len(head))) + "-+"

        print(separator_row)
        print(header_row)
        print(separator_row)

        # Print table rows
        for row in data:
            row_str = "| " + " | ".join(f"{str(row[i]):<{max_lens[i]}}" for i in range(len(row))) + " |"
            print(row_str)

        print(separator_row)
    
    def _format_config_ipam(self, var1, var2):
        '''
        Formats the lists to strings that will shown in the difference table.
        Just to make them pretty :)
        '''
        # Convert the first variable to a list of strings
        if isinstance(var1, list):
            var1_str_list = [str(x) for x in var1]
        else:
            var1_str_list = [str(var1)]
        
        # Convert the second variable to a list of strings
        if isinstance(var2, list):
            var2_str_list = [str(x) for x in var2]
        else:
            var2_str_list = [str(var2)]
        
        # Join the values into comma-separated strings
        result1 = ",".join(var1_str_list)
        result2 = ",".join(var2_str_list)
        
        return result1, result2
    

    def _patch_interface(self, intf_id, body):
        '''
        Sends a PATCH request to the IPAM with the given interface ID and body
        '''
        self.conn.request("PATCH", f"/api/dcim/interfaces/{intf_id}/",body, headers=self.headers)
        response = self.conn.getresponse()
        self.conn.close()
        if response.code == 200:
            print(f"{Colors.GREEN}Successfully updated IPAM{Colors.ENDC}")

        else:
            print(response.text)
            print(f"{Colors.FAIL}Patch failed. Code:{response.code}, Reason: {response.reason}{Colors.ENDC}")
    
    def _create_vlan(self, vid):
        '''
        Creates a VLAN based on the submitted data from the user.
        The data required from the user is:
        Name
        Status
        VLAN group
        '''
        self.conn.request("GET", f"/api/ipam/vlans/?vid={vid}", headers=self.headers)
        response = self.conn.getresponse()
        
        if json.loads(response.read().decode('utf-8'))['count'] != 0:
            print(f"Cannot create vlan{vid}. It already exists. Check VLAN Groups")
        else: 
            v_name = input("Vlan Name: ")
            choosing_status = True
            while choosing_status:
                print("")
                print("Choose an option:")
                print(f"{Colors.GREEN}1{Colors.ENDC}. Active")
                print(f"{Colors.GREEN}2{Colors.ENDC}. Reserved")
                print(f"{Colors.GREEN}3{Colors.ENDC}. Deprecated")
                        
                choice = input("Enter your choice (1-3): ")

                if choice == '1':
                    choosing_status = False
                    status = "active"

                elif choice == '2':
                    choosing_status = False
                    status = "reserved"
        
                elif choice == '3':
                    choosing_status = False
                    status = "deprecated"

                else:
                    print("Invalid choice, please try again.")
            self.conn.close()
            self.conn.request("GET", f"/api/ipam/vlan-groups/?scope_type=dcim.region", headers=self.headers)
            response = self.conn.getresponse()
            r = json.loads(response.read().decode('utf-8'))
            available_vgroups = []
            if len(r['results']) > 1:
                for group in r['results']:
                    available_vgroups.append(
                        {"id": group['id'],
                         "name": group['name']}
                    )
                found_available_vgroup = True
            
            elif len(r) == 1:
                available_vgroups.append(
                        {"id": group['id'],
                         "name": group['name']}
                    )
                found_available_vgroup = True
            else:
                print(f"{Colors.WARNING}Could not find any VLAN groups for the site  the device is located. Skipping vlan group...")
                found_available_vgroup = False

            choosing_vlan_group = True
            counter = 1
            while found_available_vgroup and choosing_vlan_group:
                print("")
                print("Choose a VLAN Group")
                for group in available_vgroups:
                    print(f"{Colors.GREEN}{counter}{Colors.ENDC}. {group['name']}")
                    counter += 1
                counter -= 1
                
                choice = input(f"Enter your choice (1-{counter}): ")
                try:
                    choice = int(choice)
                    isNumber = True
                except:
                    print("Invalid choice, not a number, please try again.")
                    isNumber = False
                    counter = 1

                if isNumber and (choice >= 1 and choice <= counter):
                    vgroup = available_vgroups[choice-1]
                    choosing_vlan_group = False
                    found_available_vgroup = True
                else:
                    print("Invalid choice, please try again.")
                    counter = 1
            
            if found_available_vgroup:
                self.conn.close()
                self.conn.request("POST", "/api/ipam/vlans/", 
                                            body=json.dumps({"name": v_name, 
                                                            "vid": vid, 
                                                            "status": status,
                                                            "group": vgroup['id']}), 
                                            headers=self.headers)
            else:
                self.conn.close()
                self.conn.request("POST", "/api/ipam/vlans/", 
                                            body=json.dumps({"name": v_name, 
                                                            "vid": vid, 
                                                            "status": status}), 
                                            headers=self.headers)
            response = self.conn.getresponse()
            r = json.loads(response.read().decode('utf-8'))
            
            if response.code == 201:
                print(f"{Colors.GREEN}Successfully updated created VLAN in IPAM{Colors.ENDC}")
                return r

            else:
                print(f"{Colors.FAIL}VLAN creation failed. Code:{response.code}, Reason: {response.reason}{Colors.ENDC}")

        self.conn.close()

    def _get_vlan_group_id(self):
        '''
        Finds the all available VLAN groups for given device
        '''
        self.conn.request("GET", f"/api/dcim/sites/?id={self.device_site_id}", headers=self.headers)
        response = self.conn.getresponse()
        r = json.loads(response.read().decode('utf-8'))
        r = r['results'][0]        
        self.region_id = r['region']['id']
        self.region_name = r['region']['name']
        self.conn.close()

        self.conn.request("GET", f"/api/ipam/vlan-groups/?scope_type=dcim.region&scope_id={self.region_id}", headers=self.headers)
        response = self.conn.getresponse()
        r = json.loads(response.read().decode('utf-8'))
        if r['count'] == 1:
            r = r['results'][0]
            self.conn.close()
            return f"?group_id={r['id']}&"
        elif r['count'] > 1:
            vgroup_list = "?"
            for vg in r['results']:
                vgroup_list += f"group_id={vg['id']}&"
            return vgroup_list

    def _clarify_duplicate_vlans(self, vlan_group_id, dup_vlan):
        '''
        Handles multiple vlans with the same VLAN id in the same region in IPAM.
        It takes in the vlan group id and the duplicated vlan id
        '''
        self.conn.request("GET", f"/api/ipam/vlans/{vlan_group_id}vid={dup_vlan}", headers=self.headers)
        response = self.conn.getresponse()
        r = json.loads(response.read().decode('utf-8'))
        choosing_vlan = True
        while choosing_vlan:
            counter = 1
            head = ["#", "Name", "Vlan ID", "Vlan Description", "Group", "Region"]
            data = []
            counter = 0
            available_vlan = r['results']

            for result in available_vlan:
                counter += 1
                data.append([counter, result['name'], result['vid'], result['description'], result['group']['name'], self.region_name])
            
            self._print_table("Multiple VLANS", head=head, data=data)
            if self.auto_update or (self.interactive and input("Update IPAM? [y/N]: ").lower() == "y"):
                choice = input(f"Which VLAN do you want to use? [1-{counter}]")
                try:
                    choice = int(choice)
                    isNumber = True
                except:
                    print("Invalid choice, not a number, please try again.")
                    isNumber = False
                    counter = 1
                if isNumber and (choice >= 1 and choice <= counter):
                    vlan = available_vlan[choice-1]
                    choosing_vlan = False

                    for vl in available_vlan:
                        if vl is not vlan:
                            self.ipam_vlan.remove({"id": vlan['id'], "vid": vlan['vid']})
                            self.ipam_vlan_id.remove(vl["id"])
            else:
                choosing_vlan = False

        
    def _get_vlanid(self, vlan_vid):
        '''
        Fetch the ID of a VLAN ID.
        '''
        vlan_group_id = self._get_vlan_group_id()

        params = vlan_group_id
        for vid in vlan_vid:
            params = params + f"vid={vid}&"
        self.conn.request("GET", f"/api/ipam/vlans/{params}", headers=self.headers)
        response = self.conn.getresponse()
        r = json.loads(response.read().decode('utf-8'))
        self.conn.close()

        
        if response.code != 200:
            print(f"{Colors.FAIL} Connection failed. Code: {response.code}. Reason: {response.reason}{Colors.ENDC}")
        vlans = r['results']
        self.ipam_vlan_id = []
        self.ipam_vid = []
        self.ipam_vlan = []

        for v in vlans:
            self.ipam_vlan.append({"id": v['id'], "vid": v['vid']})
            self.ipam_vlan_id.append(v["id"])
            self.ipam_vid.append(v["vid"])

        if len(self.ipam_vid) != len(set(self.ipam_vid)): # Checks if there are duplicates in the vid list
            duplicates = list(set([x for x in self.ipam_vid if self.ipam_vid.count(x) > 1]))
            print(f"\n{Colors.WARNING}Duplicate VLAN IDs {duplicates} found in the same region in IPAM...{Colors.ENDC}")
            if len(duplicates) > 1:
                for dup in duplicates:
                    self._clarify_duplicate_vlans(vlan_group_id=vlan_group_id, dup_vlan=dup)
            elif len(duplicates) == 1:
                self._clarify_duplicate_vlans(vlan_group_id=vlan_group_id, dup_vlan=duplicates[0])
                
            else:
                print(f"{Colors.FAIL}Failed to give the user to choose which duplicate to used. Removing vlan {duplicates} from patch{Colors.ENDC}")
            

        for v in vlan_vid:
            if  int(v) not in self.ipam_vid:
                print(f"VLAN{v} not found in IPAM")
                if (self.auto_update or (self.interactive and input(f"Do you want to create VLAN{v} in IPAM? [y/N]: ").lower() == "y")):
                    created_vlan = self._create_vlan(v)
                    self.ipam_vlan_id.append(created_vlan["id"])
                    self.ipam_vid.append(created_vlan["vid"])
                    for v in vlans:
                        self.ipam_vlan_id.append(v["id"])
                        self.ipam_vid.append(v["vid"])

        return self.ipam_vlan_id


    def _iterate_interfaces(self):
        '''
        Iterates over all interfaces. Shows differences between config file and IPAM, and can update IPAM.
        '''
        self.create_interface_objects()
        try:
            self.conn.request("GET", f"/api/dcim/interfaces/?device_id={self.device_id}",
                                          headers=self.headers)
            response = self.conn.getresponse()
            response = json.loads(response.read().decode('utf-8'))
            self.conn.close()
            
        except Exception as e:
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
        '''
        Checks and updates the description on interface
        '''
        if config_intf.description != ipam_intf.get('description'):
            self._handle_conflict(
                title="Conflicting description",
                intf=ipam_intf,
                ipam_value=ipam_intf['description'],
                config_value=config_intf.description,
                patch_data={"description": config_intf.description}
            )

    def _check_and_update_status(self, config_intf, ipam_intf):
        '''
        Checks and updates the status on interface
        '''
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
        '''
        Checks and updates the VLANS on interface
        '''
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
                if len(vid) == 1:
                    self._handle_conflict(
                        title="Untagged VLAN mismatch",
                        intf=ipam_intf,
                        ipam_value=ipam_untagged_vlan['vid'],
                        config_value=config_untagged_vlan,
                        patch_data={"mode": "access", "untagged_vlan": {"id": vid[0]}}
                    )
                elif len(vid):
                    pass
        elif config_tagged_vlans:
            if set(config_tagged_vlans) != set(ipam_tagged_vlans):
                # Can not use _handle_conflict since it will try create new vlan before showing diff to user.
                title="Tagged VLAN mismatch"
                intf=ipam_intf
                ipam_value=ipam_tagged_vlans
                config_value=config_tagged_vlans
                head = ["Host", "Interface", "Config", "IPAM"]
                data = [[self.hostname, intf['name'], config_value, ipam_value]]
                self._print_table(title=title, head=head, data=data)
                patch_data={"mode": "tagged", "tagged_vlans": self._get_vlanid(config_tagged_vlans)}
                if self.auto_update or (self.interactive and input("Update IPAM? [y/N]: ").lower() == "y"):
                    self._patch_interface(intf['id'], json.dumps(patch_data))
                    print("\n")

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
        '''
        Handles visualization of differences between config and IPAM. In addition it will update IPAM if wanted.
        '''
        head = ["Host", "Interface", "Config", "IPAM"]
        data = [[self.hostname, intf['name'], config_value, ipam_value]]
        self._print_table(title=title, head=head, data=data)

        if self.auto_update or (self.interactive and input("Update IPAM? [y/N]: ").lower() == "y"):
            self._patch_interface(intf['id'], json.dumps(patch_data))
            print("\n")
    

    def compare_netbox(self):
        '''
        Entry point for comparing the config file and IPAM. 
        '''
        try:
            params = urllib.parse.urlencode({"name": self.hostname})
            self.conn.request("GET", f"/api/dcim/devices/?{params}", None, self.headers)
            response = self.conn.getresponse()
            
            
            if response.code != 200:
                r = json.loads(response.read().decode('utf-8'))
                print(f"{Colors.FAIL}Get requested failed. {Colors.ENDC}Status code: {response.code}. Reason: {response.reason}. Details: {r['detail']}")
                quit()

            r = response.read().decode('utf-8')
            if r.strip():
                ipam_device = json.loads(r)
            else:
                print("Failed to fetch devices in IPAM. Exiting....")
                return
            self.conn.close()
            if ipam_device['count'] < 1:
                print("Device not found in IPAM", self.hostname)
                if (self.auto_update or (self.interactive and input("Would you like to add this device to IPAM [y/N]: ").lower() == "y")):
                    self.device_id = self._add_device_to_ipam()
                    self.conn.request("GET", f"/api/dcim/devices/?id={self.device_id}", headers=self.headers)
                    response = self.conn.getresponse()
                    self.ipam_device = json.loads(response.read().decode('utf-8'))['results'][0]
                    self.device_id = self.ipam_device['id']
                    self.device_site_name = self.ipam_device['site']['name']
                    self.device_site_id = self.ipam_device['site']['id']
                    self.conn.close()
                else:
                    return

            else:
                self.ipam_device = ipam_device["results"][0]
                self.device_id = self.ipam_device['id']
                self.device_site_name = self.ipam_device['site']['name']
                self.device_site_id = self.ipam_device['site']['id']

            self._iterate_interfaces()

    
        except Exception as e:
            print(e)
            print("Detailed Error:", repr(e))
            traceback.print_exc()
        self.conn.close()

def main():
    # Argument parsing
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config",
        help="The path of config file(s)",
        nargs='+',
        required=True
    )
    parser.add_argument(
        "-u", "--url", 
        help="The NetBox URL",
        required=True
    )

    parser.add_argument(
        "-t", "--token", 
        help="The NetBox API token",
        required=True
    )

    parser.add_argument(
        "-i", "--interactive",
        help="Interactively prompt for resolution to differences",
        action="store_true"
    )

    parser.add_argument(
        "-a", "--autoupdate", 
        help="Auto update data to ipam",
        action="store_true"
    )

    parser.add_argument(
        "-v", "--verbose", 
        help="Verbose - Prints summary of extracted data from config file",
        action="store_true"
    )

    args = parser.parse_args()

    for conf_file in args.config:
        path = Path(conf_file)
        if not path.is_file():
            print(f"Error: {conf_file} is not a valid file or does not exist.")
            return

    if len(args.config) == 1:
        device = CiscoDevice(config_path=args.config[0], netbox_url=args.url, 
                        netbox_token=args.token, auto_update=args.autoupdate,
                        interactive=args.interactive)
        device.parse_config()
        if args.verbose:
            device.print_summary()

        device.compare_netbox()

    else:
        devices = [CiscoDevice(config_path=conf_file, netbox_url=args.url, netbox_token=args.token, auto_update=args.autoupdate, interactive=args.interactive) for conf_file in args.config]
        for device in devices:
            device.parse_config()
            if args.verbose:
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
        from ciscoconfparse import CiscoConfParse  
        import json
        import http.client
        import urllib.request
        import urllib.parse
        import urllib.error
        import argparse
        import traceback
        from pathlib import Path
        import re
    except Exception as e:
        print(f"""Missing dependency - {e}\nPlease do the following:
    {Colors.BOLD}For {Colors.GREEN}Linux{Colors.ENDC}:
        python3 -m venv venv
        source venv/bin/activate
        pip3 install ciscoconfparse OR python3 -m pip install ciscoconfparse
              
    {Colors.BOLD}For {Colors.CYAN}Windows{Colors.ENDC}:
        python -m venv venv
        .\\venv\Scripts\Activate.ps1
        pip3 install ciscoconfparse OR python -m pip install ciscoconfparse
              """)
        quit()
    main()