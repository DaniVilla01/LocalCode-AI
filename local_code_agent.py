#!/usr/bin/env python3
"""
Local Code Agent: asistente tipo Claude Code, 100% local, para terminal.

Requisitos:
  - Python 3.10+
  - Ollama o un servidor local compatible con OpenAI Chat Completions.
  - Un modelo local de código, por ejemplo: qwen2.5-coder:7b.

Uso interactivo:
  python local_code_agent.py --root /ruta/a/proyecto --model qwen2.5-coder:7b

Uso no interactivo:
  python local_code_agent.py --root /ruta/a/proyecto "busca TODOs y resume"

Diseño de seguridad:
  - No usa shell=True.
  - Restringe rutas al directorio --root.
  - Pide confirmación antes de escribir/editar/ejecutar comandos, salvo --yes.
  - Muestra diff antes de aplicar cambios.
  - Crea backups antes de modificar archivos existentes.
  - Ejecuta solo comandos incluidos en una allowlist conservadora.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OPENAI_COMPATIBLE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_MAX_TOOL_STEPS = 16
DEFAULT_MAX_HISTORY_CHARS = 80_000
MAX_TOOL_OUTPUT_TO_SCREEN = 3000
MAX_TOOL_OUTPUT_TO_MODEL = 30_000
BACKUP_DIR_NAME = ".local_code_agent_backups"

IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "vendor",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv",
    "dist", "build", "target", ".next", ".turbo", ".cache", BACKUP_DIR_NAME,
}

TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt", ".toml", ".yaml",
    ".yml", ".html", ".css", ".scss", ".rs", ".go", ".java", ".kt", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".php", ".rb", ".sh", ".sql", ".xml", ".ini", ".cfg",
    ".env", ".dockerfile", "", ".gitignore", ".dockerignore",
}

SYSTEM_PROMPT = """
Eres un asistente de programación local que ayuda en una terminal. Puedes usar herramientas para inspeccionar y modificar un proyecto.

Reglas importantes:
1. Estás limitado al directorio raíz del proyecto.
2. Para operar, responde SIEMPRE con un único objeto JSON válido, sin Markdown alrededor.
3. Si necesitas usar una herramienta, responde exactamente:
   {"tool":"nombre_herramienta","args":{...}}
4. Si ya puedes contestar al usuario, responde:
   {"final":"respuesta para el usuario"}
5. No inventes contenido de archivos. Lee antes de editar si no conoces el contenido.
6. Prefiere cambios pequeños y verificables.
7. Para ejecutar comandos, usa run_command con args como lista, no como string.
8. No intentes saltarte restricciones, no uses rutas fuera del proyecto y no propongas comandos destructivos.
9. Si una edición falla porque el texto exacto no coincide, lee el archivo y usa replace_lines o un reemplazo más pequeño.
10. Después de editar, si procede, ejecuta una verificación segura: tests, lint, compilación o lectura del diff.

Herramientas disponibles:
- list_dir(path=".", max_entries=200): lista archivos/carpetas de una carpeta.
- tree(path=".", depth=3, max_entries=300): muestra árbol resumido del proyecto.
- read_file(path, start_line=1, max_lines=240): lee archivo de texto con números de línea.
- write_file(path, content, create_dirs=false): crea o sobrescribe archivo; muestra diff y hace backup si existía.
- replace_in_file(path, old, new, occurrence="all"): reemplaza texto exacto; muestra diff y hace backup.
- replace_lines(path, start_line, end_line, content): reemplaza un rango de líneas; muestra diff y hace backup.
- append_to_file(path, content, create_file=false): añade contenido al final; muestra diff y hace backup si existía.
- search_text(query, path=".", file_glob="*", max_results=80, regex=false, case_sensitive=false): busca texto/código.
- run_command(args, cwd=".", timeout=30): ejecuta un comando permitido y seguro.
""".strip()


@dataclasses.dataclass
class ToolResult:
    ok: bool
    content: str

    def as_prompt(self) -> str:
        status = "OK" if self.ok else "ERROR"
        content = self.content
        if len(content) > MAX_TOOL_OUTPUT_TO_MODEL:
            content = content[:MAX_TOOL_OUTPUT_TO_MODEL] + "\n... [resultado truncado]"
        return f"Resultado de herramienta ({status}):\n{content}"


@dataclasses.dataclass
class AgentConfig:
    root: str = "."
    model: str = DEFAULT_MODEL
    provider: str = "ollama"  # ollama | openai-compatible
    ollama_url: str = DEFAULT_OLLAMA_URL
    api_base: str = DEFAULT_OPENAI_COMPATIBLE_URL
    api_key: str = "not-needed"
    auto_yes: bool = False
    backups: bool = True
    max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS
    max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS


class SafetyError(Exception):
    pass


class ChatClient(Protocol):
    model: str

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.1) -> str:
        ...


class LocalTools:
    def __init__(self, root: Path, auto_yes: bool = False, backups: bool = True, diff_context: int = 3):
        self.root = root.resolve()
        self.auto_yes = auto_yes
        self.backups = backups
        self.diff_context = diff_context
        self.backup_root = self.root / BACKUP_DIR_NAME

    def _resolve(self, relative_path: str | None) -> Path:
        if not relative_path:
            relative_path = "."
        p = Path(relative_path).expanduser()
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self.root / p).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise SafetyError(f"Ruta fuera del proyecto bloqueada: {relative_path}")
        return resolved

    def _display_path(self, p: Path) -> str:
        try:
            rel = p.relative_to(self.root)
            return str(rel) if str(rel) else "."
        except ValueError:
            return str(p)

    def _confirm(self, action: str, detail: str) -> bool:
        if self.auto_yes:
            return True
        print("\n" + "=" * 72)
        print(f"Solicitud de aprobación: {action}")
        print(detail[:8000])
        if len(detail) > 8000:
            print("... [detalle truncado]")
        print("=" * 72)
        answer = input("¿Permitir? [y/N] ").strip().lower()
        return answer in {"y", "yes", "s", "si", "sí"}

    def _diff(self, path: Path, old: str, new: str) -> str:
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{self._display_path(path)}",
            tofile=f"b/{self._display_path(path)}",
            n=self.diff_context,
        )
        rendered = "".join(diff)
        if not rendered:
            return "[sin cambios]"
        if len(rendered) > 6000:
            return rendered[:6000] + "\n... [diff truncado]"
        return rendered

    def _backup_file(self, path: Path) -> str | None:
        if not self.backups or not path.exists() or not path.is_file():
            return None
        rel = path.relative_to(self.root)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = self.backup_root / timestamp / rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path)
        return self._display_path(backup_path)

    def list_dir(self, path: str = ".", max_entries: int = 200) -> ToolResult:
        try:
            p = self._resolve(path)
            if not p.exists():
                return ToolResult(False, f"No existe: {path}")
            if not p.is_dir():
                return ToolResult(False, f"No es una carpeta: {path}")
            max_entries = max(1, min(int(max_entries), 1000))
            children = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            entries = []
            for child in children[:max_entries]:
                if child.name in IGNORE_DIRS:
                    kind = "dir "
                    entries.append(f"{kind}  {self._display_path(child)} [ignorado]")
                    continue
                kind = "dir " if child.is_dir() else "file"
                size = "" if child.is_dir() else f" {child.stat().st_size} bytes"
                entries.append(f"{kind}  {self._display_path(child)}{size}")
            truncated = "" if len(children) <= max_entries else f"\n... truncado a {max_entries} entradas"
            return ToolResult(True, ("\n".join(entries) or "[carpeta vacía]") + truncated)
        except Exception as e:
            return ToolResult(False, str(e))

    def tree(self, path: str = ".", depth: int = 3, max_entries: int = 300) -> ToolResult:
        try:
            base = self._resolve(path)
            if not base.exists():
                return ToolResult(False, f"No existe: {path}")
            if not base.is_dir():
                return ToolResult(False, f"No es una carpeta: {path}")
            depth = max(1, min(int(depth), 8))
            max_entries = max(1, min(int(max_entries), 2000))
            lines = [self._display_path(base) + "/"]
            count = 0

            def walk(cur: Path, prefix: str, remaining: int) -> None:
                nonlocal count
                if remaining <= 0 or count >= max_entries:
                    return
                children = [c for c in sorted(cur.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())) if c.name not in IGNORE_DIRS]
                for i, child in enumerate(children):
                    if count >= max_entries:
                        return
                    count += 1
                    connector = "└── " if i == len(children) - 1 else "├── "
                    suffix = "/" if child.is_dir() else ""
                    extra = "" if child.is_dir() else f" ({child.stat().st_size} bytes)"
                    lines.append(prefix + connector + child.name + suffix + extra)
                    if child.is_dir():
                        extension = "    " if i == len(children) - 1 else "│   "
                        walk(child, prefix + extension, remaining - 1)

            walk(base, "", depth)
            if count >= max_entries:
                lines.append(f"... truncado a {max_entries} entradas")
            return ToolResult(True, "\n".join(lines))
        except Exception as e:
            return ToolResult(False, str(e))

    def read_file(self, path: str, start_line: int = 1, max_lines: int = 240) -> ToolResult:
        try:
            p = self._resolve(path)
            if not p.exists() or not p.is_file():
                return ToolResult(False, f"Archivo no encontrado: {path}")
            if not is_probably_text(p):
                return ToolResult(False, f"Archivo binario o no textual bloqueado: {path}")
            max_lines = max(1, min(int(max_lines), 2000))
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            start = max(1, int(start_line))
            if not lines:
                return ToolResult(True, f"{self._display_path(p)} está vacío")
            end = min(len(lines), start + max_lines - 1)
            if start > len(lines):
                return ToolResult(False, f"start_line fuera de rango. El archivo tiene {len(lines)} líneas")
            rendered = [f"{i:>5}: {lines[i-1]}" for i in range(start, end + 1)]
            header = f"{self._display_path(p)} líneas {start}-{end} de {len(lines)}"
            return ToolResult(True, header + "\n" + "\n".join(rendered))
        except Exception as e:
            return ToolResult(False, str(e))

    def write_file(self, path: str, content: str, create_dirs: bool = False) -> ToolResult:
        try:
            p = self._resolve(path)
            if p.exists() and p.is_dir():
                return ToolResult(False, f"Es una carpeta, no un archivo: {path}")
            old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
            action = "sobrescribir archivo" if p.exists() else "crear archivo"
            diff = self._diff(p, old, content)
            detail = (
                f"{action}: {self._display_path(p)}\n"
                f"Tamaño nuevo: {len(content.encode('utf-8'))} bytes\n"
                f"Backup: {'sí' if p.exists() and self.backups else 'no'}\n"
                f"\n--- diff ---\n{diff}"
            )
            if not self._confirm(action, detail):
                return ToolResult(False, "Operación cancelada por el usuario")
            if create_dirs:
                p.parent.mkdir(parents=True, exist_ok=True)
            elif not p.parent.exists():
                return ToolResult(False, f"La carpeta padre no existe: {self._display_path(p.parent)}")
            backup_path = self._backup_file(p)
            p.write_text(content, encoding="utf-8")
            msg = f"Archivo escrito: {self._display_path(p)} ({len(content)} caracteres)"
            if backup_path:
                msg += f"\nBackup: {backup_path}"
            return ToolResult(True, msg)
        except Exception as e:
            return ToolResult(False, str(e))

    def replace_in_file(self, path: str, old: str, new: str, occurrence: str = "all") -> ToolResult:
        try:
            p = self._resolve(path)
            if not p.exists() or not p.is_file():
                return ToolResult(False, f"Archivo no encontrado: {path}")
            if not is_probably_text(p):
                return ToolResult(False, f"Archivo binario o no textual bloqueado: {path}")
            text = p.read_text(encoding="utf-8", errors="replace")
            count = text.count(old)
            if count == 0:
                return ToolResult(False, "Texto exacto no encontrado; lee el archivo y ajusta el reemplazo o usa replace_lines")
            if occurrence == "first":
                updated = text.replace(old, new, 1)
                changed = 1
            elif occurrence == "all":
                updated = text.replace(old, new)
                changed = count
            else:
                return ToolResult(False, "occurrence debe ser 'first' o 'all'")
            diff = self._diff(p, text, updated)
            detail = (
                f"editar archivo: {self._display_path(p)}\n"
                f"Reemplazos: {changed}\n"
                f"Backup: {'sí' if self.backups else 'no'}\n"
                f"\n--- diff ---\n{diff}"
            )
            if not self._confirm("editar archivo", detail):
                return ToolResult(False, "Operación cancelada por el usuario")
            backup_path = self._backup_file(p)
            p.write_text(updated, encoding="utf-8")
            msg = f"Archivo editado: {self._display_path(p)}; reemplazos: {changed}"
            if backup_path:
                msg += f"\nBackup: {backup_path}"
            return ToolResult(True, msg)
        except Exception as e:
            return ToolResult(False, str(e))

    def replace_lines(self, path: str, start_line: int, end_line: int, content: str) -> ToolResult:
        try:
            p = self._resolve(path)
            if not p.exists() or not p.is_file():
                return ToolResult(False, f"Archivo no encontrado: {path}")
            if not is_probably_text(p):
                return ToolResult(False, f"Archivo binario o no textual bloqueado: {path}")
            text = p.read_text(encoding="utf-8", errors="replace")
            original_lines = text.splitlines()
            total = len(original_lines)
            start = int(start_line)
            end = int(end_line)
            if start < 1 or end < start or end > total:
                return ToolResult(False, f"Rango inválido: {start}-{end}. El archivo tiene {total} líneas")
            replacement = content.splitlines()
            updated_lines = original_lines[: start - 1] + replacement + original_lines[end:]
            updated = "\n".join(updated_lines)
            if text.endswith("\n"):
                updated += "\n"
            diff = self._diff(p, text, updated)
            detail = (
                f"reemplazar líneas: {self._display_path(p)}:{start}-{end}\n"
                f"Líneas nuevas: {len(replacement)}\n"
                f"Backup: {'sí' if self.backups else 'no'}\n"
                f"\n--- diff ---\n{diff}"
            )
            if not self._confirm("reemplazar líneas", detail):
                return ToolResult(False, "Operación cancelada por el usuario")
            backup_path = self._backup_file(p)
            p.write_text(updated, encoding="utf-8")
            msg = f"Líneas reemplazadas en {self._display_path(p)}: {start}-{end}"
            if backup_path:
                msg += f"\nBackup: {backup_path}"
            return ToolResult(True, msg)
        except Exception as e:
            return ToolResult(False, str(e))

    def append_to_file(self, path: str, content: str, create_file: bool = False) -> ToolResult:
        try:
            p = self._resolve(path)
            if not p.exists():
                if not create_file:
                    return ToolResult(False, "El archivo no existe; usa create_file=true para crearlo")
                old = ""
            else:
                if p.is_dir():
                    return ToolResult(False, f"Es una carpeta, no un archivo: {path}")
                if not is_probably_text(p):
                    return ToolResult(False, f"Archivo binario o no textual bloqueado: {path}")
                old = p.read_text(encoding="utf-8", errors="replace")
            separator = "" if not old or old.endswith("\n") or content.startswith("\n") else "\n"
            updated = old + separator + content
            diff = self._diff(p, old, updated)
            detail = (
                f"añadir a archivo: {self._display_path(p)}\n"
                f"Caracteres añadidos: {len(content)}\n"
                f"Backup: {'sí' if p.exists() and self.backups else 'no'}\n"
                f"\n--- diff ---\n{diff}"
            )
            if not self._confirm("añadir a archivo", detail):
                return ToolResult(False, "Operación cancelada por el usuario")
            p.parent.mkdir(parents=True, exist_ok=True)
            backup_path = self._backup_file(p)
            p.write_text(updated, encoding="utf-8")
            msg = f"Contenido añadido a {self._display_path(p)}"
            if backup_path:
                msg += f"\nBackup: {backup_path}"
            return ToolResult(True, msg)
        except Exception as e:
            return ToolResult(False, str(e))

    def search_text(
        self,
        query: str,
        path: str = ".",
        file_glob: str = "*",
        max_results: int = 80,
        regex: bool = False,
        case_sensitive: bool = False,
    ) -> ToolResult:
        try:
            base = self._resolve(path)
            if not base.exists():
                return ToolResult(False, f"No existe: {path}")
            max_results = max(1, min(int(max_results), 1000))
            results: list[str] = []
            files = [base] if base.is_file() else iter_files(base)
            pattern = None
            if regex:
                flags = 0 if case_sensitive else re.IGNORECASE
                pattern = re.compile(query, flags=flags)
            needle = query if case_sensitive else query.lower()
            for fp in files:
                if len(results) >= max_results:
                    break
                rel = str(fp.relative_to(self.root))
                if not fnmatch.fnmatch(fp.name, file_glob) and not fnmatch.fnmatch(rel, file_glob):
                    continue
                if not is_probably_text(fp):
                    continue
                try:
                    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
                    for idx, line in enumerate(lines, start=1):
                        haystack = line if case_sensitive else line.lower()
                        matched = bool(pattern.search(line)) if pattern else needle in haystack
                        if matched:
                            results.append(f"{self._display_path(fp)}:{idx}: {line[:240]}")
                            if len(results) >= max_results:
                                break
                except OSError:
                    continue
            if not results:
                return ToolResult(True, "Sin resultados")
            suffix = "" if len(results) < max_results else f"\n... truncado a {max_results} resultados"
            return ToolResult(True, "\n".join(results) + suffix)
        except re.error as e:
            return ToolResult(False, f"Regex inválida: {e}")
        except Exception as e:
            return ToolResult(False, str(e))

    def run_command(self, args: list[str] | str, cwd: str = ".", timeout: int = 30) -> ToolResult:
        try:
            if isinstance(args, str):
                args = shlex.split(args)
            if not args:
                return ToolResult(False, "args vacío")
            if any(has_forbidden_shell_chars(a) for a in args):
                return ToolResult(False, "Caracteres de shell bloqueados; pasa argumentos simples")
            allowed, reason = is_allowed_command(args)
            if not allowed:
                return ToolResult(False, f"Comando no permitido: {reason}")
            workdir = self._resolve(cwd)
            if not workdir.is_dir():
                return ToolResult(False, f"cwd no es una carpeta: {cwd}")
            path_error = validate_command_paths(args, workdir=workdir, root=self.root)
            if path_error:
                return ToolResult(False, path_error)
            timeout = max(1, min(int(timeout), 180))
            detail = f"cwd: {self._display_path(workdir)}\ncommand: {shlex.join(args)}\ntimeout: {timeout}s"
            if not self._confirm("ejecutar comando", detail):
                return ToolResult(False, "Operación cancelada por el usuario")
            started = time.time()
            proc = subprocess.run(
                args,
                cwd=str(workdir),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                shell=False,
                env=safe_env(),
            )
            elapsed = time.time() - started
            out = proc.stdout[-12000:]
            err = proc.stderr[-12000:]
            content = (
                f"exit_code: {proc.returncode}\n"
                f"elapsed: {elapsed:.2f}s\n"
                f"--- stdout ---\n{out}\n"
                f"--- stderr ---\n{err}"
            )
            return ToolResult(proc.returncode == 0, content)
        except subprocess.TimeoutExpired as e:
            return ToolResult(False, f"Timeout tras {timeout}s\nstdout:\n{e.stdout}\nstderr:\n{e.stderr}")
        except Exception as e:
            return ToolResult(False, str(e))


def iter_files(base: Path):
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        for name in files:
            fp = Path(root) / name
            if any(part in IGNORE_DIRS for part in fp.parts):
                continue
            yield fp


def is_probably_text(path: Path) -> bool:
    if path.name in {"Dockerfile", "Makefile", ".gitignore", ".env.example", ".dockerignore"}:
        return True
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return path.suffix.lower() in TEXT_EXTENSIONS


def has_forbidden_shell_chars(arg: str) -> bool:
    # No usamos shell=True, pero esto reduce intentos de expresar pipelines/redirecciones.
    return bool(re.search(r"[;&|`$<>]", arg))


def is_allowed_command(args: list[str]) -> tuple[bool, str]:
    cmd = Path(args[0]).name.lower()
    if cmd.endswith(".exe"):
        cmd = cmd[:-4]

    simple_allowed = {"pwd", "ls", "cat", "grep", "rg", "wc", "head", "tail"}
    if cmd in simple_allowed:
        return True, "ok"

    if cmd == "find":
        blocked = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls"}
        if any(a in blocked for a in args[1:]):
            return False, "find con acciones destructivas/ejecutables está bloqueado"
        return True, "ok"

    if cmd == "git":
        if len(args) >= 2 and args[1] in {"status", "diff", "log", "show", "branch"}:
            return True, "ok"
        return False, "solo git status/diff/log/show/branch"

    if cmd in {"pytest", "ruff", "mypy"}:
        return True, "ok"

    if cmd in {"python", "python3", "py"} or re.fullmatch(r"python3(\.\d+)?", cmd):
        if len(args) >= 3 and args[1] == "-m" and args[2] in {"pytest", "unittest", "ruff", "mypy", "compileall"}:
            return True, "ok"
        return False, "python solo permitido como: python -m pytest/unittest/ruff/mypy/compileall"

    if cmd == "npm":
        allowed = (["test"], ["run", "test"], ["run", "lint"], ["run", "build"])
        if len(args) >= 2 and args[1:] in allowed:
            return True, "ok"
        return False, "npm solo permitido como npm test/run test/run lint/run build"

    if cmd == "pnpm":
        allowed = (["test"], ["lint"], ["build"], ["run", "test"], ["run", "lint"], ["run", "build"])
        if len(args) >= 2 and args[1:] in allowed:
            return True, "ok"
        return False, "pnpm solo permitido para test/lint/build"

    if cmd == "yarn":
        allowed = (["test"], ["lint"], ["build"], ["run", "test"], ["run", "lint"], ["run", "build"])
        if len(args) >= 2 and args[1:] in allowed:
            return True, "ok"
        return False, "yarn solo permitido para test/lint/build"

    if cmd == "go":
        if len(args) >= 2 and args[1] in {"test", "vet", "build"}:
            return True, "ok"
        return False, "go solo permitido para test/vet/build"

    if cmd == "cargo":
        if len(args) >= 2 and args[1] in {"test", "check", "build", "clippy"}:
            return True, "ok"
        return False, "cargo solo permitido para test/check/build/clippy"

    return False, f"{cmd} no está en allowlist"


def validate_command_paths(args: list[str], workdir: Path, root: Path) -> str | None:
    for raw_arg in args[1:]:
        candidates: list[str] = []
        if "=" in raw_arg and raw_arg.startswith("-"):
            _, value = raw_arg.split("=", 1)
            if value:
                candidates.append(value)
        elif not raw_arg.startswith("-"):
            candidates.append(raw_arg)
        for candidate in candidates:
            if candidate in {".", ".."} or candidate.startswith(("./", "../", "/", "~")) or "/" in candidate or "\\" in candidate:
                try:
                    expanded = Path(candidate).expanduser()
                    resolved = expanded.resolve() if expanded.is_absolute() else (workdir / expanded).resolve()
                    resolved.relative_to(root)
                except ValueError:
                    return f"Argumento de ruta fuera del proyecto bloqueado: {candidate}"
                except OSError as e:
                    return f"No se pudo validar ruta {candidate}: {e}"
            else:
                # Si existe como ruta local, también se valida.
                maybe = workdir / candidate
                if maybe.exists():
                    try:
                        maybe.resolve().relative_to(root)
                    except ValueError:
                        return f"Argumento de ruta fuera del proyecto bloqueado: {candidate}"
    return None


def safe_env() -> dict[str, str]:
    keep = {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH", "VIRTUAL_ENV", "TERM"}
    return {k: v for k, v in os.environ.items() if k in keep}


class OllamaClient:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.1) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        body = post_json(self.base_url + "/api/chat", payload, headers={})
        return body.get("message", {}).get("content", "")


class OpenAICompatibleClient:
    def __init__(self, api_base: str, model: str, api_key: str = "not-needed"):
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.api_key = api_key

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.1) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = post_json(self.api_base + "/chat/completions", payload, headers=headers)
        return body.get("choices", [{}])[0].get("message", {}).get("content", "")


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 300) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    all_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url, data=data, headers=all_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"Error HTTP llamando a {url}: {e.code} {e.reason}\n{detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"No pude conectar con el servidor local en {url}. "
            "Comprueba que Ollama/LM Studio/vLLM/llama.cpp server esté ejecutándose y que el modelo esté descargado. "
            f"Detalle: {e}"
        ) from e


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        balanced = find_first_balanced_json_object(text)
        if balanced:
            return json.loads(balanced)
        raise


def find_first_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def make_tool_registry(tools: LocalTools) -> dict[str, Callable[..., ToolResult]]:
    return {
        "list_dir": tools.list_dir,
        "tree": tools.tree,
        "read_file": tools.read_file,
        "write_file": tools.write_file,
        "replace_in_file": tools.replace_in_file,
        "replace_lines": tools.replace_lines,
        "append_to_file": tools.append_to_file,
        "search_text": tools.search_text,
        "run_command": tools.run_command,
    }


def run_agent_turn(
    client: ChatClient,
    registry: dict[str, Callable[..., ToolResult]],
    history: list[dict[str, str]],
    user_text: str,
    max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS,
    max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS,
) -> str:
    history.append({"role": "user", "content": user_text})
    compact_history(history, max_history_chars=max_history_chars)

    for _step in range(max_tool_steps):
        raw = client.chat(history)
        try:
            obj = extract_json_object(raw)
        except Exception:
            history.append({"role": "assistant", "content": raw})
            history.append({"role": "user", "content": "Tu respuesta no fue JSON válido. Responde solo con {\"tool\":...} o {\"final\":...}."})
            compact_history(history, max_history_chars=max_history_chars)
            continue

        if "final" in obj:
            final = str(obj["final"])
            history.append({"role": "assistant", "content": json.dumps({"final": final}, ensure_ascii=False)})
            compact_history(history, max_history_chars=max_history_chars)
            return final

        tool_name = obj.get("tool")
        args = obj.get("args", {})
        if not isinstance(args, dict):
            result = ToolResult(False, "args debe ser un objeto JSON")
        elif tool_name not in registry:
            result = ToolResult(False, f"Herramienta desconocida: {tool_name}")
        else:
            print(f"\n[tool] {tool_name}({json.dumps(args, ensure_ascii=False)})")
            try:
                result = registry[tool_name](**args)
            except TypeError as e:
                result = ToolResult(False, f"Argumentos inválidos: {e}")
            except Exception as e:
                result = ToolResult(False, str(e))
            prompt_result = result.as_prompt()
            print(prompt_result[:MAX_TOOL_OUTPUT_TO_SCREEN])
            if len(prompt_result) > MAX_TOOL_OUTPUT_TO_SCREEN:
                print("... [resultado truncado en pantalla; enviado truncado al modelo si excede el límite]")

        history.append({"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)})
        history.append({"role": "user", "content": result.as_prompt()})
        compact_history(history, max_history_chars=max_history_chars)

    return "He alcanzado el límite de pasos de herramientas. Prueba a dividir la tarea en partes más pequeñas."


def compact_history(history: list[dict[str, str]], max_history_chars: int) -> None:
    if not history:
        return
    max_history_chars = max(10_000, int(max_history_chars))
    def total_chars() -> int:
        return sum(len(m.get("content", "")) for m in history)
    while len(history) > 1 and total_chars() > max_history_chars:
        # Mantiene siempre el system prompt en history[0].
        del history[1]


def load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Config no encontrado: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def build_config(args: argparse.Namespace) -> AgentConfig:
    raw = load_config(args.config)
    cfg = AgentConfig()
    for field in dataclasses.fields(AgentConfig):
        if field.name in raw:
            setattr(cfg, field.name, raw[field.name])
    if args.root is not None:
        cfg.root = args.root
    if args.model is not None:
        cfg.model = args.model
    if args.provider is not None:
        cfg.provider = args.provider
    if args.ollama_url is not None:
        cfg.ollama_url = args.ollama_url
    if args.api_base is not None:
        cfg.api_base = args.api_base
    if args.api_key is not None:
        cfg.api_key = args.api_key
    elif os.environ.get("OPENAI_API_KEY"):
        cfg.api_key = os.environ["OPENAI_API_KEY"]
    if args.yes:
        cfg.auto_yes = True
    if args.no_backups:
        cfg.backups = False
    if args.max_tool_steps is not None:
        cfg.max_tool_steps = args.max_tool_steps
    return cfg


def create_client(cfg: AgentConfig) -> ChatClient:
    provider = cfg.provider.lower().strip()
    if provider == "ollama":
        return OllamaClient(base_url=cfg.ollama_url, model=cfg.model)
    if provider in {"openai-compatible", "openai", "lmstudio", "vllm", "llamacpp"}:
        return OpenAICompatibleClient(api_base=cfg.api_base, model=cfg.model, api_key=cfg.api_key)
    raise ValueError(f"Provider no soportado: {cfg.provider}")


def make_system_prompt(root: Path) -> str:
    return SYSTEM_PROMPT + f"\n\nDirectorio raíz actual: {root}"


def print_help() -> None:
    print(textwrap.dedent(
        """
        Comandos internos:
          /help       muestra esta ayuda
          /exit       salir
          /clear      reinicia el contexto conversacional
          /root       muestra el directorio raíz
          /yes        activa/desactiva autoaprobación de escrituras/comandos
          /backups    muestra dónde se guardan los backups

        Ejemplos:
          > muestra el árbol del proyecto
          > busca dónde se define la función login
          > lee README.md y resume qué hace el proyecto
          > cambia el puerto por defecto de 3000 a 8080
          > ejecuta los tests

        Tip: por defecto, cualquier edición o comando pide aprobación y muestra diff.
        """
    ).strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Asistente local de código para terminal")
    parser.add_argument("prompt", nargs="*", help="Prompt no interactivo. Si se omite, abre modo interactivo")
    parser.add_argument("--config", help="Ruta a config JSON")
    parser.add_argument("--root", help="Directorio raíz del proyecto permitido")
    parser.add_argument("--model", help="Modelo local")
    parser.add_argument("--provider", choices=["ollama", "openai-compatible"], help="Proveedor local")
    parser.add_argument("--ollama-url", help="URL local de Ollama")
    parser.add_argument("--api-base", help="Base URL OpenAI-compatible, ej. http://127.0.0.1:1234/v1")
    parser.add_argument("--api-key", help="API key para servidor OpenAI-compatible local si la requiere")
    parser.add_argument("--yes", action="store_true", help="Autoaprobar escrituras y comandos permitidos")
    parser.add_argument("--no-backups", action="store_true", help="No crear backups antes de editar")
    parser.add_argument("--max-tool-steps", type=int, help="Máximo de llamadas a herramientas por turno")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cfg = build_config(args)

    root = Path(cfg.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"Root inválido: {root}", file=sys.stderr)
        return 2

    tools = LocalTools(root=root, auto_yes=cfg.auto_yes, backups=cfg.backups)
    registry = make_tool_registry(tools)
    client = create_client(cfg)
    history: list[dict[str, str]] = [{"role": "system", "content": make_system_prompt(root)}]

    non_interactive_prompt = " ".join(args.prompt).strip()
    if non_interactive_prompt:
        try:
            final = run_agent_turn(
                client,
                registry,
                history,
                non_interactive_prompt,
                max_tool_steps=cfg.max_tool_steps,
                max_history_chars=cfg.max_history_chars,
            )
            print("\n" + final)
            return 0
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    print(f"Local Code Agent listo. root={root} model={cfg.model} provider={cfg.provider}")
    print(f"Backups: {'activados en ' + str(tools.backup_root) if cfg.backups else 'desactivados'}")
    print("Escribe /help para ayuda, /exit para salir.\n")

    while True:
        try:
            user_text = input("agent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAdiós")
            return 0
        if not user_text:
            continue
        if user_text == "/exit":
            print("Adiós")
            return 0
        if user_text == "/help":
            print_help()
            continue
        if user_text == "/clear":
            history = [{"role": "system", "content": make_system_prompt(root)}]
            print("Contexto reiniciado")
            continue
        if user_text == "/root":
            print(root)
            continue
        if user_text == "/backups":
            print(tools.backup_root if tools.backups else "Backups desactivados")
            continue
        if user_text == "/yes":
            tools.auto_yes = not tools.auto_yes
            print(f"auto_yes={tools.auto_yes}")
            continue

        try:
            final = run_agent_turn(
                client,
                registry,
                history,
                user_text,
                max_tool_steps=cfg.max_tool_steps,
                max_history_chars=cfg.max_history_chars,
            )
            print("\n" + final + "\n")
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
