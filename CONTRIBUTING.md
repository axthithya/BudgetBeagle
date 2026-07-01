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

## Roadmap and Documentation Synchronization

Contributors must update README.md and FUTURE_PLAN.md in the same pull request whenever roadmap status, phase status, completed capabilities, current development priorities, supported AWS services, schema versions, stable release versions, or major feature availability changes.

Documentation roles:

- README.md contains the concise public project status.
- FUTURE_PLAN.md contains the long-term public contributor plan.
- docs/PHASE_STATUS.md contains detailed active implementation status.
- docs/ROADMAP.md contains the technical roadmap.
- docs/ARCHITECTURE.md and docs/REPORT_SCHEMA.md describe implementation and schema behavior.

These documents must not contradict one another. If a phase or feature status changes, update all affected documents in the same commit or pull request.

## Pull Request Checklist

- [ ] Changes are scoped to one behavior, feature, or documentation update.
- [ ] README.md and FUTURE_PLAN.md are synchronized when roadmap, phase status, completed capabilities, or current development priorities change.
- [ ] docs/PHASE_STATUS.md and docs/ROADMAP.md are updated when active implementation status or technical scope changes.
- [ ] Backend and frontend checks relevant to the change were run, or any blocked checks are explained.
- [ ] No credentials, full AWS account IDs, exported reports, databases, caches, `node_modules`, `dist`, or `.pytest-tmp` artifacts are staged.
