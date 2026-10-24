import ast
from dataclasses import dataclass, field

from lexical_environment import Environment
from type_lattice import LatticeValue

"""
ProvenanceTable: (col, line) -> ProvenanceTableEntry, one per occurrence
(use or definition) of a name. parents point to the entries the type was
derived from, so following them gives the trace shown on hover.

The Environment is the bookkeeper (what x is right now); this is the history.
"""


@dataclass(eq=False)         # compared by identity: entries are nodes in a DAG
class ProvenanceTableEntry():
    type: LatticeValue
    parents: list["ProvenanceTableEntry"] = field(default_factory=list)


def add_rhs_to_provenance_table(provenance_table: dict, env: Environment,
                                rhs: list[ast.Name]) -> list[ProvenanceTableEntry]:
    """
    For each rhs use (y at (5,5)): its parent is y's last assignment
    (env.which(y) at (4,4)), looked up in the provenance table. The use gets
    its own entry pointing to that parent. No parent (builtin / unknown) -> no parents.

    Call BEFORE env.assign(x, ...), so in `x = x + 1` the rhs x is the old x.
    Returns the rhs parents, which become the lhs parents.
    """
    rhs_parents = []
    for name in rhs:
        parent_entry = env.which(name.id)
        parent_key = (parent_entry.col_offset, parent_entry.lineno) if parent_entry else None
        parent_node = provenance_table.get(parent_key)

        parents = [parent_node] if parent_node else []
        provenance_table[(name.col_offset, name.lineno)] = ProvenanceTableEntry(env.get_type(parent_entry), parents)
        rhs_parents.extend(parents)
    return rhs_parents


def add_lhs_to_provenance_table(provenance_table: dict, env: Environment,
                                lhs: list[ast.Name], rhs_parents: list[ProvenanceTableEntry]) -> None:
    """
    For each lhs target (x): its type is its last assignment in env,
    its parents are all the rhs parents. Call AFTER env.assign(x, ...).
    """
    for target in lhs:
        _type = env.get_type(env.which(target.id))
        provenance_table[(target.col_offset, target.lineno)] = ProvenanceTableEntry(_type, rhs_parents)
