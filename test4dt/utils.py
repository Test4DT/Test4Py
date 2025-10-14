import ast
import os


def get_code(code: str):
    if len(code.split('```')) < 3:
        return code
    tmp = '```'.join(code.split('```')[1:-1])
    if tmp[0: 6] == 'python':
        tmp = tmp[6:]
    return tmp


def get_origin_code(file_path, start, end):
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.read().splitlines()
    return '\n'.join(lines[start - 1: end])


def get_class_attr(node, source_code) -> str:
    class_attributes_code = []
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            class_attr_code = ast.get_source_segment(source_code, stmt)
            class_attributes_code.append(class_attr_code)
    return "\n".join(class_attributes_code)


class ParentNodeVisitor(ast.NodeVisitor):
    def __init__(self):
        self.parent_map = {}

    def visit(self, node):
        for child in ast.iter_child_nodes(node):
            self.parent_map[child] = node
        self.generic_visit(node)


def get_mod_name(entry, pkg):
    input_mod = to_mod_name(
        os.path.relpath(entry, pkg))
    if input_mod.endswith("__init__"):
        input_mod = ".".join(input_mod.split(".")[:-1])
    return input_mod


def to_mod_name(name):
    return os.path.splitext(name)[0].replace("/", ".")
