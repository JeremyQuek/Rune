import builtins
import uuid
from dataclasses import dataclass
from typing import Literal

BUILTIN_SCOPE_ID = "builtins"

@dataclass
class SymbolTableEntry():
    id: str     # id of the scope this symbol belongs to
    type: str

class Environment():
    """
    LEGB lookup: scopes is a stack of (id, symbol_table), local on top,
    global at the bottom, with builtins checked last.
    """
    def __init__(self):
        self.builtin = {
            name: SymbolTableEntry(BUILTIN_SCOPE_ID, type(value).__name__)
            for name, value in vars(builtins).items()
        }
        self.scopes = []
        self.push_scope()  # global scope

    def push_scope(self) -> str:
        scope_id = str(uuid.uuid4())
        self.scopes.append((scope_id, {}))
        return scope_id

    def pop_scope(self):
        return self.scopes.pop()

    def assign(self, target: str, _type: str) -> SymbolTableEntry:
        # Assignment always binds in the local (innermost) scope
        scope_id, symbol_table = self.scopes[-1]
        if target in symbol_table:
            symbol_table[target].type = _type
        else:
            symbol_table[target] = SymbolTableEntry(scope_id, _type)
        return symbol_table[target]

    def shadow(self, target: str, scope: Literal["global", "nonlocal"]) -> SymbolTableEntry:
        """
        Handles `global x` / `nonlocal x`: binds target in the local scope to
        the SAME entry object as the outer one, so assigning to the local
        target modifies the outer one (Python exposes no refs, but this is
        what the declaration means).

        global:    looks only in the top (global) scope.
        enclosing: walks outward from the nearest enclosing scope, stopping
                   before global, until target is found.

        If target doesn't exist yet, we create the entry (Unknown) in the
        global scope, or in the nearest enclosing scope, then copy that
        entry into the local scope under the same target.
        """
        _, local_table = self.scopes[-1]

        if scope == "global":
            outer_tables = [self.scopes[0]]
        else:
            outer_tables = list(reversed(self.scopes[1:-1]))
            if not outer_tables:
                raise SyntaxError(f"no enclosing scope for nonlocal '{target}'")

        for _, symbol_table in outer_tables:
            if target in symbol_table:
                entry = symbol_table[target]
                break
        else:
            scope_id, symbol_table = outer_tables[0]
            entry = SymbolTableEntry(scope_id, "Unknown")
            symbol_table[target] = entry

        local_table[target] = entry
        return entry

    def which(self, x: str) -> SymbolTableEntry:
        # Local -> Enclosing -> Global
        for _, symbol_table in reversed(self.scopes):
            if x in symbol_table:
                return symbol_table[x]
        # Built-in
        if x in self.builtin:
            return self.builtin[x]
        # Not found: declare it as Unknown in the innermost scope
        scope_id, symbol_table = self.scopes[-1]
        entry = SymbolTableEntry(scope_id, "Unknown")
        symbol_table[x] = entry
        return entry
