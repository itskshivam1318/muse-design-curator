"""Vary is retired (replaced by Explore): its routes answer 410; its tables stay for history."""

from fastapi import APIRouter

from app.errors import AppError

router = APIRouter(prefix="/api")


def _retired() -> AppError:
    return AppError(410, "VARY_RETIRED", "Vary has been replaced by Explore")


@router.post("/boards/{board_id}/runs")
def create_run(board_id: str) -> None:
    raise _retired()


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> None:
    raise _retired()


@router.get("/corpus/{corpus_id}/image")
def corpus_image(corpus_id: str) -> None:
    raise _retired()
