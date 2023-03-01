import http.client
import urllib.request
import urllib.parse
import urllib.error
import base64
import json

headers = {
    # Request headers
    # 'Ocp-Apim-Subscription-Key': '{subscription key}',
    'Authorization': '***',
    'accept': 'text/plain',
}

params = urllib.parse.urlencode({
    # Request parameters
    'instCode': 'KAA',
    # 'groupedInstCode': '{string}',
})

try:
    conn = http.client.HTTPSConnection('stidapi.equinor.com')
    conn.request("GET", "/plants?%s" % params, "{body}", headers)
    response = conn.getresponse()
    data = response.read().decode('utf-8')
    # print(data)
    data = json.loads(data)
    print(json.dumps(data, indent=4))
    # print(data[10])

    # for installation in data:
    #     if installation["instCode"] == "KAA":
    #         print(installation)

    conn.close()
except Exception as e:
    print("[Errno {0}] {1}".format(e.errno, e.strerror))
