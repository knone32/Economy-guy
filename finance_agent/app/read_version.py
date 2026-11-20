"""Read-interval metadata shared by cache and evidence; no state owner."""
from pathlib import Path


def book_read_stamp(book):
    """DB/WAL file metadata is not a global transaction revision."""
    stamps = []
    for path in (Path(book), Path(str(book) + '-wal')):
        try:
            info = path.stat()
            stamps.append((info.st_size, info.st_mtime_ns))
        except FileNotFoundError:
            stamps.append(None)
    return tuple(stamps)
