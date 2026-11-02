"""
Type lattice used to merge environments at CFG join points.

A LatticeValue is a set of type names:

    Unknown      -> {}               bottom, no information yet
    int          -> {"int"}
    int | str    -> {"int", "str"}
    Any          -> {"Any"}          top, could be anything
    type[A]      -> {("type", key)}      the class object A, key = its global namespace table row
    A            -> {("instance", key)}  an instance of A
    Self@A       -> {("self", key)}      self in A's methods: an A, or the subclass the method was called on

A class is a ClassRef rather than a name, so the type carries its row: two classes named A
(if: class A … else: class A …) stay two members of a union, and display() shows both as A.

Join is set union, so:

    T ⊔ T        = T
    T ⊔ Unknown  = T
    A ⊔ B        = A | B
    T ⊔ Unbound  = T | Unbound
    T ⊔ Any      = Any

Unions wider than MAX_UNION_SIZE collapse to Any, which keeps the lattice
finite so fixpoint iteration always terminates.
"""

from collections.abc import Iterable

from lexical_environment import NamespaceKey

MAX_UNION_SIZE = 5

ANY = "Any"
UNBOUND = "Unbound"

ClassRef = tuple[str, NamespaceKey]   # ("type", key), ("instance", key) or ("self", key)
Type = str | ClassRef


def display(t: Type) -> str:
    """A type as hover shows it: ("type", key) -> type[A], ("instance", key) -> A, ("self", key) -> Self@A, a name as is."""
    if isinstance(t, str):
        return t
    kind, key = t
    name = key[-1][0]
    return {"type": f"type[{name}]", "self": f"Self@{name}"}.get(kind, name)

class LatticeValue():
    def __init__(self, types: Iterable[Type] = ()) -> None:
        types = frozenset(types)
        if ANY in types or len(types) > MAX_UNION_SIZE:
            types = frozenset({ANY})
        self.types = types

    @classmethod
    def unknown(cls) -> "LatticeValue":
        return cls()

    @classmethod
    def of(cls, type_name: Type) -> "LatticeValue":
        return cls({type_name})

    def join(self, other: "LatticeValue") -> "LatticeValue":
        return LatticeValue(self.types | other.types)

    def is_unknown(self) -> bool:
        return not self.types

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LatticeValue) and self.types == other.types

    def __hash__(self) -> int:
        return hash(self.types)

    def __repr__(self) -> str:
        if self.is_unknown():
            return "Unknown"
        return " | ".join(sorted(display(t) for t in self.types))


if __name__ == "__main__":
    i, s = LatticeValue.of("int"), LatticeValue.of("str")
    print(i.join(i))                              # int
    print(i.join(LatticeValue.unknown()))         # int
    print(i.join(s))                              # int | str
    print(i.join(LatticeValue.of(UNBOUND)))       # Unbound | int
    print(i.join(LatticeValue.of(ANY)))           # Any
