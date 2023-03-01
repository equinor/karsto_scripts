import json
import zipfile

with zipfile.ZipFile('ics_637883424005750561.zip') as myzip:
    for file in myzip.namelist():
        with myzip.open(file) as datafile:
            j = json.loads(datafile.read())
            print('##')
            for e in j['Data']:
                print(e)
                # print('#')
