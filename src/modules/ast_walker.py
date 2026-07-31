import ast
import ast_custom
from control_flow_graph import ControlFlowGraph

"""

Scope context markers pushed onto scope_stack to track lexical scope during AST walking.
Used for validation (e.g. return must be inside a function, break inside a loop)
and for connecting raise statements to their enclosing except handlers.

"""
class ScopeContext():
    def __repr__(self):
        return self.__class__.__name__

class TryCatchContext(ScopeContext):
    def __init__(self, try_block: ast_custom.TryBody = None):
        self.try_block = try_block
        self.except_block = []

class IfElseContext(ScopeContext): pass

class FunctionContext(ScopeContext): pass

class ClassContext(ScopeContext): pass

class LoopContext(ScopeContext): pass


class ASTWalker():
    def __init__(self, cfg: ControlFlowGraph, filepath: str):
        self.cfg = cfg
        self.filepath = filepath
        self.ast = self._get_ast()
        self.scope_stack = []
    
    def traverse_ast_for_cfg(self):
        self._parse(self.ast, None)

    def _get_ast(self) -> ast.AST:
        with open(self.filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
        return ast.parse(source_code, filename=self.filepath)

    def _get_body_type(self, ast_node: ast.AST):
        if isinstance(ast_node, ast_custom.IfBody):
            return ast_custom.IfBody
        if isinstance(ast_node, ast_custom.ElseBody):
            return ast_custom.ElseBody
        if isinstance(ast_node, ast_custom.FunctionBody):
            return ast_custom.FunctionBody
        if isinstance(ast_node, ast_custom.ClassBody):
            return ast_custom.ClassBody
        if isinstance(ast_node, ast_custom.TryBody):
            return ast_custom.TryBody
        if isinstance(ast_node, ast_custom.ExceptBody):
            return ast_custom.ExceptBody
        if isinstance(ast_node, ast_custom.ForBody):
            return ast_custom.ForBody
        if isinstance(ast_node, ast_custom.WhileBody):
            return ast_custom.WhileBody
        return ast_custom.Body
    
    def _create_body(self, stmts: list[ast.AST], body_type: ast.AST) -> ast.AST:
        return body_type(
            body=stmts,
            lineno=stmts[0].lineno,
            col_offset=stmts[0].col_offset,
            end_lineno=stmts[-1].end_lineno,
            end_col_offset=stmts[-1].end_col_offset,
        )


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

                    self.scope_stack.append(FunctionContext())
                    self._parse(func_body, parent=cur_node)
                    self.scope_stack.pop()

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

                    self.scope_stack.append(ClassContext())
                    tail = self._parse(class_body, parent=cur_node)
                    self.scope_stack.pop()

                    cfg_nodes.append(tail)
                    for tail_node in tail:
                        skip.add((cur_node, tail_node))

                    l = r+1

                case ast.If():
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

                    self.scope_stack.append(IfElseContext())
                    if_tail = self._parse(if_body, parent=cur_node)
                    self.scope_stack.pop()

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

                case ast.While():
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

                    while_body = ast_custom.WhileBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    
                    self.scope_stack.append(LoopContext())
                    while_tail = self._parse(while_body, parent=cur_node)
                    self.scope_stack.pop()

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

                    tail = while_tail + else_tail
                    cfg_nodes.append(tail)
                    for tail_node in tail:
                        skip.add((cur_node, tail_node))
                    l = r+1

                case ast.For():
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

                    for_body = ast_custom.ForBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )

                    # For the FOR case, the for statement itself is an assignment
                    # So we add another assign body right before the if body so that the assignment
                    # Only propagates down the if path
                    for_assignment_node = ast.Assign(
                        targets=[cur_node.target],
                        value=cur_node.iter,
                        lineno=cur_node.lineno,
                        col_offset=cur_node.col_offset,
                        end_lineno=cur_node.iter.lineno,
                        end_col_offset=cur_node.iter.end_col_offset,
                    )
                    for_body.body.insert(0, for_assignment_node)
                    
                    self.scope_stack.append(LoopContext())
                    for_tail = self._parse(for_body, parent=cur_node)
                    self.scope_stack.pop()

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

                    tail = for_tail + else_tail
                    cfg_nodes.append(tail)
                    for tail_node in tail:
                        skip.add((cur_node, tail_node))
                    l = r+1
                
                case ast.Try():
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
                    tails = []

                    self.scope_stack.append(TryCatchContext())
                    for handler in cur_node.handlers:
                        except_body = ast_custom.ExceptBody(
                            body=handler.body,
                            lineno=handler.body[0].lineno,
                            col_offset=handler.body[0].col_offset,
                            end_lineno=handler.body[-1].end_lineno,
                            end_col_offset=handler.body[-1].end_col_offset,
                        )
                        
                        # Ensure its not a bare except
                        # TODO handle ast.Attribute
                        if handler.name:
                            exception_assignment_node = ast.Assign(
                                targets=[ast.Name(
                                    id=handler.name,
                                    ctx=ast.Store(),
                                    lineno=handler.lineno,
                                    col_offset=handler.col_offset,
                                    end_lineno=handler.lineno,
                                    end_col_offset=handler.end_col_offset,
                                )],
                                value=handler.type,
                                lineno=handler.lineno,
                                col_offset=handler.col_offset,
                                end_lineno=handler.lineno,
                                end_col_offset=handler.end_col_offset,
                            )
                            except_body.body.insert(0, exception_assignment_node)

                        new_tails=self._parse(except_body, parent=cur_node)
                        tails +=new_tails

                        # Store (exception_type, node_ref)
                        scope_info = self.scope_stack[-1]
                        if handler.type: scope_info.except_block.append((handler.type.id, new_tails))  
                        # "" represents catch-all exception
                        else: scope_info.except_block.append(("", new_tails)) 

                    try_body = ast_custom.TryBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    ) 
                    
                    try_tail = self._parse(try_body, parent=cur_node)
                    self.scope_stack.pop()

                    tails+=try_tail
                    cfg_nodes.append(tails)
                    for tail_node in tails:
                        skip.add((cur_node, tail_node))
                    l = r+1
                
                case ast.Return() | ast.Yield():
                    stmts = code_body[l:r+1]
                    cfg_nodes.append([CustomBody(
                        body=stmts,
                        lineno=stmts[0].lineno,
                        col_offset=stmts[0].col_offset,
                        end_lineno=stmts[-1].end_lineno,
                        end_col_offset=stmts[-1].end_col_offset,
                    )])

                    # Validation check:
                    in_function = False
                    for i in range(len(self.scope_stack)-1,-1,-1):
                        if isinstance(self.scope_stack[i], FunctionContext):
                            in_function = True
                            break
                    if not in_function: raise SyntaxError

                    l=r+1
                    break
                
                case ast.Break() | ast.Continue() :
                    stmts = code_body[l:r+1]
                    cfg_nodes.append([CustomBody(
                        body=stmts,
                        lineno=stmts[0].lineno,
                        col_offset=stmts[0].col_offset,
                        end_lineno=stmts[-1].end_lineno,
                        end_col_offset=stmts[-1].end_col_offset,
                    )])

                    # Validation check:
                    for i in range(len(self.scope_stack)-1,-1,-1):
                        if isinstance(self.scope_stack[i], FunctionContext):
                            raise SyntaxError
                        if isinstance(self.scope_stack[i], LoopContext):
                            break
                    l=r+1
                    break
                
                # Need to tie in to any except handler
                case ast.Raise():
                    stmts = code_body[l:r+1]
                    cur_stmt = code_body[r]
                    cur_node = CustomBody(
                        body=stmts,
                        lineno=stmts[0].lineno,
                        col_offset=stmts[0].col_offset,
                        end_lineno=stmts[-1].end_lineno,
                        end_col_offset=stmts[-1].end_col_offset,
                    )
                    cfg_nodes.append([cur_node])
           
                    # TODO raise type = ast.Attribute
                    # Search for handlers within the nearest local scope
                    for i in range(len(self.scope_stack)-1, -1, -1):
                        if isinstance(self.scope_stack[i], FunctionContext):
                            break

                        if isinstance(self.scope_stack[i], TryCatchContext):
                            for (exception_type, exception_bodies) in self.scope_stack[i].except_block:
                                if cur_stmt.exc.id==exception_type or exception_type=="":
                                    self.cfg.insert(cur_node, exception_bodies[0])
                                    break

                    l=r+1
                    break

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
    walker = ASTWalker(cfg, "tests/try_catch.py")
    walker.traverse_ast_for_cfg()
    walker.cfg._pretty_print()

