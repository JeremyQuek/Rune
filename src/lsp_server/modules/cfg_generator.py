import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import ast_node_wrappers

if TYPE_CHECKING:  # the graph owns the generator, so importing it here at runtime would be circular
    from control_flow_graph import ControlFlowGraph

"""

Scope context management classes are pushed onto scope_stack to track lexical scope during AST descent.
Used for validation (e.g. return must be inside a function, break inside a loop)
and for connecting raise statements to their enclosing except handlers.

"""
# eq=False: contexts are compared by identity, like plain objects
@dataclass(eq=False)
class IfElseContext():
    pass

@dataclass(eq=False)
class FunctionContext():
    pass

@dataclass(eq=False)
class ClassContext():
    pass

@dataclass(eq=False)
class LoopContext():
    pass

@dataclass(eq=False)
class TryCatchContext():
    finally_entry: ast_node_wrappers.FinallyEntry | None = None   # created up front so raises in the try can reach it
    except_block: list[tuple[ast.ExceptHandler, ast_node_wrappers.ExceptEntry]] = field(default_factory=list)
    raise_reaches_finally: bool = False      # if set, the finally's tails keep propagating the raise


ScopeContext = IfElseContext | FunctionContext | ClassContext | LoopContext | TryCatchContext


class CFGGenerator():
    def __init__(self, ast: ast.AST, cfg: "ControlFlowGraph") -> None:
        self.cfg = cfg
        self.ast = ast
        self.scope_stack: list[ScopeContext] = []

    def make_graph(self) -> None:
        self._dfs(self.ast, ast_node_wrappers.ModuleEntry())

    _BODY_KIND_BY_ENTRY_TYPE = {
        ast_node_wrappers.ModuleEntry: (ast_node_wrappers.ModuleBody),
        ast_node_wrappers.IfEntry: (ast_node_wrappers.IfBody),
        ast_node_wrappers.ElseEntry: (ast_node_wrappers.ElseBody),
        ast_node_wrappers.ForEntry: (ast_node_wrappers.ForBody),
        ast_node_wrappers.WhileEntry: (ast_node_wrappers.WhileBody),
        ast_node_wrappers.TryEntry: (ast_node_wrappers.TryBody),
        ast_node_wrappers.ExceptEntry: (ast_node_wrappers.ExceptBody),
        ast_node_wrappers.FinallyEntry: (ast_node_wrappers.FinallyBody),
        ast_node_wrappers.FunctionDefinitionEntry: (ast_node_wrappers.FunctionBody),
        ast_node_wrappers.ClassDefinitionEntry: (ast_node_wrappers.ClassBody),
        ast_node_wrappers.CaseEntry: (ast_node_wrappers.CaseBody),
    }
    _EXIT_KIND_BY_ENTRY_TYPE = {
        ast_node_wrappers.ModuleEntry: (ast_node_wrappers.ExitKind.MODULE),
        ast_node_wrappers.IfEntry: (ast_node_wrappers.ExitKind.IF),
        ast_node_wrappers.ElseEntry: (ast_node_wrappers.ExitKind.ELSE),
        ast_node_wrappers.ForEntry: (ast_node_wrappers.ExitKind.FOR),
        ast_node_wrappers.WhileEntry: (ast_node_wrappers.ExitKind.WHILE),
        ast_node_wrappers.TryEntry: (ast_node_wrappers.ExitKind.TRY),
        ast_node_wrappers.ExceptEntry: (ast_node_wrappers.ExitKind.EXCEPT),
        ast_node_wrappers.FinallyEntry: (ast_node_wrappers.ExitKind.FINALLY),
        ast_node_wrappers.FunctionDefinitionEntry: (ast_node_wrappers.ExitKind.FUNCTION_DEFINITION),
        ast_node_wrappers.ClassDefinitionEntry: (ast_node_wrappers.ExitKind.CLASS_DEFINITION),
        ast_node_wrappers.CaseEntry: (ast_node_wrappers.ExitKind.CASE),
    }

    def _get_body_type(self, parent: ast.AST) -> type[ast_node_wrappers.Body]:
        return self._BODY_KIND_BY_ENTRY_TYPE[type(parent)]

    def _get_exit_kind(self, parent: ast.AST) -> ast_node_wrappers.ExitKind:
        return self._EXIT_KIND_BY_ENTRY_TYPE[type(parent)]

    def _link_raise(self, node: ast.AST) -> None:
        """
        Links a raising node to wherever its exception could go next, walking outward:
        every handler of each enclosing try, then that try's finally if it has one.

        A finally stops the walk: an uncaught exception runs the finally first, and the
        finally's tails carry it further outward (see the Try case).

        Where a raise goes, depending on where it sits in a try:

        1. Raise in the try body (scope_stack has try_catch_context: handlers + finally)
           - with finally:    -> every handler of this try + this try's finally, stop
           - without finally: -> every handler of this try, then keep walking outward
                                 to the enclosing try's handlers (+ its finally) ...

        2. Raise in an except body (scope_stack has handler_context: no handlers, so
           sibling handlers are never linked)
           - with finally:    -> this try's finally only, stop
           - without finally: -> nothing at this level, keep walking outward
                                 to the enclosing try's handlers (+ its finally) ...

        3. Raise in the finally body (this try's contexts are already popped)
           -> straight to the enclosing try's handlers (+ its finally) ...

        Separately, if any raise reached a finally, that finally's tails are passed
        through here too, so the exception continues outward once the finally has run.
        The walk always stops at a function boundary.
        """
        for i in range(len(self.scope_stack)-1, -1, -1):
            # Stop at the function boundary: a function body's raise propagates to its
            # call site, not to the try blocks lexically around the def
            if isinstance(self.scope_stack[i], FunctionContext):
                break

            if isinstance(self.scope_stack[i], TryCatchContext):
                try_catch_context = self.scope_stack[i]
                for (_, exception_entry) in try_catch_context.except_block:
                    self.cfg.insert(node, exception_entry)

                if try_catch_context.finally_entry is not None:
                    self.cfg.insert(node, try_catch_context.finally_entry)
                    try_catch_context.raise_reaches_finally = True
                    break

    def _create_body(self, stmts: list[ast.stmt], body_type: type[ast_node_wrappers.Body]) -> ast_node_wrappers.Body:
        return body_type(
            body=stmts,
            lineno=stmts[0].lineno,
            col_offset=stmts[0].col_offset,
            end_lineno=stmts[-1].end_lineno,
            end_col_offset=stmts[-1].end_col_offset,
        )

    def _dfs(self, ast_node: ast.AST, parent: ast.AST | None = None) -> list[ast.AST]:
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
        This is why the recursion generalizes cleanly. _dfs() never needs to know whether
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
                    func_entry = ast_node_wrappers.FunctionDefinitionEntry(
                        body=[func_assign],
                        lineno=func_assign.lineno,
                        col_offset=func_assign.col_offset,
                        end_lineno=func_assign.end_lineno,
                        end_col_offset=func_assign.end_col_offset,
                    )

                    cfg_nodes.append([func_entry])

                    func_body = ast_node_wrappers.FunctionBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )

                    self.scope_stack.append(FunctionContext())
                    self._dfs(func_body, parent=func_entry)
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
                    class_entry = ast_node_wrappers.ClassDefinitionEntry(
                        body=[class_assign],
                        lineno=class_assign.lineno,
                        col_offset=class_assign.col_offset,
                        end_lineno=class_assign.end_lineno,
                        end_col_offset=class_assign.end_col_offset,
                    )


                    cfg_nodes.append([class_entry])
                    class_body = ast_node_wrappers.ClassBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )

                    self.scope_stack.append(ClassContext())
                    tail = self._dfs(class_body, parent=class_entry)
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
                    
                    if_else_entry = ast_node_wrappers.IfElseEntry()
                    cfg_nodes.append([if_else_entry])

                    self.scope_stack.append(IfElseContext())
                    if_entry = ast_node_wrappers.IfEntry()
                    if_body = ast_node_wrappers.IfBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    if_tail = self._dfs(if_body, parent=if_entry)

                    else_entry = ast_node_wrappers.ElseEntry()
                    if cur_node.orelse:
                        else_body = ast_node_wrappers.ElseBody(
                            body=cur_node.orelse,
                            lineno=cur_node.orelse[0].lineno,
                            col_offset=cur_node.orelse[0].col_offset,
                            end_lineno=cur_node.orelse[-1].end_lineno,
                            end_col_offset=cur_node.orelse[-1].end_col_offset,
                        )
                    else:
                        # the dummy node inside gets returned
                        else_body = ast_node_wrappers.ElseBody(body=[ast_node_wrappers.ElseBody()])
                    else_tail = self._dfs(else_body, parent=else_entry)
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
                    
                    while_loop_entry = ast_node_wrappers.WhileLoopEntry()
                    cfg_nodes.append([while_loop_entry])

                    self.scope_stack.append(LoopContext())
                    while_entry = ast_node_wrappers.WhileEntry()
                    while_body = ast_node_wrappers.WhileBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    while_tail = self._dfs(while_body, parent=while_entry)

                    else_entry = ast_node_wrappers.ElseEntry()
                    else_body = ast_node_wrappers.ElseBody(body=[ast_node_wrappers.ElseBody()])
                    else_tail = self._dfs(else_body, parent=else_entry)
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
                    
                    for_loop_entry = ast_node_wrappers.ForLoopEntry()
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
                    for_entry = ast_node_wrappers.ForEntry(
                        body=[for_assign],
                        lineno=for_assign.lineno,
                        col_offset=for_assign.col_offset,
                        end_lineno=for_assign.end_lineno,
                        end_col_offset=for_assign.end_col_offset,
                    )
                    for_body = ast_node_wrappers.ForBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    )
                    for_tail = self._dfs(for_body, parent=for_entry)

                    else_entry = ast_node_wrappers.ElseEntry()
                    else_body = ast_node_wrappers.ElseBody(body=[ast_node_wrappers.ElseBody()])
                    else_tail = self._dfs(else_body, parent=else_entry)
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
                    
                    try_except_entry = ast_node_wrappers.TryExceptBranchEntry()
                    cfg_nodes.append([try_except_entry])

                    # Only the try body runs inside this context. Handlers are parsed
                    # outside it, so a raise in an except body propagates outward instead
                    # of being caught by its sibling handlers.
                    finally_entry = ast_node_wrappers.FinallyEntry() if cur_node.finalbody else None
                    try_catch_context = TryCatchContext(finally_entry)
                    # Handler bodies don't see their siblings, but a raise inside one
                    # still runs this try's finally before propagating outward.
                    handler_context = TryCatchContext(finally_entry)
                    try_except_tails = []
                    try_except_entries = []
                    for handler in cur_node.handlers:
                        except_entry = ast_node_wrappers.ExceptEntry()
                        except_body = ast_node_wrappers.ExceptBody(
                            body=handler.body,
                            lineno=handler.body[0].lineno,
                            col_offset=handler.body[0].col_offset,
                            end_lineno=handler.body[-1].end_lineno,
                            end_col_offset=handler.body[-1].end_col_offset,
                        )
                        
                        # Ensure its not a bare except
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

                        self.scope_stack.append(handler_context)
                        new_tails=self._dfs(except_body, parent=except_entry)
                        self.scope_stack.pop()
                        try_except_tails +=new_tails
                        try_except_entries.append(except_entry)

                        # Store (handler, node_ref). The handler is kept unresolved so
                        # the type layer can inspect handler.type when pruning raise edges.
                        try_catch_context.except_block.append((handler, except_entry))

                    try_entry = ast_node_wrappers.TryEntry()
                    try_body = ast_node_wrappers.TryBody(
                        body=cur_node.body,
                        lineno=cur_node.body[0].lineno,
                        col_offset=cur_node.body[0].col_offset,
                        end_lineno=cur_node.body[-1].end_lineno,
                        end_col_offset=cur_node.body[-1].end_col_offset,
                    ) 
                    self.scope_stack.append(try_catch_context)
                    try_tail = self._dfs(try_body, parent=try_entry)
                    self.scope_stack.pop()
                    try_except_entries.append(try_entry)

                    cfg_nodes.append(try_except_entries)
                    try_except_tails+=try_tail
                    cfg_nodes.append(try_except_tails)

                    for tail_node in try_except_tails:
                        for entry_node in try_except_entries:
                            skip.add((entry_node, tail_node))

                    if cur_node.finalbody:
                        cfg_nodes.append([finally_entry])
                        finally_body = ast_node_wrappers.FinallyBody(
                            body=cur_node.finalbody,
                            lineno=cur_node.finalbody[0].lineno,
                            col_offset=cur_node.finalbody[0].col_offset,
                            end_lineno=cur_node.finalbody[-1].end_lineno,
                            end_col_offset=cur_node.finalbody[-1].end_col_offset,
                        )
                        # All the tails of the try_except_block point to the finally's first block
                        finally_tails = self._dfs(finally_body, finally_entry)
                        cfg_nodes.append(finally_tails)
                        for finally_tail in finally_tails:
                            skip.add((finally_entry, finally_tail))

                        # An uncaught raise ran this finally, so it carries on outward from here.
                        # The tails still flow to the next code too (over-approximation).
                        if try_catch_context.raise_reaches_finally or handler_context.raise_reaches_finally:
                            for finally_tail in finally_tails:
                                self._link_raise(finally_tail)
                    l = r+1
                
                case ast.Match():
                    if r > l:
                        stmts = code_body[l:r]
                        cfg_nodes.append([CustomBody(
                            body=stmts,
                            lineno=stmts[0].lineno,
                            col_offset=stmts[0].col_offset,
                            end_lineno=stmts[-1].end_lineno,
                            end_col_offset=stmts[-1].end_col_offset,
                        )])

                    # match <subject>: the subject is evaluated once, before any case is tried
                    subject = cur_node.subject
                    match_entry = ast_node_wrappers.MatchEntry(
                        body=[ast.Expr(
                            value=subject,
                            lineno=subject.lineno,
                            col_offset=subject.col_offset,
                            end_lineno=subject.end_lineno,
                            end_col_offset=subject.end_col_offset,
                        )],
                        lineno=subject.lineno,
                        col_offset=subject.col_offset,
                        end_lineno=subject.end_lineno,
                        end_col_offset=subject.end_col_offset,
                    )
                    cfg_nodes.append([match_entry])

                    case_entries = []
                    case_tails = []
                    for case_node in cur_node.cases:
                        # case ... if <guard>: the guard is the expr evaluated on entry to this case
                        if case_node.guard is not None:
                            guard = case_node.guard
                            case_entry = ast_node_wrappers.CaseEntry(
                                body=[ast.Expr(
                                    value=guard,
                                    lineno=guard.lineno,
                                    col_offset=guard.col_offset,
                                    end_lineno=guard.end_lineno,
                                    end_col_offset=guard.end_col_offset,
                                )],
                                lineno=guard.lineno,
                                col_offset=guard.col_offset,
                                end_lineno=guard.end_lineno,
                                end_col_offset=guard.end_col_offset,
                            )
                        else:
                            pattern = case_node.pattern
                            case_entry = ast_node_wrappers.CaseEntry(
                                body=[],
                                lineno=pattern.lineno,
                                col_offset=pattern.col_offset,
                                end_lineno=pattern.end_lineno,
                                end_col_offset=pattern.end_col_offset,
                            )

                        case_body = ast_node_wrappers.CaseBody(
                            body=case_node.body,
                            lineno=case_node.body[0].lineno,
                            col_offset=case_node.body[0].col_offset,
                            end_lineno=case_node.body[-1].end_lineno,
                            end_col_offset=case_node.body[-1].end_col_offset,
                        )
                        tail = self._dfs(case_body, parent=case_entry)
                        case_entries.append(case_entry)
                        case_tails += tail

                    cfg_nodes.append(case_entries)
                    cfg_nodes.append(case_tails)
                    for tail_node in case_tails:
                        for entry_node in case_entries:
                            skip.add((entry_node, tail_node))
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
                    cur_node = CustomBody(
                        body=stmts,
                        lineno=stmts[0].lineno,
                        col_offset=stmts[0].col_offset,
                        end_lineno=stmts[-1].end_lineno,
                        end_col_offset=stmts[-1].end_col_offset,
                    )
                    cfg_nodes.append([cur_node])

                    """
                    Link the raise to EVERY handler of each enclosing try, plus the nearest
                    finally for the uncaught case (over-approximation, see _link_raise).
                    
                    Deciding which handler actually catches a raise is a type question,
                    not a control flow one, so the CFG doesn't try to answer it:
                      - raise ValueError("msg")   -> exc is a Call, the class is in .func
                      - raise errors.MyErr        -> exc is an Attribute, so which module's MyErr?
                      - bare `raise`              -> re-raises whatever is currently being handled
                      - except (A, B)             -> a Tuple of classes, each needing resolution
                      - subclasses                -> `except LookupError` catches KeyError, and
                                                     `class MyErr(ValueError)` needs its bases resolved
                    Even a plain `raise ValueError` is a guess, since the name may be shadowed.
                    
                    So the CFG keeps every edge that COULD happen, the same way it keeps both
                    arms of an if. The type layer later ignores the edges that can't happen
                    (it reaches the raise before its handlers in topological order). Edges are
                    only ever removed after this point, never added.
                    """
                    
                    self._link_raise(cur_node)

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
        
        exit_node = ast_node_wrappers.Exit(kind =  self._get_exit_kind(parent))
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
    from control_flow_graph import ControlFlowGraph

    with open("tests/cfg_graph_test_cases/func_def.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    cfg = ControlFlowGraph(tree)
    cfg._pretty_print()

