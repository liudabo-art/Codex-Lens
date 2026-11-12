"""Fixed offline manual resources shared by serving, packaging and checks."""

MANUAL_IMAGES = (
    'overview.png', 'import.png', 'add-target.png', 'target-settings.png',
    'official-reference.png', 'assessment.png', 'exam-budget.png', 'exam-report.png',
    'history-delete.png', 'periodic.png', 'usage.png', 'failure.png',
)
MANUAL_ROUTES = {'manual/content.json': ('manual/content.json', 'application/json; charset=utf-8')}
MANUAL_ROUTES.update({f'manual/{name}': (f'manual/{name}', 'image/png') for name in MANUAL_IMAGES})
