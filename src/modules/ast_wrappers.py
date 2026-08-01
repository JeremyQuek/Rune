
import ast
from enum import Enum, auto

"""
Custom AST nodes for representing spliced statement blocks in the CFG.

Python's ast.Module lacks location attributes, making it unsuitable as a
wrapper for arbitrary statement slices. These nodes provide a uniform,
hashable, location-aware container for groups of consecutive statements
that form a single basic block in the control flow graph.

Subclasses distinguish the lexical context the block belongs to, allowing
the CFG and downstream analysis to differentiate module-level code from
function bodies and class bodies without inspecting the parent.
"""

# --------- Custom AST Bodies --------- #

class Body(ast.AST):
    _fields = ('body',)
    _attributes = ('lineno', 'col_offset', 'end_lineno', 'end_col_offset')

    def __init__(self, body=None, lineno=0, col_offset=0, end_lineno=0, end_col_offset=0):
        self.body = body or []
        self.lineno = lineno
        self.col_offset = col_offset
        self.end_lineno = end_lineno
        self.end_col_offset = end_col_offset

    def unparse(self):
        return "\n".join(ast.unparse(stmt) for stmt in self.body)

class ModuleBody(Body): pass
class IfBody(Body): pass
class WhileBody(Body): pass
class ForBody(Body): pass
class ElseBody(Body): pass
class ExceptBody(Body): pass
class ClassBody(Body): pass
class FunctionBody(Body): pass
class TryBody(Body): pass
class FinallyBody(Body):pass

# --------- SESE Proxy Nodes --------- #

class Entry(ast.AST):
    _fields = ('body',)
    _attributes = ('lineno', 'col_offset', 'end_lineno', 'end_col_offset')

    def __init__(self, body=None, lineno=0, col_offset=0, end_lineno=0, end_col_offset=0):
        self.body = body or []
        self.lineno = lineno
        self.col_offset = col_offset
        self.end_lineno = end_lineno
        self.end_col_offset = end_col_offset

    def unparse(self):
        return "\n".join(ast.unparse(stmt) for stmt in self.body)

class ExitKind(Enum):
    MODULE = auto()
    IF = auto()
    ELSE = auto()
    IF_ELSE = auto()
    FOR = auto()
    FOR_LOOP = auto()
    WHILE = auto()
    WHILE_LOOP = auto()
    TRY = auto()
    EXCEPT = auto()
    TRY_EXCEPT_BRANCH = auto()
    FUNCTION_DEFINITION = auto()
    CLASS_DEFINITION = auto()
    FINALLY = auto()

class Exit(ast.AST):
    def __init__(self, kind: ExitKind):
        self.kind = kind

    def __repr__(self):
        return f"Exit({self.kind.name})"

class BranchEntry(Entry): pass
class ModuleEntry(Entry):pass

class IfElseEntry(BranchEntry):pass
class IfEntry(Entry):pass
class ElseEntry(Entry): pass

class ForLoopEntry(BranchEntry): pass
class ForEntry(Entry): pass

class WhileLoopEntry(BranchEntry):pass
class WhileEntry(Entry):pass

class TryExceptBranchEntry(BranchEntry):pass
class TryEntry(Entry):pass
class ExceptEntry(Entry):pass
class FinallyEntry(Entry):pass

class FunctionDefinitionEntry(BranchEntry): pass

class ClassDefinitionEntry(Entry): pass