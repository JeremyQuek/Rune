import ast
import ast_custom
from control_flow_graph import ControlFlowGraph

class ASTWalker():
    def __init__(self, cfg: ControlFlowGraph, filepath: str):
        self.cfg = cfg
        self.filepath = filepath
        self.ast = self._get_ast()
    
    def traverse_ast_for_cfg(self):
        self._parse(self.ast, None)

    def _get_ast(self) -> ast.AST:
        with open(self.filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
        return ast._parse(source_code, filename=self.filepath)

    def _get_body_type(self, ast_node: ast.AST):
        if isinstance(ast_node, ast_custom.IfBody):
            return ast_custom.IfBody
        if isinstance(ast_node, ast_custom.ElseBody):
            return ast_custom.ElseBody
        if isinstance(ast_node, ast_custom.FunctionBody):
            return ast_custom.FunctionBody
        if isinstance(ast_node, ast_custom.ClassBody):
            return ast_custom.ClassBody
        return ast_custom.Body
    

    def _parse(self, ast_node: ast.AST, parent: ast.AST | None = None):
        """
        Recursively decomposes a code region into CFG layers, returning its exit frontier.

        What's an exit frontier? Every code region — whether it's a module, a function body,
        an if-branch, or an else-branch — has a set of nodes where execution "leaves" that
        region. This method answers one question: "where can execution exit this region?"

        The key insight is that cfg_nodes is a list of *layers*, where each layer is a list
        of nodes at the same "depth" in the sequential flow. Adjacent layers get fully
        connected (cartesian product of edges). This means:

        - A linear block is a layer of one: [Body]
        - A branch point is a layer of one: [ast.If]
        - A convergence point is a layer of many: [if_tail, else_tail]

        When we connect layer [if_tail, else_tail] → layer [RestOfCode], both tails
        automatically get edges to the next block. The join falls out naturally from the
        data structure — no special join logic needed.

        The caller decides what to do with the returned frontier:
        - Sequential code: connect it to the next thing
        - Function def: discard it (body doesn't execute at definition time)
        - Class def: rejoin it (class body executes immediately)
        - Control flow: collect if_tail + else_tail as the combined frontier

        This is why the recursion generalizes cleanly. _parse() never needs to know whether
        its child was a while, an if, or a nested class. It simply asks "where are your
        exits?" and composes them into the enclosing graph.
        """

        code_body = ast_node.body
        CustomBody = self._get_body_type(ast_node)

        # Step 1 split the list into sections
        l=0
        cfg_nodes = [[parent]]
        skip = set()
        for r in range(len(code_body)):
            cur_node = code_body[r]
            match cur_node:
                case ast.FunctionDef():
                    if r > l:
                        stmts = code_body[l:r]
                        cfg_nodes.append([CustomBody(
                            body=stmts,
                            lineno=stmts[0].lineno,
                            col_offset=stmts[0].col_offset,
                            end_lineno=stmts[-1].end_lineno,
                            end_col_offset=stmts[-1].end_col_offset,
                        )])
                    cfg_nodes.append([cur_node])
                    func_body = ast_custom.FunctionBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    self._parse(func_body, parent=cur_node)
                    l = r+1

                case ast.ClassDef():
                    if r > l:
                        stmts = code_body[l:r]
                        cfg_nodes.append([CustomBody(
                            body=stmts,
                            lineno=stmts[0].lineno,
                            col_offset=stmts[0].col_offset,
                            end_lineno=stmts[-1].end_lineno,
                            end_col_offset=stmts[-1].end_col_offset,
                        )])
                    cfg_nodes.append([cur_node])

                    class_body = ast_custom.ClassBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    tail = self._parse(class_body, parent=cur_node)
                    cfg_nodes.append(tail)
                    for tail_node in tail:
                        skip.add((cur_node, tail_node))

                    l = r+1

                case ast.If() | ast.While() | ast.For():
                    if r > l:
                        stmts = code_body[l:r]
                        cfg_nodes.append([ast_custom.Body(
                            body=stmts,
                            lineno=stmts[0].lineno,
                            col_offset=stmts[0].col_offset,
                            end_lineno=stmts[-1].end_lineno,
                            end_col_offset=stmts[-1].end_col_offset,
                        )])
                    cfg_nodes.append([cur_node])

                    if_body = ast_custom.IfBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    if_tail = self._parse(if_body, parent=cur_node)

                    if cur_node.orelse:
                        else_body = ast_custom.ElseBody(
                            body=cur_node.orelse,
                            lineno=cur_node.orelse[0].lineno,
                            col_offset=cur_node.orelse[0].col_offset,
                            end_lineno=cur_node.orelse[-1].end_lineno,
                            end_col_offset=cur_node.orelse[-1].end_col_offset,
                        )
                    else:
                        # the dummy node inside gets returned
                        else_body = ast_custom.ElseBody(body=[ast_custom.ElseBody()])
                    else_tail = self._parse(else_body, parent=cur_node)

                    tail = if_tail + else_tail
                    cfg_nodes.append(tail)
                    for tail_node in tail:
                        skip.add((cur_node, tail_node))
                    l = r+1
                
        if l < len(code_body):
            stmts = code_body[l:]
            cfg_nodes.append([CustomBody(
                body=stmts,
                lineno=stmts[0].lineno,
                col_offset=stmts[0].col_offset,
                end_lineno=stmts[-1].end_lineno,
                end_col_offset=stmts[-1].end_col_offset,
            )])
        
        # Step 2 insert the edges
        for i in range(len(cfg_nodes)-1):
            for u in cfg_nodes[i]:
                for v in cfg_nodes[i+1]:
                    if (u, v) not in skip:
                        self.cfg.insert(u, v)
        
        # return the tail node(s)
        return cfg_nodes[-1]
        

if __name__ == "__main__":
    cfg = ControlFlowGraph()
    walker = ASTWalker(cfg, "tests/hybrid.py")
    walker.traverse_ast_for_cfg()
    walker.cfg._pretty_print()

