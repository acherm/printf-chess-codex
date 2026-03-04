#!/usr/bin/env python3
"""
CPOP MVP compiler: restricted C subset -> canonical POP C.

Subset:
- optional enum { ... } declarations (for tape indexes/constants)
- one tape declaration: signed/unsigned char d[N] = {...};
- one loop: while (d[0]) { ... }
- loop statements:
  - pop_read_byte(IDX); or pop_read_byte(d[IDX]);  # optional, at most one, first
  - d[IDX] = <expr>;
  - pop_print_if(<expr>, "literal");
  - pop_print("literal");

Expression support for assignments and print gates:
- arithmetic: +, -, *
- bitwise: &, |, ^, <<, >>
- unary: +, -, ~
- comparisons: ==, !=, <, <=, >, >= (result is 0/1, hybrid mode only)
- parentheses, integer constants, enum constants, d[IDX]
"""

from __future__ import annotations

import argparse
import ast
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
    input_idx: Optional[int]
    purity_mode: str
    has_hybrid_expr: bool
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
) -> Tuple[int, Optional[int], List[Stmt]]:
    m = re.search(r"while\s*\(\s*d\s*\[\s*([^\]]+)\s*\]\s*\)\s*\{(.*?)\}", src, flags=re.S)
    if not m:
        raise CompileError("missing while (d[RUN]) { ... } loop")
    run_idx = resolve_idx(m.group(1), constants)
    body = m.group(2)
    stmts: List[Stmt] = []
    input_idx: Optional[int] = None
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
            if input_idx is not None:
                raise CompileError("at most one pop_read_byte is allowed per loop")
            arg = im.group(1).strip()
            dref = re.fullmatch(r"d\s*\[\s*([^\]]+)\s*\]", arg)
            if dref:
                target = resolve_idx(dref.group(1), constants)
            else:
                target = resolve_idx(arg, constants)
            input_idx = target
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
    return run_idx, input_idx, stmts


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


def parse_source(path: pathlib.Path, purity_mode: str) -> Program:
    raw = path.read_text(encoding="utf-8")
    src = strip_comments(raw)
    constants, index_names = parse_enums(src)
    tape_size, init_bytes = parse_tape(src)
    allow_hybrid_ops = purity_mode == "hybrid"
    run_idx, input_idx, loop_stmts = parse_while(src, constants, allow_hybrid_ops)

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
    for st in loop_stmts:
        if isinstance(st, InputStmt):
            if st.target < 0 or st.target >= tape_size:
                raise CompileError(
                    f"input target d[{st.target}] out of bounds (tape size {tape_size})"
                )
        elif isinstance(st, AssignStmt):
            if st.target < 0 or st.target >= tape_size:
                raise CompileError(
                    f"assignment target d[{st.target}] out of bounds (tape size {tape_size})"
                )
            check_expr(st.expr, st.original)
            has_hybrid_expr = has_hybrid_expr or expr_uses_hybrid(st.expr)
        elif isinstance(st, PrintIfStmt):
            check_expr(st.gate, st.original)
            has_hybrid_expr = has_hybrid_expr or expr_uses_hybrid(st.gate)

    return Program(
        src_path=path,
        tape_size=tape_size,
        init_bytes=init_bytes,
        run_idx=run_idx,
        input_idx=input_idx,
        purity_mode=purity_mode,
        has_hybrid_expr=has_hybrid_expr,
        index_names=index_names,
        constants=constants,
        loop_stmts=loop_stmts,
    )


def quote_c_string_for_comment(s: str) -> str:
    return s.replace("*/", "* /")


def emit_c(parsed: Program) -> str:
    writes, render_ops = analyze_program(parsed)
    has_print_if = any(kind == "if" for kind, _, _, _ in render_ops)
    has_input = parsed.input_idx is not None
    has_hybrid_expr = parsed.has_hybrid_expr
    # Purity score for this generated artifact under the POP rubric.
    dim_loop = 2
    dim_mut = 2 if writes else 0
    # Hybrid expressions mean some semantics are computed in C argument expressions.
    dim_ctrl = (1 if has_hybrid_expr else 2) if has_print_if else 0
    dim_engine = 1 if has_hybrid_expr else 2
    dim_rom = 2
    total_score = dim_loop + dim_mut + dim_ctrl + dim_engine + dim_rom
    if total_score >= 9:
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

    write_specs: List[Tuple[int, int, int, str, str]] = []
    prev_val_c = "0"

    for idx, (target, val_c, src_stmt) in enumerate(writes):
        if idx == 0:
            pad_c = c_u8(val_c)
        else:
            pad_c = c_u8(f"({val_c}) - ({prev_val_c})")
        wpos = next_pos
        ppos = next_pos + 1
        next_pos += 2

        args.append(pad_c)
        args.append(f"d + {target}")
        frag = f"%1$*{wpos}$s%{ppos}$hhn"
        fmt_parts.append(frag)
        write_specs.append((target, wpos, ppos, frag, src_stmt))
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

    # Deterministic byte map comment.
    tape_map_lines = []
    for idx in range(parsed.tape_size):
        name = parsed.index_names.get(idx, f"IDX_{idx}")
        tape_map_lines.append(f" * d[{idx}] ({name})")

    write_map_lines = []
    for target, wpos, ppos, frag, src_stmt in write_specs:
        name = parsed.index_names.get(target, f"IDX_{target}")
        write_map_lines.append(
            " * "
            + f"{name} <- from `{quote_c_string_for_comment(src_stmt)}` via `{frag}` "
            + f"(pad arg %{wpos}$, ptr arg %{ppos}$)"
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
        input_name = parsed.index_names.get(parsed.input_idx, f"IDX_{parsed.input_idx}")
        input_lines = [
            " * Raw tape-in (Gate E):",
            f" * d[{parsed.input_idx}] ({input_name}) <- getchar() byte before each printf tick",
            " * EOF is preserved as raw byte value (signed char)EOF; no C-side key semantics.",
        ]
        tape_change_line = (
            f" * - Tape byte changes outside %n writes: d[{parsed.input_idx}] raw input byte only (Gate E exception)"
        )
    else:
        input_lines = [" * Raw tape-in (Gate E): (none)"]
        tape_change_line = " * - Tape byte changes outside %n writes: no"

    hybrid_expr_line = (
        " * - C-side semantic operators (comparison/bool): "
        + ("present (hybrid mode)" if has_hybrid_expr else "none")
    )
    input_semantics_line = " * - C-side input semantics beyond raw tape-in: no"

    loop_src_lines = "\n".join(f" *   {quote_c_string_for_comment(st.original)}" for st in parsed.loop_stmts)

    args_rendered = ",\n               ".join(args)
    if has_input:
        loop_block = (
            "    int in_ch = 0;\n"
            "    while (*d) {\n"
            "        in_ch = getchar();\n"
            f"        d[{parsed.input_idx}] = (signed char)in_ch;\n"
            "        printf(fmt,\n"
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
        canonical_loop_line = (
            f"while (*d) {{ d[{parsed.input_idx}] = (signed char)getchar(); printf(fmt, ARGS); }}"
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
{input_semantics_line}
{tape_change_line}
 */

static signed char d[{parsed.tape_size}] = {{{init_vals}}};
static const char z[] = "";

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
    src: pathlib.Path, out_dir: pathlib.Path, purity_mode: str, quiet: bool = False
) -> pathlib.Path:
    parsed = parse_source(src, purity_mode=purity_mode)
    emitted = emit_c(parsed)
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
    ap.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = ap.parse_args(argv)

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ok = True
    for inp in args.inputs:
        src = pathlib.Path(inp)
        try:
            compile_one(src, out_dir, purity_mode=args.purity, quiet=args.quiet)
        except CompileError as exc:
            ok = False
            print(f"error: {src}: {exc}", file=sys.stderr)
        except OSError as exc:
            ok = False
            print(f"error: {src}: {exc}", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
