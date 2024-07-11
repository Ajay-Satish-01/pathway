import os
import pathlib
from typing import List

import openapi_spec_validator
import requests
from langchain.text_splitter import CharacterTextSplitter
from langchain_core.embeddings import Embeddings
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.node_parser import TextSplitter
from llama_index.readers.pathway import PathwayReader
from llama_index.retrievers.pathway import PathwayRetriever

import pathway as pw
from pathway.tests.utils import wait_result_with_checker
from pathway.xpacks.llm.vector_store import VectorStoreClient, VectorStoreServer

PATHWAY_HOST = "127.0.0.1"


class LangChainFakeEmbeddings(Embeddings):
    def embed_query(self, text: str) -> list[float]:
        return [1.0, 1.0, 1.0 if text == "foo" else -1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def pathway_server_from_langchain(tmp_path, port):
    data_sources = []
    data_sources.append(
        pw.io.fs.read(
            tmp_path,
            format="binary",
            mode="streaming",
            with_metadata=True,
        )
    )

    embeddings_model = LangChainFakeEmbeddings()
    splitter = CharacterTextSplitter("\n\n", chunk_size=4, chunk_overlap=0)

    vector_server = VectorStoreServer.from_langchain_components(
        *data_sources, embedder=embeddings_model, splitter=splitter
    )
    thread = vector_server.run_server(
        host=PATHWAY_HOST,
        port=port,
        threaded=True,
        with_cache=False,
    )
    thread.join()


def test_llm_xpack_autogenerated_docs_validity(tmp_path: pathlib.Path, port: int):

    def checker() -> bool:
        description = None
        try:
            schema = requests.get(
                f"http://{PATHWAY_HOST}:{port}/_schema?format=json", timeout=1
            )
            schema.raise_for_status()
            description = schema.json()
            assert description is not None
            openapi_spec_validator.validate(description)
        except Exception:
            return False

        return True

    wait_result_with_checker(
        checker, 20, target=pathway_server_from_langchain, args=[tmp_path, port]
    )


def test_similarity_search_without_metadata(tmp_path: pathlib.Path, port: int):
    with open(tmp_path / "file_one.txt", "w+") as f:
        f.write("foo")

    client = VectorStoreClient(host=PATHWAY_HOST, port=port)

    def checker() -> bool:
        output = []
        try:
            output = client("foo")
        except requests.exceptions.RequestException:
            return False
        return (
            len(output) == 1
            and output[0]["dist"] < 0.0001
            and output[0]["text"] == "foo"
            and "metadata" in output[0]
        )

    wait_result_with_checker(
        checker, 20, target=pathway_server_from_langchain, args=[tmp_path, port]
    )


def test_vector_store_with_langchain(tmp_path: pathlib.Path, port) -> None:
    with open(tmp_path / "file_one.txt", "w+") as f:
        f.write("foo\n\nbar")

    client = VectorStoreClient(host=PATHWAY_HOST, port=port)

    def checker() -> bool:
        output = []
        try:
            output = client.query("foo", 1, filepath_globpattern="**/file_one.txt")
        except requests.exceptions.RequestException:
            return False

        return len(output) == 1 and output[0]["text"] == "foo"

    wait_result_with_checker(
        checker, 20, target=pathway_server_from_langchain, args=[tmp_path, port]
    )


EXAMPLE_TEXT_FILE = "example_text.md"


def get_data_sources():
    test_dir = os.path.dirname(os.path.abspath(__file__))
    example_text_path = os.path.join(test_dir, EXAMPLE_TEXT_FILE)

    data_sources = []
    data_sources.append(
        pw.io.fs.read(
            example_text_path,
            format="binary",
            mode="streaming",
            with_metadata=True,
        )
    )
    return data_sources


def mock_get_text_embedding(text: str) -> List[float]:
    """Mock get text embedding."""
    if text == "Hello world.":
        return [1.0, 0.0, 0.0, 0.0, 0.0]
    elif text == "This is a test.":
        return [0.0, 1.0, 0.0, 0.0, 0.0]
    elif text == "This is another test.":
        return [0.0, 0.0, 1.0, 0.0, 0.0]
    elif text == "This is a test v2.":
        return [0.0, 0.0, 0.0, 1.0, 0.0]
    elif text == "This is a test v3.":
        return [0.0, 0.0, 0.0, 0.0, 1.0]
    elif text == "This is bar test.":
        return [0.0, 0.0, 1.0, 0.0, 0.0]
    elif text == "Hello world backup.":
        return [0.0, 0.0, 0.0, 0.0, 1.0]
    else:
        return [0.0, 0.0, 0.0, 0.0, 0.0]


class NewlineTextSplitter(TextSplitter):
    def split_text(self, text: str) -> List[str]:
        return text.split(",")


class LlamaIndexFakeEmbedding(BaseEmbedding):
    def _get_text_embedding(self, text: str) -> List[float]:
        return mock_get_text_embedding(text)

    def _get_query_embedding(self, query: str) -> List[float]:
        return mock_get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return mock_get_text_embedding(query)


def pathway_server_from_llama_index(port):
    data_sources = get_data_sources()

    embed_model = LlamaIndexFakeEmbedding()

    custom_transformations = [
        NewlineTextSplitter(),
        embed_model,
    ]

    processing_pipeline = VectorStoreServer.from_llamaindex_components(
        *data_sources,
        transformations=custom_transformations,
    )

    thread = processing_pipeline.run_server(
        host=PATHWAY_HOST,
        port=port,
        threaded=True,
        with_cache=False,
    )
    thread.join()


def test_llama_retriever(port: int):
    retriever = PathwayRetriever(host=PATHWAY_HOST, port=port, similarity_top_k=1)

    def checker() -> bool:
        results = []
        try:
            results = retriever.retrieve(str_or_query_bundle="Hello world.")
        except requests.exceptions.RequestException:
            return False

        return (
            len(results) == 1
            and results[0].text == "Hello world."
            and results[0].score == 1.0
        )

    wait_result_with_checker(
        checker, 20, target=pathway_server_from_llama_index, args=[port]
    )


def test_llama_reader(port: int):
    pr = PathwayReader(host=PATHWAY_HOST, port=port)

    def checker() -> bool:
        results = []
        try:
            results = pr.load_data("Hello world.", k=1)
        except requests.exceptions.RequestException:
            return False

        if not (
            len(results) == 1
            and results[0].text == "Hello world."
            and EXAMPLE_TEXT_FILE in results[0].metadata["path"]
        ):
            return False

        results = []
        try:
            results = pr.load_data("This is a test.", k=1)
        except requests.exceptions.RequestException:
            return False

        return (
            len(results) == 1
            and results[0].text == "This is a test."
            and EXAMPLE_TEXT_FILE in results[0].metadata["path"]
        )

    wait_result_with_checker(
        checker, 20, target=pathway_server_from_llama_index, args=[port]
    )
