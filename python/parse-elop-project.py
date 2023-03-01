import glob
import re
import json
import datetime


class Elop_Propserties:
    def __init__(self):
        self.file_name = ""
        self.info_name = ""
        self.generator_version = ""
        self.info_date = ""

        self.config_name = ""
        self.resource_name = ""
        self.program_name = ""
        self.code_version = ""
        self.program_version = ""
        self.data_version = ""
        self.area_version = ""
        self.run_version = ""
        self.program_size = ""

    def parse(self, file):
        self.file_name = file.name
        for l in file.readlines():
            if not self.info_name:
                info = p_info.search(l)
                if info:
                    self.generator_version = info.group(1)
                    self.info_name = info.group(2)
                    self.info_date = info.group(3)

            config_name = p_config_name.search(l)
            if config_name:
                self.config_name = config_name.group(1)

            resource_name = p_resource_name.search(l)
            if resource_name:
                self.resource_name = resource_name.group(1)

            program_name = p_program_name.search(l)
            if program_name:
                self.program_name = program_name.group(1)

            code_version = p_code_version.search(l)
            if code_version:
                self.code_version = code_version.group(1)

            program_version = p_program_version.search(l)
            if program_version:
                self.program_version = program_version.group(1)

            data_version = p_data_version.search(l)
            if data_version:
                self.data_version = data_version.group(1)

            area_version = p_area_version.search(l)
            if area_version:
                self.area_version = area_version.group(1)

            run_version = p_run_version.search(l)
            if run_version:
                self.run_version = run_version.group(1)

            program_size = p_program_size.search(l)
            if program_size:
                self.program_size = program_size.group(1)

    def dict(self):
        return {"info_name": self.info_name,
                "generator_version": self.generator_version,
                "info_date": self.get_date(),
                "config_name": self.config_name,
                "resource_name": self.resource_name,
                "program_name": self.program_name,
                "code_version": self.code_version,
                "program_version": self.program_version,
                "data_version": self.data_version,
                "area_version": self.area_version,
                "run_version": self.run_version,
                "program_size": self.program_size,
                "file_name": self.file_name}

    def get_date(self):
        date = datetime.strptime(self.info_date, "%d.%m.%Y %h:%M:%s")
        return date


files = glob.glob('**/*.ERR', recursive=True)

p_info = re.compile(r"Code generator (.*?) started for <(.*?)>: (.*?)$")
p_config_name = re.compile(r"Configuration name\s*=\s*(.*?)$")
p_resource_name = re.compile(r"Resource name\s*=\s*(.*?)$")
p_program_name = re.compile(r"Program name\s*=\s*(.*?)$")
p_code_version = re.compile(r"Code version.*\s*=\s*(.*?)$")
p_program_version = re.compile(r"Program version\s*=\s*(.*?)$")
p_data_version = re.compile(r"Data version.*\s*=\s*(.*?)$")
p_area_version = re.compile(r"Area version.*\s*=\s*(.*?)$")
p_run_version = re.compile(r"Run version.*\s*=\s*(.*?)$")
p_program_size = re.compile(r"Program size\s*=\s*(.*?)\s*Byte")

props = []
for file_path in files:
    elop_props = Elop_Propserties()

    with open(file=file_path, mode='r') as file:
        elop_props.parse(file)

    props.append(elop_props.dict())

print(json.dumps(props))
