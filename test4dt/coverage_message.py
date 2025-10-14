import json
import os.path
import subprocess
from dotenv import load_dotenv


class MyCoverage:
    def __init__(self, path, test_path, source_dir):
        self.path = path
        self.test_path = test_path
        self.source_dir = source_dir
        load_dotenv()

    def get_coverage(self):
        cwd_path = self.path
        args = [os.getenv('USER_PYTHON_PATH'), '-m', 'coverage', 'run', '-m', '--branch', f'--source={self.source_dir}', 'pytest', '--continue-on-collection-errors', self.test_path]
        process = subprocess.Popen(args, cwd=cwd_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.communicate()

        args = [os.getenv('USER_PYTHON_PATH'), '-m', 'coverage', 'json', '-i', '-o', f'{self.test_path}/coverage.json']
        process = subprocess.Popen(args, cwd=cwd_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.communicate()

        with open(os.path.join(self.path, f'{self.test_path}/coverage.json'), 'r') as f:
            return json.load(f)


class CoverageMessage:
    def __init__(self, missing_lines, summary):
        self.missing_lines = missing_lines
        self.summary = summary

    def get_missing_lines(self):
        return self.summary['missing_lines']

    def get_covered_lines(self):
        return self.summary['covered_lines']

    def get_missing_branches(self):
        return self.summary['missing_branches']

    def get_covered_branches(self):
        return self.summary['covered_branches']

    def format_missing_lines(self):
        if not self.missing_lines:
            return ""
        ranges = []
        start = end = self.missing_lines[0]
        for num in self.missing_lines[1:]:
            if num == end + 1:
                end = num
            else:
                ranges.append(f"{start}-{end}" if start != end else f"{start}")
                start = end = num
        ranges.append(f"{start}-{end}" if start != end else f"{start}")
        return ", ".join(ranges)
