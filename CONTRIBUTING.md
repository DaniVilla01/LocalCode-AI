# Contribuir

Gracias por tu interés en contribuir a Local Code Agent.

## Preparar entorno

```bash
git clone https://github.com/TU_USUARIO/local-code-agent.git
cd local-code-agent
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
```

La aplicación principal usa solo librería estándar. Para construir ejecutables:

```bash
python -m pip install -r requirements-build.txt
```

## Verificaciones locales

```bash
python -m py_compile local_code_agent.py
python -m unittest discover -s tests
```

Si tienes herramientas opcionales:

```bash
python -m ruff check .
python -m mypy local_code_agent.py
```

## Estilo

- Cambios pequeños y revisables.
- Mantén la seguridad por defecto.
- No añadas comandos a la allowlist sin explicar el riesgo.
- Documenta nuevas herramientas en `README.md`.
- Añade tests cuando cambies lógica de rutas, edición o seguridad.

## Pull requests

Incluye:

- Qué problema resuelve.
- Cómo se ha probado.
- Capturas o logs si cambia la experiencia CLI.
- Consideraciones de seguridad si toca herramientas o comandos.
