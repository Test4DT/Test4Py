import os.path
import time
import json
from test4dt.config import config

class Recoder:
    def __init__(self):
        self.start_time = time.time()
        self.times = {}
        self.score = Score()

    def start_count_time(self, name):
        self.times[name] = time.time()

    def end_count_time(self, name):
        self.times[name] = time.time() - self.times[name]

    def end(self, project_name):
        end_time = time.time()
        if not os.path.exists('run_results'):
            try:
                os.mkdir('run_results')
            except FileExistsError:
                pass
        with open('./run_results/'+project_name+'.json', 'w') as f:
            json.dump({
                'time': end_time - self.start_time,
                'times': self.times,
                **self.score.to_json()
            }, f)

    
class Score:
    def __init__(self):
        self.first_run = True
        self.first_syntax_pass = 0
        self.first_syntax_error = 0
        self.first_syntax_fix_success = 0
        self.first_assertion_pass = 0
        self.first_assertion_error = 0
        self.first_assertion_fix_success = 0
        self.first_assertion_error_types = {}

        self.syntax_pass = 0
        self.syntax_error = 0
        self.syntax_fix_success = 0
        self.assertion_pass = 0
        self.assertion_error = 0
        self.assertion_fix_success = 0
        self.assertion_error_types = {}
        self.coverage = []

    def add_syntax_pass(self):
        self.syntax_pass += 1
        if self.first_run:
            self.first_syntax_pass += 1

    def add_syntax_error(self):
        self.syntax_error += 1
        if self.first_run:
            self.first_syntax_error += 1

    def add_syntax_fix_success(self):
        self.syntax_fix_success += 1
        if self.first_run:
            self.first_syntax_fix_success += 1

    def add_assertion_pass(self):
        self.assertion_pass += 1
        if self.first_run:
            self.first_assertion_pass += 1

    def add_assertion_error(self):
        self.assertion_error += 1
        if self.first_run:
            self.first_assertion_error += 1

    def add_assertion_fix_success(self):
        self.assertion_fix_success += 1
        if self.first_run:
            self.first_assertion_fix_success += 1

    def add_assertion_error_type(self, error_type: str):
        if error_type in self.assertion_error_types:
            self.assertion_error_types[error_type] += 1
        else:
            self.assertion_error_types[error_type] = 1
        if self.first_run:
            if error_type in self.first_assertion_error_types:
                self.first_assertion_error_types[error_type] += 1
            else:
                self.first_assertion_error_types[error_type] = 1

    def to_json(self):
        return {
            'syntax_pass': self.syntax_pass,
            'syntax_error': self.syntax_error,
            'syntax_fix_success': self.syntax_fix_success,
            'assertion_pass': self.assertion_pass,
            'assertion_error': self.assertion_error,
            'assertion_fix_success': self.assertion_fix_success,
            'assertion_error_types': self.assertion_error_types,
            'first_syntax_pass': self.first_syntax_pass,
            'first_syntax_error': self.first_syntax_error,
            'first_syntax_fix_success': self.first_syntax_fix_success,
            'first_assertion_pass': self.first_assertion_pass,
            'first_assertion_error': self.first_assertion_error,
            'first_assertion_fix_success': self.first_assertion_fix_success,
            'first_assertion_error_types': self.first_assertion_error_types,
            'coverage': self.coverage
        }

    def get_coverage(self, coverage, project):
        if not config.run_benchmark:
            return
        try:
            with open('projects.json', 'r') as f:
                projects = json.load(f)
        except FileNotFoundError:
            print('projects.json does not exist')
            return

        if not project in projects:
            print(f"{project} is not in projects.json")
            return

        result = {}
        modules = projects[project]
        for file_name, file in coverage['files'].items():
            module = file_name[:-3].replace("/", ".")
            if module in modules:
                result[module] = {
                    'covered_lines': file['summary']['covered_lines'],
                    'covered_branches': file['summary']['covered_branches'],
                    'num_statements': file['summary']['num_statements'],
                    'num_branches': file['summary']['num_branches']
                }
        self.coverage.append(result)
    
recoder = Recoder()
