from collections.abc import Callable
from functools import wraps
from typing import TypeAlias, TypeVar, get_type_hints

import httpx
from fastapi.params import Query
from pydantic import BaseModel, TypeAdapter
from typing_extensions import TypedDict

JSON: TypeAlias = dict

valid_return_types = (
    BaseModel,
    JSON,
    httpx.Response,
)

P = TypeVar("P", bound=str)
T = TypeVar("T", bound=BaseModel)
R = TypeVar("R", BaseModel, JSON, httpx.Response)


def get_query_params_spec(method) -> dict:
    query_params = {}
    for k, a in method.__annotations__.items():
        match getattr(a, "__metadata__", None):
            case (*_, Query()):
                query_params[k] = a
    return query_params


def get_query_params_type_adapter(method):
    spec = get_query_params_spec(method)
    return TypeAdapter(TypedDict("QueryParams", **spec))


def get(url: str) -> Callable:
    def decorator(request_func: Callable[..., R]) -> Callable[..., R]:
        return_type = get_type_hints(request_func).get("return")

        if not issubclass(return_type, valid_return_types):
            raise ValueError(
                f"You need to specify return typehint using one of the supported types: {valid_return_types}.\n\t"
                f"Type specified is: {return_type}"
            )

        type_adapter = get_query_params_type_adapter(request_func)

        @wraps(request_func)
        def wrapper(self: ApiClient, *args, **kwargs) -> R:
            query_params = type_adapter.validate_python(kwargs)

            response = self._adapter.request(
                "GET",
                url,
                params=type_adapter.dump_python(query_params, by_alias=True),
            )

            response.raise_for_status()

            if issubclass(return_type, BaseModel):
                return return_type.model_validate_json(response.content)
            elif issubclass(return_type, (JSON, dict)):
                return return_type(response.json())
            else:
                return response

        return wrapper

    return decorator


class ApiClient:
    def __init__(self, adapter: httpx.Client):
        self._adapter = adapter
