"""Select technical PDFs by explicit path labels, never substrings in part names."""
from pathlib import Path

from .common import norm

EXCLUDED_FOLDERS = {'ARTE', 'ARTES', 'APRESENTACAO', 'APRESENTACOES'}
OBSOLETE_LABELS = {'OBSOLETO', 'OBSOLETOS', 'OBSOLETA', 'OBSOLETAS'}


def is_technical_pdf(relative_path):
    path = Path(relative_path)
    if path.suffix.lower() != '.pdf' or path.name.startswith(('._', '~$')):
        return False
    for part in path.parts[:-1]:
        label = norm(part)
        if label in EXCLUDED_FOLDERS or set(label.split()) & OBSOLETE_LABELS:
            return False
    words = norm(path.stem).split()
    if words and (words[0] in EXCLUDED_FOLDERS or set(words) & OBSOLETE_LABELS):
        return False
    return True
