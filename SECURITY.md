# Política de seguridad

Local Code Agent es una herramienta local que permite a un modelo pedir operaciones sobre archivos y comandos. Aunque incluye medidas de seguridad, no debe considerarse un sandbox de sistema operativo.

## Medidas incluidas

- Restricción de rutas al directorio `--root`.
- Ejecución sin `shell=True`.
- Allowlist de comandos.
- Validación básica de rutas en comandos.
- Confirmación humana antes de editar o ejecutar comandos.
- Diff previo antes de modificar archivos.
- Backups automáticos.

## Recomendaciones

- Usa Git además de los backups del agente.
- No actives `--yes` hasta confiar en el flujo.
- Revisa siempre los diffs antes de aprobar.
- Ejecuta el agente en proyectos concretos, no en tu carpeta personal completa.
- No permitas comandos adicionales sin entender sus implicaciones.

## Reportar vulnerabilidades

Si encuentras un problema de seguridad:

1. No publiques un exploit destructivo.
2. Abre un issue privado si tu plataforma lo permite o contacta al mantenedor del repositorio.
3. Incluye pasos de reproducción, sistema operativo y versión del agente.

## Versiones soportadas

Durante la etapa inicial, solo la rama `main` se considera soportada.
