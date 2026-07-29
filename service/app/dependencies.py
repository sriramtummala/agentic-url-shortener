from fastapi import Request

from service.app.db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db
