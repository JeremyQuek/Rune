
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

    def __init__(self, body: list[ast.stmt] | None = None, lineno: int = 0, col_offset: int = 0,
                 end_lineno: int = 0, end_col_offset: int = 0) -> None:
        self.body = body or []
        self.lineno = lineno
        self.col_offset = col_offset
        self.end_lineno = end_lineno
        self.end_col_offset = end_col_offset

    def unparse(self) -> str:
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
class CaseBody(Body): pass

# --------- SESE Proxy Nodes --------- #

class Entry(ast.AST):
    _fields = ('body',)
    _attributes = ('lineno', 'col_offset', 'end_lineno', 'end_col_offset')

    def __init__(self, body: list[ast.stmt] | None = None, lineno: int = 0, col_offset: int = 0,
                 end_lineno: int = 0, end_col_offset: int = 0) -> None:
        self.body = body or []
        self.lineno = lineno
        self.col_offset = col_offset
        self.end_lineno = end_lineno
        self.end_col_offset = end_col_offset

    def unparse(self) -> str:
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
    MATCH = auto()
    CASE = auto()

class Exit(ast.AST):
    def __init__(self, kind: ExitKind) -> None:
        self.kind = kind

    def __repr__(self) -> str:
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

class MatchEntry(BranchEntry): pass
class CaseEntry(Entry): pass
# --------- Provenance recipes --------- #

class ElementOf(ast.expr):
    """
    Recipe for a name bound by unpacking or iteration, which has no expression of its own:
        x, *y = e     x -> ElementOf(e, 0), y -> ElementOf(e, 1, rest=True)
        for x in it   x -> ElementOf(it, None)
    """
    _fields = ('value',)

    def __init__(self, value: ast.AST, index: int | None, rest: bool = False) -> None:
        self.value = value
        self.index = index
        self.rest = rest
