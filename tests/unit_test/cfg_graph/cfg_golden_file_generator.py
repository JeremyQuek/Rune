"""
Writes the golden testcases/<name>.graph files: the _pretty_print output of each test case's CFG.

    python3 tests/unit_test/cfg_graph/cfg_golden_file_generator.py              # regenerate every existing golden
    python3 tests/unit_test/cfg_graph/cfg_golden_file_generator.py match class  # (re)write these, creating them if missing

Only regenerate after checking the new graph is right: a golden records whatever the
generator does now, bugs included.
"""
import ast
import contextlib
import io
import pathlib
import sys

CASES_DIR = pathlib.Path(__file__).resolve().parent / "testcases"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "src" / "lsp_server" / "modules"))
from control_flow_graph import ControlFlowGraph


def golden(py_file: pathlib.Path) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ControlFlowGraph(ast.parse(py_file.read_text(encoding="utf-8")))._pretty_print()
    return buf.getvalue()


def main(names: list[str]) -> None:
    if not names:
        names = sorted(graph.stem for graph in CASES_DIR.glob("*.graph"))
    for name in names:
        py_file = CASES_DIR / f"{name.removesuffix('.py')}.py"
        if not py_file.exists():
            print(f"  skip {name}: no {py_file.name}")
            continue
        output = golden(py_file)
        py_file.with_suffix(".graph").write_text(output, encoding="utf-8")
        print(f"  wrote {py_file.with_suffix('.graph').name} ({len(output.splitlines())} edges)")


if __name__ == "__main__":
    main(sys.argv[1:])
