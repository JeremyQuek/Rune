import ast
import os
import sys
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "lsp_server", "modules"))
from control_flow_graph import ControlFlowGraph

TESTS_DIR = os.path.join(os.path.dirname(__file__), "cfg_graph_test_cases")

def get_test_cases():
    cases = []
    for f in sorted(os.listdir(TESTS_DIR)):
        if f.endswith(".graph"):
            name = f.removesuffix(".graph")
            py_file = os.path.join(TESTS_DIR, f"{name}.py")
            graph_file = os.path.join(TESTS_DIR, f)
            if os.path.exists(py_file):
                cases.append((name, py_file, graph_file))
    return cases

def run_walker(py_file):
    with open(py_file, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    cfg = ControlFlowGraph(tree)
    buf = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    cfg._pretty_print()
    sys.stdout = old_stdout
    return set(buf.getvalue().strip().splitlines())

def load_golden(graph_file):
    with open(graph_file, "r") as f:
        return set(line for line in f.read().strip().splitlines() if line)

def run_tests():
    cases = get_test_cases()
    passed = 0
    failed = 0
    results = []

    for name, py_file, graph_file in cases:
        try:
            actual = run_walker(py_file)
            expected = load_golden(graph_file)
            if actual == expected:
                results.append((name, "PASS", None))
                passed += 1
            else:
                missing = expected - actual
                extra = actual - expected
                diff = []
                if missing:
                    diff.append(f"  missing: {missing}")
                if extra:
                    diff.append(f"  extra:   {extra}")
                results.append((name, "FAIL", "\n".join(diff)))
                failed += 1
        except Exception as e:
            results.append((name, "FAIL", f"  error: {e}"))
            failed += 1

    print("Graph Test Results")
    print("-" * 40)
    for name, status, detail in results:
        icon = "PASS" if status == "PASS" else "FAIL"
        print(f"  [{icon}] {name}")
        if detail:
            print(detail)
    print("" * 40)
    print(f"Total: {passed + failed}  Passed: {passed}  Failed: {failed}")

if __name__ == "__main__":
    run_tests()
