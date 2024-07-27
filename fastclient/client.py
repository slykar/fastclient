import dataclasses
from collections.abc import Callable
from functools import cached_property, wraps
from typing import Any, Literal, ParamSpec, TypeAlias, TypeVar, get_type_hints

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
class ApiMethodParams:
    body: dict[str, ParamSpec] = dataclasses.field(default_factory=dict)
    path: dict[str, ParamSpec] = dataclasses.field(default_factory=dict)
    query: dict[str, ParamSpec] = dataclasses.field(default_factory=dict)
    header: dict[str, ParamSpec] = dataclasses.field(default_factory=dict)

    @cached_property
    def request(self) -> dict[str, ParamSpec]:
        """Merges all mappings into one"""
        return {**self.path, **self.query, **self.body}

    @staticmethod
    def from_api_method(request_func):
        api_params = ApiMethodParams()
        for param_key, param_spec in request_func.__annotations__.items():
            # TODO: Create a class, so we can do cleaner structural matching instead of this tuple madness
            match_expr = (
                param_key,
                param_spec,
                getattr(param_spec, "__origin__", None),
                getattr(param_spec, "__metadata__", None),
            )
            match match_expr:
                case ("return", _, _, _):
                    # Return type is always under a known value. We get this type by other means.
                    continue
                case (_, _, type() as klass, (*_, fastapi_params.Query())) if issubclass(klass, pydantic.BaseModel):
                    # A model representing multiple query params
                    # TODO: query params from complex models should somehow be merged.
                    # TODO: add a warning if query param name is reused in multiple models (take aliases into account?)
                    # api_params.query[param_key] = param_spec
                    # continue
                    raise NotImplementedError("Multiple query params models are not yet supported.")
                case (_, _, _, (*_, fastapi_params.Param() as param)):
                    # Captures all explicitly annotated params (query, path, header, cookie)
                    getattr(api_params, param.in_.value, {})[param_key] = param_spec
                    continue
                case (_, _, _, (*_, fastapi_params.Body())):
                    # Captures explicitly annotated request body
                    api_params.body[param_key] = param_spec
                    continue
                case (_, type(), _, None):  # TODO: if issubclass(klass, (pydantic.BaseModel, dict))
                    # Simple type annotation. We're looking for Pydantic model, dataclasses, TypedDicts...
                    api_params.body[param_key] = param_spec
                    continue

        return api_params


class ApiMethodTypeAdapters:
    def __init__(self, params: ApiMethodParams):
        self._params = params

    @cached_property
    def request(self) -> TypeAdapter:
        return TypeAdapter(TypedDict("RequestParams", self._params.request))

    @cached_property
    def header(self) -> TypeAdapter | None:
        return TypeAdapter(TypedDict("HeaderParams", self._params.header))

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
        """Get request content as json bytes. Uses Pydantic`s json serialization. Respects aliases."""
        if not self.body:
            return None

        return self.body.dump_json(kwargs, by_alias=True)

    def build_request(self, method: str, url: str, **kwargs) -> httpx.Request:
        return httpx.Request(
            method,
            url=self._build_request_url(url, kwargs),
            params=self._build_query_params(kwargs),
            content=self._build_request_content(kwargs),
            # TODO: smarter header values, when we add support for FormData and files.
            headers={
                "Content-Type": "application/json",
                **self._build_request_headers(kwargs),
            },
        )

    def _build_request_headers(self, kwargs):
        return self.header.dump_python(kwargs) if self.header else None


def api_call(method: Literal["GET", "POST"], url: str):
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

            response = self._adapter.send(type_adapters.build_request(method, url, **validated_params))
            response.raise_for_status()

            if issubclass(return_type, BaseModel):
                return return_type.model_validate_json(response.content)
            elif issubclass(return_type, (JSON, dict)):
                return return_type(response.json())
            else:
                return response

        return wrapper

    return decorator


def get(url: str):
    return api_call("GET", url)


def post(url: str):
    return api_call("POST", url)


class ApiClient:
    def __init__(self, adapter: httpx.Client):
        self._adapter = adapter
