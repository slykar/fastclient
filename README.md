# FastClient

*Declarative, code-less, type-hint driven HTTP API clients.*

## Why?

I wasn't happy with boilerplate code needed to write a simple HTTP client.
It's my pet project exploring the concept of using type-annotations to write less of boring code.

## Requirements

The code is heavily dependent on **FastAPI**, **Pydantic** and **HTTPX**.
There's a very high chance that you already use those 3 dependencies in your project.

## Features

- Code-less client definition with type annotations and decorators.
- Pydantic driven validation and serialisation of URL path, query params, headers and request body.

## Docs?

For now, just take a look at the [tests](./fastclient/client_test.py) file.

```python
import httpx
from typing import Annotated
from fastclient import ApiClient, get, Query, Path
from annotated_types import Gt

PositiveInt = Annotated[int, Gt(0)]


class BlogApiClient(ApiClient):
    @get("/posts/{post_id}/comments")
    def get_posts(
            self, *,
            for_post_id: Annotated[PositiveInt, Path(serialization_alias="post_id")],
            author_id: Annotated[PositiveInt, Query(serialization_alias="user_id")],
    ) -> httpx.Response:
        """Yes. That's it. No function body required."""


# Create base HTTP client using HTTPX
http_adapter = httpx.Client(base_url='https://your-api.com/api/v1')

# Create an instance of your API client
client = BlogApiClient(http_adapter)

# GET https://your-api.com/api/v1/post_id=123&user_id=1
client.get_posts(author_id=1, for_post_id=123)
```