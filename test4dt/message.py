import os
from _ast import arg
import asyncio
import json

from tqdm import tqdm
from test4dt.coverage_message import MyCoverage, CoverageMessage
from test4dt.embedding import embedder, find_topK_message, function_database
import astor

from test4dt.pycg.pycg import CallGraphGenerator
from test4dt.pycg import formats
from typing import List
from test4dt.gptapi import model
from test4dt.testcase import TestManager
from test4dt.utils import *
from test4dt.recorder import recoder



class ProjectMessage:
    def __init__(self, root_dir: str, source_dir: str, dir_type='Test4DT_tests'):
        self.root_dir: str = root_dir
        self.source_dir = source_dir
        self.dir_type: str = dir_type
        self.file_messages: List[FileMessage] = []
        self.cg_edges: List[CGEdge] = []
        self.dir_message = DictionaryMessage(self.root_dir, self, None)
        self.coverage_summary = None
        self.coverage = None


    async def init(self):
        files: [str] = self._get_files()
        for file in files:
            self.file_messages.append(FileMessage(self.root_dir, file, self))

        cg = CallGraphGenerator(files, self.root_dir, -1, 'call-graph')
        cg.analyze()
        formatter = formats.Simple(cg)
        output = formatter.generate()
        self.analyze_function_members()
        self.complete_file_imports(cg)
        self.parseExtend(cg.class_manager.get_classes())
        self.parse_full_members()
        self.parseCG(output)

        await self.dir_message.init()
        await self.analyze_functions()
        await self.get_total_what_todo()
        await self.generate_summary()
        await self.analyze_each_class()
        self.embedding_class_summary()
        function_database.init(self)
        self.init_test_path(self.dir_type)
        self.coverage = MyCoverage(self.root_dir, self.dir_type, self.source_dir)


    def generate_once(self):
        asyncio.run(self.generate_test_case())
        coverage = self.coverage.get_coverage()
        recoder.score.get_coverage(coverage, self.root_dir.split(os.path.sep)[-1])
        self.coverage_summary = coverage['totals']
        for file_path, file in coverage['files'].items():
            mod_name = file_path[:-3].replace('/', '.')
            if mod_name.endswith("__init__"):
                mod_name = ".".join(mod_name.split(".")[:-1])
            file_message = self.find_file_by_mod(mod_name)
            if file_message is not None:
                for name, function in file['functions'].items():
                    for function_message in file_message.functions:
                        if function_message.func_name == name:
                            coverage_message = CoverageMessage(function['missing_lines'], function['summary'])
                            function_message.test_manager.coverage = coverage_message


    def find_file_by_mod(self, mod: str):
        for file_message in self.file_messages:
            if file_message.mod_name == mod:
                return file_message
        return None


    def get_coverage_message(self):
        covered_line = 0
        uncovered_line = 0
        covered_branch = 0
        uncovered_branch = 0
        for file_message in self.file_messages:
            for function in file_message.functions:
                if function.test_manager.coverage is None:
                    uncovered_line += function.end_line - function.start_line + 1
                else:
                    coverage: CoverageMessage = function.test_manager.coverage
                    covered_line += coverage.get_covered_lines()
                    uncovered_line += coverage.get_missing_lines()
                    covered_branch += coverage.get_covered_branches()
                    uncovered_branch += coverage.get_missing_branches()
        return covered_line, uncovered_line, covered_branch, uncovered_branch


    async def generate_test_case(self):
        num = 0
        for file_message in self.file_messages:
            for _ in file_message.functions:
                    num += 1
        with tqdm(total=num, desc=f"Generate test cases") as pbar:
            tasks = []
            for file_message in self.file_messages:
                for function in file_message.functions:
                    tasks.append(self.fetch_data(function, pbar))
            await asyncio.gather(*tasks)


    async def fetch_data(self, function, pbar):
        await function.test_manager.generate_test_case()
        pbar.update(1)


    def init_test_path(self, dir_type):
        conf_content = f"import sys\n\ndef pytest_configure(config):\n    sys.path.append(\'{self.root_dir}\')"
        test_dir = self.root_dir + os.path.sep + dir_type
        if not os.path.exists(test_dir):
            os.makedirs(test_dir, exist_ok=True)
            with open(self.root_dir + os.path.sep + dir_type + os.path.sep + '__init__.py', 'w'):
                pass
            with open(self.root_dir + os.path.sep + dir_type + os.path.sep + 'conftest.py', 'w') as f:
                f.write(conf_content)
        for file_message in self.file_messages:
            for function in file_message.functions:
                function.test_manager.init_test_single_path()


    def parseExtend(self, classes):
        for full_name, class_item in classes.items():
            son_class = self.get_class_by_full_name(full_name)
            if son_class is None:
                continue
            for father in class_item.mro:
                father_class = self.get_class_by_full_name(father)
                if father_class is not None:
                    son_class.father.append(father_class)


    def get_class_by_full_name(self, full_name):
        for file_message in self.file_messages:
            class_message = file_message.get_class_by_full_name(full_name)
            if class_message is not None:
                return class_message
        return None


    def _get_files(self) -> List[str]:
        files = []
        for dir_path, _, filenames in os.walk(os.path.join(self.root_dir, self.source_dir)):
            for filename in filenames:
                if filename.endswith('.py'):
                    py_path = os.path.join(dir_path, filename)
                    files.append(py_path)
        return files


    def parseCG(self, output):
        for module, calls in output.items():
            source = self.find_module(module)
            if source is None:
                continue
            for call in calls:
                dest = self.find_module(call['dest'])
                if dest is None:
                    continue
                self.cg_edges.append(CGEdge(source, dest, call['line_no']))


    def find_module(self, module_name: str):
        for file_message in self.file_messages:
            if module_name.__contains__(file_message.mod_name):
                for function_message in file_message.functions:
                    if function_message.module_name == module_name:
                        return function_message
        return None


    def find_file(self, file_path: str):
        for file_message in self.file_messages:
            if file_message.file_path == file_path:
                return file_message
        return None


    def complete_file_imports(self, cg: CallGraphGenerator):
        for file_message in self.file_messages:
            file_message.imports = self.find_files_by_module(cg.import_manager.get_imports(file_message.mod_name))


    def find_files_by_module(self, module_names: set[str]):
        files: List[FileMessage] = []
        for file_message in self.file_messages:
            if file_message.mod_name in module_names:
                files.append(file_message)
        return files


    def parse_full_members(self):
        for file_message in self.file_messages:
            file_message.parse_classes_full_members()


    def get_total_method_num(self):
        num = 0
        for file_message in self.file_messages:
            num += len(file_message.functions)
        return num


    async def analyze_functions(self):
        num = 0
        for file_message in self.file_messages:
            for _ in file_message.functions:
                num += 1
        with tqdm(total=num, desc=f"Analyze functions") as pbar:
            for file_message in self.file_messages:
                for function_message in file_message.functions:
                    await function_message.analyze_done_what()
                    pbar.update(1)


    async def get_total_what_todo(self):
        num = 0
        for file_message in self.file_messages:
            for _ in file_message.functions:
                num += 1
        with tqdm(total=num, desc=f"Analyze functions") as pbar:
            for file_message in self.file_messages:
                for function_message in file_message.functions:
                    if len(function_message.used) == 0:
                        await function_message.analyze_what_todo(function_message.find_readme(), False)
                    pbar.update(1)


    async def generate_summary(self):
        num = 0
        for file_message in self.file_messages:
            for _ in file_message.functions:
                num += 1
        with tqdm(total=num, desc=f"Analyze functions") as pbar:
            tasks = []
            for file_message in self.file_messages:
                for function_message in file_message.functions:
                    tasks.append(function_message.generate_summary(pbar))
            await asyncio.gather(*tasks)


    def analyze_function_members(self):
        for file_message in self.file_messages:
            for function_message in file_message.functions:
                function_message.analyze_function_members()


    async def analyze_each_class(self):
        num = 0
        for file_message in self.file_messages:
            for _ in file_message.classes:
                num += 2
        with tqdm(total=num, desc=f"Analyze each class") as pbar:
            tasks = []
            for file_message in self.file_messages:
                for class_message in file_message.classes:
                    tasks.append(class_message.generate_summary(pbar))
                    tasks.append(class_message.generate_how_to_use(pbar))
            await asyncio.gather(*tasks)


    def embedding_class_summary(self):
        for file_message in self.file_messages:
            for class_message in file_message.classes:
                class_message.vector = embedder.embed_query(class_message.summary)



class DictionaryMessage:
    def __init__(self, dir_path, project: ProjectMessage, father=None):
        self.dir_path = dir_path
        self.father = father
        self.project = project
        self.readme = None


    async def init(self):
        items = os.listdir(self.dir_path)
        for item in items:
            item_path = os.path.join(self.dir_path, item)
            if os.path.isdir(item_path):
                dictionary = DictionaryMessage(item_path, self.project, self)
                await dictionary.init()
            else:
                if item_path.endswith('.py'):
                    file_message = self.project.find_file(item_path)
                    if file_message is not None:
                        file_message.father = self
                elif item_path.endswith('README.md'):
                    with open(item_path, 'r') as f:
                        readme = f.read()
                        self.readme = await self.analyze_readme(readme)


    def find_readme(self):
        if self.readme is not None:
            return self.readme
        if self.father is not None:
            return self.father.find_readme()
        return None


    async def analyze_readme(self, readme: str):
        sys_prompt = """You are tasked with analyzing the contents of a README.md file and providing a clear, 
concise summary of what the project is about. 
The goal is to highlight the primary objectives and core functionality of the project. 
Avoid excessive details and aim for a brief summary that clearly conveys the project’s purpose in one or two short paragraphs.
"""
        user_prompt = f"""Please analyze the following README.md file and provide a summary that describes what the project aims to do.
{readme}
"""
        return await model.aask(sys_prompt, user_prompt)



class FileMessage:
    def __init__(self, root_dir: str, file_path: str, project: ProjectMessage):
        self.project = project
        self.file_path = file_path
        self.root_dir = root_dir
        self.mod_name = get_mod_name(file_path, root_dir)
        self.imports: List[FileMessage] = [self]
        self.classes: List[ClassMessage] = []
        self.functions: List[FunctionMessage] = []
        self.extract_classes_functions_with_comments(file_path)
        self.father = None


    def find_readme(self):
        if self.father is not None:
            return self.father.find_readme()
        return None


    def get_class_by_full_name(self, full_name):
        for class_message in self.classes:
            if class_message.full_name == full_name:
                return class_message
        return None


    def parse_classes_full_members(self):
        for class_message in self.classes:
            class_message.parse_full_members()


    def extract_classes_functions_with_comments(self, file_path: str):
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        tree = ast.parse(code, filename=file_path)
        visitor = ParentNodeVisitor()
        visitor.visit(tree)


        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self.classes.append(ClassMessage(self, node, code, self.mod_name))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                parent = visitor.parent_map.get(node, None)
                parent_message = None
                if isinstance(parent, ast.ClassDef):
                    for class_message in self.classes:
                        if class_message.node == parent:
                            parent_message = class_message
                            break
                self.functions.append(FunctionMessage(self, node, parent_message, file_path, self.mod_name))



class ClassMessage:
    def __init__(self, file: FileMessage, node: ast.ClassDef, code: str, mod_name: str):
        self.file = file
        self.class_name = node.name
        self.docstring = ast.get_docstring(node, clean=False)
        self.class_code = self.get_class_code(node)
        self.start_line = node.lineno
        self.end_line = max(child.lineno for child in ast.walk(node) if hasattr(child, 'lineno'))
        self.class_attr_code = get_class_attr(node, code)
        self.members :List[str] = []
        self.parse_members(node)
        self.full_members = set()
        self.full_name = f"{mod_name}.{self.class_name}"
        self.father :List[ClassMessage] = []
        self.functions: List[FunctionMessage] = []
        self.node = node
        self.init_method = None
        self.summary = None
        self.how_to_use = None
        self.vector = None

    @staticmethod
    def get_class_code(class_def: ast.ClassDef):
        non_method_statements = [
            node for node in class_def.body
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        class_stub = f"class {class_def.name}:\n"
        body_source = "\n".join(
            "    " + astor.to_source(stmt).strip().replace("\n", "\n    ") for stmt in non_method_statements)
        return class_stub + body_source

    def get_code_with_summary(self):
        define_code = f"# mod: {self.file.mod_name}"
        define_code += self.class_code
        for function in self.functions:
            define_code += function.get_code_with_summary() + '\n'
        return define_code

    def get_how_to_use(self):
        return self.how_to_use

    def suit_members(self, members: List[str]):
        count = 0
        for member in members:
            if member in self.full_members:
                count += 1
        return count

    async def generate_summary(self, pbar):
        sys_prompt = """You are an AI assistant skilled in analyzing Python code. 
Your task is to determine the role and purpose of a given class by analyzing its structure, methods, and usage.
Focus on explaining what responsibilities this class has, how it interacts with other components, 
and its overall contribution to the program. Provide a structured and concise summary of the inferred class functionality.
"""
        user_prompt = f"""Please analyze the role and responsibilities of this class. 
Explain its purpose, key functionalities, and how it might be used in the program. 

Here is a Python class:

{self.get_code_with_summary()}
"""
        self.summary = await model.aask(sys_prompt, user_prompt)
        pbar.update(1)

    async def generate_how_to_use(self, pbar):
        sys_prompt = """You are an expert in analyzing Python code. 
Your task is to examine the given class definition and provide a detailed explanation of how to initialize and use this class. 
Your response should include:

1. **Class Initialization**: Explain how to properly instantiate the class, listing the required and optional parameters in the constructor (`__init__` method).
2. **Key Methods and Attributes**: Summarize the main methods and attributes of the class, highlighting their usage.
3. **Example Usage**: Provide a Python code snippet demonstrating how to create an instance of the class and interact with its methods.

Always assume that the user wants a clear and concise explanation suitable for someone who understands Python but may not be familiar with the specific class.
"""
        user_prompt = f"""Please analyze the role and responsibilities of this class. 
Explain its purpose, key functionalities, and how it might be used in the program. 

Here is the Python class definition:

```python
{self.get_code_with_summary()}
"""
        self.how_to_use = await model.aask(sys_prompt, user_prompt)
        pbar.update(1)


    def parse_members(self, node: ast.ClassDef):
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if item.name == "__init__":
                    for stmt in item.body:
                        if isinstance(stmt, ast.Assign):
                            for target in stmt.targets:
                                if isinstance(target, ast.Attribute) and isinstance(target.value,
                                                                                    ast.Name) and target.value.id == "self":
                                    self.members.append(target.attr)
                else:
                    self.members.append(item.name)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        self.members.append(target.id)
            elif isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name):
                    self.members.append(item.target.id)

    def parse_full_members(self):
        self.full_members = set(self.members)
        for fa in self.father:
            if fa != self:
                self.full_members.union(fa.parse_full_members())
        return self.full_members


class FunctionMessage:
    builtin_members = set(dir(object))

    def __init__(self, file: FileMessage, node: ast.FunctionDef, parent: ClassMessage, file_path: str, module_name: str):
        self.file =file
        self.node: ast.FunctionDef = node
        self.func_name = node.name
        self.parent = parent
        self.class_name = None
        if parent is not None:
            self.class_name = parent.class_name
            parent.functions.append(self)
            if self.func_name == '__init__':
                parent.init_method = self
            self.func_name = f"{self.class_name}.{self.func_name}"

        self.docstring = ast.get_docstring(node, clean=False)
        self.start_line = node.lineno
        self.end_line = max(child.lineno for child in ast.walk(node) if hasattr(child, 'lineno'))
        self.standard_code = astor.to_source(node)
        self.code = get_origin_code(file_path, self.start_line, self.end_line)
        self.module_name = f"{module_name}.{self.func_name}"
        self.uses: List[CGEdge] = []
        self.used: List[CGEdge] = []

        self.done_what = None
        self.what_todo = None
        self.summary = None
        self.params: List[ArgMessage] = []
        self.judge = None
        self.test_manager = TestManager(self, self.file.project.dir_type)


    def get_code_with_summary(self):
        return f"""
\"\"\"
{self.summary}
\"\"\"
{self.code}
"""


    def get_code_with_tests_or_summary(self):
        test_code = self.test_manager.get_first_testcase()
        if test_code == "":
            return self.get_source_code()
        else:
            return f"""{self.module_name} code:
{self.code}

test case:
{test_code}
"""


    async def generate_summary(self, pbar):
        sys_prompt = """You are an AI assistant skilled in analyzing and generating comprehensive function documentation. 
Your task is to integrate two different perspectives of docstrings—one describing what the function does (implementation perspective) 
and the other describing what the function is intended to do (requirement perspective)—along with the function's source code to generate a final, 
well-structured docstring.

Your output must:
1. Preserve and merge the key information from both docstrings.
2. Clearly describe how to use the function, including its purpose, parameters, and return values.
3. Provide insights into the function’s significance within the broader context of the codebase.
4. Use clear, precise, and professional language.
5. Let's think step by step, only output the docstring content. Do not include the source code or any extra explanations.

Now, await the user’s input containing:
- The function’s source code.
- The "what it does" docstring.
- The "what it is intended to do" docstring.
Generate the final docstring accordingly.
"""
        user_prompt = f"""Here is a function along with two docstrings from different perspectives:

### Function Source Code:
```python
{self.get_source_code()}

### "What it does" Docstring:
{self.done_what}

### "What it is intended to do" Docstring:
{self.what_todo}
"""
        self.summary = await model.aask(sys_prompt, user_prompt)
        pbar.update(1)


    def find_readme(self):
        return self.file.find_readme()


    def get_source_code(self):
        source_code = ""
        if self.parent is not None:
            source_code += f"{self.parent.class_code}\n"
            if self.parent.init_method is not None:
                if self.parent.init_method.summary is not None:
                    source_code += "\"\"\"\n" + self.parent.init_method.summary + "\n\"\"\"\n"
                source_code += self.parent.init_method.code + '\n\n'
        if self.summary is not None:
            source_code += "\"\"\"\n" + self.summary + "\n\"\"\"\n"
        if self.judge is not None:
            source_code += "\"\"\"\n" + self.judge + "\n\"\"\"\n"
        source_code += self.code
        return source_code


    def analyze_function_members(self):
        params = [arg for arg in self.node.args.args]
        try:
            for arg in getattr(self.node.args, 'posonlyargs', []):
                if arg.arg not in params:
                    params.append(arg)
            for arg in self.node.args.kwonlyargs:
                if arg.arg not in params:
                    params.append(arg)
            if self.node.args.vararg:
                if self.node.args.vararg not in params:
                    params.append(self.node.args.vararg)
            if self.node.args.kwarg:
                if self.node.args.kwarg not in params:
                    params.append(self.node.args.kwarg)
        except Exception as e:
            print("Arg parse error: ", e)

        param_members = {param.arg: {'members': set(), 'node': param} for param in params}
        param_names = [arg.arg for arg in params]

        for node in ast.walk(self.node):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    param = node.value.id
                    if param in param_names:
                        if node.attr not in self.builtin_members:
                            param_members[param]['members'].add(node.attr)

        for param_name, param_members in param_members.items():
            self.params.append(ArgMessage(param_name, self.get_source_code(), self.summary,
                                          param_members['members'], param_members['node'], self))


    async def analyze_done_what(self):
        if self.done_what is not None:
            return self.done_what
        self.done_what = ""
        call_message = ""
        for use in self.uses:
            dest: FunctionMessage = use.dest
            done_what = await dest.analyze_done_what()
            if len(done_what) > 0:
                call_message += f"\n{dest.func_name}: \n{done_what}\n"
        source_code = self.get_source_code()
        if call_message != "":
            sys_prompt = "You are a helpful assistant designed to analyze Python functions. \
Based on the provided source code of a function and the docstrings of the other functions it calls, \
your task is to generate a clear and concise docstring for the given function. \
The generated docstring should describe what the function does, what parameters it accepts, highlighting the role of each parameter and how changes to their values affect the function’s execution. \
what it returns (if anything), and how to use the function effectively. \
Let's think step by step, only output the docstring content. Do not include the source code or any extra explanations."
            user_prompt = f"Here is the source code of a Python function and the docstrings of the functions it calls. \
Please analyze this and generate an appropriate docstring for the provided function. \
Be sure to explain what the function does and include examples or instructions on how to use it.\n\n\
source code: \n{source_code}\n\n functions it calls: \n{call_message}"
        else:
            sys_prompt = "You are a helpful assistant designed to analyze Python functions. \
Based on the provided source code of a function, \
your task is to generate a clear and concise docstring for the given function. \
The generated docstring should describe what the function does, what parameters it accepts, highlighting the role of each parameter and how changes to their values affect the function’s execution.  \
what it returns (if anything), and how to use the function effectively. \
Let's think step by step, only output the docstring content. Do not include the source code or any extra explanations."
            user_prompt = f"Here is the source code of a Python function. \
Please analyze this and generate an appropriate docstring for the provided function. \
Be sure to explain what the function does and include examples or instructions on how to use it.\n\n\
source code: \n{source_code}\n\n functions it calls: \n{call_message}"
        self.done_what = await model.aask(sys_prompt, user_prompt)
        return self.done_what


    async def analyze_what_todo_by_readme(self, readme):
        if readme is not None:
            sys_prompt = """You are an AI assistant specialized in analyzing Python code. 
Your task is to examine the given function and generate a concise and clear docstring that describes its purpose and usage. 
Consider the overall project objective to provide context, but focus on the function itself. 
If the function interacts with other parts of the project, briefly mention relevant dependencies without excessive details. 
Your output should be formatted as a Python docstring.
Let's think step by step, only output the docstring content. Do not include the source code or any extra explanations.
"""
            user_prompt = f"""Analyze the function and generate a docstring that clearly describes its purpose, parameters, 
return values, and usage. Ensure the docstring is informative yet concise.
    
**Project Overview:**
{readme}
    
**Function Source Code:**
```python
\"\"\"
{self.what_todo}
\"\"\"
{self.code}
"""
        else:
            sys_prompt = """You are an AI assistant that analyzes Python functions and provides a concise docstring 
summarizing their purpose and usage. The docstring should follow standard Python conventions, 
including a brief description, parameters, and return values if applicable. 
Maintain clarity and precision while avoiding unnecessary details.
Let's think step by step, only output the docstring content. Do not include the source code or any extra explanations.
"""
            user_prompt = f"""Here is a Python function. 
Please analyze its purpose and provide a docstring that describes what it does and how to use it. 
Ensure the docstring follows proper formatting.
            
```python
\"\"\"
{self.what_todo}
\"\"\"
{self.code}
"""
        return await model.aask(sys_prompt, user_prompt)


    async def analyze_what_todo(self, what_todo, is_judge: bool):
        if is_judge:
            self.what_todo = what_todo
        else:
            self.what_todo = await self.analyze_what_todo_by_readme(what_todo)

        for use in self.uses:
            dest: FunctionMessage = use.dest
            if dest.what_todo is None:
                sys_prompt = """You are a Python code analysis assistant.
Your task is to analyze a function call in the provided source code and produce a precise docstring that describes:
The purpose of the called function.
The semantic roles and exact parameter types, inferred from the call context and callee behavior.
The types must be as specific as possible (e.g., List[User], Dict[str, int], Optional[Config]) rather than generic types like list or dict.
Infer parameter types based on their usage and data flow, not just their names.

Output only the docstring content — do not include the source code or any extra explanations.
Think step by step before writing the final docstring."""
                user_prompt = f"""Identify the purpose of the called function {dest.func_name} and explain how to use it, formatted as a Python docstring.
Source Code:
\"\"\"
{self.what_todo}
\"\"\"
{self.code}
    
Function Call:
At line {use.line_no}, the function call of function {dest.func_name} occurs:
{use.call_code}
"""
                call_what_todo = await model.aask(sys_prompt, user_prompt)
                await dest.analyze_what_todo(call_what_todo, True)


    async def judge_params(self):
        if self.judge is not None or len(self.params) == 0:
            return
        sys_prompt = """You are an AI assistant skilled in understanding and generating Python code. 
Your task is to analyze a given function and determine how it should be called. 
You will receive the function's source code and its parameter information. 
Based on this, you must infer the appropriate way to call the function and generate example calls.

Provide clear and well-structured example calls that reflect typical usage of the function. 
If necessary, infer reasonable argument values based on parameter names and types. 
Ensure that your responses are concise and precise, avoiding redundant explanations.
"""
        user_prompt = f"""Here is a Python function along with its parameter information. 
Please analyze how this function should be called and provide example calls.

Function source code:

{self.get_source_code()}

params:
"""
        for param in self.params:
            user_prompt += await param.get_type_help()
        self.judge = await model.aask(sys_prompt, user_prompt)


class CGEdge:
    def __init__(self, source: FunctionMessage, dest: FunctionMessage, line_no: int):
        self.source: FunctionMessage = source
        self.dest: FunctionMessage = dest
        self.line_no = line_no
        self.call_code = self.get_call_code()
        self.add_use()

    def get_call_code(self):
        code_lines = self.source.code.splitlines()
        if len(code_lines) <= self.line_no - self.source.start_line or self.line_no < self.source.start_line:
            return "Not found"
        return code_lines[self.line_no - self.source.start_line]

    def add_use(self):
        self.dest.used.append(self)
        has_appeared = False
        for use in self.source.uses:
            if use.dest == self.dest:
                has_appeared = True
        if not has_appeared:
            self.source.uses.append(self)


class ArgMessage:
    def __init__(self, name, code, summary, members, node: arg, func: FunctionMessage):
        self.func: FunctionMessage = func
        self.node: arg = node
        self.name = name
        self.code = code
        self.summary = summary
        self.members = members
        self.meaning = None
        self.vector = None
        self.is_user_defined = None
        self.extract_type: str = ""


    async def get_type_help(self):
        return f"""
{self.name}: 

{await self.get_type_message()}
"""


    async def get_type_message(self):
        if self.node.type_comment is not None:
            for import_file in self.func.file.imports:
                for class_message in import_file.classes:
                    if (self.node.type_comment == class_message.class_name or
                            '['+class_message.class_name+']' in self.node.type_comment):
                        return class_message.get_how_to_use()
            self.extract_type = self.node.type_comment
            return self.node.type_comment

        if self.is_user_defined is None:
            self.is_user_defined = await self.judge_type()
        if self.is_user_defined:
            if self.meaning is None:
                self.meaning = await self.generate_meaning()
                self.vector = embedder.embed_query(self.meaning)
            return self.find_type_by_RAG()
        return "build-in type"


    def find_type_by_RAG(self):
        classes = self.filter_by_members()
        found_classes = find_topK_message(self.func.file.file_path+self.func.func_name+self.name, classes, self.vector, 3)
        # TODO: change to choose on from k
        result = ""
        for found_class in found_classes:
            result += found_class.file.mod_name + '\n' + found_class.get_how_to_use() + '\n'
        return result


    def filter_by_members(self) -> List[ClassMessage]:
        max_score = 0
        suitable_classes: List[ClassMessage] = []
        for file_message in self.func.file.project.file_messages:
            for class_message in file_message.classes:
                score = class_message.suit_members(self.members)
                if score == max_score:
                    suitable_classes.append(class_message)
                elif score > max_score:
                    max_score = score
                    suitable_classes = [class_message]
        return suitable_classes


    async def generate_meaning(self):
        sys_prompt = """You are an AI assistant skilled in analyzing Python code. 
Your task is to determine the role and purpose of a class based on how its instance is used as a parameter in a given function. 
Focus on analyzing what responsibilities this class might have, how it contributes to the function’s behavior, 
and what role it likely plays in the overall program. Provide a structured and concise summary of the inferred class functionality.
"""
        user_prompt = f"""The parameter I want to analyze is {self.name}. 
Based on how this parameter is used in the function, infer the possible role and responsibilities of its class. 
        
Here is a Python function:
```python
\"\"\"
{self.summary}
\"\"\"
{self.code}
"""
        return await model.aask(sys_prompt, user_prompt)


    async def judge_type(self):
        sys_prompt = """You are an expert in Python type analysis. 
Your task is to determine whether a given function parameter belongs to a built-in type, 
a third-party library type, or a user-defined type.  

Classification rules:  
- If the parameter type is a built-in Python type (e.g., `int`, `str`, `list`), output `<1>`.  
- If the parameter type is from a third-party library (e.g., `ast.FunctionCall`), output `<2>`.  
- If the parameter type is a user-defined type (a custom class written by the user), output `<3>`.  

The user will provide a function definition and specify a parameter name. 
Respond with only the corresponding classification tag (`<1>`, `<2>`, or `<3>`) without any additional text.
"""
        user_prompt = f"""
Determine the classification of the parameter named {self.name} based on its usage in the function body.

```python
\"\"\"
{self.summary}
\"\"\"
{self.code}
"""
        return not (await model.aask(sys_prompt, user_prompt)).__contains__('<1>')
