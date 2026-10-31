import ast
from dataclasses import dataclass, field
from enum import Enum, auto

from lexical_environment import Key
from type_lattice import LatticeValue


"""
ProvenanceTable              -> the occurrences: where did the type at (line, col)
                                come from? every use/definition gets an entry,
                                and parents point to the entries it was derived from.

Types are resolved lazily: an entry starts unresolved, and get_type later
resolves its parents, then evaluates its expr (the recipe) on their types.
"""

"""
Implicit Entry Keys

BUILTIN
("module", "builtins") → TableEntry("builtins", None, origin=Origin.IMPORT)     
("builtins", "len")    → TableEntry("len", builtins.len, parents=[("module", "builtins")])
("builtins", "print")  → TableEntry("print", builtins.print, parents=[("module", "builtins")])

JOIN 
Where branches merge, the environments of the arms are joined. A name whose arms hold
different keys gets a new join key:

    x = 1          # (1, 0)
    if c:
        x = "s"    # (3, 4)
    print(x)       # (4, 6)

    arm 1 env:   x → SymbolTableEntry(scope_id, (1, 0))
    arm 2 env:   x → SymbolTableEntry(scope_id, (3, 4))
    merged env:  x → SymbolTableEntry(scope_id, ("join", 7, "x"))

Implicit Entry: ("join", 7, "x") → TableEntry("x", None, origin=Origin.JOIN, parents=[(1, 0), (3, 4)])
(4, 6)           → TableEntry("x", <Name x>, parents=[("join", 7, "x")])
"""

class Origin(Enum):
    NORMAL = auto()
    PARAMETER = auto()
    IMPORT = auto()
    JOIN = auto()
    UNBOUND = auto()   # a name with no value on one arm of a merge


@dataclass(eq=False)         # compared by identity: entries are nodes in a DAG
class TableEntry():
    symbol: str                                # "a"
    expr: ast.AST | None                       # recipe: lhs -> its rhs, rhs use -> itself
    type: LatticeValue = field(default_factory=LatticeValue.unknown)
    resolved: bool = False
    parents: list[Key] = field(default_factory=list)   # keys, not entries, so re-analysis leaves no stale refs
    origin: Origin = Origin.NORMAL
    return_stmts: list[Key] | None = None              # function definitions only: keys of its return entries


ProvenanceTable = dict[Key, TableEntry]
