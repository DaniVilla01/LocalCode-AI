# Changelog

Todos los cambios relevantes de este proyecto se documentarán aquí.

El formato sigue, en lo posible, [Keep a Changelog](https://keepachangelog.com/) y versionado semántico.

## [0.1.0] - 2026-05-21

### Añadido

- Asistente local de código para terminal.
- Soporte para Ollama.
- Soporte para servidores locales OpenAI-compatible.
- Herramientas locales controladas:
  - `list_dir`
  - `tree`
  - `read_file`
  - `write_file`
  - `replace_in_file`
  - `replace_lines`
  - `append_to_file`
  - `search_text`
  - `run_command`
- Diffs antes de aplicar cambios.
- Backups automáticos antes de modificar archivos existentes.
- Modo interactivo y modo no interactivo.
- Configuración mediante JSON.
- Scripts de build con PyInstaller.
- Workflow de CI y workflow de releases para GitHub Actions.
