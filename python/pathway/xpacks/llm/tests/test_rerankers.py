# Copyright © 2024 Pathway
import pytest

import pathway as pw
from pathway.tests.utils import assert_table_equality
from pathway.xpacks.llm.rerankers import LLMReranker, rerank_topk_filter


def _test_llm_reranker(llm, expected):
    schema = pw.schema_from_types(query=str, doc=str)
    input = pw.debug.table_from_rows(schema=schema, rows=[("foo", "bar")])

    reranker = LLMReranker(llm)

    ranking = input.select(rank=reranker(input.doc, input.query))
    assert_table_equality(
        ranking,
        pw.debug.table_from_rows(pw.schema_from_types(rank=float), [(expected,)]),
    )


def _test_llm_reranker_raises(llm):
    schema = pw.schema_from_types(query=str, doc=str)
    input = pw.debug.table_from_rows(schema=schema, rows=[("foo", "bar")])

    reranker = LLMReranker(llm)

    ranking = input.select(rank=reranker(input.doc, input.query))
    with pytest.raises(ValueError):
        pw.debug._compute_tables(ranking)


def test_llm_reranker():
    @pw.udf
    def llm1(*args, **kwargs) -> str:
        return "1"

    _test_llm_reranker(llm1, 1.0)

    @pw.udf
    def llm2(*args, **kwargs) -> str:
        return "5.0"

    _test_llm_reranker(llm2, 5.0)

    @pw.udf
    def llm3(*args, **kwargs) -> str:
        return "6"

    _test_llm_reranker_raises(llm3)

    @pw.udf
    def llm4(*args, **kwargs) -> str:
        return "text"

    _test_llm_reranker_raises(llm4)


def test_rerank_topk_filter():
    input_schema = pw.schema_from_types(docs=list[dict], scores=list[float])

    docs = [{"text": str(i)} for i in range(10)]

    input = pw.debug.table_from_rows(
        input_schema,
        [
            (
                docs,
                [1, 2.0, 5.5, -10.333, 2, 9.5, 5.555, 4.3, 2.8, 9.5],
            )
        ],
    )
    filtered = input.select(docs=rerank_topk_filter(pw.this.docs, pw.this.scores, 3))

    expected_docs = [pw.Json({"text": str(i)}) for i in [5, 9, 6]]

    assert_table_equality(
        filtered,
        pw.debug.table_from_rows(
            pw.schema_from_types(docs=tuple[list[dict], list[float]]),
            [((expected_docs, [9.5, 9.5, 5.555]),)],
        ),
    )
