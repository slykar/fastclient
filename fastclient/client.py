import dataclasses
from collections.abc import Callable, Mapping
from functools import cached_property, wraps
from typing import Any, ParamSpec, TypeAlias, TypeVar, get_type_hints

import httpx
import pydantic
from fastapi import params as fastapi_params
from pydantic import BaseModel, TypeAdapter
from typing_extensions import TypedDict

JSON: TypeAlias = dict

valid_return_types = (
    BaseModel,
    JSON,
    httpx.Response,
)

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R", BaseModel, JSON, httpx.Response)
P = ParamSpec("P")


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

    def validate_all(self, kwargs): ...


class GroupedRequestParams(TypedDict, total=False):
    query: Mapping[str, ParamSpec]
    path: Mapping[str, ParamSpec]


AllRequestParams: TypeAlias = Mapping[str, ParamSpec]


# TODO: iterate annotations and gather param descriptors (name, type - query/path/body/httpx.response)
@dataclasses.dataclass
class ApiMethodParams:
    path: dict[str, ParamSpec] = dataclasses.field(default_factory=dict)
    query: dict[str, ParamSpec] = dataclasses.field(default_factory=dict)
    body: dict[str, ParamSpec] = dataclasses.field(default_factory=dict)

    @cached_property
    def request(self) -> dict[str, ParamSpec]:
        """Merges all mappings into one"""
        return {**self.path, **self.query, **self.body}

    @staticmethod
    def from_api_method(request_func):
        api_params = ApiMethodParams()

        for param_key, param_spec in request_func.__annotations__.items():
            match getattr(param_spec, "__metadata__", None):
                case (*_, fastapi_params.Param() as param):
                    getattr(api_params, param.in_.value, {})[param_key] = param_spec
                    continue
                case (*_, pydantic.BaseModel):
                    # this might be body or response
                    api_params.body[param_key] = param_spec

        return api_params


class ApiMethodTypeAdapters:
    def __init__(self, params: ApiMethodParams):
        self._params = params

    @cached_property
    def request(self) -> TypeAdapter:
        return TypeAdapter(TypedDict("RequestParams", self._params.request))

    @cached_property
    def query(self) -> TypeAdapter | None:
        return TypeAdapter(TypedDict("QueryParams", self._params.query))

    @cached_property
    def body(self) -> TypeAdapter | None:
        return TypeAdapter(TypedDict("BodyParams", self._params.body))

    def _build_query_params(self, kwargs) -> dict | None:
        return self.query.dump_python(kwargs, by_alias=True) if self.query else None

    @cached_property
    def path(self) -> TypeAdapter | None:
        return TypeAdapter(TypedDict("PathParams", self._params.path))

    def _build_request_url(self, url: str, kwargs: dict) -> str:
        if not self.path:
            return url

        return url.format(**self.path.dump_python(kwargs))

    def validate_request_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        :raises pydantic.ValidationError: In case of validation results
        :return: Validated data
        """
        return self.request.validate_python(params)

    def _build_request_content(self, kwargs) -> bytes | None:
        if not self.body:
            return None

        return self.body.dump_json(kwargs, by_alias=True)

    def build_request(self, method: str, url: str, **kwargs) -> httpx.Request:
        return httpx.Request(
            method,
            url=self._build_request_url(url, kwargs),
            params=self._build_query_params(kwargs),
            content=self._build_request_content(kwargs),
        )


def get_params_spec(request_func) -> tuple[AllRequestParams, GroupedRequestParams]:
    grouped_params_specs = {}
    request_params_specs = {}

    for param_key, param_spec in request_func.__annotations__.items():
        match getattr(param_spec, "__metadata__", None):
            case (*_, fastapi_params.Param() as param):
                grouped_params_specs.setdefault(param.in_.value, {})[param_key] = param_spec
                request_params_specs[param_key] = param_spec

    return request_params_specs, grouped_params_specs


def get(url: str):
    def decorator(request_func: Callable[..., R]) -> Callable[..., R]:
        return_type = get_type_hints(request_func).get("return")

        if not issubclass(return_type, valid_return_types):
            raise ValueError(
                f"You need to specify return typehint using one of the supported types: {valid_return_types}.\n\t"
                f"Type specified is: {return_type}"
            )

        method_params = ApiMethodParams.from_api_method(request_func)
        type_adapters = ApiMethodTypeAdapters(method_params)

        @wraps(request_func)
        def wrapper(self: ApiClient, *args, **kwargs) -> R:
            validated_params = type_adapters.validate_request_params(kwargs)

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
