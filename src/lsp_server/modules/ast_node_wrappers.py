
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

# a jump statement in a node of its own: it ends its block and never falls through
class Break(Body): pass
class Continue(Body): pass
class Return(Body): pass
class Raise(Body): pass

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
    FOR_ELSE = auto()
    WHILE_ELSE = auto()
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
    RAISE = auto()   # the module's exceptional exit: where uncaught raises go, kept apart from the normal Exit

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
class ForElseEntry(Entry): pass     # a for's literal else, after the loop exit

class WhileLoopEntry(BranchEntry):pass
class WhileEntry(Entry):pass
class WhileElseEntry(Entry): pass   # a while's literal else, after the loop exit

class LoopNeverRanEntry(Entry): pass   # a loop's zero-iteration arm, no body

class TryExceptBranchEntry(BranchEntry):pass
class TryEntry(Entry):pass
class ExceptEntry(Entry):pass
class FinallyEntry(Entry):pass

class FunctionDefinitionEntry(BranchEntry): pass

class ClassDefinitionEntry(Entry): pass

class MatchEntry(BranchEntry): pass
class CaseEntry(Entry): pass

# --------- Provenance recipes --------- #

def unparse_header(stmt: ast.stmt) -> str:
    """A statement's header as source: stmt rebuilt with an empty body, unparsed, without the colon."""
    return ast.unparse(stmt).rstrip(":")


class IteratedFrom(ast.expr):
    """
    Recipe for a name bound by `for target in value`: an element of value (the iteration protocol).
        for x in it   x -> IteratedFrom(it, target=x)
    target is the loop's whole target, kept so unparse can rebuild the statement.
    """
    _fields = ('value',)

    def __init__(self, value: ast.expr, target: ast.expr) -> None:
        self.value = value
        self.target = target

    def unparse(self) -> str:
        return unparse_header(ast.For(target=self.target, iter=self.value, body=[], orelse=[], lineno=0, type_comment=None))


class UnpackedAt(ast.expr):
    """
    Recipe for a name bound by unpacking, which has no expression of its own: the element at index.
        x, y = e      x -> UnpackedAt(e, 0, target=(x, y))
    target is the tuple being unpacked at this level. When value is itself a binding wrapper
    (for a, b in pairs: a -> UnpackedAt(IteratedFrom(pairs), 0)), the statement is the outer one's.
    """
    _fields = ('value',)

    def __init__(self, value: ast.expr, index: int, target: ast.expr) -> None:
        self.value = value
        self.index = index
        self.target = target

    def unparse(self) -> str:
        return _unpacking_statement(self)


class StarredFrom(ast.expr):
    """
    Recipe for the starred name in unpacking: the rest, as a list, from position index on.
        x, *y = e     y -> StarredFrom(e, 1, target=(x, *y))
    """
    _fields = ('value',)

    def __init__(self, value: ast.expr, index: int, target: ast.expr) -> None:
        self.value = value
        self.index = index
        self.target = target

    def unparse(self) -> str:
        return _unpacking_statement(self)


def _unpacking_statement(node: UnpackedAt | StarredFrom) -> str:
    """target = value, or the enclosing binding's statement when value is another wrapper (for, with, nested unpacking)."""
    if isinstance(node.value, (IteratedFrom, UnpackedAt, StarredFrom, EnteredFrom)):
        return node.value.unparse()
    return unparse_header(ast.Assign(targets=[node.target], value=node.value, lineno=0, type_comment=None))


class CaughtAs(ast.expr):
    """
    Recipe for `except E as e`: e is an instance of E (of each member, for a tuple of types).
    name is kept because the AST stores it as a plain string, with no position.
    """
    _fields = ('type',)

    def __init__(self, type: ast.expr, name: str) -> None:
        self.type = type
        self.name = name

    def unparse(self) -> str:
        return unparse_header(ast.ExceptHandler(type=self.type, name=self.name, body=[]))


class EnteredFrom(ast.expr):
    """
    Recipe for `with cm as f`: f is cm.__enter__().
    target is the item's `as` target, kept so unparse can rebuild the statement.
    """
    _fields = ('value',)

    def __init__(self, value: ast.expr, target: ast.expr) -> None:
        self.value = value
        self.target = target

    def unparse(self) -> str:
        item = ast.withitem(context_expr=self.value, optional_vars=self.target)
        return unparse_header(ast.With(items=[item], body=[], lineno=0, type_comment=None))


class ParameterOf(ast.expr):
    """
    Recipe for a function parameter, bound at the start of the body:
        def f(a: int, b=0, *args, c, **kw)
    arg is the ast.arg (name, annotation), default its default (or None), kind one of
    "positional", "vararg", "keyword", "kwarg". No fields: the annotation and default
    are evaluated where the def is, not in the body.
    """
    _fields = ()

    def __init__(self, arg: ast.arg, default: ast.expr | None, kind: str) -> None:
        self.arg = arg
        self.default = default
        self.kind = kind

    def unparse(self) -> str:
        """The parameter as written in the signature: *args, b: int = 0, b=0."""
        text = {"vararg": "*", "kwarg": "**"}.get(self.kind, "") + ast.unparse(self.arg)
        if self.default is not None:
            text += (" = " if self.arg.annotation is not None else "=") + ast.unparse(self.default)
        return text
