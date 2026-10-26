import ast
from dataclasses import dataclass, field
from enum import Enum, auto

from lexical_environment import Key
from type_lattice import LatticeValue

"""
ProvenanceTable: Key -> TableEntry, one per occurrence (use or definition)
of a name. parents are the keys of the entries the type is derived from, so
following them gives the trace shown on hover.

Types are resolved lazily: an entry starts unresolved, and get_type later
resolves its parents, then evaluates its expr (the recipe) on their types.

The Environment is the bookkeeper (which definition x refers to right now);
this is the history.
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
