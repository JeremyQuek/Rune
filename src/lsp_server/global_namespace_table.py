class GlobalNamespaceTable:   
    """
    
    Shape: namespace → {member name: definition key}
    ┌────────┬─────────────────────────────────────────┬────────────────────────────────────┬─────────────────────────────────────────────┬─────────────────────────────────────────────┐
    │  Row   │                   Key                   │              Members               │                Written when                 │                 Reached how                 │
    ├────────┼─────────────────────────────────────────┼────────────────────────────────────┼─────────────────────────────────────────────┼─────────────────────────────────────────────┤
    │ module │ module name, e.g. "animals"             │ its global scope: {Dog: key, a:    │ at the module's Exit (a snapshot of the     │ by name: imports are the only named way in  │
    │        │                                         │ key, ...}                          │ final global scope)                         │                                             │
    ├────────┼─────────────────────────────────────────┼────────────────────────────────────┼─────────────────────────────────────────────┼─────────────────────────────────────────────┤
    │ class  │ the class's definition key, e.g.        │ its body scope: {b: key, bark:     │ at the class's Exit                         │ only through a type: a value whose type     │
    │        │ ("animals", (6, 3))                     │ key} + its bases                   │                                             │ points at that class                        │
    └────────┴─────────────────────────────────────────┴────────────────────────────────────┴─────────────────────────────────────────────┴─────────────────────────────────────────────┘

    What it stores: definition keys, not types. It says where Dog.b is defined, (4, 5) in animals. The type comes from asking animals.get_type((4, 5)), which computes and caches it. So writing the table never needs type information.

    How it's used: every dot is the same operation. Find the receiver's type, look up the member in that type's row, then ask the owning module for that key's type.
    from animals import Dog
    a = Dog()
    a.b      → a's type: instance of ("animals", (6, 3))
            → table[("animals", (6, 3))]["b"] → key (4, 5) in animals
            → animals.get_type((4, 5)) → int
    Imports work the same way: m resolves to module(m), and m.a → table["m"]["a"].

    Rules we agreed:
    - Every class is indexed, including nested ones and classes defined inside functions. Visibility doesn't matter: the environment decides which names you can reach, types decide which rows.
    - Class rows are keyed by definition key, not name, because names collide (if: class A … else: class A …). The qualified name is kept for display only.
    - The type carries where the class was defined, not the file it passed through. a = Dog() in M.py, with Dog imported from animals, looks in Dog's row in animals, never "M.Dog".
    - No circular asks: the table only ever hands out keys, never passes the question on. A missing row makes the owning module build, and building is type-free.
    - Inheritance: if the member isn't in the row, check the bases' rows.
    - On rebuild, a module replaces its own rows.
    - Not covered yet: instance attributes (self.x in __init__) feeding the class row.
    
    """

    pass