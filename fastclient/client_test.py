from collections.abc import Callable
from typing import Annotated, Type, TypeVar
from unittest import mock

import httpx
import pydantic
import pytest
from annotated_types import Gt
from pytest_mock import MockerFixture

from fastclient import Path, Query
from fastclient.client import ApiClient, get, get_params_spec

PositiveInt = Annotated[int, Gt(0)]

CT = TypeVar("CT", bound=ApiClient)


@pytest.fixture()
def client_factory(httpx_client) -> Callable[[Type[CT]], CT]:
    return lambda cls: cls(httpx_client)


@pytest.fixture
def httpx_client(mocker: MockerFixture):
    c = httpx.Client(base_url="https://httpbin.org")
    mocker.patch.object(c, "send")
    return c


@pytest.fixture()
def httpx_request(httpx_client: mock.Mock):
    """A handy proxy to a `request` argument of mocked `send` method."""

    class RequestProxy:
        def __getattr__(self, name):
            return getattr(httpx_client.send.call_args.args[0], name)

    return RequestProxy()


def test_query_params_using_kwargs(
    client_factory,
    httpx_request: httpx.Request,
):
    class TestClient(ApiClient):
        @get("/comments")
        def query_params_using_kwargs(
            self, *, qs_test_id: Annotated[PositiveInt, Query(serialization_alias="testID")]
        ) -> httpx.Response: ...

    client = client_factory(TestClient)
    client.query_params_using_kwargs(qs_test_id=42)
    assert b"testID=42" == httpx_request.url.query


def test_path_params_using_kwargs(
    client_factory,
    httpx_request: httpx.Request,
):
    class TestClient(ApiClient):
        @get("/posts/{post_id}/comments")
        def path_params_using_kwargs(self, *, post_id: Annotated[PositiveInt, Path()]) -> httpx.Response: ...

    post_id = 123

    client = client_factory(TestClient)
    client.path_params_using_kwargs(post_id=post_id)

    assert f"/posts/{post_id}/comments" == httpx_request.url.path


def test_request_body_with_model(
    client_factory,
    httpx_request: httpx.Request,
):
    class CreatePostRequest(pydantic.BaseModel):
        title: str
        body: str

    class CreatePostResponse(pydantic.BaseModel):
        title: str
        body: str

    class TestClient(ApiClient):
        @get("/posts")
        def create_post(self, *, post: CreatePostRequest) -> CreatePostResponse: ...

    post_id = 123

    client = client_factory(TestClient)
    client.create_post(post_id=post_id)

    assert f"/posts/{post_id}/comments" == httpx_request.url.path


def test_get_params_spec(snapshot):
    class TestSubject:
        def all_possible_params(self, *, post_id: Annotated[PositiveInt, Path()], ignore_me: bool): ...

    all_params, _ = get_params_spec(TestSubject.all_possible_params)
    assert all_params == snapshot
