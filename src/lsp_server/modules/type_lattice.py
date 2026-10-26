"""
Type lattice used to merge environments at CFG join points.

A LatticeValue is a set of type names:

    Unknown      -> {}               bottom, no information yet
    int          -> {"int"}
    int | str    -> {"int", "str"}
    Any          -> {"Any"}          top, could be anything

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

MAX_UNION_SIZE = 5

ANY = "Any"
UNBOUND = "Unbound"

class LatticeValue():
    def __init__(self, types: Iterable[str] = ()) -> None:
        types = frozenset(types)
        if ANY in types or len(types) > MAX_UNION_SIZE:
            types = frozenset({ANY})
        self.types = types

    @classmethod
    def unknown(cls) -> "LatticeValue":
        return cls()

    @classmethod
    def of(cls, type_name: str) -> "LatticeValue":
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
        return " | ".join(sorted(self.types))


if __name__ == "__main__":
    i, s = LatticeValue.of("int"), LatticeValue.of("str")
    print(i.join(i))                              # int
    print(i.join(LatticeValue.unknown()))         # int
    print(i.join(s))                              # int | str
    print(i.join(LatticeValue.of(UNBOUND)))       # Unbound | int
    print(i.join(LatticeValue.of(ANY)))           # Any
