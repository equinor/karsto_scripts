import json
import os
import subprocess
import zipfile

events = []
event_count = 0

path = "archive"
files = os.listdir(path)
number_of_files = len(files)
current_file_number = 1
command=["curl", "-H", r'Content-Type: application/x-ndjson', "-XPOST", r'https://localhost:9200/_bulk?pretty', "--cacert", r"/mnt/ub/home/royvegard/elastic_stack/elasticsearch-8.6.2/config/certs/http_ca.crt", "-u", r"elastic:qVcMGZ7Kw9Qsic=ykvXg", "--data-binary", r"@out.json"]
index = { "create" : { "_index" : "sas-event-01" } }


for f in files:
    full_path = os.path.join(path, f)
    print("file %d of %d: %s " % (current_file_number, number_of_files, full_path))

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

                    events.append(event)
                    event_count = event_count + 1

                    if len(events) > 90000:
                        print("events: ", event_count)
                        with open("out.json", "w", encoding="utf-8") as out_file:
                            for ev in events:
                                out_file.write(json.dumps(index, ensure_ascii=False) + "\n")
                                out_file.write(json.dumps(ev, ensure_ascii=False) + "\n")

                        events.clear()
                        process = subprocess.run(args=command, text=True, capture_output=True)

                        error = process.stdout.find('"errors" : true')
                        if error > -1:
                            print("Errors! Sequence:", j['Sequence'])
                            #print(process.stdout)

    if len(events) > 0:
        print("remaining events: ", len(events))
        with open("out.json", "w", encoding="utf-8") as out_file:
            for ev in events:
                out_file.write(json.dumps(index, ensure_ascii=False) + "\n")
                out_file.write(json.dumps(ev, ensure_ascii=False) + "\n")

        events.clear()
        process = subprocess.run(args=command, text=True, capture_output=True)
        error = process.stdout.find('"errors" : true')
        if error > -1:
            print("Errors! Sequence:", j['Sequence'])

print("Done! Total events: ", event_count)
