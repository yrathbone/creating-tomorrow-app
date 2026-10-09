"""One safe way to answer "something broke on our side" (risk-audit finding F-08).

Before, many routes answered with 'Unexpected error: <ExceptionName>: <the exception's own text>'. That text can reveal file
paths, library versions or a fragment of someone's data. Now the visitor gets a plain sentence and a short reference number;
the server log gets the same reference with the kind of error (never the message), so a reported problem can be found.
"""
import secrets

from fastapi import HTTPException


def internal_error(e: BaseException, what: str = "request") -> HTTPException:
    ref = secrets.token_hex(3)
    print(f"[error] ref={ref} what={what} class={type(e).__name__}")
    return HTTPException(
        status_code=500,
        detail=f"Something went wrong on our side (reference {ref}). Please try again. If it keeps happening, tell us the reference.",
    )
