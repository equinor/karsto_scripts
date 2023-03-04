import json
import os
import zipfile

events = []
event_count = 0

path = "C:/temp/alarm-manager/archive"
files = os.listdir(path)
for f in files:
    full_path = os.path.join(path, f)
    print(full_path)
    with zipfile.ZipFile(full_path) as myzip:
        for file in myzip.namelist():
            with myzip.open(file) as datafile:
                j = json.loads(datafile.read())
                # print('##')
                for e in j['Data']:
                    # print(e)
                    event = {}
                    for i in range(len(e)):
                        #print(j['Schema'][i]['Name'], ": ", e[i])
                        event[j['Schema'][i]['Name']] = e[i]

                    # Format timestamp strings
                    event['TimeStamp'] = event['TimeStamp'].replace(
                        " ", "T", 1)
                    event['TimeStampLocal'] = event['TimeStampLocal'].replace(
                        " ", "T", 1)
                    event['ActiveTime'] = event['ActiveTime'].replace(
                        " ", "T", 1)

                    print(json.dumps(event, indent=4))
                    events.append(event)

                    if len(events) > 100000:
                        event_count = event_count + len(events)
                        print(event_count)
                        # TODO Output the collected events
                        events.clear()
                    # print('#')

    print(len(events))
