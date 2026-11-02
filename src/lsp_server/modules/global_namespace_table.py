from collections import defaultdict
from typing import Literal

from lexical_environment import Key, NamespaceKey

class GlobalNamespaceTable:   
    """
    One row per class, keyed by where it's defined. Holds definition keys, never types.

    Key:  (path, (Outer, (line, col)), (Inner, (line, col)))      functions skipped
    Row:  class_attrs     {name: [key, ...]}   cls.x in a classmethod
          instance_attrs  {name: [key, ...]}   self.x in an instance method
          bases           [key, ...]           base read keys, in order (not yet)

    - Created on each class push; replaced on re-push (loop pass, rebuild), like CPython.
    - Receiver = the method's first param. Static methods and nested functions write nothing.
    - A member keeps every key written to it; its type is their union.
    - Lookup (evaluator): X → instance_attrs then class_attrs along the MRO;
      type[X] → class_attrs along the MRO, then the metaclass. MRO = C3 over bases.
    """

    def __init__(self) -> None:
        self.table: dict[NamespaceKey, dict] = {}

    def create_entry(self, key: NamespaceKey) -> None:
        self.table[key] = {"class_attrs": {}, "instance_attrs": {}, "bases": []}

    def add_attribute(self, 
        receiver_key: NamespaceKey, 
        name: str, 
        kind: Literal["class", "instance"], 
        key: Key) -> None:
        if receiver_key not in self.table:
            return
        keys = self.table[receiver_key][f"{kind}_attrs"].setdefault(name, [])
        if key not in keys:  
            keys.append(key)


    def _pretty_print(self) -> None:
        """Each row as Outer[line,col].Inner[line,col], then its members and the keys written to them."""
        for row_key, row in self.table.items():
            print(".".join(f"{name}[{line},{col}]" for name, (line, col) in row_key[1:]))
            for field in ("class_attrs", "instance_attrs"):
                members = "   ".join(f"{name}: {' '.join(map(str, keys))}" for name, keys in row[field].items())
                print(f"    {field:<15} {members}")
            print(f"    {'bases':<15} {row['bases']}")

def visualise_table(table: GlobalNamespaceTable, builder, path: str | None = None) -> str:
    """
    The file's class rows next to its source, in a browser page: a line from every key in a row
    to the name it points at (the class name for the row, x in self.x for an attribute).
    """
    import html, json, pathlib, tempfile, webbrowser

    rows = [{"qualname": ".".join(f"{name}[{line},{col}]" for name, (line, col) in row_key[1:]),
             "label": row_key[-1][0], "site": list(row_key[-1][1]),
             "class_attrs": row["class_attrs"], "instance_attrs": row["instance_attrs"], "bases": row["bases"]}
            for row_key, row in table.table.items() if row_key[0] == builder.filepath]
    data = {"file": builder.filepath, "lines": builder.source_lines, "rows": rows}

    # the page lives in tests/unit_test_html_templates; only the placeholders are filled in here
    template = (pathlib.Path(__file__).resolve().parents[3] / "tests" / "unit_test_html_templates"
                / "namespace_table.html").read_text(encoding="utf-8")
    name = pathlib.Path(builder.filepath).name
    page = template.replace("__TITLE__", html.escape(name)).replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    out = pathlib.Path(path) if path else pathlib.Path(tempfile.gettempdir()) / f"rune_ns_{pathlib.Path(name).stem}.html"
    out.write_text(page, encoding="utf-8")
    webbrowser.open(out.as_uri())
    return str(out)

if __name__=="__main__":
    from module_file_builder import ModuleFileBuilder   # here, not at the top: module_file_builder imports this file

    table = GlobalNamespaceTable()
    filepath= "/Users/jeremyquek/Desktop/rune/tests/unit_test/global_namespace_table/testcases/classes.py"
    module_file_builder = ModuleFileBuilder(filepath, table)
    module_file_builder.process_file()
    table._pretty_print()
    visualise_table(table, module_file_builder)

