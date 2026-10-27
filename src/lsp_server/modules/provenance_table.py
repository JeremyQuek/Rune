import ast
from dataclasses import dataclass, field
from enum import Enum, auto

from lexical_environment import Key
from type_lattice import LatticeValue


"""
ProvenanceTable              -> the occurrences: where did the type at (col, line)
                                come from? every use/definition gets an entry,
                                and parents point to the entries it was derived from.

Types are resolved lazily: an entry starts unresolved, and get_type later
resolves its parents, then evaluates its expr (the recipe) on their types.
"""


class Origin(Enum):
    NORMAL = auto()
    PARAMETER = auto()
    IMPORT = auto()
    JOIN = auto()


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
