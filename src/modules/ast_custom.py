
import ast

"""
Custom AST nodes for representing spliced statement blocks in the CFG.

Python's ast.Module lacks location attributes, making it unsuitable as a
wrapper for arbitrary statement slices. These nodes provide a uniform,
hashable, location-aware container for groups of consecutive statements
that form a single basic block in the control flow graph.

Subclasses distinguish the lexical context the block belongs to, allowing
the CFG and downstream analysis to differentiate module-level code from
function bodies and class bodies without inspecting the parent.
"""

class Body(ast.AST):
    _fields = ('body',)
    _attributes = ('lineno', 'col_offset', 'end_lineno', 'end_col_offset')

    def __init__(self, body=None, lineno=0, col_offset=0, end_lineno=0, end_col_offset=0):
        self.body = body or []
        self.lineno = lineno
        self.col_offset = col_offset
        self.end_lineno = end_lineno
        self.end_col_offset = end_col_offset

    def unparse(self):
        return "\n".join(ast.unparse(stmt) for stmt in self.body)

class IfBody(Body): pass
class WhileBody(Body): pass
class ForBody(Body): pass
class ElseBody(Body): pass
class ExceptBody(Body): pass
class ClassBody(Body): pass
class FunctionBody(Body): pass
class TryBody(Body): pass