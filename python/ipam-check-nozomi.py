import argparse
import http.client
import urllib.request
import urllib.parse
import urllib.error
import json


parser = argparse.ArgumentParser()
parser.add_argument("-t", help='API token', required=True)
args = parser.parse_args()
token = args.t

file_path = "nodes.csv"
nodes = []
with open(file=file_path, mode='r') as file:
    firstline = True
    keys = []

    for l in file.readlines():
        if firstline:
            # read keys from first line
            firstline = False
            keys = l.split(';')
            continue

        values = l.split(';')
        node = {}
        for k in range(len(keys)):
            node[keys[k]] = values[k].strip('"')

        nodes.append(node.copy())

headers = {
    # Request headers
    'Authorization': f'Token {token}',
    'accept': 'application/json',
}

conn = http.client.HTTPSConnection('karsto-ipam.equinor.com')

for n in nodes:
    if n["is_broadcast"] == 'true':
        continue
    if len(n["ip"]) > 2:
        params = urllib.parse.urlencode({
            # Request parameters
            # 'format': 'json',
            # 'id': '31395',
            # 'custom_fields.security_zone': 'Analyse',
            'address': n["ip"]
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
            data = response.read().decode('utf-8')

            # print(data)
            data = json.loads(data)
            if data["count"] < 1:
                print("Not found in IPAM", n["ip"], n["label"],
                      n["mac_address"], n["mac_vendor"])
            else:
                if len(n["label"]) > 0:
                    names = []
                    for r in data["results"]:
                        if (r["assigned_object_type"] == "virtualization.vminterface"):
                            names.append(r["assigned_object"]
                                         ["virtual_machine"]["name"].lower())
                        elif (r["assigned_object_type"] == "dcim.interface"):
                            names.append(r["assigned_object"]
                                         ["device"]["name"].lower())
                    if not (n["label"].lower() in names):
                        #print("Wrong label ", "Network monitor: " + n["label"], "IPAM:", names)
                        pass
        except Exception as e:
            print("Exception", n["ip"], n["mac_address"],
                  n["mac_vendor"], e.__doc__)

print("Nodes: ", len(nodes))
conn.close()
