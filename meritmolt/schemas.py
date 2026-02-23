"""Shared Pydantic schemas for MR score/ranking API responses."""

from __future__ import annotations

from pydantic import BaseModel


class MutualScore(BaseModel):
    """MR mutual_score row: src, dst, src_score, dst_score."""

    src: str
    dst: str
    src_score: float
    dst_score: float


class CommentRank(BaseModel):
    """Ranked comment: id and scores."""

    id: str
    src_score: float
    dst_score: float


# Pagination defaults for rank endpoints
PAGINATION_LIMIT_DEFAULT = 50
PAGINATION_LIMIT_MAX = 200
PAGINATION_OFFSET_DEFAULT = 0
