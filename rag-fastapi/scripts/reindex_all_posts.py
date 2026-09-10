"""Reindex every post from inside the Compose application network."""

import html
import json
import os
import re
from urllib.request import Request, urlopen


POSTS_URL = os.getenv("REINDEX_POSTS_URL", "http://backend-spring:8080/api/posts")
INDEX_URL = os.getenv("REINDEX_INDEX_URL", "http://localhost:8000/api/rag/index")


def searchable_text(content: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", content or "")
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def main() -> None:
    with urlopen(POSTS_URL, timeout=30) as response:
        posts = json.load(response)

    for post in posts:
        payload = {
            "source_type": "POST",
            "source_id": post["id"],
            "title": post["title"],
            "content": searchable_text(post.get("content", "")),
            "category": post["categorySection"],
            "tags": post.get("tags"),
            "url": f"/posts/{post['id']}",
            "visibility": "PUBLIC" if post.get("isPublished") else "PRIVATE",
            "owner_id": post.get("authorId"),
        }
        request = Request(
            INDEX_URL,
            data=json.dumps(payload, ensure_ascii=True).encode("ascii"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
        print(post["id"], result["success"], result["chunks_indexed"])


if __name__ == "__main__":
    main()
