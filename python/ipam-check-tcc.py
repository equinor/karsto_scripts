import argparse
import http.client
import json

### Get command line arguments
parser = argparse.ArgumentParser()
parser.add_argument("-t", help='API token', required=True)
parser.add_argument("-f", help='TCC file', required=True)
args = parser.parse_args()
token = args.t
file_path = args.f

### Read json file generated by TCC Splunk.
# Search:
# index=ka_* sourcetype="Equinor - Win32_NetworkAdapterConfiguration" IPEnabled=TRUE
# | rex mode=sed field=MACAddress "s/(\w{4})(?=\w+)/\1./g"
# | eval MACAddress=lower(MACAddress)
# | lookup host_index_tag_domain.csv host AS host index AS index OUTPUT taginput as Tag 
# | dedup IPAddress_ext
# | table index host Tag Description IPAddress_ext IPSubnet_ext DefaultIPGateway_ext MACAddress ServiceName IPEnabled DNSServerSearchOrder
# | sort IPAddress_ext

nodes = []
with open(file=file_path, mode='r') as file:
    for l in file.readlines():
        node = json.loads(l)['result']
        nodes.append(node.copy())

### Get all IP adresses from IPAM
ipam_ip = []
conn = http.client.HTTPSConnection('karsto-ipam.equinor.com')
headers = {
    # Request headers
    'Authorization': f'Token {token}',
    'accept': 'application/json',
}
next = 'https://karsto-ipam.equinor.com/api/ipam/ip-addresses/?limit=5000'

while next:
    conn.request("GET", next, None, headers)
    response = conn.getresponse()
    if response.code != 200:
        print(
            f'Connection failed. Code: {response.code}, Reason: {response.reason}')
        quit()

    data = response.read().decode('utf-8')
    data = json.loads(data)

    # Only use the address part and not the netmask part
    for d in data['results']:
        ipam_ip.append(d['address'].split('/')[0])
    next = data['next']

### Compare
for n in nodes:
    if (not n['IPAddress_ext'] in ipam_ip):
        print("Not found in IPAM", n["IPAddress_ext"], n["Description"],
            n["Tag"], n["host"])
    else:
        pass

print("Nodes: ", len(nodes))
conn.close()
