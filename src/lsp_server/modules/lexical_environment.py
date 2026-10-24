import builtins
import symtable
import uuid
from dataclasses import dataclass

from type_lattice import LatticeValue

"""
Two tables, two jobs:

    Environment (symbol tables)  -> the bookkeeper: what is x RIGHT NOW?
                                    one entry per name, overwritten on reassignment.

    ProvenanceTable              -> the occurrences: where did the type at (col, line)
                                    come from? every use/definition gets an entry,
                                    and parents point to the entries it was derived from.

Scope rules (local / enclosing / global) are not guessed from the walk:
Python's own `symtable` module decides them up front for the whole file.
"""

BUILTIN_SCOPE_ID = "builtins"


@dataclass
class SymbolTableEntry():
    scope_id: str           
    type: LatticeValue
    lineno: int | None       # where it was last assigned, None for builtins
    col_offset: int | None


@dataclass
class Scope():
    id: str                          # uuid4
    symtable: symtable.SymbolTable   # Python's scope analysis for this scope
    table: dict[str, SymbolTableEntry]

    def is_class(self) -> bool:
        return self.symtable.get_type() == "class"

    def declares_local(self, x: str) -> bool:
        return x in self.symtable.get_identifiers() and self.symtable.lookup(x).is_local()


class Environment():
    """
    scopes is a stack of Scope, global at the bottom, local on top.
    builtins live outside the stack and are checked last for global names.
    """
    def __init__(self, source: str, filename: str = "<file>"):
        top = symtable.symtable(source, filename, "exec")
        self.symtables = self._index_symtables(top)   # (name, lineno) -> SymbolTable
        self.builtin = {
            name: SymbolTableEntry(BUILTIN_SCOPE_ID, LatticeValue.of(type(value).__name__), None, None)
            for name, value in vars(builtins).items()
        }
        self.scopes = [Scope(str(uuid.uuid4()), top, {})]   # global scope

    def _index_symtables(self, table, index=None):
        index = {} if index is None else index
        for child in table.get_children():
            index[(child.get_name(), child.get_lineno())] = child
            self._index_symtables(child, index)
        return index

    def push_scope(self, name: str, lineno: int) -> Scope:
        """Enter the function/class `name` defined on `lineno`."""
        scope = Scope(str(uuid.uuid4()), self.symtables[(name, lineno)], {})
        self.scopes.append(scope)
        return scope

    def pop_scope(self) -> Scope:
        return self.scopes.pop()


    def _scope_of(self, x: str) -> Scope | None:
        """
        The scope x belongs to according to symtable, even if x has not
        been assigned in it yet. None if no enclosing scope binds a free x.
        Names symtable never saw in this scope are treated as global
        (then builtins), like Python does for an unbound name.
        """
        local = self.scopes[-1]
        if x not in local.symtable.get_identifiers():
            return self.scopes[0]
        symbol = local.symtable.lookup(x)

        if symbol.is_free():
            # Enclosing: nearest outer function that binds x, skipping
            # class scopes (methods can't see class attributes) and global
            for scope in reversed(self.scopes[1:-1]):
                if not scope.is_class() and scope.declares_local(x):
                    return scope
            return None

        if symbol.is_global():
            return self.scopes[0]

        return local

    def which(self, x: str) -> SymbolTableEntry | None:
        """The entry x currently refers to, or None if it has no value yet."""
        scope = self._scope_of(x)
        if scope is None:
            return None
        if x in scope.table:
            return scope.table[x]
        if scope is self.scopes[0]:
            return self.builtin.get(x)
        return None

    def get_type(self, entry: SymbolTableEntry | None) -> LatticeValue:
        return entry.type if entry else LatticeValue.unknown()


    def assign(self, x: str, _type: LatticeValue, lineno: int, col_offset: int) -> SymbolTableEntry | None:
        """
        Bind x in the scope symtable says it belongs to. Replaces the entry
        rather than mutating it, so branches sharing the old entry are
        unaffected. Never touches builtins: `list = 5` creates a global.
        """
        scope = self._scope_of(x)
        if scope is None:
            return None
        entry = SymbolTableEntry(scope.id, _type, lineno, col_offset)
        scope.table[x] = entry
        return entry
