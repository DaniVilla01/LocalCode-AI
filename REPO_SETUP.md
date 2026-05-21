# Publicar este proyecto en GitHub

Esta guía asume que ya tienes una cuenta de GitHub y `git` instalado.

## 1. Crear el repositorio en GitHub

En GitHub:

1. Pulsa **New repository**.
2. Nombre recomendado: `local-code-agent`.
3. Descripción sugerida: `Asistente local de código para terminal, tipo Claude Code, con Ollama y herramientas seguras.`
4. Visibilidad: pública o privada.
5. No marques README, licencia ni `.gitignore`, porque este proyecto ya los incluye.

## 2. Inicializar el repo local

Desde la carpeta `local-code-agent`:

```bash
git init
git add .
git commit -m "Initial release: local code agent"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/local-code-agent.git
git push -u origin main
```

Cambia `TU_USUARIO` por tu usuario u organización de GitHub.

## 3. Verificar CI

Al hacer push, GitHub Actions ejecutará:

- compilación de `local_code_agent.py`,
- tests unitarios,
- prueba de instalación del paquete,
- prueba de `local-code-agent --help`.

Puedes ver el resultado en la pestaña **Actions**.

## 4. Crear una release con binarios

Para generar binarios automáticamente para Windows, Linux y macOS:

```bash
git tag v0.1.0
git push origin v0.1.0
```

El workflow `Build release binaries` creará una GitHub Release con artefactos:

```text
local-code-agent-windows.exe
local-code-agent-linux
local-code-agent-macos
```

## 5. Actualizar URLs del proyecto

Edita `pyproject.toml` y cambia:

```text
https://github.com/TU_USUARIO/local-code-agent
```

por la URL real de tu repositorio.

También puedes actualizar el copyright del `LICENSE` si quieres usar tu nombre.

## 6. Recomendación para el primer release

Antes de etiquetar:

```bash
python -m py_compile local_code_agent.py
python -m unittest discover -s tests
```

Luego:

```bash
git status
git tag v0.1.0
git push origin main --tags
```
