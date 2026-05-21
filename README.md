# Local Code Agent

Un asistente de programación tipo **Claude Code**, pero **100% local**, para terminal. Usa un modelo local mediante **Ollama** o un servidor local **OpenAI-compatible** —por ejemplo LM Studio, vLLM o llama.cpp server— y herramientas controladas para listar carpetas, leer/editar archivos, buscar código y ejecutar comandos seguros.

## Estado

El proyecto ya es funcional como prototipo local de terminal:

- modo interactivo,
- modo no interactivo,
- lectura y edición de archivos,
- diffs antes de aplicar cambios,
- backups automáticos,
- búsqueda de código,
- árbol de carpetas,
- ejecución de comandos con allowlist,
- soporte para Ollama,
- soporte para servidores locales OpenAI-compatible,
- configuración por JSON.

## Requisitos

- Python 3.10+
- Un servidor local de LLM:
  - recomendado: [Ollama](https://ollama.com/), o
  - LM Studio / vLLM / llama.cpp server con endpoint OpenAI-compatible.
- Un modelo local de código.

Modelo recomendado para empezar:

```bash
ollama pull qwen2.5-coder:7b
ollama serve
```

Otros modelos que suelen funcionar bien para código si tu máquina los soporta:

- `qwen2.5-coder:7b`
- `qwen2.5-coder:14b`
- `deepseek-coder-v2`
- modelos compatibles cargados en LM Studio.

## Uso con Ollama

```bash
cd local-code-agent
python local_code_agent.py --root /ruta/a/tu/proyecto --model qwen2.5-coder:7b
```

Ejemplos dentro del agente:

```text
agent> muestra el árbol del proyecto
agent> busca dónde se define la función login
agent> lee README.md y resume el proyecto
agent> cambia el puerto por defecto de 3000 a 8080
agent> ejecuta los tests
```

## Uso no interactivo

Puedes pasar el prompt directamente:

```bash
python local_code_agent.py --root /ruta/a/proyecto "busca TODOs y resume los más importantes"
```

Si la tarea requiere escribir o ejecutar comandos, seguirá pidiendo confirmación salvo que uses `--yes`.

## Uso con LM Studio u otro servidor OpenAI-compatible

Ejemplo con LM Studio escuchando en `http://127.0.0.1:1234/v1`:

```bash
python local_code_agent.py \
  --provider openai-compatible \
  --api-base http://127.0.0.1:1234/v1 \
  --model tu-modelo-local \
  --root /ruta/a/proyecto
```

## Configuración por JSON

Puedes usar `config.example.json` como base:

```bash
cp config.example.json config.json
python local_code_agent.py --config config.json
```

Ejemplo:

```json
{
  "provider": "ollama",
  "model": "qwen2.5-coder:7b",
  "ollama_url": "http://127.0.0.1:11434",
  "root": "/ruta/a/tu/proyecto",
  "auto_yes": false,
  "backups": true,
  "max_tool_steps": 16,
  "max_history_chars": 80000
}
```

## Comandos internos

```text
/help       muestra ayuda
/exit       salir
/clear      reinicia el contexto conversacional
/root       muestra el directorio raíz
/yes        activa/desactiva autoaprobación de escrituras/comandos
/backups    muestra dónde se guardan los backups
```

## Herramientas internas

El modelo no recibe acceso directo al sistema. Solo puede pedir llamadas JSON a estas herramientas:

```text
list_dir(path=".", max_entries=200)
tree(path=".", depth=3, max_entries=300)
read_file(path, start_line=1, max_lines=240)
write_file(path, content, create_dirs=false)
replace_in_file(path, old, new, occurrence="all")
replace_lines(path, start_line, end_line, content)
append_to_file(path, content, create_file=false)
search_text(query, path=".", file_glob="*", max_results=80, regex=false, case_sensitive=false)
run_command(args, cwd=".", timeout=30)
```

El formato interno es JSON. Por ejemplo:

```json
{"tool":"read_file","args":{"path":"README.md","start_line":1,"max_lines":120}}
```

Para terminar una respuesta:

```json
{"final":"He encontrado la función en src/auth.py..."}
```

## Seguridad incluida

Medidas implementadas:

1. **Sandbox por ruta**: todas las rutas se resuelven dentro de `--root`.
2. **Sin shell**: los comandos se ejecutan con `subprocess.run(..., shell=False)`.
3. **Validación de rutas en comandos**: se bloquean argumentos que apunten fuera del proyecto.
4. **Allowlist de comandos**: solo comandos de inspección, tests, lint y build comunes.
5. **Confirmación humana**: escribir, reemplazar, añadir o ejecutar comandos pide aprobación salvo `--yes`.
6. **Diff previo**: antes de modificar un archivo se muestra un diff unificado.
7. **Backups automáticos**: antes de editar archivos existentes se guarda una copia en `.local_code_agent_backups/`.
8. **Búsquedas prudentes**: ignora `.git`, `node_modules`, `.venv`, `dist`, `build`, `.next`, etc.

> Nota: comandos como `npm run build` o `pytest` pueden ejecutar código del proyecto. Por eso la confirmación humana está activada por defecto.

## Comandos permitidos por defecto

Inspección:

```text
pwd, ls, cat, grep, rg, wc, head, tail, find limitado
```

Git:

```text
git status, git diff, git log, git show, git branch
```

Python:

```text
pytest, ruff, mypy
python -m pytest/unittest/ruff/mypy/compileall
```

JavaScript/TypeScript:

```text
npm test
npm run test
npm run lint
npm run build
pnpm test/lint/build
pnpm run test/lint/build
yarn test/lint/build
yarn run test/lint/build
```

Go/Rust:

```text
go test/vet/build
cargo test/check/build/clippy
```

Puedes ajustar la política editando `is_allowed_command()` en `local_code_agent.py`.

## Backups

Los backups se guardan dentro del proyecto en:

```text
.local_code_agent_backups/
```

Ejemplo:

```text
.local_code_agent_backups/20260521-153012-123456/src/app.py
```

La carpeta de backups se ignora durante búsquedas y árbol del proyecto.

## Recomendaciones de uso

1. Empieza sin `--yes`.
2. Pide cambios pequeños.
3. Revisa el diff antes de aprobar.
4. Pide al agente que ejecute tests/lint tras modificar.
5. Usa Git además de los backups.

## Limitaciones

- No es un sandbox de sistema operativo; es un control de herramientas a nivel de aplicación.
- La calidad depende mucho del modelo local elegido.
- Los modelos pequeños pueden fallar más al seguir el protocolo JSON.
- La edición mediante LLM debe revisarse siempre antes de aprobar.

## Próximas mejoras posibles

- Aplicación de parches unificados estilo `git apply` con parser propio.
- Índice semántico local con embeddings.
- Memoria persistente por proyecto.
- Perfiles de permisos por repositorio.
- UI TUI con panel de diff.
- Integración opcional con Git worktrees o snapshots.

## Crear un ejecutable tipo `.exe`

Sí. La forma más sencilla es usar PyInstaller. El ejecutable generado sigue siendo 100% local, pero **no incluye el modelo LLM dentro**: el `.exe` se conecta a Ollama, LM Studio o tu servidor local igual que el script Python.

### Windows

Desde PowerShell o CMD, dentro de esta carpeta:

```bat
py -3 -m pip install -r requirements-build.txt
build_windows.bat
```

El resultado queda en:

```text
dist\local-code-agent.exe
```

Ejemplo de uso:

```bat
dist\local-code-agent.exe --root C:\ruta\a\tu\proyecto --model qwen2.5-coder:7b
```

O con config:

```bat
dist\local-code-agent.exe --config config.json
```

### Linux/macOS

```bash
./build_unix.sh
```

El resultado queda en:

```text
dist/local-code-agent
```

### Importante sobre compilación cruzada

PyInstaller normalmente **no genera `.exe` de Windows desde Linux/macOS**. Para obtener un `.exe`, compílalo en Windows o usa una pipeline de CI con Windows.

### Falsos positivos de antivirus

Los ejecutables `--onefile` creados con PyInstaller a veces pueden generar falsos positivos en antivirus. Para distribuirlo públicamente, considera:

- firmar el ejecutable,
- compilar en modo carpeta en vez de onefile,
- usar Nuitka como alternativa,
- publicar también el código fuente.

## Publicar en GitHub

Este proyecto ya incluye estructura de repositorio para GitHub:

```text
.github/workflows/ci.yml
.github/workflows/release.yml
.github/ISSUE_TEMPLATE/
.github/pull_request_template.md
.github/dependabot.yml
.gitignore
LICENSE
CONTRIBUTING.md
SECURITY.md
CHANGELOG.md
REPO_SETUP.md
pyproject.toml
MANIFEST.in
tests/
```

Guía rápida:

```bash
git init
git add .
git commit -m "Initial release: local code agent"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/local-code-agent.git
git push -u origin main
```

Consulta `REPO_SETUP.md` para los pasos completos, incluyendo cómo crear releases con binarios para Windows, Linux y macOS.
