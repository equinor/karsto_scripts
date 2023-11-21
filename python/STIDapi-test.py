import argparse
import http.client
import urllib.request
import urllib.parse
import urllib.error
import base64
import json

parser = argparse.ArgumentParser()
parser.add_argument("-t", help='API token', required=True)
args = parser.parse_args()
token = args.t

headers = {
    # Request headers
    # 'Ocp-Apim-Subscription-Key': '{subscription key}',
    'Authorization': f'Bearer {token}',
    'accept': 'text/plain',
}

params = urllib.parse.urlencode({
    # Request parameters
    'instCode': 'KAA',
    'tagNo': '93-ZA-101-SC16'
    # 'groupedInstCode': '{string}',
})

try:
    conn = http.client.HTTPSConnection('stidapi.equinor.com')
    conn.request("GET", "/KAA/tag/tag-refs?%s" % params, None, headers)
    response = conn.getresponse()
    data = response.read().decode('utf-8')
    # print(data)
    data = json.loads(data)
    #print(json.dumps(data, indent=4))
    # print(data[10])

    for tag in data:
        if tag["tagType"] == "NP":
            print(json.dumps(tag, indent=4))

    conn.close()
except Exception as e:
    print("[Errno {0}] {1}".format(e.errno, e.strerror))
