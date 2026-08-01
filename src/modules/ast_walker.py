import ast
import ast_wrappers
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
    def __init__(self):
        self.except_block = []

class IfElseContext(ScopeContext): pass
class FunctionContext(ScopeContext): pass
class ClassContext(ScopeContext): pass
class LoopContext(ScopeContext): pass


class ASTWalker():
    def __init__(self, ast: ast.AST, cfg: ControlFlowGraph,):
        self.cfg = cfg
        self.ast = ast
        self.scope_stack = []
    
    def traverse_and_create_cfg(self):
        self._parse(self.ast, ast_wrappers.ModuleEntry())

    _BODY_KIND_BY_ENTRY_TYPE = {
        ast_wrappers.ModuleEntry: (ast_wrappers.ModuleBody),
        ast_wrappers.IfEntry: (ast_wrappers.IfBody),
        ast_wrappers.ElseEntry: (ast_wrappers.ElseBody),
        ast_wrappers.ForEntry: (ast_wrappers.ForBody),
        ast_wrappers.WhileEntry: (ast_wrappers.WhileBody),
        ast_wrappers.TryEntry: (ast_wrappers.TryBody),
        ast_wrappers.ExceptEntry: (ast_wrappers.ExceptBody),
        ast_wrappers.FinallyEntry: (ast_wrappers.FinallyBody),
        ast_wrappers.FunctionDefinitionEntry: (ast_wrappers.FunctionBody),
        ast_wrappers.ClassDefinitionEntry: (ast_wrappers.ClassBody),
    }
    _EXIT_KIND_BY_ENTRY_TYPE = {
        ast_wrappers.ModuleEntry: (ast_wrappers.ExitKind.MODULE),
        ast_wrappers.IfEntry: (ast_wrappers.ExitKind.IF),
        ast_wrappers.ElseEntry: (ast_wrappers.ExitKind.ELSE),
        ast_wrappers.ForEntry: (ast_wrappers.ExitKind.FOR),
        ast_wrappers.WhileEntry: (ast_wrappers.ExitKind.WHILE),
        ast_wrappers.TryEntry: (ast_wrappers.ExitKind.TRY),
        ast_wrappers.ExceptEntry: (ast_wrappers.ExitKind.EXCEPT),
        ast_wrappers.FinallyEntry: (ast_wrappers.ExitKind.FINALLY),
        ast_wrappers.FunctionDefinitionEntry: (ast_wrappers.ExitKind.FUNCTION_DEFINITION),
        ast_wrappers.ClassDefinitionEntry: (ast_wrappers.ExitKind.CLASS_DEFINITION),
    }

    def _get_body_type(self, parent: ast.AST):
        return self._BODY_KIND_BY_ENTRY_TYPE[type(parent)]

    def _get_exit_kind(self, parent: ast.AST):
        return self._EXIT_KIND_BY_ENTRY_TYPE[type(parent)]

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
 f
        This is why the recursion generalizes cleanly. _parse() never needs to know whether
        its child was a while, an if, or a nested class. It simply asks "where are your
        exits?" and composes them into the enclosing graph.
        """

        code_body = ast_node.body
        CustomBody = self._get_body_type(parent)

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
                    
                    # def foo(): ... binds the name foo to the function value
                    # in the enclosing scope, so the entry node carries that assign.
                    func_assign = ast.Assign(
                        targets=[ast.Name(
                            id=cur_node.name,
                            ctx=ast.Store(),
                            lineno=cur_node.lineno,
                            col_offset=cur_node.col_offset,
                            end_lineno=cur_node.lineno,
                            end_col_offset=cur_node.end_col_offset,
                        )],
                        value=cur_node,
                        lineno=cur_node.lineno,
                        col_offset=cur_node.col_offset,
                        end_lineno=cur_node.lineno,
                        end_col_offset=cur_node.end_col_offset,
                    )

                    # Add the proxy node with this definition
                    func_entry = ast_wrappers.FunctionDefinitionEntry(
                        body=[func_assign],
                        lineno=func_assign.lineno,
                        col_offset=func_assign.col_offset,
                        end_lineno=func_assign.end_lineno,
                        end_col_offset=func_assign.end_col_offset,
                    )

                    cfg_nodes.append([func_entry])

                    func_body = ast_wrappers.FunctionBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )

                    self.scope_stack.append(FunctionContext())
                    self._parse(func_body, parent=func_entry)
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
                    
                    # Add a new assign statement for the class name to its definition
                    class_assign = ast.Assign(
                        targets=[ast.Name(
                            id=cur_node.name,
                            ctx=ast.Store(),
                            lineno=cur_node.lineno,
                            col_offset=cur_node.col_offset,
                            end_lineno=cur_node.lineno,
                            end_col_offset=cur_node.end_col_offset,
                        )],
                        value=cur_node,
                        lineno=cur_node.lineno,
                        col_offset=cur_node.col_offset,
                        end_lineno=cur_node.lineno,
                        end_col_offset=cur_node.end_col_offset,
                    )
                    
                    # Add the proxy node with this assignment
                    class_entry = ast_wrappers.ClassDefinitionEntry(
                        body=[class_assign],
                        lineno=class_assign.lineno,
                        col_offset=class_assign.col_offset,
                        end_lineno=class_assign.end_lineno,
                        end_col_offset=class_assign.end_col_offset,
                    )


                    cfg_nodes.append([class_entry])
                    class_body = ast_wrappers.ClassBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )

                    self.scope_stack.append(ClassContext())
                    tail = self._parse(class_body, parent=class_entry)
                    self.scope_stack.pop()

                    cfg_nodes.append(tail)
                    for tail_node in tail:
                        skip.add((class_entry, tail_node))

                    l = r+1

                case ast.If():
                    if r > l:
                        stmts = code_body[l:r]
                        cfg_nodes.append([CustomBody(
                            body=stmts,
                            lineno=stmts[0].lineno,
                            col_offset=stmts[0].col_offset,
                            end_lineno=stmts[-1].end_lineno,
                            end_col_offset=stmts[-1].end_col_offset,
                        )])
                    
                    if_else_entry = ast_wrappers.IfElseEntry()
                    cfg_nodes.append([if_else_entry])

                    self.scope_stack.append(IfElseContext())
                    if_entry = ast_wrappers.IfEntry()
                    if_body = ast_wrappers.IfBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    if_tail = self._parse(if_body, parent=if_entry)

                    else_entry = ast_wrappers.ElseEntry()
                    if cur_node.orelse:
                        else_body = ast_wrappers.ElseBody(
                            body=cur_node.orelse,
                            lineno=cur_node.orelse[0].lineno,
                            col_offset=cur_node.orelse[0].col_offset,
                            end_lineno=cur_node.orelse[-1].end_lineno,
                            end_col_offset=cur_node.orelse[-1].end_col_offset,
                        )
                    else:
                        # the dummy node inside gets returned
                        else_body = ast_wrappers.ElseBody(body=[ast_wrappers.ElseBody()])
                    else_tail = self._parse(else_body, parent=else_entry)
                    self.scope_stack.pop()

                    cfg_nodes.append([if_entry, else_entry])
                    tail = if_tail + else_tail
                    cfg_nodes.append(tail)
                    for tail_node in tail:
                        skip.add((if_entry, tail_node))
                        skip.add((else_entry, tail_node))
                    l = r+1

                case ast.While():
                    if r > l:
                        stmts = code_body[l:r]
                        cfg_nodes.append([CustomBody(
                            body=stmts,
                            lineno=stmts[0].lineno,
                            col_offset=stmts[0].col_offset,
                            end_lineno=stmts[-1].end_lineno,
                            end_col_offset=stmts[-1].end_col_offset,
                        )])
                    
                    while_loop_entry = ast_wrappers.WhileLoopEntry()
                    cfg_nodes.append([while_loop_entry])

                    self.scope_stack.append(LoopContext())
                    while_entry = ast_wrappers.WhileEntry()
                    while_body = ast_wrappers.WhileBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    while_tail = self._parse(while_body, parent=while_entry)

                    else_entry = ast_wrappers.ElseEntry()
                    else_body = ast_wrappers.ElseBody(body=[ast_wrappers.ElseBody()])
                    else_tail = self._parse(else_body, parent=else_entry)
                    self.scope_stack.pop()

                    cfg_nodes.append([while_entry,else_entry])
                    tail = while_tail + else_tail
                    cfg_nodes.append(tail)
                    for tail_node in tail:
                        skip.add((while_entry, tail_node))
                        skip.add((else_entry, tail_node))
                    l = r+1

                case ast.For():
                    if r > l:
                        stmts = code_body[l:r]
                        cfg_nodes.append([CustomBody(
                            body=stmts,
                            lineno=stmts[0].lineno,
                            col_offset=stmts[0].col_offset,
                            end_lineno=stmts[-1].end_lineno,
                            end_col_offset=stmts[-1].end_col_offset,
                        )])
                    
                    for_loop_entry = ast_wrappers.ForLoopEntry()
                    cfg_nodes.append([for_loop_entry])

                    self.scope_stack.append(LoopContext())
                    # for x in iter: ... binds x at the top of every iteration,
                    # so the loop-body entry node carries that assign.
                    for_assign = ast.Assign(
                        targets=[cur_node.target],
                        value=cur_node.iter,
                        lineno=cur_node.lineno,
                        col_offset=cur_node.col_offset,
                        end_lineno=cur_node.iter.end_lineno,
                        end_col_offset=cur_node.iter.end_col_offset,
                    )
                    for_entry = ast_wrappers.ForEntry(
                        body=[for_assign],
                        lineno=for_assign.lineno,
                        col_offset=for_assign.col_offset,
                        end_lineno=for_assign.end_lineno,
                        end_col_offset=for_assign.end_col_offset,
                    )
                    for_body = ast_wrappers.ForBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    for_tail = self._parse(for_body, parent=for_entry)

                    else_entry = ast_wrappers.ElseEntry()
                    else_body = ast_wrappers.ElseBody(body=[ast_wrappers.ElseBody()])
                    else_tail = self._parse(else_body, parent=else_entry)
                    self.scope_stack.pop()

                    cfg_nodes.append([for_entry, else_entry])
                    tail = for_tail + else_tail
                    cfg_nodes.append(tail)
                    for tail_node in tail:
                        skip.add((for_entry, tail_node))
                        skip.add((else_entry, tail_node))
                    l = r+1
                
                case ast.Try():
                    if r > l:
                        stmts = code_body[l:r]
                        cfg_nodes.append([CustomBody(
                            body=stmts,
                            lineno=stmts[0].lineno,
                            col_offset=stmts[0].col_offset,
                            end_lineno=stmts[-1].end_lineno,
                            end_col_offset=stmts[-1].end_col_offset,
                        )])
                    
                    try_except_entry = ast_wrappers.TryExceptBranchEntry()
                    cfg_nodes.append([try_except_entry])

                    try_catch_context = TryCatchContext()
                    self.scope_stack.append(try_catch_context)
                    try_except_tails = []
                    try_except_entries = []
                    for handler in cur_node.handlers:
                        except_entry = ast_wrappers.ExceptEntry()
                        except_body = ast_wrappers.ExceptBody(
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

                        new_tails=self._parse(except_body, parent=except_entry)
                        try_except_tails +=new_tails
                        try_except_entries.append(except_entry)

                        # Store (exception_type, node_ref)
                        scope_info = self.scope_stack[-1]
                        if handler.type: scope_info.except_block.append((handler.type.id, except_entry))  
                        else: scope_info.except_block.append(("", except_entry)) 

                    try_entry = ast_wrappers.TryEntry()
                    try_body = ast_wrappers.TryBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    ) 
                    try_tail = self._parse(try_body, parent=try_entry)
                    try_except_entries.append(try_entry)
                    self.scope_stack.pop()

                    cfg_nodes.append(try_except_entries)
                    try_except_tails+=try_tail
                    cfg_nodes.append(try_except_tails)

                    for tail_node in try_except_tails:
                        for entry_node in try_except_entries:
                            skip.add((entry_node, tail_node))

                    if cur_node.finalbody:
                        finally_entry = ast_wrappers.FinallyEntry()
                        cfg_nodes.append([finally_entry])
                        finally_body = ast_wrappers.FinallyBody(
                            body=cur_node.finalbody,
                            lineno=stmts[0].lineno,
                            col_offset=stmts[0].col_offset,
                            end_lineno=stmts[-1].end_lineno,
                            end_col_offset=stmts[-1].end_col_offset,
                        )
                        # All the tails of the try_except_block point to the finally's first block
                        finally_tails = self._parse(finally_body, finally_entry)
                        cfg_nodes.append(finally_tails)
                        for finally_tail in finally_tails:
                            skip.add((finally_entry, finally_tail))
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
                            for (exception_type, exception_entry) in self.scope_stack[i].except_block:
                                if cur_stmt.exc.id==exception_type or exception_type=="":
                                    self.cfg.insert(cur_node, exception_entry)
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
        
        exit_node = ast_wrappers.Exit(kind =  self._get_exit_kind(parent))
        cfg_nodes.append([exit_node])
        # Step 2 insert the edges
        for i in range(len(cfg_nodes)-1):
            for u in cfg_nodes[i]:
                for v in cfg_nodes[i+1]:
                    if (u, v) not in skip:
                        self.cfg.insert(u, v)
        
        # return the exit noe
        return cfg_nodes[-1]
        

if __name__ == "__main__":
    cfg = ControlFlowGraph()
    walker = ASTWalker(cfg, "tests/try_catch.py")
    walker.traverse_ast_for_cfg()
    walker.cfg._pretty_print()

