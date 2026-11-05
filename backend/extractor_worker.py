"""Child process that reads ONE uploaded file (Word, PDF or text) and prints ONE json line. Started by extractor.extract_text_async.

It is given the file on stdin and a file type as its only argument, runs with no secrets in its environment, and (where the operating
system supports it) with caps on memory, processor time, open files and file size. If the file defeats the reader, only this child
is hurt: the parent kills it on a timeout and answers the visitor with a plain message.

Output, always a single line:  {"outcome": "text", "text": "..."}  or  {"outcome": "refused", "message": "..."}
"""
import json
import sys

MEMORY_MB = 1536
CPU_SECONDS = 25
MAX_FILES = 64


def _limit_resources() -> None:
    try:
        import resource
    except ImportError:  # Windows: the parent's timeout and kill still apply
        return
    for name, value in (("RLIMIT_AS", MEMORY_MB * 1024 * 1024), ("RLIMIT_CPU", CPU_SECONDS), ("RLIMIT_NOFILE", MAX_FILES), ("RLIMIT_FSIZE", 0)):
        try:
            resource.setrlimit(getattr(resource, name), (value, value))
        except (ValueError, OSError, AttributeError):
            pass


def main() -> None:
    suffix = sys.argv[1] if len(sys.argv) > 1 else ""
    data = sys.stdin.buffer.read()
    _limit_resources()
    import extractor  # imported after the limits are set, so its libraries are limited too

    try:
        text = extractor.extract_text("upload." + suffix, data)
        line = {"outcome": "text", "text": text}
    except ValueError as e:
        line = {"outcome": "refused", "message": str(e)}
    sys.stdout.write(json.dumps(line, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
