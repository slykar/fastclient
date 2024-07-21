import dataclasses
from collections.abc import Callable, Mapping
from functools import wraps
from typing import ParamSpec, TypeAlias, TypeVar, get_type_hints

import httpx
from fastapi import params as fastapi_params
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


@dataclasses.dataclass
class RequestParamsTypeAdapters:
    all: TypeAdapter
    query: TypeAdapter | None = None
    path: TypeAdapter | None = None

    def build_request(self, method: str, url: str, **kwargs) -> httpx.Request:
        path_params = self.path.dump_python(kwargs) if self.path else None
        query_params = self.query.dump_python(kwargs, by_alias=True) if self.query else None
        return httpx.Request(
            method,
            url=url.format(**path_params) if path_params else url,
            params=query_params,
        )


class GroupedRequestParams(TypedDict, total=False):
    query: Mapping[str, ParamSpec]
    path: Mapping[str, ParamSpec]


AllRequestParams: TypeAlias = Mapping[str, ParamSpec]


def get_params_spec(request_func) -> tuple[AllRequestParams, GroupedRequestParams]:
    grouped_params_specs = {}
    request_params_specs = {}

    for param_key, param_spec in request_func.__annotations__.items():
        match getattr(param_spec, "__metadata__", None):
            case (*_, fastapi_params.Param() as param):
                grouped_params_specs.setdefault(param.in_.value, {})[param_key] = param_spec
                request_params_specs[param_key] = param_spec

    return request_params_specs, grouped_params_specs


def get_request_params_type_adapters(request_func) -> RequestParamsTypeAdapters:
    all_params, grouped_params = get_params_spec(request_func)
    return RequestParamsTypeAdapters(
        all=TypeAdapter(TypedDict("AllParams", all_params)),
        query=TypeAdapter(TypedDict("QueryParams", grouped_params["query"])) if "query" in grouped_params else None,
        path=TypeAdapter(TypedDict("PathParams", grouped_params["path"])) if "path" in grouped_params else None,
    )


def build_request(method: str, url: str, request_kwargs, type_adapters: RequestParamsTypeAdapters): ...


def get(url: str) -> Callable:
    def decorator(request_func: Callable[..., R]) -> Callable[..., R]:
        return_type = get_type_hints(request_func).get("return")

        if not issubclass(return_type, valid_return_types):
            raise ValueError(
                f"You need to specify return typehint using one of the supported types: {valid_return_types}.\n\t"
                f"Type specified is: {return_type}"
            )

        type_adapters = get_request_params_type_adapters(request_func)

        @wraps(request_func)
        def wrapper(self: ApiClient, *args, **kwargs) -> R:
            validated_params = type_adapters.all.validate_python(kwargs)

            response = self._adapter.send(type_adapters.build_request("GET", url, **validated_params))
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
