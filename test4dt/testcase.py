import ast
import json
import logging
import os
import subprocess
from typing import List

from test4dt.embedding import function_database
from test4dt.gptapi import model
from test4dt.recorder import recoder
from test4dt.utils import get_code


class TestManager:
    def __init__(self, func, dir_type):
        self.func = func
        self.directory = self.get_directory(dir_type)
        self.testcases: List[Testcase] = []
        self.count = 0
        self.coverage = None

    def get_directory(self, dir_type):
        root_dir = self.func.file.root_dir
        file_path = self.func.file.file_path
        directory = file_path[0:-3] + '_t'
        dirs = directory.split(os.path.sep)
        dirs = dirs[len(root_dir.split(os.path.sep)):]
        return root_dir + os.path.sep + dir_type + os.path.sep + "_".join(dirs)

    def init_test_single_path(self):
        if not os.path.exists(self.directory):
            os.makedirs(self.directory, exist_ok=True)
            init_path = self.directory + os.path.sep + '__init__.py'
            with open(init_path, 'w'):
                pass

    async def generate_test_case(self):
        if self.coverage is not None:
            if len(self.coverage.missing_lines) == 0:
                return
        test_path = self.directory + os.path.sep + 'test_' + self.func.func_name.replace('.', '_') + str(len(self.testcases)) + '.py'
        await self.func.judge_params()
        if self.get_first_testcase() != "" and self.coverage is not None:
            code = await self.generate_test_case_evol()
        elif self.count > 0 and self.coverage is None:
            code = await self.generate_test_case_easy()
        else:
            code = await self.generate_test_case_normal()
        testcase = Testcase(self, self.func, test_path, code)
        if await testcase.assert_check():
            self.testcases.append(testcase)
        else:
            testcase.delete()
        self.count += 1

    def get_first_testcase(self):
        if len(self.testcases) == 0:
            return ""
        try:
            with open(self.testcases[0].test_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return ""

    async def generate_test_case_normal(self):
        sys_prompt = """You are an AI assistant that generates high-quality pytest test cases for Python functions. 
Given a function definition and its module name, your task is to produce well-structured and correct test cases. Ensure the following:

Correct Import: Import the function using its provided module name.
Test Structure: Use pytest conventions, including function-based tests.
Assertions: Ensure that the assertions are meaningful and correctly validate the function’s expected behavior.
Edge Cases: Consider different input scenarios, including edge cases and potential failure points.
No Redundant Information: Only generate the test file content.        
Analyze the target function before writing the test cases.
"""
        user_prompt = f"""Here is a Python function and its module name. 
Generate a pytest test case file ensuring proper assertions:

# Module: {self.func.file.mod_name}
**Do not re-implement the function.** Instead, import it correctly and write meaningful test cases.

Function Code: 

{self.func.get_source_code()}
"""
        return f'# Module: {self.func.file.mod_name}' + get_code(await model.aask(sys_prompt, user_prompt))

    def get_coverage_message_code(self):
        lines = self.func.code.splitlines()
        for index in self.coverage.missing_lines:
            if index - self.func.start_line < 0 or index - self.func.start_line >= len(lines):
                continue
            lines[index - self.func.start_line] = str(index) + ": " + lines[index - self.func.start_line]
        code = '\n'.join(lines)
        return code


    async def generate_test_case_evol(self):
        with open(self.testcases[0].test_path, 'r') as f:
            test_case_code = f.read()
        sys_prompt = """You are an expert in Python testing, 
specifically in writing high-quality `pytest` test cases to maximize code coverage. 
Your goal is to generate additional `pytest` test cases for a given function based on the provided function source code, 
existing test cases, and uncovered lines. The generated tests should:  

1. Focus on covering uncovered lines while maintaining correctness.  
2. Ensure all assertions accurately reflect the expected behavior of the function.  
3. Follow best practices for `pytest`, keeping tests readable and maintainable.  
4. Avoid redundant test cases that overlap with existing ones.  
5. Import the function properly using the provided module name.

If any uncovered lines indicate potential edge cases, ensure those are explicitly tested. Do not modify the function itself—only generate new test cases.  
"""
        user_prompt = f"""Here is the function source code, the existing test cases, 
and a list of uncovered lines. Please generate additional `pytest` test cases to increase coverage, 
ensuring that all assertions are correct.  

# Module: {self.func.file.mod_name}

**Function source code:**  
```python
{self.get_coverage_message_code()}
```

Uncovered lines:
{self.coverage.format_missing_lines()}

Existing test cases:
```python
{test_case_code}
```

Other messages:
{await self.auto_find_message()}
"""
        return get_code(await model.aask(sys_prompt, user_prompt))

    async def auto_find_message(self, task="improve_coverage") -> str:
        if task == "improve_coverage":
            query = await self.generate_query()
        else:
            query = await self.generate_repair_query(task)
        function_messages = function_database.query(query, 3)
        found_message = ""
        for function_message in function_messages:
            found_message += function_message.get_code_with_tests_or_summary()
        if found_message != "":
                found_message = await self.summary_query(query, found_message)
        return found_message

    async def summary_query(self, query, found_message):
        sys_prompt = """You are an AI assistant responsible for generating Python test cases with high coverage.  
You have queried a Retrieval-Augmented Generation (RAG) system to retrieve relevant function documentation.  
Now, you need to **process the retrieved information and answer your query**, summarizing the key insights that will help improve test case generation.  

### **Your Responsibilities:**  
1. **Analyze the retrieved documentation** and determine how it answers your query.  
2. **Summarize key insights** in a structured and concise manner.  
3. **Ensure that your summary highlights aspects that directly contribute to better test cases.**  
"""
        user_prompt = f"""You previously generated the following query to retrieve additional function documentation:  
**Query:** `{query}`  

You have now retrieved the following related documentation:  
**Retrieved Information:** 
{found_message}

### **Task:**  
- **Summarize how the retrieved information answers your query.**  
- **Extract key insights** that are directly useful for generating better test cases.  

Your summary should be precise and focused on improving test case generation.  
"""
        return await model.aask(sys_prompt, user_prompt)

    async def generate_repair_query(self, repair_message):
        sys_prompt = """You are an AI test case generation assistant specializing in Python. 
Your goal is to generate high-coverage test cases using pytest and iteratively refine them based on error messages. 
You have access to a RAG system that retrieves function documentation based on semantic similarity. 
When modifying test cases, you should autonomously determine what information is missing and generate concise, 
effective queries to retrieve relevant function documentation. 
Ensure that queries are specific and avoid generic language that could lead to irrelevant results.
"""
        user_prompt = f"""Based on the pytest error message, identify the missing information needed to fix the test case. 
Formulate a precise query to retrieve the relevant function documentation from the RAG system. Output only the query.

{repair_message}
"""
        return await model.aask(sys_prompt, user_prompt)

    async def generate_query(self):
        sys_prompt = """You are an AI assistant responsible for generating Python test cases with high coverage. 
To enhance test quality, you can autonomously query a Retrieval-Augmented Generation (RAG) system that indexes function docstrings based on semantic similarity.
Your goal is to strategically retrieve the most relevant information to generate more comprehensive test cases. 

You must actively analyze the target function and determine what additional context is necessary to improve coverage. 
Consider querying for:
- Related functions that interact with the target function
- Edge cases specific to the function’s logic
- Expected input variations or constraints
- Common failure scenarios based on similar functions

Only generate queries that are directly relevant to the target function. Output only the query.
"""
        user_prompt = f"""Generate a concise and effective query to retrieve relevant function documentation from the RAG system. 
Analyze the target function carefully and decide what additional information is necessary to improve test coverage.

**Function source code:**  
```python
{self.get_coverage_message_code()}  

Uncovered lines:
{self.coverage.format_missing_lines()}

Then, construct a precise and minimal query to retrieve only the most relevant function documentation.
Your query should be specific, avoiding broad or generic wording.
Output only the query.
"""
        return await model.aask(sys_prompt, user_prompt)


    async def generate_test_case_easy(self):
        sys_prompt = """You are an AI assistant that generates pytest test cases for Python functions.
Given a function definition and its module name, your task is to generate simple and correct test cases. Follow these guidelines:

Correct Import: Import the function properly using the provided module name.
Simple Assertions: Ensure assertions are correct but avoid unnecessary complexity.
Basic Test Cases: Cover common and edge cases with straightforward inputs and expected outputs.
No Additional Explanations: Only output the test file content without extra comments or explanations.     
"""
        user_prompt = f"""Here is a Python function and its module name. 
Generate a pytest test case file ensuring proper assertions:

# Module: {self.func.file.mod_name}
**Do not re-implement the function.** Instead, import it correctly and write meaningful test cases.

Function Code: 

{self.func.get_source_code()}
"""
        return f'# Module: {self.func.file.mod_name}' + get_code(await model.aask(sys_prompt, user_prompt))


class Testcase:
    def __init__(self, test_manager: TestManager, func, test_path: str, code: str):
        self.test_manager = test_manager
        self.test_path = test_path
        self.func = func
        self.error_message = ""
        self.set_code(code)

    def delete(self):
        try:
            os.remove(self.test_path)
        except FileNotFoundError:
            return

    def get_code(self):
        try:
            with open(self.test_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return ''

    def set_code(self, code):
        with open(self.test_path, 'w') as f:
            f.write(code)

    def find_syntax_error(self):
        root_dir = self.func.file.root_dir
        user_python_path = os.getenv('USER_PYTHON_PATH')
        command = f'PYTHONPATH={root_dir} {user_python_path} -m pylint --errors-only --init-hook="import sys; sys.path.append(\'{root_dir}\')" {self.test_path}'

        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            return False
        else:
            with open(self.test_path, 'r') as f:
                logging.error(f.read())
            logging.error(result.stdout)
            self.error_message = result.stdout
            return True

    def find_assert_error(self):
        try:
            result = subprocess.run([os.getenv('USER_PYTHON_PATH'), '-m', 'pytest', self.test_path, '--json-report', '--json-report-file=pytest_report.json'],
                                    capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            self.error_message = "time exceeded"
            recoder.score.add_assertion_error_type('TimeoutExpired')
            return True
        if result.returncode == 0:
            return False
        else:
            with open('pytest_report.json', 'r') as f:
                pytest_report = json.load(f)
            tests = pytest_report['tests']
            for test in tests:
                try:
                    traceback = test['call']['traceback']
                    for item in traceback:
                        error_type = item['message']
                        recoder.score.add_assertion_error_type(error_type)
                except KeyError:
                    pass

            self.error_message = result.stdout
            return True

    async def syntax_check(self, check_rate=False):
        if self.find_syntax_error():
            if check_rate:
                recoder.score.add_syntax_error()
            await self.repair_syntax_error()
            if self.find_syntax_error():
                return False
            if check_rate:
                recoder.score.add_syntax_fix_success()
        else:
            if check_rate:
                recoder.score.add_syntax_pass()
        return True

    async def assert_check(self):
        # TODO: add model auto repair function
        if not await self.syntax_check(check_rate=True):
            return False
        if self.find_assert_error():
            recoder.score.add_assertion_error()
            await self.repair_assert_error()
            if not await self.syntax_check():
                return False
            if self.find_assert_error():
                found_message = await self.test_manager.auto_find_message(self.get_assert_error_message())
                await self.repair_assert_error(found_message)
                if not await self.syntax_check():
                    return False
                if self.find_assert_error():
                    return self.decline_error_code()
                else:
                    recoder.score.add_assertion_fix_success()
                    return True
            else:
                recoder.score.add_assertion_fix_success()
                return True
        else:
            recoder.score.add_assertion_pass()
            return True

    def decline_error_code(self):
        if self.error_message == "time exceeded":
            return self.declineTimeoutTestcase()
        else:
            return self.declineTestCase()

    @staticmethod
    def find_asserts_in_file(file_content):
        asserts = []
        try:
            tree = ast.parse(file_content)
        except Exception:
            return []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                asserts.append(node.lineno)
        return asserts

    def declineTestCase(self):
        code = self.get_code()
        lines = code.splitlines()
        asserts = self.find_asserts_in_file(code)
        reached_line = 0
        low, high = 0, len(asserts) - 1

        while low <= high:
            mid = (low + high) // 2
            declined_code = '\n'.join(lines[0:asserts[mid] - 1])
            success = True
            self.set_code(declined_code)
            if self.find_syntax_error():
                success = False
            else:
                if self.find_assert_error():
                    success = False
            if not success:
                high = mid - 1
            else:
                reached_line = mid
                low = mid + 1
        if reached_line > 0:
            pass_the_assert = True
            declined_code = '\n'.join(lines[0:asserts[reached_line] - 1])
            self.set_code(declined_code)
        else:
            pass_the_assert = False
        return pass_the_assert

    def declineTimeoutTestcase(self):
        code = self.get_code()
        lines = code.splitlines()
        asserts = self.find_asserts_in_file(code)
        reached_line = 0
        now_line = -1

        while reached_line < len(asserts):
            declined_code = '\n'.join(lines[0:asserts[reached_line] - 1])
            success = True
            self.set_code(declined_code)
            if self.find_syntax_error():
                success = False
            else:
                if self.find_assert_error():
                    success = False
            if not success:
                break
            else:
                now_line = reached_line
                reached_line = 2 * reached_line + 1

        if now_line >= 0:
            pass_the_assert = True
            declined_code = '\n'.join(lines[0:asserts[now_line] - 1])
            self.set_code(declined_code)
        else:
            pass_the_assert = False
        return pass_the_assert

    async def repair_syntax_error(self):
        sys_prompt = """You are an AI assistant that specializes in fixing syntax errors in Python test cases. 
Given a test case written by the user and the corresponding pylint error messages, 
your task is to correct the syntax errors while preserving the original logic and structure of the test case.

Your response should:

Fix all syntax errors reported by pylint.
Ensure the corrected code remains a valid test case.
Maintain the original coding style and structure as much as possible.
Not introduce any logic changes beyond necessary fixes.
**Do not re-implement the function.** Instead, import it correctly and write meaningful test cases.
If the provided pylint errors are ambiguous or incomplete, make reasonable assumptions to correct the syntax while preserving the intent.
"""
        user_prompt = f"""Here is a Python test case and the pylint errors it produces. Please correct the syntax errors accordingly.

Test Case:
{self.get_code()}

Pylint Errors:
{self.error_message}
"""
        self.set_code(get_code(await model.aask(sys_prompt, user_prompt)))

    def get_assert_error_message(self):
        return f"""# Function under test  
{self.func.get_source_code()}  
    
# Test case  
{self.get_code()}  

The test case was run using pytest, and the following output was produced:
{self.error_message}
"""

    async def repair_assert_error(self, found_message=None):
        sys_prompt = """You are an AI assistant specialized in analyzing and correcting test cases. 
Your task is to modify a given test case based on its pytest execution result to ensure that the assertions are correct. 
If an assertion fails, update it to match the actual output while maintaining the integrity of the test. 
Simplify assertions where possible, but do not alter the overall intent of the test. 
Preserve the structure and readability of the test case while making minimal necessary modifications.
"""
        user_prompt = f"""Here is a Python test case and the function it tests:
Please correct the test case to ensure that the assertions are valid based on the pytest output. 
**Do not re-implement the function.** Instead, import it correctly and write meaningful test cases.
If needed, simplify the assertions while keeping the test meaningful. Return only the modified test case.

{self.get_assert_error_message()}
"""
        if found_message is not None:
            user_prompt += '\nfound messages:\n' + found_message
        self.set_code(get_code(await model.aask(sys_prompt, user_prompt)))
