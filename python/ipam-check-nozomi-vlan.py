# Import necessary modules
import argparse
import http.client
import urllib.parse
import urllib.error
import json
import csv


# Define the command-line arguments using argparse module
parser = argparse.ArgumentParser()
parser.add_argument("-t", help='API token', required=True)
parser.add_argument("-f", help='Nodes file', required=True)
args = parser.parse_args()

# Assign variables to the command-line arguments
token = args.t
file_path = args.f


# Initialize a list to store nodes from the nodes file
nodes = []

# Initialize a list to store VLANs from the API
vlans_api = []

# Initialize a list to store output data
output_data = []

# Read data from the nodes file and add nodes to the nodes list
with open(file_path, newline='') as file:
    reader = csv.DictReader(file, delimiter=';')
    for row in reader:
        node = {
            'ip': row['ip'],
            'label': row['label'],
            'vlan_id': row['vlan_id'],
        }

        nodes.append(node)

# Set up the headers for the API request
headers = {
    'Authorization': f'Token {token}', # Set the authorization token for the header
    'accept': 'application/json', # Set the response data format
}

# Set up a connection to the IPAM API server
conn = http.client.HTTPSConnection('karsto-ipam.equinor.com')
#object for count storage in if loop
counter = 0
for n in nodes:
    # Skip nodes that do not have a valid IP address or VLAN ID
    if len(n['ip']) > 2 and len(n['vlan_id']) > 0:
        #print (n)
        try:
            # Prepare the query parameters for the API request using urllib.parse.urlencode
            params = urllib.parse.urlencode({
                'contains': n['ip'], # Set the VLAN ID as the query parameter
            })
            
            # Send an HTTP GET request to the IPAM API server and get the response data
            conn.request("GET", f"/api/ipam/prefixes/?{params}", None, headers)
            response = conn.getresponse()

            # Check if the API request was successful. If not, print an error message and exit
            if response.code != 200:
                print(
                    f'Connection failed. Code: {response.code}, Reason: {response.reason}')
                quit()
            data = response.read().decode('utf-8')

            # Parse the response data as JSON
            data = json.loads(data)
            # Compares nozomi and IPAM vlans and prints the IPs and Vlans for the non-matches
            for d in data['results']:
                if d['vlan']: 
                   # print (d['vlan']['vid'])
                    if d['vlan']['vid'] != int(n['vlan_id']):
                       print ("Nozomi IP:", n['ip'],"Nozomi VLAN:",int(n['vlan_id']),"IPAM IP:", d['prefix'],"IPAM VLAN:", d['vlan']['vid'])
                       counter = counter + 1
                   # else:
                       # print ("Nozomi IP:", n['ip'],"IPAM IP:", d['display'],"VLAN MATCH")
            
           
        # Catch and print any exceptions that occur during the API request, add them to the output data
        except Exception as e:
          print (e)
print ("Number of mismatching VLAN/IP:", counter)        
# Close the connection
conn.close()


