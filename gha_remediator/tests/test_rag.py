from gha_remediator.rag import Doc, KnowledgeBase


def test_empty_knowledge_base_returns_no_results():
    kb = KnowledgeBase([])

    assert kb.retrieve("missing dependency") == []


def test_retrieve_returns_relevant_documents():
    kb = KnowledgeBase(
        [
            Doc("1", "Python import failure", "ModuleNotFoundError for requests"),
            Doc("2", "Workflow YAML", "Indentation problem in gha workflow"),
            Doc("3", "Java build", "Maven dependency resolution error"),
        ]
    )

    docs = kb.retrieve("requests ModuleNotFoundError", top_k=1)

    assert [doc.doc_id for doc in docs] == ["1"]


def test_retrieve_filters_zero_score_documents():
    kb = KnowledgeBase(
        [
            Doc("1", "Python import failure", "ModuleNotFoundError for requests"),
            Doc("2", "Workflow YAML", "Indentation problem in gha workflow"),
            Doc("3", "Java build", "Maven dependency resolution error"),
        ]
    )

    docs = kb.retrieve("totally unrelated query", top_k=5)

    assert docs == []
