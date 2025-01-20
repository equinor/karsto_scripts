import http.client
import urllib.request
import urllib.parse
import urllib.error
import json
import argparse

conn = http.client.HTTPSConnection('karsto-ipam.equinor.com')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", help='API token', required=True)
    parser.add_argument("-i", help='Interactively prompt for resolution to differences', action="store_true")
    parser.add_argument("-a", help='Autoupdate information in IPAM', action="store_true")
    parser.add_argument("--ports", help='File with ports information', required=True)
    parser.add_argument("--devices", help='File with devices information', required=True)
    parser.add_argument("--qrs", help='File with qr codes information', required=True)
    args = parser.parse_args()
    token = args.t
    interactive = args.i
    autoupdate = args.a

    if (autoupdate and input("Are you sure you want to automatically update IPAM? (yes,NO) ").lower() != 'yes'):
        quit()

    # Exported ports list from HiVision
    ports_path = args.ports
    # Exported devices list from HiVision
    devices_path = args.devices
    # Exported QR codes list from HiVision
    qr_code_path = args.qrs

    ports = {}
    with open(file=ports_path, mode='r') as file:
        firstline = True
        keys = []

        for l in file.readlines()[2:]:
            if firstline:
                # read keys from first line
                firstline = False
                keys = l.replace('"', '').rstrip().split(';')
                keys = list(map(lambda k: k.strip(), keys))
                continue

            values = l.replace('"', '').split(';')
            ipam_port = {}
            for k in range(len(keys)):
                ipam_port[keys[k]] = values[k].strip('"').rstrip()

            if (not ipam_port["Device"] in ports.keys()):
                ports[ipam_port["Device"]] = []

            ports[ipam_port["Device"]].append(ipam_port.copy())

    devices = {}
    with open(file=devices_path, mode='r') as file:
        firstline = True
        keys = []

        for l in file.readlines()[3:]:
            if firstline:
                # read keys from first line
                firstline = False
                keys = l.replace('"', '').rstrip().split(';')
                keys = list(map(lambda k: k.strip(), keys))
                continue

            values = l.replace('"', '').split(';')
            device = {}
            for k in range(len(keys)):
                device[keys[k]] = values[k].strip('"').rstrip()

            devices[device["IP Address"]] = device.copy()
            devices[device["IP Address"]]["QR Code"] = None

    with open(file=qr_code_path, mode='r') as file:
        firstline = True
        keys = []

        for l in file.readlines()[3:]:
            if firstline:
                # read keys from first line
                firstline = False
                keys = l.replace('"', '').rstrip().split(';')
                keys = list(map(lambda k: k.strip(), keys))
                continue

            values = l.replace('"', '').split(';')
            device = {}
            for k in range(len(keys)):
                device[keys[k]] = values[k].strip('"').rstrip()

            devices[device["IP Address"]]["QR Code"] = device["Value"].split('+')[1]

    headers = {
        # Request headers
        'Authorization': f'Token {token}',
        'accept': 'application/json',
        'Content-Type': 'application/json',
    }

# Check devices
    print("# Check Devices")
    for d in devices:
        device_name = devices[d]["System Name"]

        try:
            params = urllib.parse.urlencode({
                'name': device_name
            })
            conn.request("GET", f"/api/dcim/devices/?{params}", None, headers)
            response = conn.getresponse()
            if response.code != 200:
                print(
                    f'Connection failed. Code: {response.code}, Reason: {response.reason}')
                quit()
            ipam_device = json.loads(response.read().decode('utf-8'))
            if (ipam_device["count"] < 1):
                print("Device not found in IPAM:", device_name)
                continue

            ipam_device = ipam_device["results"][0]

            params = urllib.parse.urlencode({
                'id': ipam_device["device_type"]["id"]
            })
            conn.request("GET", f"/api/dcim/device-types/?{params}", None, headers)
            response = conn.getresponse()
            if response.code != 200:
                print(
                    f'Connection failed. Code: {response.code}, Reason: {response.reason}')
                quit()
            ipam_device_type = json.loads(response.read().decode('utf-8'))["results"][0]

            conn.close()
        except Exception as e:
            print("Exception", device_name, e)


        if (not ipam_device["rack"]):
            print(f'{device_name}: un-racked "{devices[d]["Location"]}"')
        elif (ipam_device["rack"] and devices[d]["Location"].find(ipam_device["rack"]["name"]) < 0):
            print(f'{device_name}: rack "{devices[d]["Location"]}" != "{ipam_device["rack"]["name"]}"')
            #if (autoupdate or (interactive and input("Update IPAM? (y,N) ").lower() == 'y')):

        if (devices[d]["QR Code"] != ipam_device_type["part_number"]):
            print(f'{device_name}: part number "{devices[d]["QR Code"]}" != "{ipam_device_type["part_number"]}"')



# Check ports and interfaces
    print("# Check ports and interfaces")
    for d in ports:
        params = urllib.parse.urlencode({
            'address': d
        })

        try:
            conn.request("GET", "/api/ipam/ip-addresses/?%s" %
                            params, None, headers)
            response = conn.getresponse()
            # print(response.code)
            if response.code != 200:
                print(
                    f'Connection failed. Code: {response.code}, Reason: {response.reason}')
                quit()
            address = json.loads(response.read().decode('utf-8'))
            conn.close()

            # print(address)
            if address["count"] < 1:
                print("IP address not found in IPAM", d)
                continue

            if address["count"] > 1:
                print("More than one IP found in IPAM", d)
                continue

            device_id = address["results"][0]["assigned_object"]["device"]["id"]
            params = urllib.parse.urlencode({
                'device_id': device_id
            })
            
            conn.request("GET", "/api/dcim/interfaces/?%s" %
                            params, None, headers)
            response = conn.getresponse()
            # print(response.code)
            if response.code != 200:
                print(
                    f'Connection failed. Code: {response.code}, Reason: {response.reason}')
                quit()
            interface = json.loads(response.read().decode('utf-8'))
            conn.close()

            if (interface["count"] != len(ports[d])):
                print("Number of interfaces does not match", d)
                continue

            for i in interface["results"]:
                device_port = None
                for p in ports[d]:
                    if (p["Port"] == i["name"]):
                        device_port = p
                        continue
                if (not device_port):
                    print("Port not found", d, i["name"])
                    continue

                if (device_port["Port Name"].strip() != i["description"]):
                    print(f'{d} port {device_port["Port"]}: description "{device_port["Port Name"]}" != "{i["description"]}"')
                    if (autoupdate or (interactive and input("Update IPAM? (y,N) ").lower() == 'y')):
                        patch_interface(i["id"], json.dumps({"description": f"{device_port['Port Name']}"}), headers)

                device_port_enabled = device_port["Port Enabled"] == 'Yes'
                if (device_port_enabled != i["enabled"]):
                    print(f'{d} port {device_port["Port"]}: port enabled "{device_port["Port Enabled"]}" != "{i["enabled"]}"')
                    if (autoupdate or (interactive and input("Update IPAM? (y,N) ").lower() == 'y')):
                        patch_interface(i["id"], json.dumps({"enabled": device_port_enabled}), headers)

                device_vlans = device_port["VLANs"].split(',')
                if (device_vlans[0] == ''):
                    device_vlans = []
                device_untagged_vlan = None
                device_tagged_vlan = []
                for vlan in device_vlans:
                    if (vlan[-1] == 'U'):
                        device_untagged_vlan = int(vlan[0:-1])
                    elif (vlan[-1] == 'T'):
                        device_tagged_vlan.append(int(vlan[0:-1]))
                ipam_tagged_vlan = []
                for vlan in i["tagged_vlans"]:
                    ipam_tagged_vlan.append(vlan["vid"])

                tagged_vlan_diff = False
                for vlan in device_tagged_vlan:
                    if (not vlan in ipam_tagged_vlan):
                        tagged_vlan_diff = True
                        break
                for vlan in ipam_tagged_vlan:
                    if (not vlan in device_tagged_vlan):
                        tagged_vlan_diff = True
                        break
                if (tagged_vlan_diff):
                    print(f'{d} port {device_port["Port"]}: tagged vlan {device_tagged_vlan} != {ipam_tagged_vlan}')
                    if (autoupdate or (interactive and input("Update IPAM? (y,N) ").lower() == 'y')):
                        if (len(device_tagged_vlan) > 0):
                            vlan_id = get_vlanid(device_tagged_vlan, headers)
                            patch_interface(i["id"], json.dumps({"mode": "tagged", "tagged_vlans": vlan_id}), headers)
                        else:
                            patch_interface(i["id"], json.dumps({"mode": "access", "tagged_vlans": []}), headers)

                untagged_vlan_diff = False
                if (not i["untagged_vlan"] and not device_untagged_vlan):
                    pass
                elif (not i["untagged_vlan"] and device_untagged_vlan):
                    untagged_vlan_diff = True
                    print(f'{d} port {device_port["Port"]}: untagged vlan "{device_untagged_vlan}" != "{i["untagged_vlan"]}"')
                elif (i["untagged_vlan"]["vid"] != device_untagged_vlan):
                    untagged_vlan_diff = True
                    print(f'{d} port {device_port["Port"]}: untagged vlan "{device_untagged_vlan}" != "{i["untagged_vlan"]["vid"]}"')
                
                if (untagged_vlan_diff and (autoupdate or (interactive and input("Update IPAM? (y,N) ").lower() == 'y'))):
                    if (not device_untagged_vlan):
                        patch_interface(i["id"], json.dumps({"untagged_vlan": None}), headers)
                    else:
                        patch_interface(i["id"], json.dumps({"mode": "access", "untagged_vlan": {"vid": device_untagged_vlan}, "tagged_vlans": []}), headers)

        except Exception as e:
            print("Exception", device_port, e)

    conn.close()

def patch_interface(id, body, headers):
    conn.request("PATCH", f"/api/dcim/interfaces/{id}/", body, headers)
    response = conn.getresponse()
    # print(response.code)
    if response.code != 200:
        print(f'Patch failed. Code: {response.code}, Reason: {response.reason}')
    conn.close()

def get_vlanid(vlan_vid, headers):
    params = ""
    for vid in vlan_vid:
        params = params + f"vid={vid}&"
    params = params.rstrip('&')

    conn.request("GET", f"/api/ipam/vlans/?{params}", None, headers)
    response = conn.getresponse()
    if response.code != 200:
        print(
            f'Connection failed. Code: {response.code}, Reason: {response.reason}')
    vlan = json.loads(response.read().decode('utf-8'))
    vlan = vlan["results"]
    conn.close()
    vlan_id = []
    ipam_vid = []
    for v in vlan:
        vlan_id.append(v["id"])
        ipam_vid.append(v["vid"])
    for v in vlan_vid:
        if (not v in ipam_vid):
            print(f"VLAN {v} not found in IPAM")
            return []
    return vlan_id

if (__name__ == "__main__"):
    main()