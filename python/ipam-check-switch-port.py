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
    args = parser.parse_args()
    token = args.t
    interactive = args.i
    autoupdate = args.a

    if (autoupdate and input("Are you sure you want to automatically update IPAM? (yes,NO) ").lower() != 'yes'):
        quit()
    #quit()

    # Exported ports list from HiVision
    file_path = "switch_ports.csv"

    devices = {}
    with open(file=file_path, mode='r') as file:
        firstline = True
        keys = []

        for l in file.readlines():
            if firstline:
                # read keys from first line
                firstline = False
                keys = l.replace('"', '').split(';')
                continue

            values = l.replace('"', '').split(';')
            ipam_port = {}
            for k in range(len(keys)):
                ipam_port[keys[k]] = values[k].strip('"')

            if (not ipam_port["Device"] in devices.keys()):
                devices[ipam_port["Device"]] = []

            devices[ipam_port["Device"]].append(ipam_port.copy())


    headers = {
        # Request headers
        'Authorization': f'Token {token}',
        'accept': 'application/json',
        'Content-Type': 'application/json',
    }

    for d in devices:
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

            if (interface["count"] != len(devices[d])):
                print("Number of interfaces does not match", d)
                continue

            for i in interface["results"]:
                device_port = None
                for p in devices[d]:
                    if (p["Port"] == i["name"]):
                        device_port = p
                        continue
                if (not device_port):
                    print("Port not found", i["name"])
                    continue

                if (device_port["Port Name"] != i["description"]):
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