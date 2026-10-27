import builtins
import symtable
import uuid
from dataclasses import dataclass

"""
    Environment (symbol tables)  -> the bookkeeper: which definition of x do reads see RIGHT NOW?
                                    one entry per name, overwritten on reassignment.
                                    It stores keys only, never types.


Scope rules (local / enclosing / global) are not guessed from the walk:
Python's own `symtable` module decides them up front for the whole file.
"""

BUILTIN_SCOPE_ID = "builtins"

# Provenance table key of a definition:
#   (col, line)             a real assignment
#   ("builtins", name)      a builtin, treated as an implicit `from builtins import name`
#   ("join", node_id, x)    a merge of several definitions at a CFG join
Key = tuple[int | str, ...]

@dataclass
class SymbolTableEntry():
    scope_id: str
    key: Key                 # the definition that reads of this name currently see


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
    def __init__(self, source: str, filename: str = "<file>") -> None:
        top = symtable.symtable(source, filename, "exec")
        self.symtables = self._index_symtables(top)   # (name, lineno) -> SymbolTable
        self.builtin = {
            name: SymbolTableEntry(BUILTIN_SCOPE_ID, (BUILTIN_SCOPE_ID, name))
            for name in vars(builtins)
        }
        self.scopes = [Scope(str(uuid.uuid4()), top, {})]   # global scope

    def _index_symtables(self, table: symtable.SymbolTable,
                         index: dict[tuple[str, int], symtable.SymbolTable] | None = None,
                         ) -> dict[tuple[str, int], symtable.SymbolTable]:
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
        An attribute chain "a.b" belongs to the scope of its root name a.
        """
        x = x.split(".")[0]
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
        """The definition x currently refers to, or None if it has no value yet."""
        scope = self._scope_of(x)
        if scope is None:
            return None
        if x in scope.table:
            return scope.table[x]
        if scope is self.scopes[0]:
            return self.builtin.get(x)
        return None

    def assign(self, x: str, key: Key) -> SymbolTableEntry | None:
        """
        Point x at the definition `key`, in the scope symtable says x belongs to. Replaces the entry
        rather than mutating it, so branches sharing the old entry are
        unaffected. Never touches builtins: `list = 5` creates a global.
        Assigning x also drops every longer chain: `a = ...` drops "a.b", "a.b.c".
        """
        scope = self._scope_of(x)
        if scope is None:
            return None
        for chain in [name for name in scope.table if name.startswith(x + ".")]:
            del scope.table[chain]
        entry = SymbolTableEntry(scope.id, key)
        scope.table[x] = entry
        return entry
