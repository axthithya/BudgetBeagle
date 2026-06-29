# Contributing

Thanks for helping improve AI Cloud Cost Detective.

## Issues

- Include your operating system, Python version, Node version, and startup path (`start.sh`, Docker, or manual).
- For AWS scanner issues, include the service name, region, and the sanitized API error shown by the app.
- Never paste AWS secret keys, Groq keys, account IDs, or private resource names into public issues.

## Pull Requests

- Keep changes scoped to one behavior or feature.
- Run the backend syntax check and frontend build before opening a PR:

  ```bash
  py -3 -c "from pathlib import Path; [compile(p.read_text(), str(p), 'exec') for p in Path('backend').glob('*.py')]"
  cd frontend && npm run build
  ```

- Update README or docs when setup, environment variables, API routes, or screenshots change.
- Prefer read-only AWS permissions for tests and examples.

## Security

This project is designed to read AWS metadata and metrics only. Do not add automatic account mutations. Fix commands should remain visible for users to review and run themselves.