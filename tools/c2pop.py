#!/usr/bin/env python3
"""
CPOP MVP compiler: restricted C subset -> canonical POP C.

Subset:
- optional enum { ... } declarations (for tape indexes/constants)
- one tape declaration: signed/unsigned char d[N] = {...};
- one loop: while (d[0]) { ... }
- loop statements:
  - pop_read_byte(IDX); or pop_read_byte(d[IDX]);  # optional, any number, first
  - d[IDX] = <expr>;
  - pop_print_if(<expr>, "literal");
  - pop_print("literal");

Expression support for assignments and print gates:
- arithmetic: +, -, *
- bitwise: &, |, ^, <<, >>
- unary: +, -, ~
- comparisons: ==, !=, <, <=, >, >= (result is 0/1, hybrid mode only)
- parentheses, integer constants, enum constants, d[IDX]

Optional enforcement:
- --vm-pure rejects any per-tick C-evaluated expression in assignments/print gates
  (only raw tape bytes or integer constants are allowed there)
- --vm-pure-backend micro (experimental) tries boolean expression lowering
  into printf-side micro-ops (rejects read-after-write dependencies in one tick)
- --vm-pure-backend phase (experimental) executes one source statement per
  runtime phase to preserve read-after-write semantics
- --vm-pure-backend vm (experimental) lowers boolean/state expressions into
  printf-side micro-phases (no C expression evaluation), writing VM_PC_LO/HI
  and vm_fmt pointer bytes via %hhn; currently limited to 65536 phases
- non-vm-pure backend may use C-side write-delta construction (%w[i]-%w[i-1]);
  vm-pure backend uses counter-reset writes instead
"""

from __future__ import annotations

import argparse
import ast
import copy
import ctypes
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


class CompileError(Exception):
    pass


@dataclass
class AssignStmt:
    target: int
    expr: ast.AST
    original: str


@dataclass
class PrintIfStmt:
    gate: ast.AST
    text_lit: str
    original: str


@dataclass
class PrintStmt:
    text_lit: str
    original: str


@dataclass
class InputStmt:
    target: int
    original: str


Stmt = AssignStmt | PrintIfStmt | PrintStmt | InputStmt


@dataclass
class Program:
    src_path: pathlib.Path
    tape_size: int
    init_bytes: List[int]
    run_idx: int
    input_idxs: List[int]
    purity_mode: str
    vm_pure: bool
    vm_pure_backend: str
    has_hybrid_expr: bool
    has_c_eval_expr: bool
    has_c_input_semantics: bool
    index_names: Dict[int, str]
    constants: Dict[str, int]
    loop_stmts: List[Stmt]


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//.*", "", src)
    return src


def parse_int_token(tok: str) -> int:
    tok = tok.strip()
    if re.fullmatch(r"'.'", tok):
        return ord(tok[1])
    if tok.startswith("'") and tok.endswith("'") and len(tok) >= 4 and tok[1] == "\\":
        esc = tok[2:-1]
        val = bytes(esc, "utf-8").decode("unicode_escape")
        if len(val) != 1:
            raise CompileError(f"invalid char literal: {tok}")
        return ord(val)
    try:
        return int(tok, 0)
    except ValueError as exc:
        raise CompileError(f"invalid integer literal: {tok}") from exc


def split_commas(s: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    depth = 0
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            cur.append(ch)
            continue
        if ch == '(':
            depth += 1
            cur.append(ch)
            continue
        if ch == ')':
            depth = max(0, depth - 1)
            cur.append(ch)
            continue
        if ch == ',' and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        out.append(tail)
    return out


def split_statements(block: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    depth = 0
    in_str = False
    esc = False
    for ch in block:
        if in_str:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            cur.append(ch)
            continue
        if ch == '(':
            depth += 1
            cur.append(ch)
            continue
        if ch == ')':
            depth = max(0, depth - 1)
            cur.append(ch)
            continue
        if ch == ';' and depth == 0:
            st = "".join(cur).strip()
            if st:
                out.append(st)
            cur = []
            continue
        cur.append(ch)
    trail = "".join(cur).strip()
    if trail:
        out.append(trail)
    return out


def parse_enums(src: str) -> Tuple[Dict[str, int], Dict[int, str]]:
    constants: Dict[str, int] = {}
    index_names: Dict[int, str] = {}
    enum_pat = re.compile(r"enum\s*\{(.*?)\}\s*;", flags=re.S)
    for m in enum_pat.finditer(src):
        body = m.group(1)
        value = 0
        for item in split_commas(body):
            if not item:
                continue
            if "=" in item:
                lhs, rhs = item.split("=", 1)
                name = lhs.strip()
                value = parse_int_token(rhs.strip())
            else:
                name = item.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise CompileError(f"invalid enum identifier: {name}")
            constants[name] = value
            if value not in index_names:
                index_names[value] = name
            value += 1
    return constants, index_names


def parse_tape(src: str) -> Tuple[int, List[int]]:
    m = re.search(
        r"(?:signed|unsigned)\s+char\s+d\s*\[\s*(\d+)\s*\]\s*=\s*\{(.*?)\}\s*;",
        src,
        flags=re.S,
    )
    if not m:
        raise CompileError("missing tape declaration: signed/unsigned char d[N] = {...};")
    n = int(m.group(1))
    vals = [parse_int_token(x) for x in split_commas(m.group(2))] if m.group(2).strip() else []
    if len(vals) > n:
        raise CompileError(f"too many tape initializers ({len(vals)} > {n})")
    vals.extend([0] * (n - len(vals)))
    vals = [((v + 128) % 256) - 128 for v in vals]
    return n, vals


def resolve_idx(name_or_num: str, constants: Dict[str, int]) -> int:
    t = name_or_num.strip()
    if re.fullmatch(r"\d+", t):
        return int(t)
    if t in constants:
        return constants[t]
    raise CompileError(f"unknown tape index '{t}'")


def replace_d_refs(expr: str, constants: Dict[str, int]) -> str:
    def repl(m: re.Match[str]) -> str:
        idx_txt = m.group(1)
        idx = resolve_idx(idx_txt, constants)
        return f"v_{idx}"

    return re.sub(r"d\s*\[\s*([^\]]+)\s*\]", repl, expr)


def validate_expr_ast(node: ast.AST, constants: Dict[str, int], allow_hybrid_ops: bool) -> None:
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, int):
            raise CompileError("only integer constants are supported in expressions")
        return
    if isinstance(node, ast.Name):
        if node.id.startswith("v_") and node.id[2:].isdigit():
            return
        if node.id in constants:
            return
        raise CompileError(f"unknown identifier in expression: {node.id}")
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert)):
            raise CompileError("unsupported unary operator in expression")
        validate_expr_ast(node.operand, constants, allow_hybrid_ops)
        return
    if isinstance(node, ast.BinOp):
        if not isinstance(
            node.op,
            (ast.Add, ast.Sub, ast.Mult, ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift),
        ):
            raise CompileError("unsupported binary operator in expression")
        validate_expr_ast(node.left, constants, allow_hybrid_ops)
        validate_expr_ast(node.right, constants, allow_hybrid_ops)
        return
    if isinstance(node, ast.Compare):
        if not allow_hybrid_ops:
            raise CompileError("comparison operators require --purity hybrid")
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise CompileError("only single comparisons are supported in expressions")
        if not isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
            raise CompileError("unsupported comparison operator in expression")
        validate_expr_ast(node.left, constants, allow_hybrid_ops)
        validate_expr_ast(node.comparators[0], constants, allow_hybrid_ops)
        return
    if isinstance(node, ast.BoolOp):
        if not allow_hybrid_ops:
            raise CompileError("boolean operators require --purity hybrid")
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise CompileError("unsupported boolean operator in expression")
        for v in node.values:
            validate_expr_ast(v, constants, allow_hybrid_ops)
        return
    raise CompileError("unsupported expression form")


def parse_expr(expr: str, constants: Dict[str, int], allow_hybrid_ops: bool) -> ast.AST:
    rewritten = replace_d_refs(expr, constants)
    try:
        tree = ast.parse(rewritten, mode="eval")
    except SyntaxError as exc:
        raise CompileError(f"invalid expression syntax: {expr}") from exc
    validate_expr_ast(tree.body, constants, allow_hybrid_ops)
    return tree.body


def collect_expr_indices(node: ast.AST) -> List[int]:
    out: List[int] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id.startswith("v_") and n.id[2:].isdigit():
            out.append(int(n.id[2:]))
    return out


def expr_uses_hybrid(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, (ast.Compare, ast.BoolOp)):
            return True
    return False


def expr_needs_c_eval(node: ast.AST) -> bool:
    # "Raw tape read" expressions are considered VM-pure at callsite level.
    # Any operator/composition means C evaluates semantics each tick.
    if isinstance(node, ast.Constant):
        return False
    if isinstance(node, ast.Name):
        return False
    return True


def expr_is_raw_byte_or_const(node: ast.AST) -> bool:
    return isinstance(node, (ast.Constant, ast.Name))


def expr_is_vm_bool_lowerable(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Constant):
        return isinstance(node.value, int)
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, (ast.BitOr, ast.BitAnd, ast.BitXor)):
            return expr_is_vm_bool_lowerable(node.left) and expr_is_vm_bool_lowerable(node.right)
        if isinstance(node.op, ast.Sub):
            terms = _bool_terms_from_sub(node)
            if terms is None:
                return False
            return all(expr_is_vm_bool_lowerable(t) for t in terms)
    return False


def vm_backend_blocker_reason(node: ast.AST) -> str:
    if expr_is_raw_byte_or_const(node):
        return ""
    if not expr_is_vm_bool_lowerable(node):
        return (
            "vm backend currently supports only boolean/state forms "
            "(constants, d[idx], |, &, ^, and subtraction chains rooted at 1)"
        )
    return ""


def vm_pure_blocker_reason(node: ast.AST) -> str:
    """Explain why an expression cannot be lowered by the current vm-pure backend."""
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.BitAnd):
            return (
                "bitwise AND requires non-linear combination; with one printf call, "
                "varargs are pre-evaluated and intermediate %hhn writes cannot feed later widths"
            )
        if isinstance(node.op, ast.BitOr):
            return (
                "bitwise OR requires non-linear combination; with one printf call, "
                "varargs are pre-evaluated and intermediate %hhn writes cannot feed later widths"
            )
        if isinstance(node.op, ast.BitXor):
            return (
                "bitwise XOR requires non-linear combination; with one printf call, "
                "varargs are pre-evaluated and intermediate %hhn writes cannot feed later widths"
            )
        if isinstance(node.op, (ast.Mult, ast.LShift, ast.RShift)):
            return (
                "operator is non-linear in vm-pure backend; one-call printf lowering only supports "
                "raw-byte/constant argument use without C-side expression evaluation"
            )
    if isinstance(node, ast.Compare):
        return (
            "comparisons require branch semantics; current vm-pure backend forbids C-evaluated branching"
        )
    if isinstance(node, ast.BoolOp):
        return (
            "boolean operators require branch semantics; current vm-pure backend forbids C-evaluated branching"
        )
    if isinstance(node, (ast.UnaryOp, ast.BinOp)):
        return (
            "expression needs C-side evaluation in current backend; one-call printf cannot reuse "
            "intermediate %hhn results as later width/precision arguments"
        )
    return "expression form is not lowerable by current vm-pure backend"


def expr_refs_any(node: ast.AST, idxs: set[int]) -> bool:
    for i in collect_expr_indices(node):
        if i in idxs:
            return True
    return False


def detect_host_snapshot_input(parsed: Program) -> bool:
    """
    Heuristic for Gate-E host-driven snapshots:
    - more than one raw input byte per tick, and
    - loop body never combines those inputs with persistent VM state.

    If we observe any non-input state computation (including constants written
    to non-input cells, or gates that read non-input cells), we treat the loop
    as VM-driven (not host snapshot).
    """
    input_set = set(parsed.input_idxs)
    if len(input_set) <= 1:
        return False

    for st in parsed.loop_stmts:
        if isinstance(st, AssignStmt):
            if st.target in input_set:
                continue
            refs = set(collect_expr_indices(st.expr))
            # Constant writes or reads from non-input bytes indicate in-VM logic.
            if not refs or any(i not in input_set for i in refs):
                return False
            continue
        if isinstance(st, PrintIfStmt):
            refs = set(collect_expr_indices(st.gate))
            if any(i not in input_set for i in refs):
                return False

    return True


def expr_replace_idx(node: ast.AST, src_idx: int, dst_idx: int) -> ast.AST:
    out = copy.deepcopy(node)
    src_name = f"v_{src_idx}"
    dst_name = f"v_{dst_idx}"
    for n in ast.walk(out):
        if isinstance(n, ast.Name) and n.id == src_name:
            n.id = dst_name
    return out


def expr_ast_to_c(node: ast.AST, env: Dict[int, str], constants: Dict[str, int]) -> str:
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, int):
            raise CompileError("only integer constants are supported in expressions")
        return str(int(node.value))
    if isinstance(node, ast.Name):
        if node.id.startswith("v_") and node.id[2:].isdigit():
            idx = int(node.id[2:])
            if idx not in env:
                raise CompileError(f"internal error: missing env value for d[{idx}]")
            return env[idx]
        if node.id in constants:
            return str(constants[node.id])
        raise CompileError(f"unknown identifier in expression: {node.id}")
    if isinstance(node, ast.UnaryOp):
        inner = expr_ast_to_c(node.operand, env, constants)
        if isinstance(node.op, ast.USub):
            return f"(-({inner}))"
        if isinstance(node.op, ast.UAdd):
            return f"(+({inner}))"
        if isinstance(node.op, ast.Invert):
            return f"(~({inner}))"
        raise CompileError("unsupported unary operator in expression")
    if isinstance(node, ast.BinOp):
        left = expr_ast_to_c(node.left, env, constants)
        right = expr_ast_to_c(node.right, env, constants)
        op_map = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.BitAnd: "&",
            ast.BitOr: "|",
            ast.BitXor: "^",
            ast.LShift: "<<",
            ast.RShift: ">>",
        }
        for klass, op_str in op_map.items():
            if isinstance(node.op, klass):
                return f"(({left}) {op_str} ({right}))"
        raise CompileError("unsupported binary operator in expression")
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise CompileError("only single comparisons are supported in expressions")
        left = expr_ast_to_c(node.left, env, constants)
        right = expr_ast_to_c(node.comparators[0], env, constants)
        op_map = {
            ast.Eq: "==",
            ast.NotEq: "!=",
            ast.Lt: "<",
            ast.LtE: "<=",
            ast.Gt: ">",
            ast.GtE: ">=",
        }
        for klass, op_str in op_map.items():
            if isinstance(node.ops[0], klass):
                return f"(({left}) {op_str} ({right}))"
        raise CompileError("unsupported comparison operator in expression")
    if isinstance(node, ast.BoolOp):
        values = [expr_ast_to_c(v, env, constants) for v in node.values]
        if isinstance(node.op, ast.And):
            joined = " && ".join(f"(({v}) != 0)" for v in values)
            return f"({joined})"
        if isinstance(node.op, ast.Or):
            joined = " || ".join(f"(({v}) != 0)" for v in values)
            return f"({joined})"
        raise CompileError("unsupported boolean operator in expression")
    raise CompileError("unsupported expression form")


def parse_while(
    src: str, constants: Dict[str, int], allow_hybrid_ops: bool
) -> Tuple[int, List[int], List[Stmt]]:
    m = re.search(r"while\s*\(\s*d\s*\[\s*([^\]]+)\s*\]\s*\)\s*\{(.*?)\}", src, flags=re.S)
    if not m:
        raise CompileError("missing while (d[RUN]) { ... } loop")
    run_idx = resolve_idx(m.group(1), constants)
    body = m.group(2)
    stmts: List[Stmt] = []
    input_idxs: List[int] = []
    seen_inputs: set[int] = set()
    saw_print = False
    saw_non_input = False
    for raw in split_statements(body):
        st = raw.strip()
        if not st:
            continue

        im = re.fullmatch(r"pop_read_byte\s*\((.*)\)", st, flags=re.S)
        if im:
            if saw_non_input:
                raise CompileError("pop_read_byte must appear before assignments/prints in loop body")
            arg = im.group(1).strip()
            dref = re.fullmatch(r"d\s*\[\s*([^\]]+)\s*\]", arg)
            if dref:
                target = resolve_idx(dref.group(1), constants)
            else:
                target = resolve_idx(arg, constants)
            if target in seen_inputs:
                raise CompileError(f"duplicate pop_read_byte target d[{target}] in loop")
            seen_inputs.add(target)
            input_idxs.append(target)
            stmts.append(InputStmt(target=target, original=st + ";"))
            continue

        am = re.fullmatch(r"d\s*\[\s*([^\]]+)\s*\]\s*=\s*(.+)", st, flags=re.S)
        if am:
            saw_non_input = True
            if saw_print:
                raise CompileError(
                    "assignments must come before pop_print/pop_print_if in loop body"
                )
            target = resolve_idx(am.group(1), constants)
            expr = parse_expr(am.group(2).strip(), constants, allow_hybrid_ops)
            stmts.append(AssignStmt(target=target, expr=expr, original=st + ";"))
            continue

        pim = re.fullmatch(r"pop_print_if\s*\((.*)\)", st, flags=re.S)
        if pim:
            saw_non_input = True
            saw_print = True
            args = split_commas(pim.group(1))
            if len(args) != 2:
                raise CompileError(f"pop_print_if expects 2 args: {st}")
            gate = parse_expr(args[0], constants, allow_hybrid_ops)
            lit = args[1].strip()
            if not re.fullmatch(r'"(?:[^"\\]|\\.)*"', lit):
                raise CompileError(f"pop_print_if second arg must be string literal: {st}")
            stmts.append(PrintIfStmt(gate=gate, text_lit=lit, original=st + ";"))
            continue

        pm = re.fullmatch(r"pop_print\s*\((.*)\)", st, flags=re.S)
        if pm:
            saw_non_input = True
            saw_print = True
            args = split_commas(pm.group(1))
            if len(args) != 1:
                raise CompileError(f"pop_print expects 1 arg: {st}")
            lit = args[0].strip()
            if not re.fullmatch(r'"(?:[^"\\]|\\.)*"', lit):
                raise CompileError(f"pop_print arg must be string literal: {st}")
            stmts.append(PrintStmt(text_lit=lit, original=st + ";"))
            continue

        raise CompileError(f"unsupported loop statement: {st}")

    if not stmts:
        raise CompileError("empty loop body")
    return run_idx, input_idxs, stmts


def c_u8(expr_c: str) -> str:
    return f"((unsigned)((unsigned char)({expr_c})))"


def analyze_program(
    parsed: Program,
) -> Tuple[List[Tuple[int, str, str]], List[Tuple[str, str | None, str, str]]]:
    env: Dict[int, str] = {i: f"(int)(unsigned char)d[{i}]" for i in range(parsed.tape_size)}
    writes: List[Tuple[int, str, str]] = []
    render_ops: List[Tuple[str, str | None, str, str]] = []

    for st in parsed.loop_stmts:
        if isinstance(st, InputStmt):
            # Input is staged in generated loop control before each printf tick.
            continue
        if isinstance(st, AssignStmt):
            resolved = expr_ast_to_c(st.expr, env, parsed.constants)
            env[st.target] = resolved
            writes.append((st.target, resolved, st.original))
        elif isinstance(st, PrintIfStmt):
            gate = expr_ast_to_c(st.gate, env, parsed.constants)
            render_ops.append(("if", gate, st.text_lit, st.original))
        elif isinstance(st, PrintStmt):
            render_ops.append(("plain", None, st.text_lit, st.original))

    return writes, render_ops


def parse_source(path: pathlib.Path, purity_mode: str, vm_pure: bool, vm_pure_backend: str) -> Program:
    raw = path.read_text(encoding="utf-8")
    src = strip_comments(raw)
    constants, index_names = parse_enums(src)
    tape_size, init_bytes = parse_tape(src)
    allow_hybrid_ops = purity_mode == "hybrid"
    run_idx, input_idxs, loop_stmts = parse_while(src, constants, allow_hybrid_ops)

    if run_idx != 0:
        raise CompileError(
            f"RUN byte must be d[0] for canonical POP loop while(*d), found d[{run_idx}]"
        )

    for idx in range(tape_size):
        if idx not in index_names:
            index_names[idx] = f"IDX_{idx}"

    # Validate that all referenced indices are in tape bounds.
    def check_expr(node: ast.AST, context: str) -> None:
        for i in collect_expr_indices(node):
            if i < 0 or i >= tape_size:
                raise CompileError(
                    f"tape index d[{i}] out of bounds in {context} (tape size {tape_size})"
                )

    has_hybrid_expr = False
    has_c_eval_expr = False
    has_c_input_semantics = False
    input_targets: set[int] = set()

    if vm_pure and vm_pure_backend == "micro":
        # In a single printf call, all varargs are evaluated before formatting.
        # So any expression reading bytes assigned earlier in the same source tick
        # would observe stale pre-tick values and break semantics.
        assigned_so_far: set[int] = set()
        for st in loop_stmts:
            if isinstance(st, InputStmt):
                continue
            if isinstance(st, AssignStmt):
                refs = set(collect_expr_indices(st.expr))
                hazards = sorted(refs & assigned_so_far)
                if hazards:
                    hazards_txt = ", ".join(f"d[{i}]" for i in hazards)
                    raise CompileError(
                        "vm-pure micro backend cannot lower read-after-write dependency in one tick: "
                        + st.original
                        + " (reads "
                        + hazards_txt
                        + " assigned earlier in loop; single-call printf pre-evaluates varargs)"
                    )
                assigned_so_far.add(st.target)
                continue
            if isinstance(st, PrintIfStmt):
                refs = set(collect_expr_indices(st.gate))
                hazards = sorted(refs & assigned_so_far)
                if hazards:
                    hazards_txt = ", ".join(f"d[{i}]" for i in hazards)
                    raise CompileError(
                        "vm-pure micro backend cannot lower print gate with read-after-write dependency: "
                        + st.original
                        + " (reads "
                        + hazards_txt
                        + " assigned earlier in loop; single-call printf pre-evaluates varargs)"
                    )

    for st in loop_stmts:
        if isinstance(st, InputStmt):
            if st.target < 0 or st.target >= tape_size:
                raise CompileError(
                    f"input target d[{st.target}] out of bounds (tape size {tape_size})"
                )
            input_targets.add(st.target)

    for st in loop_stmts:
        if isinstance(st, InputStmt):
            continue
        elif isinstance(st, AssignStmt):
            if st.target < 0 or st.target >= tape_size:
                raise CompileError(
                    f"assignment target d[{st.target}] out of bounds (tape size {tape_size})"
                )
            check_expr(st.expr, st.original)
            has_hybrid_expr = has_hybrid_expr or expr_uses_hybrid(st.expr)
            needs_eval = expr_needs_c_eval(st.expr)
            if vm_pure and vm_pure_backend == "vm":
                why = vm_backend_blocker_reason(st.expr)
                if why:
                    raise CompileError(
                        "vm-pure vm backend cannot lower expression: "
                        + st.original
                        + " ("
                        + why
                        + ")"
                    )
                needs_eval = False
            has_c_eval_expr = has_c_eval_expr or needs_eval
            if vm_pure and vm_pure_backend == "simple" and needs_eval:
                why = vm_pure_blocker_reason(st.expr)
                raise CompileError(
                    "vm-pure mode cannot lower expression: "
                    + st.original
                    + " ("
                    + why
                    + ")"
                )
            if input_targets and expr_refs_any(st.expr, input_targets) and needs_eval:
                has_c_input_semantics = True
                if purity_mode == "strict":
                    raise CompileError(
                        "input semantics in C expression are not allowed in strict mode: "
                        + st.original
                    )
        elif isinstance(st, PrintIfStmt):
            check_expr(st.gate, st.original)
            has_hybrid_expr = has_hybrid_expr or expr_uses_hybrid(st.gate)
            needs_eval = expr_needs_c_eval(st.gate)
            if vm_pure and vm_pure_backend == "vm":
                why = vm_backend_blocker_reason(st.gate)
                if why:
                    raise CompileError(
                        "vm-pure vm backend cannot lower expression: "
                        + st.original
                        + " ("
                        + why
                        + ")"
                    )
                needs_eval = False
            has_c_eval_expr = has_c_eval_expr or needs_eval
            if vm_pure and vm_pure_backend == "simple" and needs_eval:
                why = vm_pure_blocker_reason(st.gate)
                raise CompileError(
                    "vm-pure mode cannot lower expression: "
                    + st.original
                    + " ("
                    + why
                    + ")"
                )
            if input_targets and expr_refs_any(st.gate, input_targets) and needs_eval:
                has_c_input_semantics = True
                if purity_mode == "strict":
                    raise CompileError(
                        "input-driven branch semantics in C are not allowed in strict mode: "
                        + st.original
                    )

    return Program(
        src_path=path,
        tape_size=tape_size,
        init_bytes=init_bytes,
        run_idx=run_idx,
        input_idxs=input_idxs,
        purity_mode=purity_mode,
        vm_pure=vm_pure,
        vm_pure_backend=vm_pure_backend,
        has_hybrid_expr=has_hybrid_expr,
        has_c_eval_expr=has_c_eval_expr,
        has_c_input_semantics=has_c_input_semantics,
        index_names=index_names,
        constants=constants,
        loop_stmts=loop_stmts,
    )


def quote_c_string_for_comment(s: str) -> str:
    return s.replace("*/", "* /")


def _bool_terms_from_sub(node: ast.AST) -> Optional[List[ast.AST]]:
    """Parse chains like 1-a-b-c as [a,b,c]."""
    terms: List[ast.AST] = []
    cur = node
    while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Sub):
        terms.append(cur.right)
        cur = cur.left
    if isinstance(cur, ast.Constant) and isinstance(cur.value, int) and int(cur.value) == 1:
        terms.reverse()
        return terms
    return None


def _flatten_binop(node: ast.AST, op_type: type) -> List[ast.AST]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, op_type):
        return _flatten_binop(node.left, op_type) + _flatten_binop(node.right, op_type)
    return [node]


class VmPureMicroBuilder:
    def __init__(self, parsed: Program):
        self.parsed = parsed
        self.fmt_parts: List[str] = []
        self.args: List[str] = ["z"]
        self.next_pos = 2
        self.prev_written_idx: Optional[int] = None
        self.write_specs: List[Tuple[int, int, str, str]] = []
        self.printif_specs: List[Tuple[int, int, str, str]] = []
        self.print_specs: List[Tuple[int, str, str]] = []
        self.temp_base = parsed.tape_size
        self.temp_next = parsed.tape_size
        self.temp_names: Dict[int, str] = {}
        self.const_zero = self.alloc_temp("CONST_0")
        self.const_one = self.alloc_temp("CONST_1")
        self.count_idx = self.alloc_temp("CNT")
        # Initialize immutable constants in tape.
        self.init_writes: List[Tuple[int, int, str]] = [
            (self.const_zero, 0, "micro-init"),
            (self.const_one, 1, "micro-init"),
            (self.count_idx, 0, "micro-init"),
        ]

    def alloc_temp(self, name: str) -> int:
        idx = self.temp_next
        self.temp_next += 1
        self.temp_names[idx] = name
        return idx

    def _u8_idx(self, idx: int) -> str:
        return c_u8(f"(int)(unsigned char)d[{idx}]")

    def _append_frag(self, frag: str) -> None:
        self.fmt_parts.append(frag)

    def _reset_frag(self) -> Tuple[int, str]:
        if self.prev_written_idx is None:
            return 0, ""
        rpos = self.next_pos
        self.next_pos += 1
        self.args.append(f"r + {self._u8_idx(self.prev_written_idx)}")
        return rpos, f"%{rpos}$s"

    def _emit_linear_write(
        self,
        target: int,
        byte_terms: List[int],
        const_terms: List[int],
        src_stmt: str,
    ) -> None:
        rpos, frag = self._reset_frag()
        arg_notes: List[str] = []
        for idx in byte_terms:
            wpos = self.next_pos
            self.next_pos += 1
            self.args.append(self._u8_idx(idx))
            frag += f"%1$*{wpos}$s"
            arg_notes.append(f"byte %{wpos}$<-d[{idx}]")
        for c in const_terms:
            wpos = self.next_pos
            self.next_pos += 1
            self.args.append(c_u8(str(c)))
            frag += f"%1$*{wpos}$s"
            arg_notes.append(f"const %{wpos}$={c & 0xFF}")
        ppos = self.next_pos
        self.next_pos += 1
        self.args.append(f"d + {target}")
        frag += f"%{ppos}$hhn"
        if rpos:
            arg_notes.append(f"reset %{rpos}$")
        arg_notes.append(f"ptr %{ppos}$")
        self._append_frag(frag)
        self.write_specs.append((target, ppos, frag, src_stmt + " [" + ", ".join(arg_notes) + "]"))
        self.prev_written_idx = target

    def _record_counter(self, src_stmt: str) -> None:
        ppos = self.next_pos
        self.next_pos += 1
        self.args.append(f"d + {self.count_idx}")
        frag = f"%{ppos}$hhn"
        self._append_frag(frag)
        self.write_specs.append(
            (
                self.count_idx,
                ppos,
                frag,
                src_stmt + " [counter-sync]",
            )
        )
        self.prev_written_idx = self.count_idx

    def emit_copy(self, target: int, src: int, src_stmt: str) -> None:
        self._emit_linear_write(target, [src], [], src_stmt)

    def emit_const(self, target: int, value: int, src_stmt: str) -> None:
        self._emit_linear_write(target, [], [value & 0xFF], src_stmt)

    def emit_boolize(self, target: int, src: int, src_stmt: str) -> None:
        rpos, frag = self._reset_frag()
        ppos = self.next_pos
        spos = self.next_pos + 1
        tpos = self.next_pos + 2
        self.next_pos += 3
        self.args.append(self._u8_idx(src))
        self.args.append('" "')
        self.args.append(f"d + {target}")
        frag += f"%{spos}$.*{ppos}$s%{tpos}$hhn"
        notes = [f"prec %{ppos}$<-d[{src}]", f"str %{spos}$", f"ptr %{tpos}$"]
        if rpos:
            notes.append(f"reset %{rpos}$")
        self._append_frag(frag)
        self.write_specs.append((target, tpos, frag, src_stmt + " [" + ", ".join(notes) + "]"))
        self.prev_written_idx = target

    def emit_not_bool(self, target: int, src: int, src_stmt: str) -> None:
        # For src in {0,1}: len(r + src) is 256-src, so +1 gives 1-src (mod 256).
        rpos, frag = self._reset_frag()
        spos = self.next_pos
        onepos = self.next_pos + 1
        tpos = self.next_pos + 2
        self.next_pos += 3
        self.args.append(f"r + {self._u8_idx(src)}")
        self.args.append(c_u8("1"))
        self.args.append(f"d + {target}")
        frag += f"%{spos}$s%1$*{onepos}$s%{tpos}$hhn"
        notes = [f"str %{spos}$<-r+d[{src}]", f"const1 %{onepos}$", f"ptr %{tpos}$"]
        if rpos:
            notes.append(f"reset %{rpos}$")
        self._append_frag(frag)
        self.write_specs.append((target, tpos, frag, src_stmt + " [" + ", ".join(notes) + "]"))
        self.prev_written_idx = target

    def emit_bool_to_255(self, target: int, src_bool: int, src_stmt: str) -> None:
        # For src in {0,1}: len(r + src) is 256-src -> 0 or 255 (mod 256).
        rpos, frag = self._reset_frag()
        spos = self.next_pos
        tpos = self.next_pos + 1
        self.next_pos += 2
        self.args.append(f"r + {self._u8_idx(src_bool)}")
        self.args.append(f"d + {target}")
        frag += f"%{spos}$s%{tpos}$hhn"
        notes = [f"str %{spos}$<-r+d[{src_bool}]", f"ptr %{tpos}$"]
        if rpos:
            notes.append(f"reset %{rpos}$")
        self._append_frag(frag)
        self.write_specs.append((target, tpos, frag, src_stmt + " [" + ", ".join(notes) + "]"))
        self.prev_written_idx = target

    def _compile_bool_expr(self, node: ast.AST, src_stmt: str) -> int:
        if isinstance(node, ast.Name) and node.id.startswith("v_") and node.id[2:].isdigit():
            return int(node.id[2:])
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            v = int(node.value)
            if v == 0:
                return self.const_zero
            if v == 1:
                return self.const_one
            tmp = self.alloc_temp("CONST_LIT")
            self.emit_const(tmp, v & 0xFF, src_stmt)
            b = self.alloc_temp("BOOL_LIT")
            self.emit_boolize(b, tmp, src_stmt)
            return b

        terms = _bool_terms_from_sub(node)
        if terms is not None:
            # 1-a-b-c => !(a|b|c) in boolean domain.
            or_idx = self._compile_or(terms, src_stmt)
            out = self.alloc_temp("NOT_SUB")
            self.emit_not_bool(out, or_idx, src_stmt)
            return out

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self._compile_or(_flatten_binop(node, ast.BitOr), src_stmt)

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitAnd):
            return self._compile_and(_flatten_binop(node, ast.BitAnd), src_stmt)

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitXor):
            a = self._compile_bool_expr(node.left, src_stmt)
            b = self._compile_bool_expr(node.right, src_stmt)
            return self._compile_xor2(a, b, src_stmt)

        raise CompileError(
            "vm-pure micro backend supports boolean forms only "
            "(constants, d[idx], |, &, ^, and subtraction chains rooted at 1): "
            + src_stmt
        )

    def _compile_or(self, nodes: List[ast.AST], src_stmt: str) -> int:
        if not nodes:
            return self.const_zero
        vals = [self._compile_bool_expr(n, src_stmt) for n in nodes]
        sum_idx = self.alloc_temp("OR_SUM")
        self._emit_linear_write(sum_idx, vals, [], src_stmt)
        out = self.alloc_temp("OR_BOOL")
        self.emit_boolize(out, sum_idx, src_stmt)
        return out

    def _compile_and2(self, a: int, b: int, src_stmt: str) -> int:
        na = self.alloc_temp("AND_NOT_A")
        self.emit_not_bool(na, a, src_stmt)
        nb = self.alloc_temp("AND_NOT_B")
        self.emit_not_bool(nb, b, src_stmt)
        or_sum = self.alloc_temp("AND_OR_SUM")
        self._emit_linear_write(or_sum, [na, nb], [], src_stmt)
        or_bool = self.alloc_temp("AND_OR_BOOL")
        self.emit_boolize(or_bool, or_sum, src_stmt)
        out = self.alloc_temp("AND_OUT")
        self.emit_not_bool(out, or_bool, src_stmt)
        return out

    def _compile_and(self, nodes: List[ast.AST], src_stmt: str) -> int:
        if not nodes:
            return self.const_one
        vals = [self._compile_bool_expr(n, src_stmt) for n in nodes]
        cur = vals[0]
        for nxt in vals[1:]:
            cur = self._compile_and2(cur, nxt, src_stmt)
        return cur

    def _compile_xor2(self, a: int, b: int, src_stmt: str) -> int:
        or_sum = self.alloc_temp("XOR_OR_SUM")
        self._emit_linear_write(or_sum, [a, b], [], src_stmt)
        or_bool = self.alloc_temp("XOR_OR_BOOL")
        self.emit_boolize(or_bool, or_sum, src_stmt)
        and_ab = self._compile_and2(a, b, src_stmt)
        not_and = self.alloc_temp("XOR_NOT_AND")
        self.emit_not_bool(not_and, and_ab, src_stmt)
        return self._compile_and2(or_bool, not_and, src_stmt)

    def compile_expr_to_byte(self, node: ast.AST, src_stmt: str) -> int:
        if isinstance(node, ast.Name) and node.id.startswith("v_") and node.id[2:].isdigit():
            return int(node.id[2:])
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            v = int(node.value) & 0xFF
            if v == 0:
                return self.const_zero
            if v == 1:
                return self.const_one
            tmp = self.alloc_temp("CONST_RAW")
            self.emit_const(tmp, v, src_stmt)
            return tmp
        return self._compile_bool_expr(node, src_stmt)

    def emit_assign(self, target: int, expr: ast.AST, src_stmt: str) -> None:
        v_idx = self.compile_expr_to_byte(expr, src_stmt)
        self.emit_copy(target, v_idx, src_stmt)

    def emit_print_if(self, gate_expr: ast.AST, lit: str, src_stmt: str) -> None:
        gate_raw = self.compile_expr_to_byte(gate_expr, src_stmt)
        gate_bool = self.alloc_temp("GATE_BOOL")
        self.emit_boolize(gate_bool, gate_raw, src_stmt)
        gate_255 = self.alloc_temp("GATE_255")
        self.emit_bool_to_255(gate_255, gate_bool, src_stmt)
        ppos = self.next_pos
        spos = self.next_pos + 1
        self.next_pos += 2
        self.args.append(self._u8_idx(gate_255))
        self.args.append(lit)
        frag = f"%{spos}$.*{ppos}$s"
        self._append_frag(frag)
        self.printif_specs.append((ppos, spos, frag, src_stmt))
        self._record_counter(src_stmt)

    def emit_print(self, lit: str, src_stmt: str) -> None:
        spos = self.next_pos
        self.next_pos += 1
        self.args.append(lit)
        frag = f"%{spos}$s"
        self._append_frag(frag)
        self.print_specs.append((spos, frag, src_stmt))
        self._record_counter(src_stmt)

    def build(self) -> Tuple[List[str], List[str], Dict[int, str], int]:
        # Materialize micro constants now as initial tape values.
        return self.fmt_parts, self.args, self.temp_names, self.temp_next


def emit_c_vm_pure_micro(parsed: Program) -> str:
    has_input = len(parsed.input_idxs) > 0
    has_host_snapshot_input = detect_host_snapshot_input(parsed)

    mb = VmPureMicroBuilder(parsed)
    for st in parsed.loop_stmts:
        if isinstance(st, InputStmt):
            continue
        if isinstance(st, AssignStmt):
            mb.emit_assign(st.target, st.expr, st.original)
            continue
        if isinstance(st, PrintIfStmt):
            mb.emit_print_if(st.gate, st.text_lit, st.original)
            continue
        if isinstance(st, PrintStmt):
            mb.emit_print(st.text_lit, st.original)
            continue
        raise CompileError("internal error: unknown statement in micro backend")

    fmt_parts, args, temp_names, final_tape_size = mb.build()
    if not fmt_parts:
        raise CompileError("loop has no compilable statements")

    # Expand tape for micro temporaries.
    init_bytes = list(parsed.init_bytes) + [0] * (final_tape_size - parsed.tape_size)
    for idx, val, _ in mb.init_writes:
        init_bytes[idx] = ((val + 128) % 256) - 128
    init_vals = ", ".join(str(v) for v in init_bytes)

    # Merge index names with micro temp names.
    index_names = dict(parsed.index_names)
    for idx in range(parsed.tape_size, final_tape_size):
        if idx in temp_names:
            index_names[idx] = temp_names[idx]
        else:
            index_names[idx] = f"TMP_{idx - parsed.tape_size}"

    # Score: no source-level C eval in micro backend.
    has_print_if = len(mb.printif_specs) > 0
    dim_loop = 2
    dim_mut = 2 if mb.write_specs else 0
    if has_host_snapshot_input:
        dim_mut = min(dim_mut, 1)
    dim_ctrl = 2 if has_print_if else 0
    if has_host_snapshot_input and has_print_if:
        dim_ctrl = min(dim_ctrl, 1)
    dim_engine = 1 if has_host_snapshot_input else 2
    dim_rom = 2
    total_score = dim_loop + dim_mut + dim_ctrl + dim_engine + dim_rom
    classification = "POP-pure" if (total_score >= 9 and not has_host_snapshot_input) else (
        "hybrid POP" if total_score >= 6 else "POP-shaped / not POP"
    )

    fmt_c = "\n".join(f'    "{p}"' for p in fmt_parts)
    reset_pad = " " * 256

    tape_map_lines = []
    for idx in range(final_tape_size):
        tape_map_lines.append(f" * d[{idx}] ({index_names.get(idx, f'IDX_{idx}')})")

    write_map_lines = []
    for target, ppos, frag, src_stmt in mb.write_specs:
        name = index_names.get(target, f"IDX_{target}")
        write_map_lines.append(
            f" * {name} <- from `{quote_c_string_for_comment(src_stmt)}` via `{frag}` (ptr arg %{ppos}$)"
        )
    if not write_map_lines:
        write_map_lines.append(" * (no tape writes)")

    gate_lines = []
    for ppos, spos, frag, src_stmt in mb.printif_specs:
        gate_lines.append(
            f" * from `{quote_c_string_for_comment(src_stmt)}` via `{frag}` (prec arg %{ppos}$, str arg %{spos}$)"
        )
    if not gate_lines:
        gate_lines.append(" * (none)")

    print_lines = []
    for spos, frag, src_stmt in mb.print_specs:
        print_lines.append(
            f" * from `{quote_c_string_for_comment(src_stmt)}` via `{frag}` (str arg %{spos}$)"
        )
    if not print_lines:
        print_lines.append(" * (none)")

    if has_input:
        input_lines = [" * Raw tape-in (Gate E):"]
        for idx in parsed.input_idxs:
            input_name = index_names.get(idx, f"IDX_{idx}")
            input_lines.append(f" * d[{idx}] ({input_name}) <- getchar() byte before each printf tick")
        input_lines.append(" * EOF is preserved as raw byte value (signed char)EOF.")
        changed = ", ".join(f"d[{idx}]" for idx in parsed.input_idxs)
        tape_change_line = (
            f" * - Tape byte changes outside %n writes: {changed} raw input bytes only (Gate E exception)"
        )
    else:
        input_lines = [" * Raw tape-in (Gate E): (none)"]
        tape_change_line = " * - Tape byte changes outside %n writes: no"

    vm_backend_line = " * - VM-pure backend: micro"
    backend_line = " * - Backend write sequencing: VM-pure counter reset (%r+u8(prev) trick)"
    host_snapshot_line = (
        " * - Host-driven state snapshot input: "
        + (f"present ({len(parsed.input_idxs)} raw bytes/tick)" if has_host_snapshot_input else "no")
    )
    loop_src_lines = "\n".join(
        f" *   {quote_c_string_for_comment(st.original)}" for st in parsed.loop_stmts
    )
    args_rendered = ",\n               ".join(args)

    if has_input:
        read_lines = []
        for idx in parsed.input_idxs:
            read_lines.append("        in_ch = getchar();")
            read_lines.append(f"        d[{idx}] = (signed char)in_ch;")
        read_block = "\n".join(read_lines) + "\n"
        loop_block = (
            "    int in_ch = 0;\n"
            "    while (*d) {\n"
            + read_block
            + "        printf(fmt,\n"
            f"               {args_rendered});\n"
            "    }"
        )
        writes = " ".join(f"d[{idx}] = (signed char)getchar();" for idx in parsed.input_idxs)
        canonical_loop_line = f"while (*d) {{ {writes} printf(fmt, ARGS); }}"
    else:
        loop_block = (
            "    while (*d)\n"
            "        printf(fmt,\n"
            f"               {args_rendered});"
        )
        canonical_loop_line = "while (*d) printf(fmt, ARGS);"

    return f"""#include <stdio.h>
#include <stdint.h>

/*
 * Generated by tools/c2pop.py from: {parsed.src_path}
 *
 * Source loop statements:
{loop_src_lines}
 *
 * POP Compliance Report
 * Canonical loop: {canonical_loop_line}
 * Purity score: {total_score}/10 ({classification})
 * - Loop purity: {dim_loop}/2
 * - Mutation purity: {dim_mut}/2
 * - Control/branch purity: {dim_ctrl}/2
 * - Engine purity: {dim_engine}/2
 * - No C-script ROM: {dim_rom}/2
 * Tape bytes:
{chr(10).join(tape_map_lines)}
 *
 * Tape writes (all via %hhn):
{chr(10).join(write_map_lines)}
 *
 * Data-dependent formatting-time selection (%.*s gates):
{chr(10).join(gate_lines)}
 *
 * Unconditional formatting prints (%s):
{chr(10).join(print_lines)}
 *
{chr(10).join(input_lines)}
 *
 * Cheat audit:
 * - Per-iteration helper calls: no
 * - table[d[i]] argument selections: no
 * - C-side semantic operators (comparison/bool): none
 * - C-side per-tick expression evaluation (state/branch): none
 * - C-side input semantics beyond raw tape-in: no
{backend_line}
 * - VM-pure mode: enabled
{vm_backend_line}
{host_snapshot_line}
{tape_change_line}
 */

static signed char d[{final_tape_size}] = {{{init_vals}}};
static const char z[] = "";
static const char r[] = "{reset_pad}";

static const char *fmt =
{fmt_c}
;

int main(void) {{
{loop_block}
    return 0;
}}
"""


def emit_c_vm_pure_phase(parsed: Program) -> str:
    has_input = len(parsed.input_idxs) > 0
    has_host_snapshot_input = detect_host_snapshot_input(parsed)
    phase_ops = [st for st in parsed.loop_stmts if not isinstance(st, InputStmt)]
    if not phase_ops:
        raise CompileError("loop has no compilable statements")

    env = {i: f"(int)(unsigned char)d[{i}]" for i in range(parsed.tape_size)}
    cases: List[Dict[str, object]] = []
    for phase_idx, st in enumerate(phase_ops):
        if isinstance(st, AssignStmt):
            val_c = expr_ast_to_c(st.expr, env, parsed.constants)
            cases.append(
                {
                    "phase_idx": phase_idx,
                    "stmt": st.original,
                    "kind": "assign",
                    "target": st.target,
                    "val_c": val_c,
                    "fmt": "%1$*2$s%3$hhn",
                    "args": ["z", c_u8(val_c), f"d + {st.target}"],
                    "map": f"target d[{st.target}] from {quote_c_string_for_comment(st.original)}",
                }
            )
            continue

        if isinstance(st, PrintIfStmt):
            gate_c = expr_ast_to_c(st.gate, env, parsed.constants)
            cases.append(
                {
                    "phase_idx": phase_idx,
                    "stmt": st.original,
                    "kind": "print_if",
                    "fmt": "%2$.*1$s",
                    "args": [f"(255 * (int){c_u8(gate_c)})", st.text_lit],
                    "map": f"gate from {quote_c_string_for_comment(st.original)}",
                }
            )
            continue

        if isinstance(st, PrintStmt):
            cases.append(
                {
                    "phase_idx": phase_idx,
                    "stmt": st.original,
                    "kind": "print",
                    "fmt": "%1$s",
                    "args": [st.text_lit],
                    "map": f"literal from {quote_c_string_for_comment(st.original)}",
                }
            )
            continue

        raise CompileError("internal error: unknown statement in phase backend")

    dim_loop = 1
    dim_mut = 2 if any(c["kind"] == "assign" for c in cases) else 0
    if has_host_snapshot_input:
        dim_mut = min(dim_mut, 1)
    dim_ctrl = 2 if any(c["kind"] == "print_if" for c in cases) else 0
    if has_host_snapshot_input and dim_ctrl:
        dim_ctrl = min(dim_ctrl, 1)
    dim_engine = 1
    dim_rom = 0
    total_score = dim_loop + dim_mut + dim_ctrl + dim_engine + dim_rom
    classification = "hybrid POP" if total_score >= 6 else "POP-shaped / not POP"

    tape_map_lines = [
        f" * d[{idx}] ({parsed.index_names.get(idx, f'IDX_{idx}')})"
        for idx in range(parsed.tape_size)
    ]

    write_map_lines = []
    gate_lines = []
    print_lines = []
    for c in cases:
        phase_idx = int(c["phase_idx"])  # type: ignore[arg-type]
        kind = str(c["kind"])  # type: ignore[arg-type]
        if kind == "assign":
            tgt = int(c["target"])  # type: ignore[arg-type]
            fmt = str(c["fmt"])  # type: ignore[arg-type]
            write_map_lines.append(
                f" * [phase {phase_idx}] d[{tgt}] via `{fmt}` ({c['map']})"
            )
        elif kind == "print_if":
            fmt = str(c["fmt"])  # type: ignore[arg-type]
            gate_lines.append(f" * [phase {phase_idx}] via `{fmt}` ({c['map']})")
        elif kind == "print":
            fmt = str(c["fmt"])  # type: ignore[arg-type]
            print_lines.append(f" * [phase {phase_idx}] via `{fmt}` ({c['map']})")

    if not write_map_lines:
        write_map_lines.append(" * (no tape writes)")
    if not gate_lines:
        gate_lines.append(" * (none)")
    if not print_lines:
        print_lines.append(" * (none)")

    if has_input:
        input_lines = [" * Raw tape-in (Gate E):"]
        for idx in parsed.input_idxs:
            name = parsed.index_names.get(idx, f"IDX_{idx}")
            input_lines.append(f" * d[{idx}] ({name}) <- getchar() byte once per source tick (phase 0)")
        input_lines.append(" * EOF is preserved as raw byte value (signed char)EOF.")
        changed = ", ".join(f"d[{idx}]" for idx in parsed.input_idxs)
        tape_change_line = (
            f" * - Tape byte changes outside %n writes: {changed} raw input bytes only (Gate E exception)"
        )
    else:
        input_lines = [" * Raw tape-in (Gate E): (none)"]
        tape_change_line = " * - Tape byte changes outside %n writes: no"

    loop_src_lines = "\n".join(
        f" *   {quote_c_string_for_comment(st.original)}" for st in parsed.loop_stmts
    )

    fmt_blocks: List[str] = []
    switch_cases: List[str] = []
    for c in cases:
        phase_idx = int(c["phase_idx"])  # type: ignore[arg-type]
        fmt_name = f"fmt_{phase_idx}"
        fmt = str(c["fmt"])  # type: ignore[arg-type]
        fmt_blocks.append(f'static const char *{fmt_name} = "{fmt}";')
        args_rendered = ",\n                       ".join(c["args"])  # type: ignore[index]
        switch_cases.append(
            f"        case {phase_idx}:\n"
            f"            printf({fmt_name},\n"
            f"                       {args_rendered});\n"
            f"            break;"
        )

    read_block = ""
    if has_input:
        read_lines = []
        for idx in parsed.input_idxs:
            read_lines.append("            in_ch = getchar();")
            read_lines.append(f"            d[{idx}] = (signed char)in_ch;")
        read_block = "\n".join(read_lines)

    canonical_loop_line = (
        "while (1) { if (pc==0 && !*d) break; if (pc==0) tape-in; "
        "switch(pc){printf(fmt_pc,...);} pc=(pc+1)%PHASES; }"
    )
    reset_pad = " " * 256

    c_sem_ops_line = "present" if parsed.has_hybrid_expr else "none"
    has_phase_c_eval = any(isinstance(st, (AssignStmt, PrintIfStmt)) for st in phase_ops)
    if has_phase_c_eval:
        c_eval_line = "present (assignment/print gate expressions evaluated in C per phase)"
    else:
        c_eval_line = "none"
    if parsed.has_c_input_semantics:
        c_input_semantics_line = "present (input-derived expressions evaluated in C)"
    else:
        c_input_semantics_line = "no"

    init_vals = ", ".join(str(v) for v in parsed.init_bytes)
    return f"""#include <stdio.h>
#include <stdint.h>

/*
 * Generated by tools/c2pop.py from: {parsed.src_path}
 *
 * Source loop statements:
{loop_src_lines}
 *
 * POP Compliance Report
 * Canonical loop: {canonical_loop_line}
 * Purity score: {total_score}/10 ({classification})
 * - Loop purity: {dim_loop}/2
 * - Mutation purity: {dim_mut}/2
 * - Control/branch purity: {dim_ctrl}/2
 * - Engine purity: {dim_engine}/2
 * - No C-script ROM: {dim_rom}/2
 * Tape bytes:
{chr(10).join(tape_map_lines)}
 *
 * Tape writes (all via %hhn):
{chr(10).join(write_map_lines)}
 *
 * Data-dependent formatting-time selection (%.*s gates):
{chr(10).join(gate_lines)}
 *
 * Unconditional formatting prints (%s):
{chr(10).join(print_lines)}
 *
{chr(10).join(input_lines)}
 *
 * Cheat audit:
 * - Per-iteration helper calls: no
 * - table[d[i]] argument selections: yes (C phase dispatcher)
 * - C-side semantic operators (comparison/bool): {c_sem_ops_line}
 * - C-side per-tick expression evaluation (state/branch): {c_eval_line}
 * - C-side input semantics beyond raw tape-in: {c_input_semantics_line}
 * - Backend write sequencing: VM-pure phased dispatcher + counter reset
 * - VM-pure mode: enabled
 * - VM-pure backend: phase
 * - Host-driven state snapshot input: {"present (" + str(len(parsed.input_idxs)) + " raw bytes/tick)" if has_host_snapshot_input else "no"}
{tape_change_line}
 */

static signed char d[{parsed.tape_size}] = {{{init_vals}}};
static const char z[] = "";
{chr(10).join(fmt_blocks)}
int main(void) {{
    int in_ch = 0;
    int pc = 0;
    const int phases = {len(cases)};
    while (1) {{
        if (pc == 0) {{
            if (!*d) break;
{read_block}
        }}
        switch (pc) {{
{chr(10).join(switch_cases)}
        default:
            pc = 0;
            continue;
        }}
        pc++;
        if (pc >= phases) pc = 0;
    }}
    return 0;
}}
"""


class VmPureVmLowerer:
    def __init__(self, parsed: Program):
        self.parsed = parsed
        self.phases: List[Dict[str, object]] = []
        self.temp_next = parsed.tape_size
        self.temp_names: Dict[int, str] = {}
        self.init_values: Dict[int, int] = {}
        self.const_zero = self.alloc_temp("CONST_0", init_val=0)
        self.const_one = self.alloc_temp("CONST_1", init_val=1)

    def alloc_temp(self, name: str, init_val: Optional[int] = None) -> int:
        idx = self.temp_next
        self.temp_next += 1
        self.temp_names[idx] = name
        if init_val is not None:
            self.init_values[idx] = ((init_val + 128) % 256) - 128
        return idx

    def _u8_idx(self, idx: int) -> str:
        return c_u8(f"(int)(unsigned char)d[{idx}]")

    def _append_phase(
        self,
        kind: str,
        fmt: str,
        args: List[str],
        src_stmt: str,
        map_text: str,
        target: Optional[int] = None,
    ) -> None:
        self.phases.append(
            {
                "kind": kind,
                "fmt": fmt,
                "args": args,
                "stmt": src_stmt,
                "map": map_text,
                "target": target,
            }
        )

    def _emit_sum_write(
        self,
        target: int,
        byte_terms: List[int],
        const_terms: List[int],
        src_stmt: str,
        map_text: str,
    ) -> None:
        args: List[str] = ["z"]
        frag = ""
        next_pos = 2
        for idx in byte_terms:
            args.append(self._u8_idx(idx))
            frag += f"%1$*{next_pos}$s"
            next_pos += 1
        for c in const_terms:
            args.append(c_u8(str(c)))
            frag += f"%1$*{next_pos}$s"
            next_pos += 1
        args.append(f"d + {target}")
        ppos = next_pos
        if not frag:
            frag = f"%{ppos}$hhn"
        else:
            frag += f"%{ppos}$hhn"
        self._append_phase("assign", frag, args, src_stmt, map_text, target=target)

    def emit_copy(self, target: int, src: int, src_stmt: str) -> None:
        self._emit_sum_write(target, [src], [], src_stmt, f"copy d[{target}] <- d[{src}]")

    def emit_const(self, target: int, value: int, src_stmt: str) -> None:
        self._emit_sum_write(
            target, [], [value & 0xFF], src_stmt, f"const d[{target}] <- {value & 0xFF}"
        )

    def emit_boolize(self, target: int, src: int, src_stmt: str) -> None:
        fmt = "%2$.*1$s%3$hhn"
        args = [self._u8_idx(src), '" "', f"d + {target}"]
        self._append_phase(
            "assign",
            fmt,
            args,
            src_stmt,
            f"boolize d[{target}] <- (d[{src}]!=0)",
            target=target,
        )

    def emit_not_bool(self, target: int, src: int, src_stmt: str) -> None:
        fmt = "%2$s%1$*3$s%4$hhn"
        args = ["z", f"r + {self._u8_idx(src)}", c_u8("1"), f"d + {target}"]
        self._append_phase(
            "assign",
            fmt,
            args,
            src_stmt,
            f"not-bool d[{target}] <- 1-d[{src}]",
            target=target,
        )

    def emit_bool_to_255(self, target: int, src_bool: int, src_stmt: str) -> None:
        fmt = "%2$s%3$hhn"
        args = ["z", f"r + {self._u8_idx(src_bool)}", f"d + {target}"]
        self._append_phase(
            "assign",
            fmt,
            args,
            src_stmt,
            f"bool-to-255 d[{target}] <- (d[{src_bool}]?255:0)",
            target=target,
        )

    def _name_idx(self, node: ast.AST) -> Optional[int]:
        if isinstance(node, ast.Name) and node.id.startswith("v_") and node.id[2:].isdigit():
            return int(node.id[2:])
        return None

    def _compile_or(self, nodes: List[ast.AST], src_stmt: str) -> int:
        if not nodes:
            return self.const_zero
        vals = [self.compile_bool_expr(n, src_stmt) for n in nodes]
        if len(vals) == 1:
            return vals[0]
        sum_idx = self.alloc_temp("OR_SUM")
        self._emit_sum_write(sum_idx, vals, [], src_stmt, "or-sum")
        out = self.alloc_temp("OR_BOOL")
        self.emit_boolize(out, sum_idx, src_stmt)
        return out

    def _compile_and2(self, a: int, b: int, src_stmt: str) -> int:
        na = self.alloc_temp("AND_NOT_A")
        self.emit_not_bool(na, a, src_stmt)
        nb = self.alloc_temp("AND_NOT_B")
        self.emit_not_bool(nb, b, src_stmt)
        n_or = self.alloc_temp("AND_NOR_SUM")
        self._emit_sum_write(n_or, [na, nb], [], src_stmt, "and-demorgan-sum")
        n_or_bool = self.alloc_temp("AND_NOR_BOOL")
        self.emit_boolize(n_or_bool, n_or, src_stmt)
        out = self.alloc_temp("AND_OUT")
        self.emit_not_bool(out, n_or_bool, src_stmt)
        return out

    def _compile_and(self, nodes: List[ast.AST], src_stmt: str) -> int:
        if not nodes:
            return self.const_one
        vals = [self.compile_bool_expr(n, src_stmt) for n in nodes]
        cur = vals[0]
        for nxt in vals[1:]:
            cur = self._compile_and2(cur, nxt, src_stmt)
        return cur

    def _compile_xor2(self, a: int, b: int, src_stmt: str) -> int:
        or_sum = self.alloc_temp("XOR_OR_SUM")
        self._emit_sum_write(or_sum, [a, b], [], src_stmt, "xor-or-sum")
        or_bool = self.alloc_temp("XOR_OR_BOOL")
        self.emit_boolize(or_bool, or_sum, src_stmt)
        and_ab = self._compile_and2(a, b, src_stmt)
        not_and = self.alloc_temp("XOR_NOT_AND")
        self.emit_not_bool(not_and, and_ab, src_stmt)
        out = self._compile_and2(or_bool, not_and, src_stmt)
        return out

    def compile_bool_expr(self, node: ast.AST, src_stmt: str) -> int:
        idx = self._name_idx(node)
        if idx is not None:
            return idx
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            v = int(node.value) & 0xFF
            if v == 0:
                return self.const_zero
            if v == 1:
                return self.const_one
            tmp = self.alloc_temp("CONST_LIT")
            self.emit_const(tmp, v, src_stmt)
            out = self.alloc_temp("CONST_BOOL")
            self.emit_boolize(out, tmp, src_stmt)
            return out
        terms = _bool_terms_from_sub(node)
        if terms is not None:
            or_idx = self._compile_or(terms, src_stmt)
            out = self.alloc_temp("SUB_NOT")
            self.emit_not_bool(out, or_idx, src_stmt)
            return out
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self._compile_or(_flatten_binop(node, ast.BitOr), src_stmt)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitAnd):
            return self._compile_and(_flatten_binop(node, ast.BitAnd), src_stmt)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitXor):
            a = self.compile_bool_expr(node.left, src_stmt)
            b = self.compile_bool_expr(node.right, src_stmt)
            return self._compile_xor2(a, b, src_stmt)
        raise CompileError(
            "vm backend internal error: unsupported expression after parse validation: " + src_stmt
        )

    def lower_assign(self, st: AssignStmt) -> None:
        idx = self._name_idx(st.expr)
        if idx is not None:
            self.emit_copy(st.target, idx, st.original)
            return
        if isinstance(st.expr, ast.Constant) and isinstance(st.expr.value, int):
            self.emit_const(st.target, int(st.expr.value), st.original)
            return
        val_idx = self.compile_bool_expr(st.expr, st.original)
        self.emit_copy(st.target, val_idx, st.original)

    def lower_print_if(self, st: PrintIfStmt) -> None:
        idx = self._name_idx(st.gate)
        if idx is None:
            gate_raw = self.compile_bool_expr(st.gate, st.original)
        else:
            gate_raw = idx
        gate_bool = self.alloc_temp("GATE_BOOL")
        self.emit_boolize(gate_bool, gate_raw, st.original)
        gate_255 = self.alloc_temp("GATE_255")
        self.emit_bool_to_255(gate_255, gate_bool, st.original)
        fmt = "%2$.*1$s"
        args = [self._u8_idx(gate_255), st.text_lit]
        self._append_phase(
            "print_if",
            fmt,
            args,
            st.original,
            f"print-if gate d[{gate_255}]",
            target=None,
        )

    def lower_print(self, st: PrintStmt) -> None:
        self._append_phase(
            "print",
            "%1$s",
            [st.text_lit],
            st.original,
            f"print literal {quote_c_string_for_comment(st.text_lit)}",
            target=None,
        )


def emit_c_vm_pure_vm(parsed: Program) -> str:
    has_input = len(parsed.input_idxs) > 0
    has_host_snapshot_input = detect_host_snapshot_input(parsed)

    lowerer = VmPureVmLowerer(parsed)
    vm_run_state_idx = lowerer.alloc_temp("VM_RUN_STATE", init_val=parsed.init_bytes[parsed.run_idx])
    for st in parsed.loop_stmts:
        if isinstance(st, InputStmt):
            continue
        if isinstance(st, AssignStmt):
            tgt = vm_run_state_idx if st.target == parsed.run_idx else st.target
            expr = expr_replace_idx(st.expr, parsed.run_idx, vm_run_state_idx)
            st2 = AssignStmt(target=tgt, expr=expr, original=st.original)
            lowerer.lower_assign(st2)
            continue
        if isinstance(st, PrintIfStmt):
            gate = expr_replace_idx(st.gate, parsed.run_idx, vm_run_state_idx)
            st2 = PrintIfStmt(gate=gate, text_lit=st.text_lit, original=st.original)
            lowerer.lower_print_if(st2)
            continue
        if isinstance(st, PrintStmt):
            lowerer.lower_print(st)
            continue
        raise CompileError("internal error: unknown statement in vm backend")
    lowerer.emit_copy(parsed.run_idx, vm_run_state_idx, "vm backend RUN latch apply")

    phases = lowerer.phases
    if not phases:
        raise CompileError("loop has no compilable statements")
    if len(phases) > 65536:
        raise CompileError("vm backend supports at most 65536 micro-phases (16-bit PC)")
    ptr_bytes = ctypes.sizeof(ctypes.c_void_p)
    if ptr_bytes < 4 or ptr_bytes > 16:
        raise CompileError(f"unsupported host pointer size for vm backend: {ptr_bytes}")

    vm_pc_lo_idx = lowerer.temp_next
    vm_pc_hi_idx = lowerer.temp_next + 1
    vm_boundary_idx = lowerer.temp_next + 2
    final_tape_size = vm_boundary_idx + 1
    init_bytes = list(parsed.init_bytes) + [0] * (final_tape_size - parsed.tape_size)
    for idx, val in lowerer.init_values.items():
        init_bytes[idx] = val
    init_bytes[vm_pc_lo_idx] = 0
    init_bytes[vm_pc_hi_idx] = 0
    init_bytes[vm_boundary_idx] = 1
    init_vals = ", ".join(str(v) for v in init_bytes)

    index_names = dict(parsed.index_names)
    for idx in range(parsed.tape_size, final_tape_size):
        index_names[idx] = lowerer.temp_names.get(idx, f"TMP_{idx - parsed.tape_size}")
    index_names[vm_pc_lo_idx] = "VM_PC_LO"
    index_names[vm_pc_hi_idx] = "VM_PC_HI"
    index_names[vm_boundary_idx] = "VM_BOUNDARY"

    phases_with_pc: List[Dict[str, object]] = []
    for i, ph in enumerate(phases):
        next_pc = (i + 1) % len(phases)
        next_lo = next_pc & 0xFF
        next_hi = (next_pc >> 8) & 0xFF
        hi_delta = (next_hi - next_lo) & 0xFF
        next_boundary = 1 if next_pc == 0 else 0
        args = list(ph["args"])  # type: ignore[index]

        # Phase-local vm format pointer update: write vm_fmt bytes for next phase.
        fmt_ptr_frag = ""
        zfmt_pos = len(args) + 1
        args.append("z")
        for b in range(ptr_bytes):
            wpos = len(args) + 1
            ppos = len(args) + 2
            rpos = len(args) + 3
            byte_expr = c_u8(f"((uintptr_t)fmt_{next_pc} >> {8 * b})")
            args.extend(
                [
                    byte_expr,
                    f"((unsigned char *)&vm_fmt) + {b}",
                    f"r + {byte_expr}",
                ]
            )
            fmt_ptr_frag += f"%{zfmt_pos}$*{wpos}$s%{ppos}$hhn%{rpos}$s"

        base = len(args)
        zpos = base + 1
        wlo_pos = base + 2
        plo_pos = base + 3
        whi_pos = base + 4
        phi_pos = base + 5
        rpos = base + 6
        pc_frag = (
            f"%{zpos}$*{wlo_pos}$s"
            f"%{plo_pos}$hhn"
            f"%{zpos}$*{whi_pos}$s"
            f"%{phi_pos}$hhn"
            f"%{rpos}$s"
        )
        args.extend(
            [
                "z",
                c_u8(str(next_lo)),
                f"d + {vm_pc_lo_idx}",
                c_u8(str(hi_delta)),
                f"d + {vm_pc_hi_idx}",
                f"r + {next_hi}",
            ]
        )
        base2 = len(args)
        bzpos = base2 + 1
        bwpos = base2 + 2
        bppos = base2 + 3
        brpos = base2 + 4
        boundary_frag = f"%{bzpos}$*{bwpos}$s%{bppos}$hhn%{brpos}$s"
        args.extend(
            [
                "z",
                c_u8(str(next_boundary)),
                f"d + {vm_boundary_idx}",
                f"r + {next_boundary}",
            ]
        )
        ph2 = dict(ph)
        ph2["fmt"] = fmt_ptr_frag + pc_frag + boundary_frag + str(ph["fmt"])
        ph2["args"] = args
        ph2["fmt_ptr_frag"] = fmt_ptr_frag
        ph2["pc_frag"] = pc_frag
        ph2["boundary_frag"] = boundary_frag
        ph2["next_pc"] = next_pc
        ph2["next_lo"] = next_lo
        ph2["next_hi"] = next_hi
        ph2["next_boundary"] = next_boundary
        phases_with_pc.append(ph2)

    dim_loop = 2
    dim_mut = 2 if phases_with_pc else 0
    if has_host_snapshot_input:
        dim_mut = min(dim_mut, 1)
    dim_ctrl = 2 if any(str(p["kind"]) == "print_if" for p in phases_with_pc) else 0
    if has_host_snapshot_input and dim_ctrl:
        dim_ctrl = min(dim_ctrl, 1)
    dim_engine = 1 if has_host_snapshot_input else 2
    dim_rom = 2
    total_score = dim_loop + dim_mut + dim_ctrl + dim_engine + dim_rom
    classification = "POP-pure" if (total_score >= 9 and not has_host_snapshot_input) else (
        "hybrid POP" if total_score >= 6 else "POP-shaped / not POP"
    )

    tape_map_lines = []
    for idx in range(final_tape_size):
        tape_map_lines.append(f" * d[{idx}] ({index_names.get(idx, f'IDX_{idx}')})")

    write_map_lines: List[str] = []
    gate_lines: List[str] = []
    print_lines: List[str] = []
    for i, ph in enumerate(phases_with_pc):
        kind = str(ph["kind"])
        fmt = str(ph["fmt"])
        map_txt = str(ph["map"])
        fmt_ptr_frag = str(ph["fmt_ptr_frag"])
        pc_frag = str(ph["pc_frag"])
        boundary_frag = str(ph["boundary_frag"])
        next_pc = int(ph["next_pc"])  # type: ignore[arg-type]
        next_lo = int(ph["next_lo"])  # type: ignore[arg-type]
        next_hi = int(ph["next_hi"])  # type: ignore[arg-type]
        next_boundary = int(ph["next_boundary"])  # type: ignore[arg-type]
        write_map_lines.append(
            f" * [phase {i}] vm_fmt bytes via `{fmt_ptr_frag}` (next fmt_{next_pc})"
        )
        write_map_lines.append(
            f" * [phase {i}] d[{vm_pc_lo_idx}]/d[{vm_pc_hi_idx}] via `{pc_frag}` "
            f"(next phase {next_pc} lo={next_lo} hi={next_hi}, then counter reset)"
        )
        write_map_lines.append(
            f" * [phase {i}] d[{vm_boundary_idx}] via `{boundary_frag}` "
            f"(next boundary={next_boundary})"
        )
        if kind == "assign":
            tgt = int(ph["target"])  # type: ignore[arg-type]
            write_map_lines.append(f" * [phase {i}] d[{tgt}] via `{fmt}` ({map_txt})")
        elif kind == "print_if":
            gate_lines.append(f" * [phase {i}] via `{fmt}` ({map_txt})")
        elif kind == "print":
            print_lines.append(f" * [phase {i}] via `{fmt}` ({map_txt})")

    if not write_map_lines:
        write_map_lines.append(" * (no tape writes)")
    if not gate_lines:
        gate_lines.append(" * (none)")
    if not print_lines:
        print_lines.append(" * (none)")

    if has_input:
        input_lines = [" * Raw tape-in (Gate E):"]
        for idx in parsed.input_idxs:
            name = index_names.get(idx, f"IDX_{idx}")
            input_lines.append(
                f" * d[{idx}] ({name}) <- getchar() byte when d[{vm_boundary_idx}] (VM_BOUNDARY) != 0"
            )
        input_lines.append(" * EOF is preserved as raw byte value (signed char)EOF.")
        changed = ", ".join(f"d[{idx}]" for idx in parsed.input_idxs)
        tape_change_line = (
            f" * - Tape byte changes outside %n writes: {changed} raw input bytes only (Gate E exception)"
        )
    else:
        input_lines = [" * Raw tape-in (Gate E): (none)"]
        tape_change_line = " * - Tape byte changes outside %n writes: no"

    loop_src_lines = "\n".join(
        f" *   {quote_c_string_for_comment(st.original)}" for st in parsed.loop_stmts
    )

    def remap_fmt_positions(fmt: str, local_to_global: Dict[int, int]) -> str:
        def repl_pct(m: re.Match[str]) -> str:
            lp = int(m.group(1))
            gp = local_to_global.get(lp)
            if gp is None:
                raise CompileError(f"internal error: missing arg position %{lp}$ in vm backend")
            return f"%{gp}$"

        def repl_star(m: re.Match[str]) -> str:
            lp = int(m.group(1))
            gp = local_to_global.get(lp)
            if gp is None:
                raise CompileError(f"internal error: missing arg position *{lp}$ in vm backend")
            return f"*{gp}$"

        fmt = re.sub(r"%(\d+)\$", repl_pct, fmt)
        fmt = re.sub(r"\*(\d+)\$", repl_star, fmt)
        return fmt

    global_arg_pos: Dict[str, int] = {}
    global_args: List[str] = []
    fmt_blocks: List[str] = []
    for i, ph in enumerate(phases_with_pc):
        fmt_name = f"fmt_{i}"
        local_args = list(ph["args"])  # type: ignore[index]
        local_to_global: Dict[int, int] = {}
        for lp, arg_expr in enumerate(local_args, start=1):
            expr = str(arg_expr)
            gp = global_arg_pos.get(expr)
            if gp is None:
                gp = len(global_args) + 1
                global_arg_pos[expr] = gp
                global_args.append(expr)
            local_to_global[lp] = gp
        fmt = remap_fmt_positions(str(ph["fmt"]), local_to_global)
        fmt_blocks.append(f'static const char *{fmt_name} = "{fmt}";')
    args_rendered = ",\n               ".join(global_args)

    read_block = ""
    if has_input:
        read_lines = []
        for idx in parsed.input_idxs:
            read_lines.append(
                f"        (void)fread(d + {idx}, (size_t)((unsigned char)d[{vm_boundary_idx}]), 1, stdin);"
            )
        read_block = "\n".join(read_lines)

    canonical_loop_line = (
        f"while (*d) {{ tape-in(size=d[{vm_boundary_idx}]); printf(vm_fmt, ARGS); }}"
    )
    reset_pad = " " * 256

    return f"""#include <stdio.h>

/*
 * Generated by tools/c2pop.py from: {parsed.src_path}
 *
 * Source loop statements:
{loop_src_lines}
 *
 * POP Compliance Report
 * Canonical loop: {canonical_loop_line}
 * Purity score: {total_score}/10 ({classification})
 * - Loop purity: {dim_loop}/2
 * - Mutation purity: {dim_mut}/2
 * - Control/branch purity: {dim_ctrl}/2
 * - Engine purity: {dim_engine}/2
 * - No C-script ROM: {dim_rom}/2
 * Tape bytes:
{chr(10).join(tape_map_lines)}
 *
 * Tape writes (all via %hhn):
{chr(10).join(write_map_lines)}
 *
 * Data-dependent formatting-time selection (%.*s gates):
{chr(10).join(gate_lines)}
 *
 * Unconditional formatting prints (%s):
{chr(10).join(print_lines)}
 *
{chr(10).join(input_lines)}
 *
 * Cheat audit:
 * - Per-iteration helper calls: no
 * - table[d[i]] argument selections: no
 * - C-side semantic operators (comparison/bool): none
 * - C-side per-tick expression evaluation (state/branch): none
 * - C-side input semantics beyond raw tape-in: no
 * - Backend write sequencing: VM micro-phases (including VM_PC_LO/VM_PC_HI via %hhn and vm_fmt bytes) + single-call dispatch
 * - VM-pure mode: enabled
 * - VM-pure backend: vm
 * - Host-driven state snapshot input: {"present (" + str(len(parsed.input_idxs)) + " raw bytes/tick)" if has_host_snapshot_input else "no"}
{tape_change_line}
 */

static signed char d[{final_tape_size}] = {{{init_vals}}};
static const char z[] = "";
static const char r[] = "{reset_pad}";
{chr(10).join(fmt_blocks)}
int main(void) {{
    const char *vm_fmt = fmt_0;
    while (*d) {{
{read_block}
        printf(vm_fmt,
               {args_rendered});
    }}
    return 0;
}}
"""


def emit_c(parsed: Program, reject_delta_compiler: bool = False) -> str:
    if parsed.vm_pure and parsed.vm_pure_backend == "micro":
        return emit_c_vm_pure_micro(parsed)
    if parsed.vm_pure and parsed.vm_pure_backend == "phase":
        return emit_c_vm_pure_phase(parsed)
    if parsed.vm_pure and parsed.vm_pure_backend == "vm":
        return emit_c_vm_pure_vm(parsed)

    writes, render_ops = analyze_program(parsed)
    has_print_if = any(kind == "if" for kind, _, _, _ in render_ops)
    has_input = len(parsed.input_idxs) > 0
    has_host_snapshot_input = detect_host_snapshot_input(parsed)
    has_hybrid_expr = parsed.has_hybrid_expr
    has_c_eval_expr = parsed.has_c_eval_expr
    has_c_input_semantics = parsed.has_c_input_semantics
    vm_pure = parsed.vm_pure
    input_idx_set = set(parsed.input_idxs)

    def c_expr_refs_input(expr_c: str) -> bool:
        if not input_idx_set:
            return False
        for m in re.finditer(r"d\[(\d+)\]", expr_c):
            if int(m.group(1)) in input_idx_set:
                return True
        return False

    # Non-vm-pure path can still use delta arithmetic for compact output.
    has_backend_delta_compiler = (not vm_pure) and len(writes) > 1
    has_backend_counter_reset = vm_pure and len(writes) > 1
    has_backend_input_delta_semantics = False
    if reject_delta_compiler and has_backend_delta_compiler:
        raise CompileError(
            "reject-delta-compiler mode forbids backend C-side write-delta "
            "construction (%w[i]-%w[i-1]); reduce to <=1 tape write per tick "
            "or use --vm-pure counter-reset lowering"
        )
    # Purity score for this generated artifact under the POP rubric.
    dim_loop = 2
    dim_mut = 2 if writes else 0
    if has_host_snapshot_input:
        dim_mut = min(dim_mut, 1)
    # C-evaluated expressions mean semantics are computed outside printf VM.
    dim_ctrl = (1 if has_c_eval_expr else 2) if has_print_if else 0
    if has_host_snapshot_input and has_print_if:
        dim_ctrl = min(dim_ctrl, 1)
    dim_engine = 1 if (has_c_eval_expr or has_host_snapshot_input or has_backend_delta_compiler) else 2
    dim_rom = 2
    total_score = dim_loop + dim_mut + dim_ctrl + dim_engine + dim_rom
    if (
        total_score >= 9
        and not has_host_snapshot_input
        and not has_backend_delta_compiler
        and not has_c_eval_expr
    ):
        classification = "POP-pure"
    elif total_score >= 6:
        classification = "hybrid POP"
    else:
        classification = "POP-shaped / not POP"

    fmt_parts: List[str] = []
    args: List[str] = []

    # Positional arguments: 1 is zero string used by all %*s pads.
    args.append("z")
    next_pos = 2

    write_specs: List[Tuple[int, int, int, int, str, str]] = []
    prev_val_c = "0"

    for idx, (target, val_c, src_stmt) in enumerate(writes):
        rpos = 0
        reset_frag = ""
        cur_refs_input = c_expr_refs_input(val_c)

        if vm_pure and idx > 0:
            # VM-pure lowering: avoid C-side delta arithmetic by resetting low byte
            # to zero via a 256-byte reset string offset.
            rpos = next_pos
            next_pos += 1
            args.append(f"r + {c_u8(prev_val_c)}")
            reset_frag = f"%{rpos}$s"

        if vm_pure or idx == 0:
            pad_c = c_u8(val_c)
        else:
            pad_c = c_u8(f"({val_c}) - ({prev_val_c})")
            if cur_refs_input or c_expr_refs_input(prev_val_c):
                has_backend_input_delta_semantics = True

        wpos = next_pos
        ppos = next_pos + 1
        next_pos += 2

        args.append(pad_c)
        args.append(f"d + {target}")
        frag = f"{reset_frag}%1$*{wpos}$s%{ppos}$hhn"
        fmt_parts.append(frag)
        write_specs.append((target, rpos, wpos, ppos, frag, src_stmt))
        prev_val_c = val_c

    printif_specs: List[Tuple[int, int, str, str]] = []
    print_specs: List[Tuple[int, str, str]] = []
    for kind, gate_c, lit, src_stmt in render_ops:
        if kind == "if":
            if gate_c is None:
                raise CompileError(f"internal error: missing gate for print_if: {src_stmt}")
            ppos = next_pos
            spos = next_pos + 1
            next_pos += 2
            # vm-pure mode uses gate byte directly as precision (producer must
            # provide large enough non-zero precision for full-string prints).
            if vm_pure:
                prec_c = c_u8(gate_c)
            else:
                # Any positive precision prints full literal (cap at string length).
                prec_c = f"(255 * (int){c_u8(gate_c)})"
            args.append(prec_c)
            args.append(lit)
            frag = f"%{spos}$.*{ppos}$s"
            fmt_parts.append(frag)
            printif_specs.append((ppos, spos, frag, src_stmt))
            continue

        if kind == "plain":
            spos = next_pos
            next_pos += 1
            args.append(lit)
            frag = f"%{spos}$s"
            fmt_parts.append(frag)
            print_specs.append((spos, frag, src_stmt))
            continue

        raise CompileError(f"internal error: unknown render op '{kind}'")

    if not fmt_parts:
        raise CompileError("loop has no compilable statements")

    # Build fmt string split across lines.
    fmt_lines = [f'    "{p}"' for p in fmt_parts]
    fmt_c = "\n".join(fmt_lines)

    # Render tape initializer as signed char constants.
    init_vals = ", ".join(str(v) for v in parsed.init_bytes)
    reset_pad = " " * 256
    reset_decl = f'static const char r[] = "{reset_pad}";\n' if has_backend_counter_reset else ""

    # Deterministic byte map comment.
    tape_map_lines = []
    for idx in range(parsed.tape_size):
        name = parsed.index_names.get(idx, f"IDX_{idx}")
        tape_map_lines.append(f" * d[{idx}] ({name})")

    write_map_lines = []
    for target, rpos, wpos, ppos, frag, src_stmt in write_specs:
        name = parsed.index_names.get(target, f"IDX_{target}")
        reset_info = f", reset arg %{rpos}$" if rpos else ""
        write_map_lines.append(
            " * "
            + f"{name} <- from `{quote_c_string_for_comment(src_stmt)}` via `{frag}` "
            + f"(pad arg %{wpos}$, ptr arg %{ppos}${reset_info})"
        )

    if not write_map_lines:
        write_map_lines.append(" * (no tape writes)")

    gate_lines = []
    for ppos, spos, frag, src_stmt in printif_specs:
        gate_lines.append(
            " * "
            + f"from `{quote_c_string_for_comment(src_stmt)}` via `{frag}` "
            + f"(prec arg %{ppos}$, str arg %{spos}$)"
        )
    if not gate_lines:
        gate_lines.append(" * (none)")

    print_lines = []
    for spos, frag, src_stmt in print_specs:
        print_lines.append(
            " * "
            + f"from `{quote_c_string_for_comment(src_stmt)}` via `{frag}` "
            + f"(str arg %{spos}$)"
        )
    if not print_lines:
        print_lines.append(" * (none)")

    if has_input:
        input_lines = [" * Raw tape-in (Gate E):"]
        for idx in parsed.input_idxs:
            input_name = parsed.index_names.get(idx, f"IDX_{idx}")
            input_lines.append(
                f" * d[{idx}] ({input_name}) <- getchar() byte before each printf tick"
            )
        input_lines.append(
            " * EOF is preserved as raw byte value (signed char)EOF."
        )
        changed = ", ".join(f"d[{idx}]" for idx in parsed.input_idxs)
        tape_change_line = (
            f" * - Tape byte changes outside %n writes: {changed} raw input bytes only (Gate E exception)"
        )
    else:
        input_lines = [" * Raw tape-in (Gate E): (none)"]
        tape_change_line = " * - Tape byte changes outside %n writes: no"

    hybrid_expr_line = (
        " * - C-side semantic operators (comparison/bool): "
        + ("present (hybrid mode)" if has_hybrid_expr else "none")
    )
    c_eval_line = (
        " * - C-side per-tick expression evaluation (state/branch): "
        + ("present" if has_c_eval_expr else "none")
    )
    effective_input_semantics = has_c_input_semantics or has_backend_input_delta_semantics
    input_semantics_line = (
        " * - C-side input semantics beyond raw tape-in: "
        + ("present" if effective_input_semantics else "no")
    )
    if has_backend_delta_compiler:
        backend_line = (
            " * - Backend write sequencing: delta compiler (%w[i]-%w[i-1])"
        )
    elif has_backend_counter_reset:
        backend_line = (
            " * - Backend write sequencing: VM-pure counter reset (%r+u8(prev) trick)"
        )
    else:
        backend_line = " * - Backend write sequencing: single-write/no sequencing needed"
    vm_pure_line = " * - VM-pure mode: " + ("enabled" if vm_pure else "disabled")
    host_snapshot_line = (
        " * - Host-driven state snapshot input: "
        + (
            f"present ({len(parsed.input_idxs)} raw bytes/tick)"
            if has_host_snapshot_input
            else "no"
        )
    )

    loop_src_lines = "\n".join(f" *   {quote_c_string_for_comment(st.original)}" for st in parsed.loop_stmts)

    args_rendered = ",\n               ".join(args)
    if has_input:
        read_lines = []
        for idx in parsed.input_idxs:
            read_lines.append("        in_ch = getchar();")
            read_lines.append(f"        d[{idx}] = (signed char)in_ch;")
        read_block = "\n".join(read_lines) + "\n"
        loop_block = (
            "    int in_ch = 0;\n"
            "    while (*d) {\n"
            + read_block
            + "        printf(fmt,\n"
            f"               {args_rendered});\n"
            "    }"
        )
    else:
        loop_block = (
            "    while (*d)\n"
            "        printf(fmt,\n"
            f"               {args_rendered});"
        )

    if has_input:
        writes = " ".join(f"d[{idx}] = (signed char)getchar();" for idx in parsed.input_idxs)
        canonical_loop_line = (
            f"while (*d) {{ {writes} printf(fmt, ARGS); }}"
        )
    else:
        canonical_loop_line = "while (*d) printf(fmt, ARGS);"

    out = f"""#include <stdio.h>

/*
 * Generated by tools/c2pop.py from: {parsed.src_path}
 *
 * Source loop statements:
{loop_src_lines}
 *
 * POP Compliance Report
 * Canonical loop: {canonical_loop_line}
 * Purity score: {total_score}/10 ({classification})
 * - Loop purity: {dim_loop}/2
 * - Mutation purity: {dim_mut}/2
 * - Control/branch purity: {dim_ctrl}/2
 * - Engine purity: {dim_engine}/2
 * - No C-script ROM: {dim_rom}/2
 * Tape bytes:
{chr(10).join(tape_map_lines)}
 *
 * Tape writes (all via %hhn):
{chr(10).join(write_map_lines)}
 *
 * Data-dependent formatting-time selection (%.*s gates):
{chr(10).join(gate_lines)}
 *
 * Unconditional formatting prints (%s):
{chr(10).join(print_lines)}
 *
{chr(10).join(input_lines)}
 *
 * Cheat audit:
 * - Per-iteration helper calls: no
 * - table[d[i]] argument selections: no
{hybrid_expr_line}
{c_eval_line}
{input_semantics_line}
{backend_line}
{vm_pure_line}
{host_snapshot_line}
{tape_change_line}
 */

static signed char d[{parsed.tape_size}] = {{{init_vals}}};
static const char z[] = "";
{reset_decl}

static const char *fmt =
{fmt_c}
;

int main(void) {{
{loop_block}
    return 0;
}}
"""
    return out


def compile_one(
    src: pathlib.Path,
    out_dir: pathlib.Path,
    purity_mode: str,
    vm_pure: bool,
    vm_pure_backend: str,
    reject_delta_compiler: bool = False,
    quiet: bool = False,
) -> pathlib.Path:
    parsed = parse_source(
        src,
        purity_mode=purity_mode,
        vm_pure=vm_pure,
        vm_pure_backend=vm_pure_backend,
    )
    emitted = emit_c(parsed, reject_delta_compiler=reject_delta_compiler)
    out_path = out_dir / (src.stem + ".pop.c")
    out_path.write_text(emitted, encoding="utf-8")
    if not quiet:
        print(f"compiled {src} -> {out_path}")
    return out_path


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Compile restricted C subset into POP C")
    ap.add_argument("inputs", nargs="+", help="Input .c subset files")
    ap.add_argument("-o", "--out-dir", default="generated", help="Output directory")
    ap.add_argument(
        "--purity",
        choices=("strict", "hybrid"),
        default="strict",
        help="strict rejects comparison/boolean operators in expressions",
    )
    ap.add_argument(
        "--vm-pure",
        action="store_true",
        help=(
            "reject C-evaluated expressions in assignments/print gates "
            "(only constants/raw d[idx])"
        ),
    )
    ap.add_argument(
        "--vm-pure-backend",
        choices=("simple", "micro", "phase", "vm"),
        default="simple",
        help=(
            "vm-pure lowering backend: simple (raw constants/d[idx] only) "
            "or experimental micro/phase/vm backends"
        ),
    )
    ap.add_argument(
        "--reject-delta-compiler",
        action="store_true",
        help=(
            "hard-fail if non-vm-pure backend lowering needs "
            "C-side write-delta construction (%%w[i]-%%w[i-1])"
        ),
    )
    ap.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = ap.parse_args(argv)

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.vm_pure and args.vm_pure_backend in {"micro", "phase", "vm"} and not args.quiet:
        print(
            "warning: selected vm-pure backend is experimental and still under validation",
            file=sys.stderr,
        )

    ok = True
    for inp in args.inputs:
        src = pathlib.Path(inp)
        try:
            compile_one(
                src,
                out_dir,
                purity_mode=args.purity,
                vm_pure=args.vm_pure,
                vm_pure_backend=args.vm_pure_backend,
                reject_delta_compiler=args.reject_delta_compiler,
                quiet=args.quiet,
            )
        except CompileError as exc:
            ok = False
            print(f"error: {src}: {exc}", file=sys.stderr)
        except OSError as exc:
            ok = False
            print(f"error: {src}: {exc}", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
