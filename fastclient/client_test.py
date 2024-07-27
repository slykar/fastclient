import dataclasses
from collections.abc import Callable
from typing import Annotated, Type, TypedDict, TypeVar
from unittest import mock

import httpx
import pydantic
import pydantic_core
import pytest
from annotated_types import Gt
from pytest_mock import MockerFixture

import fastclient
from fastclient import Path, Query
from fastclient.client import ApiClient, get

PositiveInt = Annotated[int, Gt(0)]

CT = TypeVar("CT", bound=ApiClient)


class CreatePostRequest(pydantic.BaseModel):
    title: str
    body: str


class CreateCommentRequest(pydantic.BaseModel):
    user_id: int
    body: str


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


@pytest.mark.skip(reason="not implemented yet")
def test_query_params_using_model(
    client_factory,
    httpx_request: httpx.Request,
):
    class QueryComments(pydantic.BaseModel):
        user_id: int
        post_id: int

    class TestClient(ApiClient):
        @get("/comments")
        def get_comments_by(self, *, filters: Annotated[QueryComments, Query()]) -> httpx.Response: ...

    client = client_factory(TestClient)
    client.get_comments_by(filters=QueryComments(user_id=123, post_id=456))
    assert b"user_id=123&post_id=456" == httpx_request.url.query


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
    class TestClient(ApiClient):
        @get("/posts")
        def create_post(self, *, post: CreatePostRequest) -> httpx.Response: ...

    post_create_data = CreatePostRequest(
        title="How to create a great API client?",
        body="Just reuse existing code.",
    )

    client = client_factory(TestClient)
    client.create_post(post=post_create_data)

    assert (
        pydantic_core.to_json(
            {
                "post": {
                    "title": "How to create a great API client?",
                    "body": "Just reuse existing code.",
                }
            }
        )
        == httpx_request.content
    )


def test_request_body_with_multiple_models(
    client_factory,
    httpx_request: httpx.Request,
):
    class TestClient(ApiClient):
        @get("/posts")
        def create_post_with_comment(
            self, *, post: CreatePostRequest, comment: CreateCommentRequest
        ) -> httpx.Response: ...

    post_create_data = CreatePostRequest(
        title="How to create a great API client?",
        body="Just reuse existing code.",
    )

    comment_create_data = CreateCommentRequest(
        user_id=1,
        body="What a bloated mess! I don't even use FastAPI!",
    )

    client = client_factory(TestClient)
    client.create_post_with_comment(post=post_create_data, comment=comment_create_data)

    assert (
        pydantic_core.to_json(
            {
                "post": {
                    "title": "How to create a great API client?",
                    "body": "Just reuse existing code.",
                },
                "comment": {"user_id": 1, "body": "What a bloated mess! I don't even use FastAPI!"},
            }
        )
        == httpx_request.content
    )


def test_request_body_with_explicit_annotations(
    client_factory,
    httpx_request: httpx.Request,
):
    class TestClient(ApiClient):
        @get("/posts")
        def create_post_with_comment(
            self, *, post: CreatePostRequest, comment: Annotated[CreateCommentRequest, fastclient.Body()]
        ) -> httpx.Response: ...

    post_create_data = CreatePostRequest(
        title="How to create a great API client?",
        body="Just reuse existing code.",
    )

    comment_create_data = CreateCommentRequest(
        user_id=1,
        body="What a bloated mess! I don't even use FastAPI!",
    )

    client = client_factory(TestClient)
    client.create_post_with_comment(post=post_create_data, comment=comment_create_data)

    assert (
        pydantic_core.to_json(
            {
                "post": {
                    "title": "How to create a great API client?",
                    "body": "Just reuse existing code.",
                },
                "comment": {"user_id": 1, "body": "What a bloated mess! I don't even use FastAPI!"},
            }
        )
        == httpx_request.content
    )


def test_request_body_with_typeddict(
    client_factory,
    httpx_request: httpx.Request,
):
    QuickPost = TypedDict("QuickPost", {"title": str, "body": str})

    class TestClient(ApiClient):
        @get("/posts")
        def create_post(self, *, post: QuickPost) -> httpx.Response: ...

    post_create_data = QuickPost(
        title="How to create a great API client?",
        body="Just reuse existing code.",
    )

    client = client_factory(TestClient)
    client.create_post(post=post_create_data)

    assert (
        pydantic_core.to_json(
            {
                "post": {
                    "title": "How to create a great API client?",
                    "body": "Just reuse existing code.",
                }
            }
        )
        == httpx_request.content
    )


def test_request_body_with_dataclass(
    client_factory,
    httpx_request: httpx.Request,
):
    @dataclasses.dataclass
    class CreatePostData:
        title: str
        body: str

    class TestClient(ApiClient):
        @get("/posts")
        def create_post(self, *, post: CreatePostData) -> httpx.Response: ...

    post_create_data = CreatePostData(
        title="How to create a great API client?",
        body="Just reuse existing code.",
    )

    client = client_factory(TestClient)
    client.create_post(post=post_create_data)

    assert (
        pydantic_core.to_json(
            {
                "post": {
                    "title": "How to create a great API client?",
                    "body": "Just reuse existing code.",
                }
            }
        )
        == httpx_request.content
    )
